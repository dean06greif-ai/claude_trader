"""Leitstand (Phase B, 15.11.2026): ein Fenster für alles Wichtige.

Fünf Bereiche, alle regelbasiert aus vorhandenen Daten (0 KI-Aufrufe):
  1. jetzt        – was der KI-Trader gerade tut, offene Trades/Signale, letzte
                    Entscheidungen, Handelsfluss, gesparte KI-Prüfungen
  2. fortschritt  – belegte Vorteile, Kandidaten im Vorwärtstest, Setups bis zum
                    Live-Tor, Vorher/Nachher seit dem Bewertungs-Stichtag
  3. neu          – Zeitleiste der letzten 7 Tage (Setups, Lab, Suchen, Lektionen …)
  4. maengel      – Befunde des Systemarztes (services/system_doctor)
  5. empfehlungen – konkrete nächste Schritte, um einen Vorteil zu finden;
                    mit gefahrlosem Knopf, wo möglich (nie Handel/Geld)

Jeder Bereich ist einzeln abgesichert – ein Fehler leert nur seinen Bereich.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

DISMISS_ID = "cockpit_dismissed"
NEW_DAYS = 7
SAFE_ACTIONS = ("doctor_run", "selftest", "night_research_now", "lab_auto_on", "candidate_adopt",
                "candidate_discard", "candidate_retest", "dismiss", "undismiss_all",
                "daily_report_now", "live_watchdog_auto_pause")
FEED_ROLES = ("governance", "playbook", "research", "setup_review", "learning", "strategy")


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _short(txt, n: int = 160) -> str:
    s = " ".join(str(txt or "").split())
    return s if len(s) <= n else s[: n - 1] + "…"


def _r(t: Dict) -> Optional[float]:
    try:
        risk = float(t.get("risk_usdt") or 0)
        return float(t.get("realized_pnl") or 0) / risk if risk > 0 else None
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Reine Bausteine
# ---------------------------------------------------------------------------
def activity_text(cfg: Dict, analyzing: bool, next_run: Optional[str], role: Optional[str]) -> str:
    if not cfg.get("enabled"):
        return "KI-Trader ist ausgeschaltet."
    mode = ("prüft nur Detektor-Signale (Prüfer-Modus)" if role == "pruefer"
            else "analysiert den Markt und schlägt eigene Trades vor")
    if analyzing:
        return f"Analysiert gerade den Markt – {mode}."
    nxt = ""
    if next_run and role != "pruefer":     # Prüfer: kein Analyse-Zyklus, nur Signal-Prüfungen
        try:
            dt = datetime.fromisoformat(str(next_run).replace("Z", "+00:00"))
            from zoneinfo import ZoneInfo
            nxt = f" Nächste Marktanalyse um {dt.astimezone(ZoneInfo('Europe/Berlin')).strftime('%H:%M')} Uhr."
        except (TypeError, ValueError):
            nxt = ""
    return f"Wartet auf das nächste Signal – {mode}.{nxt}"


def trade_reason(t: Dict) -> str:
    gs = t.get("guard_shadow")
    if isinstance(gs, dict) and gs.get("guard"):
        return f"Schattentrade: vom {gs.get('guard')} geblockt, läuft zum Lernen in Paper weiter"
    src = t.get("signal_source")
    if src == "regel" or t.get("data_collection"):
        return "Lern-Trade (Detektor-Regel, ohne KI) – Vergleichsbasis für das Veto"
    if src == "ki_geprueft":
        return "KI-geprüfter Trade (Detektor + KI)"
    if src == "regel_live":
        return "Regel-Live (Lab-Freigabe)"
    if src == "ki_frei":
        return "freie KI-Idee (ohne Detektor, nur Paper)"
    return "KI-Trade"


def decision_sentence(d: Dict) -> str:
    act = str(d.get("action") or "HOLD").upper()
    sym = d.get("symbol") or "?"
    setup = f" ({d.get('setup')})" if d.get("setup") else ""
    if d.get("blocked_by"):
        return f"{sym}: {act}{setup} wurde blockiert – {_short(d.get('blocked_by'), 90)}"
    if act in ("LONG", "SHORT"):
        conf = f", Konfidenz {d.get('confidence')}" if d.get("confidence") is not None else ""
        return f"{sym}: {act}{setup}{conf} – {_short(d.get('reasoning') or d.get('reason'), 90)}"
    return f"{sym}: kein Einstieg{setup} – {_short(d.get('reasoning') or d.get('reason'), 90)}"


def before_after(trades: List[Dict], since: Optional[str], window_days: int = 30) -> Optional[Dict]:
    """Vorher/Nachher-Kachel (rein): `window_days` vor dem Stichtag gegen seither."""
    if not since:
        return None
    try:
        s_dt = datetime.fromisoformat(str(since).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if s_dt.tzinfo is None:
        s_dt = s_dt.replace(tzinfo=timezone.utc)
    lo = (s_dt - timedelta(days=window_days)).isoformat()
    s_iso = s_dt.isoformat()
    now = datetime.now(timezone.utc)

    def block(rows: List[Dict], days: float) -> Dict:
        rs = [x for x in (_r(t) for t in rows) if x is not None]
        fees = []
        for t in rows:
            try:
                risk = float(t.get("risk_usdt") or 0)
                if risk > 0:
                    fees.append(float(t.get("fees_paid") or 0) / risk)
            except (TypeError, ValueError):
                continue
        ct = 0
        known = 0
        from services.edge_filter import counter_trend
        for t in rows:
            bias = ((t.get("edge_filter") or {}).get("bias")
                    or (((t.get("entry_market_snapshot") or {}).get("features") or {}).get("daily_bias")))
            if bias:
                known += 1
                ct += 1 if counter_trend(t.get("side"), bias) else 0
        return {"trades": len(rows), "per_day": round(len(rows) / max(days, 1e-6), 1),
                "avg_r": round(sum(rs) / len(rs), 3) if rs else None,
                "fee_r": round(sum(fees) / len(fees), 3) if fees else None,
                "liquidations": sum(1 for t in rows if t.get("liquidated")),
                "counter_trend_pct": round(100.0 * ct / known, 1) if known else None}

    before = [t for t in trades if lo <= str(t.get("opened_at") or "") < s_iso]
    after = [t for t in trades if str(t.get("opened_at") or "") >= s_iso]
    days_after = max((now - s_dt).total_seconds() / 86400.0, 1 / 24)
    out = {"since": s_iso, "window_days": window_days, "before": block(before, window_days),
           "after": block(after, days_after), "days_after": round(days_after, 1)}
    n = out["after"]["trades"]
    out["note"] = ("Noch zu wenige neue Trades für ein Urteil – aussagekräftig ab etwa 100."
                   if n < 100 else "Genug neue Trades für einen ersten Vergleich.")
    return out


def _key(rid: str) -> str:
    """Empfehlungs-ID als Mongo-Feldname (keine Punkte/Dollar) – rein."""
    return str(rid).replace(".", "_").replace("$", "_")


def dismissed_active(doc: Optional[Dict], now: Optional[datetime] = None) -> Dict[str, str]:
    now_iso = (now or datetime.now(timezone.utc)).isoformat()
    return {k: v for k, v in ((doc or {}).get("items") or {}).items() if str(v) > now_iso}


def rec(rid: str, prio: int, area: str, title: str, detail: str,
        action: Optional[Dict] = None) -> Dict:
    return {"id": rid, "prio": prio, "area": area, "title": title, "detail": detail, "action": action}


def rec_live_strategies(verdicts: Dict[str, Dict]) -> List[Dict]:
    out = []
    for sid, v in verdicts.items():
        if not v.get("alarm"):
            continue
        out.append(rec(f"live_{sid}", 1, "Live-Strategien",
                       f"{v['name']}: Vorteil im Live-Handel nicht belegt",
                       f"{v['trades']} Live-Trades, Ø {v['avg_r']:+.2f} R je Trade (t {v['t']}, Untergrenze "
                       f"{v['lb']:+.2f} R). Pausieren (auf Paper weiterlaufen lassen) oder mit neuen Daten "
                       "neu prüfen. Läuft sie bewusst weiter, blende diese Empfehlung aus."))
    return out


def rec_candidates(cands: List[Dict]) -> List[Dict]:
    out = []
    for c in cands:
        p = c.get("progress") or {}
        if c.get("stage") == "bestanden":
            out.append(rec(f"cand_{c['id']}", 1, "Forschung", f"Kandidat bestanden: {c.get('title')}",
                           f"Vorwärtstest auf neuen Daten: {p.get('trades')} Trades, Ø {p.get('avg_r')} R, "
                           f"Untergrenze {p.get('lb')} R. Übernehmen legt sie als Strategie an und lässt sie im "
                           "Paper-Betrieb laufen (echte Ausführung, kein Geld). Live schaltest nur du.",
                           {"kind": "candidate_adopt", "id": c["id"], "label": "Übernehmen (Paper)"}))
        elif c.get("kind") == "vorgabe" and c.get("stage") == "vorwaertstest":
            he = c.get("history_evidence") or {}
            fwd = (f"Vorwärtstest bisher: {p.get('trades')} Trades, Ø {p.get('avg_r')} R. "
                   if int(p.get("trades") or 0) else "Der Vorwärtstest auf neuen Daten läuft automatisch. ")
            out.append(rec(f"preset_{c['id']}", 3 if c.get("adoptable") else 5, "Forschung",
                           f"Trendfolge-Vorgabe: {c.get('title')}",
                           f"Fest vorab festgelegte Strategie (nicht aus einer Suche). Auf echten Daten seit "
                           f"{he.get('since')}: {he.get('trades')} Trades, Ø {he.get('avg_r'):+.2f} R nach Kosten "
                           f"(t {he.get('t')}); {he.get('recent')}. {fwd}"
                           + ("Du kannst sie schon jetzt als Paper-Strategie laufen lassen (kein Geld). "
                              "Live schaltest nur du." if c.get("adoptable") else
                              "4h- und Tageskerzen kann der Live-Scanner noch nicht speicherschonend "
                              "handeln – sie läuft deshalb nur im Vorwärtstest. Nichts zu tun."),
                           {"kind": "candidate_adopt", "id": c["id"], "label": "Als Paper-Strategie starten"}
                           if c.get("adoptable") else None))
        elif c.get("stage") == "vorwaertstest" and int(p.get("trades") or 0) > 0:
            need = max(0, 30 - int(p.get("trades") or 0))
            if need:
                out.append(rec(f"candp_{c['id']}", 4, "Forschung", f"Kandidat im Vorwärtstest: {c.get('title')}",
                               f"{p.get('trades')} Trades auf neuen Daten (Ø {p.get('avg_r')} R) – noch etwa "
                               f"{need} bis zum Urteil. Nichts zu tun, läuft automatisch."))
    return out


def rec_research(night: Dict, worker_ok: bool, worker_why: str, lab_auto: Dict,
                 champions_7d: int) -> List[Dict]:
    out = []
    cfg = (night or {}).get("config") or {}
    if cfg.get("enabled") and not worker_ok:
        out.append(rec("night_worker", 2, "Forschung", "Nacht-Forschung wartet auf den Worker",
                       f"Die nächtliche Endlossuche ({night.get('next')}) kann nicht laufen: {worker_why}. "
                       "Worker abends auf dem PC starten bzw. aktualisieren."))
    elif worker_ok:
        out.append(rec("night_now", 3, "Forschung", f"Nächste Suche: {night.get('next')}",
                       "Die Nacht-Forschung plant sie automatisch ab 23 Uhr. Mit dem Knopf sofort in die "
                       "Nacht-Serie einreihen (empfohlene Einstellungen, ehrliche Prüfung).",
                       {"kind": "night_research_now", "label": "Jetzt einplanen"}))
    if not (lab_auto or {}).get("enabled"):
        out.append(rec("lab_auto", 2, "Forschung", "Lab-Automatik ist aus",
                       "Das KI-Trader-Lab prüft Setups auf historischen Daten – seit 11/2026 mit "
                       "ehrlicher Validierung (Signifikanz, Paper-Abgleich). Wöchentlich einschalten?",
                       {"kind": "lab_auto_on", "label": "Wöchentlich einschalten"}))
    if champions_7d == 0 and worker_ok:
        out.append(rec("no_champions", 4, "Forschung", "Diese Woche kein Champion gefunden",
                       "Normal bei ehrlicher Prüfung. Mehr Assets einer Klasse und 15m/1h erhöhen die "
                       "Chance; die Nacht-Forschung rotiert automatisch durch Klassen und Zeitebenen."))
    return out


def rec_setups(rows: List[Dict]) -> List[Dict]:
    out = []
    for r in rows[:3]:
        if r["state"] == "live-reif":
            out.append(rec(f"setup_ready_{r['setup']}", 2, "Setups", f"Setup {r['setup']} ist live-reif",
                           f"{r['trades']} Paper-Trades seit Stichtag, Ø {r['avg_r']:+.2f} R, Untergrenze "
                           f"{r['lb']:+.2f} R. Die Live-Tore prüfen das automatisch."))
        elif r["need"] and r["progress_pct"] >= 50:
            out.append(rec(f"setup_{r['setup']}", 4, "Setups", f"{r['setup']}: {r['state']}",
                           f"{r['trades']} Paper-Trades seit Stichtag, Ø "
                           f"{'–' if r['avg_r'] is None else format(r['avg_r'], '+.2f')} R."))
    return out


def rec_events(snaps: List[Dict], days: int = 10) -> List[Dict]:
    out = []
    now = datetime.now(timezone.utc)
    for s in snaps:
        nxt = s.get("next_release_utc")
        if not nxt:
            continue
        try:
            dt = datetime.fromisoformat(str(nxt).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            continue
        if now <= dt <= now + timedelta(days=days):
            out.append(rec(f"event_{s.get('event')}_{dt.date().isoformat()}", 5, "Events",
                           f"{s.get('label')} am {dt.strftime('%d.%m.')} um {dt.strftime('%H:%M')} UTC",
                           "Das Event-Setup sammelt dabei Daten (Paper). Live erst nach bestandener "
                           "Event-Prüfung (mind. 12 Events, t ≥ 2)."))
    return out


def rec_cutoff(since: Optional[str], n_after: int) -> List[Dict]:
    if not since:
        return [rec("cutoff_off", 3, "Bewertung", "Kein Bewertungs-Stichtag gesetzt",
                    "Lernlauf und Live-Tore mischen Trades unter alten und neuen Regeln. Im Leitstand "
                    "einen Stichtag setzen (Standard: Start der Kostenregeln).")]
    if n_after < 100:
        return [rec("cutoff_young", 5, "Bewertung", f"Bewertung seit {since[:10]}: {n_after} neue Trades",
                    "Für ein erstes Urteil über die Verbesserungen braucht es etwa 100–200 neue Trades. "
                    "Bis dahin: laufen lassen, nicht nachjustieren.")]
    return []


# ---------------------------------------------------------------------------
# Bereiche
# ---------------------------------------------------------------------------
async def now_section(db, engine) -> Dict:
    from services import review_allocation, system_doctor
    cfg = dict(getattr(engine, "config", None) or {})
    try:
        from services import ai_role
        role = "pruefer" if ai_role.is_pruefer(cfg) else (cfg.get("ai_role") or "trader")
    except Exception:  # noqa: BLE001
        role = cfg.get("ai_role")
    open_rows = await db.auto_trades.find(
        {"strategy_id": "ai_trader", "status": "open"},
        {"_id": 0, "id": 1, "symbol": 1, "side": 1, "setup": 1, "mode": 1, "signal_source": 1,
         "opened_at": 1, "data_collection": 1, "guard_shadow.guard": 1, "entry": 1}).to_list(60)
    trades = [{"symbol": t.get("symbol"), "side": t.get("side"), "setup": t.get("setup"),
               "mode": t.get("mode"), "since": t.get("opened_at"), "reason": trade_reason(t)}
              for t in sorted(open_rows, key=lambda x: str(x.get("opened_at")), reverse=True)]
    signals = []
    try:
        from services.signal_broker import signal_broker
        for s in signal_broker.open_signals()[:10]:
            signals.append({"symbol": s.get("symbol"), "setup": s.get("setup"), "side": s.get("side"),
                            "expires_at": s.get("expires_at"), "status": s.get("status")})
    except Exception:  # noqa: BLE001
        pass
    decs = await db.ai_decisions.find({}, {"_id": 0, "ts": 1, "symbol": 1, "action": 1, "setup": 1,
                                           "confidence": 1, "blocked_by": 1, "reasoning": 1,
                                           "reason": 1}).sort("ts", -1).limit(5).to_list(5)
    flow = await system_doctor.flow_data(db, hours=24)
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    n_today = await db.ai_decisions.count_documents({"ts": {"$gte": day}})
    return {"activity": activity_text(cfg, bool(getattr(engine, "_analyzing", False)),
                                      getattr(engine, "next_run", None), role),
            "enabled": bool(cfg.get("enabled")), "role": role,
            "model": getattr(engine, "_effective_model", None) or cfg.get("model"),
            "last_run": getattr(engine, "last_run", None), "next_run": getattr(engine, "next_run", None),
            "open_trades": trades, "open_signals": signals,
            "last_decisions": [{"ts": d.get("ts"), "text": decision_sentence(d)} for d in decs],
            "flow_24h": flow, "decisions_today": n_today, "reviews": review_allocation.stats()}


async def progress_section(db) -> Dict:
    from services import ai_playbook, evaluation_cutoff, live_watchdog, research_pipeline, setup_lifecycle
    since = evaluation_cutoff.cached_since()
    cands = await research_pipeline.list_candidates(db, limit=20)
    stats = await ai_playbook.setup_stats(db, days=60, paper_only=True)
    rows = research_pipeline.setup_progress_rows(stats, {}, setup_lifecycle.MIN_TRADES_PROMOTE)
    verdicts = await live_watchdog.load(db)
    lo = None
    if since:
        try:
            lo = (datetime.fromisoformat(since) - timedelta(days=30)).isoformat()
        except ValueError:
            lo = None
    trades = await db.auto_trades.find(
        {"strategy_id": "ai_trader", "status": "closed", **({"opened_at": {"$gte": lo}} if lo else {})},
        {"_id": 0, "opened_at": 1, "realized_pnl": 1, "risk_usdt": 1, "fees_paid": 1, "liquidated": 1,
         "side": 1, "edge_filter.bias": 1, "entry_market_snapshot.features.daily_bias": 1}).to_list(30000) \
        if lo else []
    proven = ([r["setup"] for r in rows if r["state"] == "live-reif"]
              + [v["name"] for v in verdicts.values() if v.get("state") == "Vorteil belegt"]
              + [c["title"] for c in cands if c.get("stage") in ("bestanden", "uebernommen")])
    from services import daily_report
    try:
        from services import market_climate
        climate = await market_climate.report(db)
    except Exception as e:  # noqa: BLE001 – Zusatz-Info, darf den Leitstand nie stören
        climate = {"available": False, "text": f"Markt-Klima nicht verfügbar ({type(e).__name__})"}
    return {"proven_count": len(proven), "proven": proven[:10], "candidates": cands, "climate": climate,
            "setups": rows[:12], "live_strategies": list(verdicts.values()),
            "before_after": before_after(trades, since), "evaluation_since": since,
            "daily": await daily_report.history(db, days=30)}


async def new_section(db, days: int = NEW_DAYS) -> List[Dict]:
    from services import deep_explore, night_research
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    items: List[Dict] = []
    for m in await db.ai_chat.find({"ts": {"$gte": since}, "role": {"$in": list(FEED_ROLES)}},
                                   {"_id": 0, "ts": 1, "role": 1, "text": 1}) \
            .sort("ts", -1).limit(40).to_list(40):
        items.append({"ts": m.get("ts"), "kind": m.get("role"), "text": _short(m.get("text"), 220)})
    for r in await night_research.last_runs(db, limit=7):
        if str(r.get("created_at") or "") < since:
            continue
        s = r.get("summary") or {}
        res = (f"fertig – {s.get('champions', s.get('candidates', 0))} Champion(s)"
               if r.get("status") == "done" else r.get("status"))
        items.append({"ts": r.get("finished_at") or r.get("created_at"), "kind": "suche",
                      "text": f"{r.get('label')}: {res}"})
    doc = await db.settings.find_one({"_id": "deep_explore_best"}) or {}
    cur, _ = deep_explore.split_best(doc)
    for c in cur:
        if str(c.get("found_at") or "") >= since:
            ev = c.get("evidence") or {}
            items.append({"ts": c.get("found_at"), "kind": "champion",
                          "text": f"Endlossuche-Champion: {' + '.join(c.get('labels') or [])} "
                                  f"(t {ev.get('t')}, Hürde {ev.get('t_required')})"})
    lab = await db.settings.find_one({"_id": "setup_backtest_state"}, {"auto": 1}) or {}
    for h in ((lab.get("auto") or {}).get("history") or [])[-5:]:
        if str(h.get("at") or "") >= since:
            items.append({"ts": h.get("at"), "kind": "lab",
                          "text": f"Lab-Lauf: {h.get('passed')} von {h.get('tested')} Setups bestanden"
                                  + (f" – Fehler: {_short(h.get('error'), 80)}" if h.get("error") else "")})
    rep = await db.settings.find_one({"_id": "ai_research_report"}, {"summary": 1, "ts": 1}) or {}
    if rep.get("summary") and str(rep.get("ts") or "") >= since:
        items.append({"ts": rep.get("ts"), "kind": "forschungsbericht", "text": _short(rep.get("summary"), 260)})
    items.sort(key=lambda x: str(x.get("ts") or ""), reverse=True)
    return items[:40]


async def defects_section(db, engine=None, scanner=None) -> Dict:
    from services import system_doctor
    doc = await system_doctor.latest(db)
    if not doc:
        doc = await system_doctor.run(db, engine, scanner, run_selftest=False)
    return doc


def _de(x, digits: int = 0) -> str:
    """Zahl im deutschen Format (1.234,5)."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        v = 0.0
    return f"{v:,.{digits}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def rec_credit_runway(snap: Optional[Dict], top: Optional[Dict]) -> List[Dict]:
    """KI-Guthaben reicht nur noch wenige Tage (rein). `top` = größter Verbraucher heute."""
    from services.key_credits import RUNWAY_WARN_DAYS
    rows = [r for r in (snap or {}).get("keys") or []
            if r.get("runway_days") is not None and r.get("total_credits")]
    low = sorted((r for r in rows if r["runway_days"] < RUNWAY_WARN_DAYS), key=lambda r: r["runway_days"])
    if not low:
        return []
    r = low[0]
    days = r["runway_days"]
    who = ""
    if top and top.get("role"):
        from services.notifications import ROLE_LABELS
        who = (f" Größter Verbraucher heute: {ROLE_LABELS.get(top['role'], top['role'])} mit "
               f"~{_de(top.get('tokens', 0) / 1e6, 1)} Mio. Tokens ({top.get('model') or '?'}).")
    return [rec(f"credit_runway_{int(days)}", 2 if days < 7 else 3, "KI-Kosten",
                f"KI-Guthaben reicht noch ~{_de(days, 0)} Tage",
                f"{r.get('label')}: {_de(r.get('remaining', 0), 2)} $ übrig, Verbrauch ~{_de(r.get('burn_usd_day', 0), 2)} $ "
                f"pro Tag.{who} Danach übernehmen die Gratis-Ersatzmodelle der Rollen. Optionen: Guthaben "
                "aufladen (openrouter.ai/settings/credits) oder im KI-Team für die teuerste Rolle ein "
                "günstigeres Hauptmodell wählen.", None)]


