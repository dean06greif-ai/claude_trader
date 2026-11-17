"""Systemarzt (Leitstand Phase B, 15.11.2026): alle 15 min, ohne KI-Kosten.

Bündelt die vorhandenen Prüfungen (Self-Test, Sicherheits-Ampel, Live-Daten,
Hauptschleife) und ergänzt, was bisher niemand meldete: Worker-Version,
Daten-Frische nach Handelszeiten, Handelsfluss des KI-Traders, fehlgeschlagene
Jobs, KI-Anbieter (Fehler, Guthaben, kostenloses Entscheidungsmodell) und
Fehler, die die Website selbst meldet (services/client_errors).

Jeder Befund ist für Menschen geschrieben:
  {id, level: kritisch|warnung|hinweis, area, title, detail, fix, action?, first_seen}
`detail` sagt, was los ist und warum es zählt, `fix`, was zu tun ist.
`action` ist optional ein gefahrloser Knopf im Leitstand (nie Handel/Geld).
Die Prüfungen sind einzeln abgesichert: Fällt eine aus, wird das selbst ein
Hinweis – der Arzt läuft weiter.
"""
import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

REPORT_ID = "system_doctor"
HISTORY = "system_doctor_history"
HISTORY_KEEP_DAYS = 7
CHECK_TIMEOUT_S = 25
LEVELS = ("kritisch", "warnung", "hinweis")
LEVEL_RANK = {"kritisch": 0, "warnung": 1, "hinweis": 2, "ok": 3}

# Schwellen (bewusst großzügig: lieber eine echte Meldung als zehn Fehlalarme)
STALE_WARN_MIN = 10.0          # 1m-Kerzen älter als 10 min bei offenem Markt
STALE_CRIT_MIN = 60.0
FLOW_QUIET_H = 12              # so lange ohne KI-Trade/Schatten -> Handelsfluss prüfen
LOOP_STALE_MIN = 45.0          # Hauptschleife ohne Lauf
FREE_MODEL_SHARE = 0.5         # Anteil Entscheidungen eines :free-Modells
CLIENT_ERR_WARN = 3            # gleiche Fehlerquelle so oft in 24 h -> Warnung
FAILED_JOBS_H = 24


def finding(fid: str, level: str, area: str, title: str, detail: str, fix: str,
            action: Optional[Dict] = None) -> Dict:
    return {"id": fid, "level": level, "area": area, "title": title, "detail": detail,
            "fix": fix, "action": action}


def _age_min(iso: Optional[str], now: Optional[datetime] = None) -> Optional[float]:
    if not iso:
        return None
    try:
        ts = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ((now or datetime.now(timezone.utc)) - ts).total_seconds() / 60.0


# ---------------------------------------------------------------------------
# Reine Bewertungen (ohne DB) – einzeln testbar
# ---------------------------------------------------------------------------
def judge_selftest(res: Optional[Dict]) -> List[Dict]:
    if not res:
        return []
    failed = [c for c in res.get("checks") or [] if not c.get("ok")]
    if not failed:
        return []
    names = "; ".join(f"{c.get('label')}: {c.get('detail')}" for c in failed[:4])
    return [finding("selftest_failed", "kritisch", "Rechenkern",
                    f"Self-Test: {len(failed)} Prüfung(en) fehlgeschlagen",
                    f"Feste Rechenprüfungen der Kernlogik liefern falsche Werte ({names}). "
                    "Ergebnisse von Backtests, Gebühren oder Risiko-Rechnung sind dann nicht verlässlich.",
                    "Nicht live handeln, bis der Fehler behoben ist; Befund an die Entwicklung geben.",
                    {"kind": "selftest", "label": "Self-Test erneut ausführen"})]


