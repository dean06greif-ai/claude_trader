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