HARVEST_ENTER_DAY = 0.0015      # Ø 3 Tage > 0,15 %/Tag (= 0,05 % je 8 h, ~55 % p. a.)


def funding_harvest(docs: List[Dict], last_day_ms: int) -> List[Dict]:
    """Coins mit sehr hohem Funding in den letzten 3 abgeschlossenen Tagen (rein).

    Messung 17.11.2026 (Portfolio-Coins, Binance-Funding seit 2020): Kassa kaufen +
    Perp leerverkaufen bei Ø > 0,05 %/8 h, Ausstieg unter 0,01 %/8 h -> im Schnitt
    +4,7 % je Episode nach Kosten, 89 % der Episoden im Plus; fast nur in
    Hype-Phasen (2021 +33 %, seit 2025 nur ~0,5 % p. a.)."""
    day = 86_400_000
    out = []
    for d in docs or []:
        days = d.get("days") or {}
        vals = [days.get(str(last_day_ms - k * day)) for k in range(3)]
        if any(v is None for v in vals):
            continue
        avg = sum(float(v) for v in vals) / 3.0
        if avg > HARVEST_ENTER_DAY:
            out.append({"symbol": d.get("_id"), "avg_day_pct": round(avg * 100, 3),
                        "annual_pct": round(avg * 365 * 100, 0)})
    return sorted(out, key=lambda x: -x["avg_day_pct"])