SAFETY_TEXT = {
    "sl_missing": ("Live-Trade ohne Stop-Loss an der Börse",
                   "Ein offener Echtgeld-Trade hat keinen bestätigten Stop-Loss bei Bitunix.",
                   "Sofort in Bitunix prüfen und den Stop setzen; neue Live-Trades sind gesperrt."),
    "close_failed": ("Schließen eines Live-Trades fehlgeschlagen",
                     "Die Börse hat das Schließen eines Trades abgelehnt – die Position kann noch offen sein.",
                     "In Bitunix prüfen und die Position notfalls dort schließen."),
    "sync_stale": ("Abgleich mit der Börse veraltet",
                   "Offene Live-Trades wurden länger nicht mit Bitunix abgeglichen.",
                   "Bitunix-Verbindung prüfen (API-Schlüssel, Erreichbarkeit)."),
    "watchdog_stale": ("Positions-Wächter meldet sich nicht",
                       "Der Wächter, der fehlende Stops und fremde Positionen findet, läuft nicht.",
                       "Server-Log prüfen; nach einem Neustart läuft er wieder an."),
    "kill_switch": ("Handel pausiert (Kill-Switch)",
                    "Die Risiko-Notbremse hat neue Trades gestoppt.",
                    "Ursache in den Sicherheits-Einstellungen prüfen und bewusst wieder freigeben."),
    "db_storage": ("Datenbank-Speicher knapp",
                   "Die kostenlose Datenbank (512 MB) läuft voll; bei 100 % schlagen Schreibvorgänge fehl.",
                   "Im Wartungs-Bereich die Aufbewahrung prüfen bzw. „Aufräumen jetzt“ ausführen."),
}


def judge_safety(st: Optional[Dict]) -> List[Dict]:
    out = []
    for c in (st or {}).get("checks") or []:
        lvl = c.get("level")
        if lvl not in ("warn", "critical"):
            continue
        title, why, fix = SAFETY_TEXT.get(c.get("name"), (c.get("name"), "", "Details in der Sicherheits-Ampel."))
        out.append(finding(f"safety_{c.get('name')}", "kritisch" if lvl == "critical" else "warnung",
                           "Sicherheit", title, f"{why} ({c.get('detail')})".strip(), fix))
    return out


def judge_workers(workers: List[Dict], required: str, now_s: float, timeout_s: float = 8.0) -> List[Dict]:
    """workers: [{id, version, last_seen}] (rein)."""
    from services import local_exec
    online = [w for w in workers if now_s - float(w.get("last_seen") or 0) < timeout_s]
    if not online:
        return [finding("worker_offline", "hinweis", "Worker",
                        "Lokaler Worker nicht verbunden",
                        "Die Endlossuche und die Nacht-Forschung rechnen auf deinem PC. Ohne Worker "
                        "fallen die nächtlichen Suchen aus (der Handel ist davon nicht betroffen).",
                        "Worker auf dem PC starten (Bereich „Lokaler Worker“), wenn nachts gesucht werden soll.")]
    need = local_exec._ver(required)
    old = [w for w in online if local_exec._ver(w.get("version")) < need]
    if old and len(old) == len(online):
        vers = ", ".join(sorted({str(w.get("version")) for w in old}))
        return [finding("worker_outdated", "kritisch", "Worker", f"Lokaler Worker veraltet ({vers})",
                        f"Suchen rechnen mit dem Code IM Worker-Paket. Version {vers} enthält noch die alte "
                        f"Prüfung ohne Signifikanz/Tresor – die Endlossuche wird deshalb abgelehnt.",
                        f"Neues Worker-Paket (mind. {required}) im Bereich „Lokaler Worker“ laden und neu starten.")]
    return []


def judge_freshness(rows: List[Dict]) -> List[Dict]:
    """rows aus ai_diagnosis.data_quality_rows (rein)."""
    stale = [r for r in rows or [] if not r.get("market_closed")
             and float(r.get("last_candle_age_min") or 0) >= STALE_WARN_MIN]
    if not stale:
        return []
    crit = [r for r in stale if float(r.get("last_candle_age_min") or 0) >= STALE_CRIT_MIN]
    names = ", ".join(f"{r['symbol']} ({r['last_candle_age_min']:.0f} min)" for r in stale[:6])
    return [finding("data_stale", "kritisch" if crit else "warnung", "Marktdaten",
                    f"Kurse veraltet: {len(stale)} Asset(s) bei offenem Markt",
                    f"Für {names} kamen keine frischen Kerzen. Der KI-Trader und die Detektoren "
                    "entscheiden dort auf alten Kursen (Wochenenden/Handelspausen sind bereits ausgenommen).",
                    "Datenquelle des Assets prüfen (Broker-Verbindung, Feed); bei Forex den IBKR-Gateway.")]


