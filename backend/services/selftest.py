"""Selbsttest: prüft mit bekannten Eingaben, ob die Kernlogik das Erwartete liefert.

Zweck (15.11.2026): Nach jedem Deploy soll in Sekunden sichtbar sein, ob die
Teile, an denen Geld hängt, noch richtig rechnen – ohne Testumgebung, ohne
Handel, ohne Schreibzugriff. Jede Prüfung ist eine kleine Funktion mit festem
Sollwert; schlägt eine fehl, steht im Ergebnis, was erwartet wurde.

  run_logic()        reine Rechenprüfungen (kein Netz, keine DB) – läuft auch
                     offline: `python -m scripts.systemcheck selftest`
  run_all(db)        zusätzlich Laufzeitprüfungen (DB erreichbar, Konfiguration
                     lesbar und plausibel, Hintergrund-Schleifen) – Endpunkt
                     GET /api/selftest (Admin) und einmal beim Start im Log.

Neue Prüfung: Funktion schreiben und in LOGIC_CHECKS bzw. RUNTIME_CHECKS eintragen.
"""
import logging
import time
from typing import Callable, Dict, List, Tuple

logger = logging.getLogger(__name__)


def _expect(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def _candles(prices: List[float]) -> List[Dict]:
    out, ts = [], 1_700_000_000_000
    for i, p in enumerate(prices):
        prev = prices[i - 1] if i else p
        out.append({"timestamp": ts + i * 60_000, "open": prev, "high": max(prev, p),
                    "low": min(prev, p), "close": p, "volume": 10.0})
    return out


class _Dummy:
    STRATEGY_ID = "selftest"


def _reference_trade(extra: Dict) -> Dict:
    """Ein Long bei 100, Stop 2 % (98), Ziel 2R (104); Kurs steigt stetig."""
    from services.backtester import simulate_pair
    c = _candles([100.0] * 100 + [100.0 + 0.1 * i for i in range(1, 80)])
    cfg = {"max_capital": 100.0, "leverage": 2, "fee_percent": 0.0, "sl_mode": "percent",
           "sl_fixed_percent": 2.0, "tp1_crv": 1.0, "tp_full_crv": 2.0, **extra}
    prov = lambda i: {"type": "LONG", "entry_price": c[i]["close"]} if i == 100 else None  # noqa: E731
    return simulate_pair(_Dummy(), c, "BTCUSDT", {}, cfg, signal_provider=prov)


# ----------------------------- Rechenprüfungen -----------------------------
def check_backtest_reference() -> str:
    r = _reference_trade({"slippage_percent": 0.0})
    _expect(r["trades"] == 1 and r["wins"] == 1, f"erwartet 1 Gewinn-Trade, ist {r['trades']}/{r['wins']}")
    _expect(r["pnl"] > 0, f"Gewinn-Trade mit PnL {r['pnl']}")
    _expect(0.5 < r["avg_r"] <= 2.01, f"Ergebnis {r['avg_r']} R außerhalb 0,5–2 R")
    return f"1 Trade, {r['pnl']:+.2f} USDT, {r['avg_r']:+.2f} R"


def check_costs_are_charged() -> str:
    free = _reference_trade({"slippage_percent": 0.0})
    slip = _reference_trade({"slippage_percent": 0.05})
    fee = _reference_trade({"slippage_percent": 0.0, "fee_percent": 0.06})
    _expect(slip["slippage"] > 0 and slip["pnl"] < free["pnl"], "Slippage wird nicht abgezogen")
    _expect(fee["fees"] > 0 and fee["pnl"] < free["pnl"], "Gebühren werden nicht abgezogen")
    return f"Gebühr −{free['pnl'] - fee['pnl']:.2f}, Slippage −{free['pnl'] - slip['pnl']:.2f} USDT"


def check_stop_loss_limits_loss() -> str:
    from services.backtester import simulate_pair
    c = _candles([100.0] * 100 + [100.0 - 0.2 * i for i in range(1, 60)])
    cfg = {"max_capital": 100.0, "leverage": 2, "fee_percent": 0.0, "slippage_percent": 0.0,
           "sl_mode": "percent", "sl_fixed_percent": 2.0, "tp1_crv": 1.0, "tp_full_crv": 2.0}
    prov = lambda i: {"type": "LONG", "entry_price": c[i]["close"]} if i == 100 else None  # noqa: E731
    r = simulate_pair(_Dummy(), c, "BTCUSDT", {}, cfg, signal_provider=prov)
    _expect(r["trades"] == 1 and r["losses"] == 1, "fallender Kurs muss den Stop auslösen")
    _expect(-1.05 <= r["avg_r"] <= -0.95, f"Stop-Verlust {r['avg_r']} R statt −1 R")
    return f"Stop ausgelöst bei {r['avg_r']:+.2f} R"


def check_significance_gate() -> str:
    from services import evidence_stats as es
    noise = {"r_n": 100, "r_sum": 5.0, "r_sq": 121.0}        # Ø +0,05 R, Streuung 1,1
    edge = {"r_n": 200, "r_sum": 80.0, "r_sq": 274.0}        # Ø +0,40 R
    _expect(not es.significance(noise)["passed"], "Rauschen gilt als belegter Vorteil")
    _expect(es.significance(edge, n_trials=50)["passed"], "klarer Vorteil wird nicht erkannt")
    _expect(es.required_t(100) > es.required_t(1), "Hürde steigt nicht mit der Zahl der Versuche")
    return f"Hürde t={es.required_t(1):.2f} (1 Versuch) bis {es.required_t(100):.2f} (100 Versuche)"


def check_walk_forward_fails_on_loss() -> str:
    from services import robustness
    robust = robustness.parse_config({"walk_forward": {"enabled": True}})
    _expect(robust["wf_strict"] and robust["vault_pct"] > 0, "Walk-Forward-Standard nicht streng")
    v = robustness.wf_verdict({"trades": 80, "pnl": -12.0, "r_n": 80, "r_sum": -8.0, "r_sq": 90.0}, robust)
    _expect(not v["passed"], "Verlust auf Testdaten gilt als bestanden")
    return f"Verlust fällt durch; Tresor-Daten {robust['vault_pct']:.0f} %"


def check_live_gate() -> str:
    from services import signal_broker as sb, source_stats as ss
    cfg = dict(sb.DEFAULTS)
    lucky = {"n": 6, "wins": 6, "r_n": 6, "r_sum": 3.6, "r_sq": 2.16, "avg_r": 0.6,
             "shrunk_r": ss.shrunk(0.6, 6), "live_r_n": 0, "live_r_sum": 0.0}
    ok, why, _ = ss.maturity(lucky, cfg)
    _expect(not ok, "6 Glücks-Trades reichen für Live")
    return f"Live erst ab {cfg['signal_min_ki_trades']} Trades mit belegtem Vorteil ({why})"


def check_edge_readiness() -> str:
    from services import edge_filter as ef
    rows = [{"opened_at": f"2026-01-01T00:{i:02d}:00", "realized_pnl": 45 if i % 4 == 0 else -13,
             "risk_usdt": 10, "edge_filter": {"ok": True}} for i in range(60)]
    out = ef.readiness(rows)
    _expect(out["ready"] is False, "stark streuende 60 Trades gelten als live-bereit")
    return f"nicht bereit bei t={out['t']} (nötig {ef.READY_MIN_T:.0f})"


def check_setups() -> str:
    from services import ai_playbook as pb, setup_asset_class as ac
    enum = pb.SETUP_ENUM.split("|")
    _expect(len(enum) >= 5, f"nur {len(enum)} Setups angeboten")
    _expect(not set(enum) & set(ac.RETIRED), "stillgelegtes Setup wird der KI angeboten")
    for cls in (ac.CRYPTO, ac.FOREX):
        _expect(ac.allowed_setups(cls, pb.all_setups()), f"keine Setups für {cls}")
    return f"{len(enum)} Setups aktiv, stillgelegt: {', '.join(ac.RETIRED) or '–'}"


def check_strategies() -> str:
    from strategies.registry import registry
    ids = registry.list_ids()
    _expect(len(ids) >= 10, f"nur {len(ids)} Strategien geladen")
    for sid in ids:
        _expect(callable(getattr(registry.get(sid), "check_signal", None)), f"{sid} ohne check_signal")
    return f"{len(ids)} Strategien geladen"


def check_instruments_and_fees() -> str:
    from core import instruments
    from services import fee_model, history_sources as hs
    _expect(instruments.get("BTCUSDT") is not None, "BTCUSDT unbekannt")
    fee = fee_model.fee_percent_for("BTCUSDT", 0.06, 1000.0)
    _expect(0.0 < float(fee) < 0.5, f"Krypto-Gebühr {fee} % unplausibel")
    info = hs.source_info("BTCUSDT")
    _expect(info["volume"] == "echt" and info["label"], "Datenquelle BTCUSDT unklar")
    return f"BTC-Gebühr {float(fee):.3f} %, Kerzen von {info['label']}"


def check_risk_defaults() -> str:
    from services import position_sizing
    r = float(position_sizing.DEFAULTS["risk_per_trade_pct"])
    _expect(0 < r <= 2.0, f"Standard-Risiko {r} % je Trade außerhalb 0–2 %")
    return f"Standard-Risiko {r} % je Trade"


CALENDAR_MIN_DAYS = 60


def check_event_calendar() -> str:
    """Event-Kalender (CPI/NFP/PPI/PCE/FOMC) muss noch mindestens 60 Tage in
    die Zukunft reichen – sonst feuern die Event-Setups stillschweigend nie."""
    from datetime import date, timedelta
    from services import econ_event
    from services.structure_indicators import FOMC_MEETINGS
    horizon = (date.today() + timedelta(days=CALENDAR_MIN_DAYS)).isoformat()
    lasts = {"CPI": max(econ_event.CPI_RELEASES), "NFP": max(econ_event.NFP_RELEASES),
             "PPI": max(econ_event.PPI_RELEASES), "PCE": max(econ_event.PCE_RELEASES),
             "FOMC": max(d2 for _, d2 in FOMC_MEETINGS)}
    short = [f"{k} bis {v}" for k, v in lasts.items() if v < horizon]
    _expect(not short, "Event-Kalender läuft bald aus (Termine nachtragen): " + ", ".join(short))
    return "Termine bis " + min(lasts.values())


def check_leverage_cap() -> str:
    """Liquidation liegt mindestens 2× so weit weg wie der Stop."""
    from services.backtester import liq_safe_max_leverage
    cfg = {"maintenance_margin_rate": 0.5}
    lev = liq_safe_max_leverage(cfg, 100.0, 99.0)          # SL 1 %
    _expect(lev is not None, "Hebel-Deckel fehlt")
    liq_dist = 1.0 / lev - 0.005
    _expect(liq_dist + 1e-9 >= 0.02, f"Liquidation nur {liq_dist * 100:.2f} % entfernt bei 1 % SL")
    return f"SL 1 % -> max. {lev:g}x (Liquidation {liq_dist * 100:.1f} % entfernt)"



def check_evaluation_cutoff() -> str:
    """Bewertungs-Stichtag schneidet alte Trades ab, ohne das Fenster zu verlängern."""
    from services import evaluation_cutoff as ec
    lb = "2026-11-01T00:00:00+00:00"
    _expect(ec.apply(lb, "2026-11-15T21:00:00+00:00") == "2026-11-15T21:00:00+00:00",
            "Stichtag wird nicht angewendet")
    _expect(ec.apply(lb, "2026-10-01T00:00:00+00:00") == lb, "Stichtag verlängert das Rückschau-Fenster")
    _expect(ec.apply(lb, "ungültig") == lb, "ungültiger Stichtag kippt die Abfrage")
    return "späterer Zeitpunkt aus Fenster und Stichtag gilt"


def check_forward_verdict() -> str:
    """Kandidaten-Vorwärtstest: Glück besteht nicht, belegter Vorteil schon."""
    from datetime import datetime, timezone
    from services import research_pipeline as rp
    now = datetime.now(timezone.utc).isoformat()
    lucky = rp.r_stats(12, 12 * 0.6, 12 * 1.4)            # stark, aber zu wenige Trades
    _expect(rp.verdict(lucky, now) == "vorwaertstest", "12 Trades reichen fälschlich für ein Urteil")
    good = rp.r_stats(60, 60 * 0.35, 60 * 1.1)
    _expect(rp.verdict(good, now) == "bestanden", "belegter Vorteil wird nicht erkannt")
    bad = rp.r_stats(60, -60 * 0.2, 60 * 1.0)
    _expect(rp.verdict(bad, now) == "durchgefallen", "Verlierer gilt nicht als durchgefallen")
    return "Urteil erst ab 30 Trades, Untergrenze > 0 nötig"


def check_review_allocation() -> str:
    """KI-Prüfung nur dort, wo die KI-Auswahl nachweislich hilft (mit Stichprobe)."""
    from services import review_allocation as ra
    no_value = {"taken": {"n": 20, "avg_r": -0.38}, "rejected": {"n": 177, "avg_r": -0.30}}
    picks = [ra.decide(no_value, n)[0] for n in range(1, 10)]
    _expect(sum(picks) == 3, f"Stichprobe falsch ({sum(picks)} von 9 statt 3)")
    helps = {"taken": {"n": 20, "avg_r": 0.25}, "rejected": {"n": 40, "avg_r": -0.30}}
    _expect(all(ra.decide(helps, n)[0] for n in range(1, 6)), "hilfreiche KI-Prüfung wird gespart")
    _expect(ra.decide(None, 1)[0], "ohne Daten wird nicht geprüft")
    return "ohne Mehrwert nur jede 3. Prüfung, mit Mehrwert immer"



def check_pool_data() -> str:
    """Multi-Core-Pool bewertet nur die Daten, mit denen er gestartet wurde."""
    from services import parallel_sim
    train = {"BTCUSDT": [{"c": 1}], "ETHUSDT": [{"c": 2}]}
    test = {"BTCUSDT": [{"c": 3}], "ETHUSDT": [{"c": 4}]}

    class _Pool:  # Attrappe: nur die Buchführung wird geprüft, kein Prozess
        pass
    pool = _Pool()
    parallel_sim._POOL_DATA[id(pool)] = train
    try:
        _expect(parallel_sim.pool_has_data(pool, train), "Pool erkennt seine Trainingsdaten nicht")
        _expect(not parallel_sim.pool_has_data(pool, test), "Pool würde Testdaten auf Training rechnen")
        _expect(not parallel_sim.pool_has_data(pool, {"BTCUSDT": train["BTCUSDT"], "SOLUSDT": [{}]}),
                "Pool würde ein fremdes Symbol rechnen")
    finally:
        parallel_sim._POOL_DATA.pop(id(pool), None)
    return "Test- und Tresor-Daten werden nie im Trainings-Pool gerechnet"


def check_champion_checks() -> str:
    """Strenge Champion-Prüfung: Tresor, Training in R, Rückwärtstest, Versuchs-Konto."""
    from services import champion_checks as cc, evidence_stats

    def m(n, mean, sd=1.0):
        return {"trades": n, "pnl": mean * n, "r_n": n, "r_sum": mean * n,
                "r_sq": n * (sd * sd + mean * mean)}
    _expect(not cc.vault_ok(m(4, 0.5), 3)[0], "Tresor besteht mit 4 Trades")
    _expect(not cc.vault_ok(m(20, -0.1), 3)[0], "Tresor besteht mit negativem Ø R")
    _expect(cc.vault_ok(m(20, 0.2), 3)[0], "Tresor lehnt klaren Vorteil ab")
    _expect(not cc.train_ok({**m(100, -0.05), "pnl": 300})[0], "Training mit negativem R besteht")
    _expect(not cc.back_verdict(m(60, -0.2), 180)["passed"], "Rückwärtstest besteht trotz Verlust")
    _expect(cc.back_verdict(m(5, -0.2), 180)["state"] == "nicht_pruefbar", "5 Trades gelten als Urteil")
    _expect(cc.back_verdict(m(60, 0.2), 180)["state"] == "bestanden", "Rückwärtstest lehnt Vorteil ab")
    _expect(evidence_stats.required_t(100 + 5000) > evidence_stats.required_t(100),
            "Versuchs-Konto erhöht die Hürde nicht")
    return "Tresor, Training in R, Rückwärtstest und Versuchs-Konto urteilen richtig"


def check_portfolio_core() -> str:
    """Portfolio-Rechenkern: gleiches Ergebnis bei gleichem Input, kein Blick in die Zukunft."""
    from services import portfolio_core as pc
    day, t0 = pc.DAY_MS, 1_546_300_800_000
    candles, funding = {}, {}
    for k in range(13):
        name = "BTCUSDT" if k == 12 else f"T{k}USDT"
        x, p, rows, fs = 1000 + k * 77, 100.0, [], {}
        for i in range(260):
            x = (x * 48271) % 2147483647
            u = x / 2147483647
            o = p
            p = p * (1 + (0.004 if (i // 60) % 2 == 0 else -0.004) + (u - 0.5) * 0.06)
            rows.append([t0 + i * day, o, max(o, p) * 1.01, min(o, p) * 0.99, p])
            fs[t0 + i * day] = 0.0001 * ((k % 5) - 2)
        candles[name], funding[name] = rows, fs
    a = pc.run(candles, funding, None)
    _expect(pc.run(candles, funding, None)["equity"] == a["equity"], "Replay ist nicht deterministisch")
    short = pc.run({s: b[:200] for s, b in candles.items()}, funding, None)
    _expect([c[1] for c in a["curve"][:len(short["curve"])]] == [c[1] for c in short["curve"]],
            "spätere Daten ändern den früheren Verlauf (Blick in die Zukunft)")
    _expect(a["trend_trades"]["trades"] > 0 and a["carry_rebalances"] > 0, "Kern handelt nicht")
    losers = [t["r"] for t in a["trades"] if t["r"] < 0]
    _expect(not losers or min(losers) > -4.0, "ein Verlust-Trade kostet ein Vielfaches des geplanten Risikos")
    return f"Replay deterministisch, ohne Zukunftsblick ({a['trend_trades']['trades']} Trades im Test)"


def check_portfolio_live() -> str:
    """Live-Ausführung: keine stille Vergrößerung, Liquidation hinter dem Stop, Not-Aus blockt."""
    from services import portfolio_live as pl
    near = {"qty_step": 1, "min_qty": 10, "max_lev": 50}
    _expect(not pl.size_qty(15.0, 4.0, near, 2.0)["ok"], "Order unter Mindestmenge würde stillschweigend vergrößert")
    for stop in (0.02, 0.08, 0.2, 0.4):
        lev = pl.leverage_for(stop)
        _expect(lev == 1 or 1.0 / lev >= 2 * stop, f"Hebel {lev} liquidiert vor dem Stop ({stop:.0%})")
    cfg = pl.normalize_config({"mode": "live", "capital": 100, "risk_pct": 1, "halted": True})
    pf = {"equity": 10000.0, "risk_pct": 0.25, "last_ts": 1, "positions": [
        {"sleeve": "trend", "symbol": "BTCUSDT", "side": "LONG", "entry": 100.0, "stop": 92.0, "init_stop": 92.0,
         "entry_ts": 1, "notional": 1000.0}]}
    meta = {"BTCUSDT": {"qty_step": 0.001, "min_qty": 0.001, "max_lev": 100}}
    acts = pl.plan_actions(cfg, pf, [], set(), [], {"BTCUSDT": 100.0}, meta, 500.0)
    _expect(not [a for a in acts if a["kind"] == "open"], "Not-Aus verhindert keine neuen Einstiege")
    cfg["halted"] = False
    o = [a for a in pl.plan_actions(cfg, pf, [], set(), [], {"BTCUSDT": 100.0}, meta, 500.0) if a["kind"] == "open"]
    _expect(len(o) == 1 and o[0]["sl"] == 92.0, "neue Position ohne Stop geplant")
    _expect(abs(o[0]["risk"] - 1.0) < 0.05, f"Risiko {o[0]['risk']} statt 1 USDT")
    return "Mindestmenge, Hebel, Stop und Not-Aus der Live-Ausführung stimmen"


LOGIC_CHECKS: List[Tuple[str, str, Callable[[], str]]] = [
    ("backtest_reference", "Backtest rechnet einen bekannten Trade richtig", check_backtest_reference),
    ("costs", "Gebühren und Slippage werden abgezogen", check_costs_are_charged),
    ("stop_loss", "Stop-Loss begrenzt den Verlust auf 1 R", check_stop_loss_limits_loss),
    ("significance", "Zufall gilt nicht als Vorteil", check_significance_gate),
    ("walk_forward", "Verlust auf Testdaten fällt durch", check_walk_forward_fails_on_loss),
    ("live_gate", "Glückssträhne geht nicht live", check_live_gate),
    ("edge_readiness", "Live-Freigabe verlangt belegten Vorteil", check_edge_readiness),
    ("setups", "KI-Setups vollständig, stillgelegte nicht angeboten", check_setups),
    ("strategies", "Alle Strategien laden", check_strategies),
    ("instruments", "Instrumente, Gebühren, Datenquellen", check_instruments_and_fees),
    ("risk", "Risiko-Standard plausibel", check_risk_defaults),
    ("event_calendar", "Event-Kalender reicht weit genug", check_event_calendar),
    ("leverage_cap", "Liquidation weit hinter dem Stop", check_leverage_cap),
    ("evaluation_cutoff", "Bewertungs-Stichtag trennt alte Regeln ab", check_evaluation_cutoff),
    ("forward_verdict", "Vorwärtstest urteilt erst mit genug Trades", check_forward_verdict),
    ("review_allocation", "KI-Prüfung nur, wo sie hilft", check_review_allocation),
    ("pool_data", "Endlossuche testet auf eigenen Testdaten", check_pool_data),
    ("champion_checks", "Champions werden streng geprüft (Tresor, Rückwärtstest)", check_champion_checks),
    ("portfolio_core", "Portfolio rechnet nachvollziehbar und ohne Zukunftsblick", check_portfolio_core),
    ("portfolio_live", "Live-Ausführung hält Mindestmenge, Stop und Not-Aus ein", check_portfolio_live),
]


# ---------------------------- Laufzeitprüfungen ----------------------------
async def check_db(db) -> str:
    _expect(db is not None, "keine Datenbank-Verbindung")
    await db.command("ping")
    n = await db.auto_trades.estimated_document_count()
    return f"Datenbank erreichbar, {n} Trades gespeichert"


async def check_ai_config(db) -> str:
    doc = await db.settings.find_one({"_id": "ai_trader_config"}) or {}
    risk = doc.get("risk_per_trade_pct")
    if risk is not None:
        _expect(0 < float(risk) <= 5.0, f"Risiko je Trade {risk} % außerhalb 0–5 %")
    need = doc.get("signal_min_ki_trades")
    note = "" if need is None or int(need) >= 20 else f" · ACHTUNG: Live-Tor schon nach {need} Trades"
    return f"KI-Konfiguration lesbar (Risiko {risk if risk is not None else 'Standard'} %){note}"


async def check_trade_mode(db) -> str:
    doc = await db.settings.find_one({"_id": "autotrade_config"}) or {}
    mode = str(doc.get("mode") or "unbekannt")
    open_live = await db.auto_trades.count_documents({"status": "open", "mode": "live"})
    return f"Handelsmodus: {mode} · offene Live-Trades: {open_live}"


async def check_loops(db) -> str:
    from core import loop_watchdog
    snap = loop_watchdog.snapshot()
    if not (isinstance(snap, dict) and snap.get("enabled")):
        return "Schleifen-Überwachung ist abgeschaltet (LOOP_WATCHDOG_DISABLE)"
    lag = snap.get("current_lag_s")
    _expect(lag is None or float(lag) < 30.0, f"Hauptschleife hängt seit {lag} s")
    return f"Hauptschleife reagiert (Verzug {lag} s, bisher {snap.get('blocks')} Blockaden)"


RUNTIME_CHECKS = [
    ("db", "Datenbank erreichbar", check_db),
    ("ai_config", "KI-Konfiguration plausibel", check_ai_config),
    ("trade_mode", "Handelsmodus und offene Live-Trades", check_trade_mode),
    ("loops", "Hintergrund-Schleifen überwacht", check_loops),
]


# -------------------------------- Ausführung --------------------------------
def _result(cid: str, label: str, ok: bool, detail: str, ms: float) -> Dict:
    return {"id": cid, "label": label, "ok": ok, "detail": detail, "ms": round(ms, 1)}


def _summary(rows: List[Dict], started: float) -> Dict:
    failed = [r for r in rows if not r["ok"]]
    return {"ok": not failed, "passed": len(rows) - len(failed), "failed": len(failed),
            "seconds": round(time.time() - started, 2), "checks": rows,
            "text": ("Selbsttest bestanden: " + f"{len(rows)} Prüfungen in Ordnung" if not failed else
                     "Selbsttest FEHLGESCHLAGEN: " + "; ".join(f"{r['label']} – {r['detail']}" for r in failed))}


def run_logic() -> Dict:
    started, rows = time.time(), []
    for cid, label, fn in LOGIC_CHECKS:
        t0 = time.time()
        try:
            rows.append(_result(cid, label, True, fn(), (time.time() - t0) * 1000))
        except Exception as e:  # noqa: BLE001 – jede Abweichung ist ein Befund
            rows.append(_result(cid, label, False, f"{type(e).__name__}: {e}", (time.time() - t0) * 1000))
    return _summary(rows, started)


async def run_all(db) -> Dict:
    import asyncio
    started = time.time()
    rows = list((await asyncio.to_thread(run_logic))["checks"])
    for cid, label, fn in RUNTIME_CHECKS:
        t0 = time.time()
        try:
            rows.append(_result(cid, label, True, await fn(db), (time.time() - t0) * 1000))
        except Exception as e:  # noqa: BLE001
            rows.append(_result(cid, label, False, f"{type(e).__name__}: {e}", (time.time() - t0) * 1000))
    return _summary(rows, started)


async def run_at_startup(db, delay: float = 20.0) -> None:
    """Einmal nach dem Start: Ergebnis ins Log, bei Fehlern zusätzlich Telegram.
    Hält den Start nicht auf und ändert nichts."""
    import asyncio
    try:
        await asyncio.sleep(delay)
        res = await run_all(db)
        (logger.info if res["ok"] else logger.error)(res["text"])
        if not res["ok"]:
            try:
                from core import state
                tg = getattr(state, "telegram", None)
                if tg is not None and getattr(tg, "bot", None) and getattr(tg, "chat_id", None):
                    await tg.bot.send_message(chat_id=tg.chat_id, text="⚠️ " + res["text"][:900])
            except Exception as e:  # noqa: BLE001
                logger.warning(f"Selbsttest-Meldung nicht gesendet: {e}")
    except Exception as e:  # noqa: BLE001
        logger.error(f"Selbsttest konnte nicht laufen: {e}")