def rec_harvest(cands: List[Dict], last_day_ms: Optional[int]) -> List[Dict]:
    if not cands:
        return []
    top = ", ".join(f"{c['symbol'].replace('USDT', '')} ({c['annual_pct']:.0f} % p. a.)" for c in cands[:5])
    return [rec(f"funding_harvest_{last_day_ms}", 3, "Chance", f"Funding-Ernte möglich: {len(cands)} Coin(s)",
                f"Sehr hohes Funding in den letzten 3 Tagen: {top}. Methode: den Coin an der Börse kaufen (Kassa) "
                "und den Perpetual gleich groß leerverkaufen – das Funding fließt dir zu, Kursbewegungen heben "
                "sich auf. Rückrechnung seit 2020: im Schnitt +4,7 % je Episode nach Kosten, 89 % im Plus – "
                "lohnt fast nur in Hype-Phasen. Aussteigen, wenn das Funding unter 0,01 % je 8 h fällt. Die Website "
                "führt das nicht selbst aus (Kassa-Handel ist nicht angebunden).", None)]


def rec_portfolio(pf: Optional[Dict]) -> List[Dict]:
    """Empfehlung zum Portfolio (rein): Tagesplan mit neuen Orders bzw. Einrichtung."""
    pf = pf or {}
    st = pf.get("state")
    if not (pf.get("config") or {}).get("enabled", True):
        return []
    if not st:
        return [rec("portfolio_setup", 2, "Portfolio", "Portfolio wird eingerichtet",
                    "Die Handels-Schiene auf Tagesebene (Trendfolge + Funding-Korb) lädt beim ersten Lauf "
                    "die Tagesdaten seit 2020. Danach steht der Verlauf im Reiter „Portfolio“.", None)]
    acts = [p for p in st.get("plan") or [] if p.get("kind") != "stop"]
    if not acts:
        return []
    day = datetime.fromtimestamp((st.get("last_ts") or 0) / 1000, tz=timezone.utc).strftime("%d.%m.")
    return [rec(f"portfolio_plan_{st.get('last_ts')}", 2, "Portfolio",
                f"Portfolio: {len(acts)} neue Order(s) im Tagesplan vom {day}",
                " · ".join(p["text"] for p in acts[:4]) + (" …" if len(acts) > 4 else "")
                + " Das Portfolio läuft als Paper-Konto; Details im Reiter „Portfolio“.", None)]