def judge_loop(cfg: Dict, last_run: Optional[str], analyzing: bool,
               now: Optional[datetime] = None) -> List[Dict]:
    if not cfg.get("enabled"):
        return [finding("ai_disabled", "hinweis", "KI-Trader", "KI-Trader ist ausgeschaltet",
                        "Es laufen keine Analysen und keine KI-Trades; Regel-Datensammlung je nach Einstellung.",
                        "Im KI-Panel einschalten, wenn er handeln und lernen soll.")]
    age = _age_min(last_run, now)
    limit = max(LOOP_STALE_MIN, 3 * float(cfg.get("interval_min", 10) or 10))
    if age is not None and age > limit and not analyzing:
        return [finding("ai_loop_stale", "kritisch", "KI-Trader",
                        f"KI-Trader-Schleife läuft nicht (letzter Lauf vor {age:.0f} min)",
                        "Die Marktanalyse soll alle paar Minuten laufen. Ohne sie gibt es keine neuen "
                        "Entscheidungen, kein Trade-Management durch die KI und kein Lernen.",
                        "Server-Log auf Fehler prüfen; ein Neustart des Backends startet die Schleife neu.")]
    return []


def judge_flow(opened_recent: int, shadows_recent: int, baseline_per_day: Optional[float],
               blocks: List[Dict], quiet_h: int = FLOW_QUIET_H) -> List[Dict]:
    """Handelsfluss: keine KI-Trades (auch keine Schattentrades) seit `quiet_h` Stunden.
    blocks: [{reason, count}] häufigste Block-Gründe im selben Zeitraum (rein)."""
    if opened_recent or shadows_recent:
        return []
    top = "; ".join(f"{b['reason']} ({b['count']}×)" for b in blocks[:3]) or "keine Blockaden protokolliert"
    base = (f" Vorher waren es im Schnitt {baseline_per_day:.0f} Trades pro Tag."
            if baseline_per_day else "")
    return [finding("trade_flow_quiet", "warnung", "KI-Trader",
                    f"Seit {quiet_h} h kein KI-Trade (auch kein Lern-/Schattentrade)",
                    f"Der KI-Trader lernt nur aus Trades.{base} Häufigste Gründe: {top}.",
                    "Gründe im Bereich Mängel/Empfehlungen prüfen. Ruhige Märkte sind normal; dauert es "
                    "länger, Schwellen (z. B. Fee-Faktor, Richtungs-Limit) prüfen statt Regeln abzuschalten.")]


def judge_failed_jobs(series_errors: List[Dict], lab_error: Optional[str]) -> List[Dict]:
    out = []
    if series_errors:
        names = "; ".join(f"{i.get('label')}: {str(i.get('error') or '')[:80]}" for i in series_errors[:3])
        out.append(finding("jobs_failed", "warnung", "Forschung",
                           f"{len(series_errors)} Job(s) der Nacht-Serie fehlgeschlagen (24 h)",
                           f"Diese Rechenläufe haben kein Ergebnis geliefert: {names}.",
                           "In der Nacht-Serie den Fehlertext ansehen; oft fehlt der Worker oder Daten."))
    if lab_error:
        out.append(finding("lab_failed", "warnung", "Forschung", "Letzter Lab-Lauf fehlgeschlagen",
                           f"Das KI-Trader-Lab meldete: {str(lab_error)[:200]}",
                           "Im KI-Trader-Lab den Lauf erneut starten; bei RAM-Mangel nachts laufen lassen."))
    return out