async def recommendations(db) -> List[Dict]:
    from services import (econ_event, evaluation_cutoff, live_watchdog, night_research,
                          research_pipeline, ai_playbook, setup_lifecycle)
    from services import deep_explore
    out: List[Dict] = []
    out += rec_live_strategies(await live_watchdog.load(db))
    out += rec_candidates(await research_pipeline.list_candidates(db, limit=20))
    try:
        from core import timeutil
        from services import key_credits
        top = await db.ai_token_usage.find({"date": timeutil.berlin_date()}) \
            .sort("tokens", -1).limit(1).to_list(1)
        out += rec_credit_runway(key_credits.snapshot(), top[0] if top else None)
    except Exception:  # noqa: BLE001 – Zusatz, darf die Empfehlungen nie stören
        pass
    try:
        from services import portfolio_engine
        pfs = await portfolio_engine.get_state(db)
        out += rec_portfolio(pfs)
        last = (pfs.get("state") or {}).get("last_ts")
        if last:
            docs = await db[portfolio_engine.FUNDING].find({}, {"days": 1}).to_list(200)
            out += rec_harvest(funding_harvest(docs, int(last)), int(last))
    except Exception:  # noqa: BLE001 – Zusatz, darf die Empfehlungen nie stören
        pass
    night = await night_research.get_state(db)
    w_ok, w_why = night_research.worker_status()
    lab = await db.settings.find_one({"_id": "setup_backtest_state"}, {"auto": 1}) or {}
    doc = await db.settings.find_one({"_id": "deep_explore_best"}) or {}
    cur, _ = deep_explore.split_best(doc)
    week = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    out += rec_research(night, w_ok, w_why, lab.get("auto") or {},
                        sum(1 for c in cur if str(c.get("found_at") or "") >= week))
    stats = await ai_playbook.setup_stats(db, days=60, paper_only=True)
    out += rec_setups(research_pipeline.setup_progress_rows(stats, {}, setup_lifecycle.MIN_TRADES_PROMOTE))
    snaps = list(econ_event.status_snapshots().values())
    try:
        from services import fomc_event
        nd = fomc_event.next_decision()
        if nd:
            snaps.append({"event": "fomc", "label": "FOMC-Zinsentscheid", "next_release_utc": nd.isoformat()})
    except Exception:  # noqa: BLE001
        pass
    out += rec_events(snaps)
    since = evaluation_cutoff.cached_since()
    n_after = await db.auto_trades.count_documents(
        {"strategy_id": "ai_trader", "status": "closed", "opened_at": {"$gte": since}}) if since else 0
    out += rec_cutoff(since, n_after)
    dis = dismissed_active(await db.settings.find_one({"_id": DISMISS_ID}))
    visible = [r for r in out if _key(r["id"]) not in dis]
    visible.sort(key=lambda r: (r["prio"], r["area"], r["title"]))
    for r in visible:
        r["dismissable"] = True
    return visible


async def _safe(name: str, fn: Callable, default):
    try:
        return await fn()
    except Exception as e:  # noqa: BLE001 – ein Bereich darf das Fenster nicht leeren
        logger.warning(f"Leitstand-Bereich {name} fehlgeschlagen: {e}")
        return {"error": f"{type(e).__name__}: {str(e)[:160]}"} if isinstance(default, dict) else default


async def _portfolio_line(db) -> Optional[str]:
    from services import portfolio_engine
    return portfolio_engine.summary_line((await portfolio_engine.get_state(db)).get("state"))


async def build(db, engine=None, scanner=None) -> Dict:
    from services import evaluation_cutoff
    dis = dismissed_active(await db.settings.find_one({"_id": DISMISS_ID}))
    return {
        "generated_at": _iso_now(),
        "evaluation": await evaluation_cutoff.status(db),
        "jetzt": await _safe("jetzt", lambda: now_section(db, engine), {}),
        "fortschritt": await _safe("fortschritt", lambda: progress_section(db), {}),
        "neu": await _safe("neu", lambda: new_section(db), []),
        "maengel": await _safe("maengel", lambda: defects_section(db, engine, scanner), {}),
        "empfehlungen": await _safe("empfehlungen", lambda: recommendations(db), []),
        "dismissed_count": len(dis),
        "portfolio": await _safe("portfolio", lambda: _portfolio_line(db), None),
    }


async def summary(db) -> Dict:
    """Kopfzeilen-Anzeige: Ampel + Anzahl offener Mängel (billig)."""
    from services import system_doctor
    doc = await system_doctor.latest(db) or {}
    c = doc.get("counts") or {}
    return {"level": doc.get("level") or "unbekannt", "counts": c,
            "open": int(c.get("kritisch", 0)) + int(c.get("warnung", 0)),
            "generated_at": doc.get("generated_at")}


async def dismiss(db, rid: str, days: int = 14) -> Dict:
    days = max(1, min(180, int(days or 14)))
    until = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
    await db.settings.update_one({"_id": DISMISS_ID}, {"$set": {f"items.{_key(rid)}": until}}, upsert=True)
    return {"id": rid, "until": until}


async def undismiss_all(db) -> Dict:
    await db.settings.update_one({"_id": DISMISS_ID}, {"$set": {"items": {}}}, upsert=True)
    return {"cleared": True}