def judge_providers(health: Optional[Dict], credits: Optional[Dict], decisions_by_model: Dict[str, int],
                    last_error: Optional[str]) -> List[Dict]:
    out = []
    h = health or {}
    groups = h.get("rate_limited_grouped") or []
    errs = h.get("errors") or []
    if groups:
        names = ", ".join(f"{g.get('provider')} ({', '.join(g.get('roles') or [])})" for g in groups[:3])
        out.append(finding("llm_rate_limited", "warnung", "KI-Anbieter",
                           "KI-Anbieter gedrosselt (Kontingent erschöpft)",
                           f"Betroffen: {names}. Die Rollen weichen auf Ersatz-Modelle aus oder pausieren.",
                           "Kontingent/Guthaben beim Anbieter prüfen oder ein Ersatz-Modell hinterlegen."))
    elif len(errs) >= 3:
        out.append(finding("llm_errors", "warnung", "KI-Anbieter", f"{len(errs)} KI-Aufrufe mit Fehlern",
                           "Mehrere Modelle antworteten zuletzt mit Fehlern.",
                           "Im KI-Panel unter Anbieter-Zustand die Fehlertexte prüfen."))
    for k in (credits or {}).get("keys") or []:
        lvl = k.get("level")
        if lvl in ("critical", "warning"):
            out.append(finding(f"credits_{k.get('label')}", "kritisch" if lvl == "critical" else "warnung",
                               "KI-Anbieter", f"Guthaben niedrig: {k.get('label')}",
                               f"Restguthaben {k.get('remaining')} $ – danach fallen bezahlte Modelle aus.",
                               "Guthaben beim Anbieter (OpenRouter) aufladen."))
    total = sum(decisions_by_model.values())
    free = sum(n for m, n in decisions_by_model.items() if str(m).endswith(":free"))
    if total >= 10 and free / total >= FREE_MODEL_SHARE:
        top = max((m for m in decisions_by_model if str(m).endswith(":free")),
                  key=lambda m: decisions_by_model[m])
        out.append(finding("free_model_decides", "warnung", "KI-Anbieter",
                           f"Ein kostenloses Modell trifft {free / total:.0%} der Entscheidungen",
                           f"{top} entschied {free} von {total} Prüfungen der letzten 24 h. Freie Modelle "
                           "sind meist das Ausweich-Modell, wenn das Hauptmodell ausfällt – für Prüf-"
                           "Entscheidungen sind sie spürbar schwächer.",
                           "Im KI-Panel prüfen, warum das Hauptmodell ausweicht (Kontingent/Guthaben), "
                           "bzw. ein günstiges bezahltes Modell als Hauptmodell setzen."))
    if last_error and not out:
        out.append(finding("ai_last_error", "hinweis", "KI-Anbieter", "Letzter KI-Lauf mit Fehler",
                           str(last_error)[:240], "Meist vorübergehend; bei Wiederholung KI-Panel prüfen."))
    return out


def judge_client_errors(groups: List[Dict]) -> List[Dict]:
    from services import client_errors
    out = []
    for g in groups[:3]:
        lvl = "warnung" if int(g.get("count") or 0) >= CLIENT_ERR_WARN else "hinweis"
        out.append(finding(f"web_{g.get('fingerprint')}", lvl, "Website",
                           "Fehler auf der Website" if g.get("kind") not in ("api", "network")
                           else "Server-Anfrage schlägt fehl",
                           client_errors.describe(g),
                           "Fenster neu laden; tritt es wiederholt auf, Befund an die Entwicklung geben "
                           "(Fingerabdruck " + str(g.get("fingerprint")) + ")."))
    return out


def judge_portfolio(enabled: bool, state: Optional[Dict], progress: Optional[Dict],
                    now_ms: int, running: bool = False) -> List[Dict]:
    """Portfolio (Tagesebene): rechnet es jeden Tag? Fehlen Funding-Daten? (rein)"""
    if not enabled:
        return []
    day = 86_400_000
    prog = progress or {}
    phase = str(prog.get("phase") or "")
    if phase.startswith("Fehler"):
        return [finding("portfolio_error", "warnung", "Portfolio", "Portfolio-Lauf fehlgeschlagen",
                        f"Letzter Lauf: {phase}.",
                        "Im Leitstand unter „Portfolio“ auf „Neu rechnen“ klicken. Bleibt der Fehler, sind die "
                        "Tagesdaten (Binance-Archiv) gerade nicht erreichbar – das löst sich meist von selbst.")]
    if not state or not state.get("last_ts"):
        return [] if running else [finding(
            "portfolio_missing", "hinweis", "Portfolio", "Portfolio noch nicht gerechnet",
            "Der erste Lauf lädt die Tagesdaten seit 2020 (einige Minuten).",
            "Nichts zu tun – der Lauf startet von selbst. Sonst im Reiter „Portfolio“ auf „Jetzt rechnen“.")]
    out = []
    age_days = (int(now_ms) // day - 1) - int(state["last_ts"]) // day
    if age_days >= 2:
        out.append(finding("portfolio_stale", "warnung", "Portfolio",
                           f"Portfolio seit {age_days} Tagen nicht aktualisiert",
                           "Der Tagesplan ist veraltet – neue Signale und nachgezogene Stops fehlen.",
                           "Im Reiter „Portfolio“ auf „Neu rechnen“ klicken."))
    n = len(state.get("symbols") or [])
    cov = state.get("funding_coverage")
    if n and cov is not None and cov < n / 2:
        out.append(finding("portfolio_funding", "hinweis", "Portfolio", "Funding-Daten unvollständig",
                           f"Nur {cov} von {n} Coins haben Funding-Daten – der Funding-Korb pausiert so lange, "
                           "der Trend-Teil läuft weiter.",
                           "Nichts zu tun – die Daten werden beim nächsten Tageslauf erneut geladen."))
    return out


def judge_portfolio_live(cfg: Optional[Dict], preview: Optional[Dict], now_s: float) -> List[Dict]:
    """Portfolio live: Not-Aus, Ausführungsfehler, ausbleibende Prüfung (rein)."""
    cfg = cfg or {}
    if cfg.get("mode") != "live":
        return []
    out = []
    if cfg.get("halted"):
        out.append(finding("portfolio_live_halt", "warnung", "Portfolio live", "Not-Aus aktiv – keine neuen Einstiege",
                           str(cfg.get("halt_reason") or "Grund unbekannt") + ". Stops und Ausstiege laufen weiter.",
                           "Im Reiter „Portfolio“ unter „Live-Ausführung“ prüfen und bei Bedarf „Not-Aus lösen“."))
    errs = int((preview or {}).get("errors") or 0)
    if errs:
        out.append(finding("portfolio_live_errors", "warnung", "Portfolio live",
                           f"{errs} Order(s) beim letzten Lauf fehlgeschlagen",
                           "Details im Reiter „Portfolio“ unter „Live-Ausführung → Protokoll“.",
                           "Protokoll ansehen; bei „Position nicht gefunden“ die Börse direkt prüfen."))
    last = float(cfg.get("last_check_at") or 0)
    if last and now_s - last > 3 * 3600:
        out.append(finding("portfolio_live_stale", "warnung", "Portfolio live", "Live-Prüfung läuft nicht",
                           f"Letzte Prüfung vor {(now_s - last) / 3600:.0f} Stunden.",
                           "Server neu starten, falls der Autonomie-Takt hängt."))
    return out


def judge_settings(cfg: Dict) -> List[Dict]:
    out = []
    if cfg.get("live_gate_bypass_enabled"):
        out.append(finding("live_bypass_on", "hinweis", "KI-Trader", "Live-Bypass bei hoher Konfidenz ist an",
                           "Nicht belegte Setups dürfen bei hoher Konfidenz live handeln. Die Konfidenz "
                           "trennt gute und schlechte Trades bisher nachweislich nicht.",
                           "Im KI-Panel ausschalten, solange die Konfidenz-Kalibrierung keinen Zusammenhang zeigt."))
    return out


def merge_first_seen(findings: List[Dict], previous: Optional[Dict], now_iso: str) -> List[Dict]:
    """first_seen aus dem letzten Bericht übernehmen (rein)."""
    prev = {f.get("id"): f.get("first_seen") for f in (previous or {}).get("findings") or []}
    for f in findings:
        f["first_seen"] = prev.get(f["id"]) or now_iso
    return findings


def sort_findings(findings: List[Dict]) -> List[Dict]:
    return sorted(findings, key=lambda f: (LEVEL_RANK.get(f.get("level"), 9), str(f.get("area")),
                                           str(f.get("title"))))


def overall(findings: List[Dict]) -> str:
    lv = {f.get("level") for f in findings}
    return "kritisch" if "kritisch" in lv else "warnung" if "warnung" in lv else "ok"


# ---------------------------------------------------------------------------
# Datenbeschaffung (fail-safe)
# ---------------------------------------------------------------------------
async def _decisions_by_model(db, hours: int = 24) -> Dict[str, int]:
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    out: Dict[str, int] = {}
    rows = await db.ai_decisions.find({"ts": {"$gte": since}, "model": {"$nin": [None, ""]}},
                                      {"_id": 0, "model": 1}).to_list(5000)
    for r in rows:
        out[str(r.get("model"))] = out.get(str(r.get("model")), 0) + 1
    return out


async def flow_data(db, hours: int = FLOW_QUIET_H) -> Dict:
    now = datetime.now(timezone.utc)
    since = (now - timedelta(hours=hours)).isoformat()
    q = {"strategy_id": "ai_trader", "opened_at": {"$gte": since}}
    opened = await db.auto_trades.count_documents({**q, "guard_shadow.guard": {"$exists": False}})
    shadows = await db.auto_trades.count_documents({**q, "guard_shadow.guard": {"$exists": True}})
    week = (now - timedelta(days=7)).isoformat()
    n_week = await db.auto_trades.count_documents({"strategy_id": "ai_trader", "opened_at": {"$gte": week}})
    blocks: Dict[str, int] = {}
    for r in await db.fee_guard_blocks.find({"ts": {"$gte": since}}, {"_id": 0, "reason": 1}).to_list(2000):
        key = "Fee-Wächter (SL zu eng für die Gebühren)" if "Minimum" in str(r.get("reason")) else "Fee-Wächter"
        blocks[key] = blocks.get(key, 0) + 1
    for r in await db.ai_decisions.find({"ts": {"$gte": since}, "blocked_by": {"$nin": [None, ""]}},
                                        {"_id": 0, "blocked_by": 1}).to_list(5000):
        key = str(r.get("blocked_by")).split(":")[0][:60]
        blocks[key] = blocks.get(key, 0) + 1
    top = sorted(({"reason": k, "count": v} for k, v in blocks.items()), key=lambda b: -b["count"])
    return {"opened": opened, "shadows": shadows, "baseline_per_day": round(n_week / 7.0, 1) if n_week else None,
            "blocks": top}


async def _series_errors(db, hours: int = FAILED_JOBS_H) -> List[Dict]:
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    return await db.job_series.find({"status": "error", "finished_at": {"$gte": since}},
                                    {"_id": 0, "label": 1, "error": 1}).to_list(20)


async def _lab_error(db) -> Optional[str]:
    doc = await db.settings.find_one({"_id": "setup_backtest_state"}, {"auto": 1}) or {}
    return ((doc.get("auto") or {}).get("last_error")) or None


# ---------------------------------------------------------------------------
# Lauf
# ---------------------------------------------------------------------------
async def _guarded(name: str, coro_fn: Callable, out: List[Dict], ok: List[str]):
    try:
        res = await asyncio.wait_for(coro_fn(), timeout=CHECK_TIMEOUT_S)
        if res:
            out.extend(res)
        else:
            ok.append(name)
    except Exception as e:  # noqa: BLE001 – eine kaputte Prüfung stoppt den Arzt nicht
        logger.warning(f"Systemarzt-Prüfung {name} fehlgeschlagen: {e}")
        out.append(finding(f"check_{name}", "hinweis", "Systemarzt", f"Prüfung „{name}“ nicht möglich",
                           f"{type(e).__name__}: {str(e)[:160]}", "Wird beim nächsten Lauf erneut versucht."))


async def run(db, engine=None, scanner=None, run_selftest: bool = True) -> Dict:
    """Alle Prüfungen ausführen, Bericht speichern und zurückgeben."""
    from services import client_errors, local_exec
    started = time.time()
    findings: List[Dict] = []
    ok: List[str] = []
    cfg = dict(getattr(engine, "config", None) or {})
    if not cfg:
        cfg = await db.settings.find_one({"_id": "ai_trader_config"}) or {}

    async def c_selftest():
        if not run_selftest:
            return []
        from services import selftest
        return judge_selftest(await selftest.run_all(db))

    async def c_safety():
        from services import safety_status
        return judge_safety(await safety_status.status(db))

    async def c_worker():
        rows = [{"id": k, **v} for k, v in local_exec.WORKERS.items()]
        return judge_workers(rows, local_exec.REQUIRED_WORKER_VERSION_STR, time.time(),
                             float(local_exec.WORKER_TIMEOUT))

    async def c_fresh():
        from services import ai_diagnosis
        return judge_freshness(ai_diagnosis.data_quality_rows(scanner)) if scanner is not None else []

    async def c_loop():
        return judge_loop(cfg, getattr(engine, "last_run", None), bool(getattr(engine, "_analyzing", False)))

    async def c_flow():
        if not cfg.get("enabled"):
            return []
        f = await flow_data(db)
        return judge_flow(f["opened"], f["shadows"], f["baseline_per_day"], f["blocks"])

    async def c_jobs():
        return judge_failed_jobs(await _series_errors(db), await _lab_error(db))

    async def c_providers():
        from services import ai_providers, key_credits
        return judge_providers(ai_providers.health_status(), key_credits.snapshot(),
                               await _decisions_by_model(db), getattr(engine, "last_error", None))

    async def c_web():
        s = await client_errors.summary(db, hours=24, limit=5)
        return judge_client_errors(s["groups"])

    async def c_settings():
        return judge_settings(cfg)

    async def c_portfolio():
        from services import portfolio_engine
        pf = await portfolio_engine.get_state(db)
        return judge_portfolio(bool(pf["config"].get("enabled")), pf.get("state"), pf.get("progress"),
                               int(time.time() * 1000), bool(pf.get("running")))

    async def c_portfolio_live():
        from services import portfolio_live
        cfg = await portfolio_live.get_config(db)
        prev = await db.settings.find_one({"_id": portfolio_live.PREVIEW_ID}) or {}
        return judge_portfolio_live(cfg, prev, time.time())

    for name, fn in (("selftest", c_selftest), ("sicherheit", c_safety), ("worker", c_worker),
                     ("marktdaten", c_fresh), ("hauptschleife", c_loop), ("handelsfluss", c_flow),
                     ("jobs", c_jobs), ("ki_anbieter", c_providers), ("website", c_web),
                     ("einstellungen", c_settings), ("portfolio", c_portfolio),
                     ("portfolio_live", c_portfolio_live)):
        await _guarded(name, fn, findings, ok)

    now_iso = datetime.now(timezone.utc).isoformat()
    prev = await db.settings.find_one({"_id": REPORT_ID}) or {}
    findings = sort_findings(merge_first_seen(findings, prev, now_iso))
    counts = {lv: sum(1 for f in findings if f["level"] == lv) for lv in LEVELS}
    report = {"generated_at": now_iso, "level": overall(findings), "counts": counts,
              "findings": findings, "checks_ok": ok, "seconds": round(time.time() - started, 2)}
    await db.settings.update_one({"_id": REPORT_ID}, {"$set": report}, upsert=True)
    try:
        await db[HISTORY].insert_one({"ts": now_iso, "level": report["level"], "counts": counts,
                                      "ids": [f["id"] for f in findings]})
        await db[HISTORY].delete_many(
            {"ts": {"$lt": (datetime.now(timezone.utc) - timedelta(days=HISTORY_KEEP_DAYS)).isoformat()}})
    except Exception:  # noqa: BLE001
        pass
    return report


async def latest(db) -> Optional[Dict]:
    doc = await db.settings.find_one({"_id": REPORT_ID}, {"_id": 0})
    return doc or None
