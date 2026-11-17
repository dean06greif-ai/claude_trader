"""17.11.2026: Prüfer blockierte sich selbst („bereits offen“), TF2/Sweep ohne Signal = Verschwendung."""
import asyncio
from datetime import datetime, timedelta, timezone

from services import ai_role
from services import signal_broker as sb

NOW = datetime.now(timezone.utc)
PRUEFER = {"ai_role": "pruefer", "signal_broker_enabled": True}


def _hit(minutes_ago=1, side="LONG"):
    bar_ts = int((NOW - timedelta(minutes=minutes_ago + 5)).timestamp() * 1000)
    return {"setup": "safe_haven_flow", "side": side, "entry": 100.0, "sl": 99.0, "tp1": 101.0,
            "tpf": 102.0, "note": "x", "has_edge": False, "bar_ts": bar_ts}


def test_prompt_marks_control_trade_and_explains():
    broker = sb.SignalBroker()
    sig = sb.build_signal("POLUSDT", "crypto", _hit(), {})
    sig["rule_paper"] = True
    broker.signals.append(sig)
    txt = broker.prompt_block({"POLUSDT": 100.1}, {})
    assert "Kontrollgruppe" in txt and "KEIN Grund für HOLD" in txt


def test_hold_already_open_is_not_a_veto():
    broker = sb.SignalBroker()
    sig = sb.build_signal("ADAUSDT", "crypto", _hit(), {})
    broker.signals.append(sig)
    broker.note_review({"symbol": "ADAUSDT", "action": "HOLD",
                        "reasoning": "Signal bereits als Sammlungstrade eröffnet; keine Doppelposition."})
    assert sig.get("reviews", 0) == 0 and sig["control_blocked"] == 1
    assert sig["last_review"]["control_blocked"] is True
    broker.note_review({"symbol": "ADAUSDT", "action": "HOLD",
                        "reasoning": "TF2-Short gegen 15m-Aufwärtstrend; Bestätigung fehlt."})
    assert sig["reviews"] == 1


def test_expired_control_blocked_signal_counts_as_unreviewed():
    broker = sb.SignalBroker()
    sig = sb.build_signal("XRPUSDT", "crypto", _hit(minutes_ago=300), {})
    broker.signals.append(sig)
    broker.note_review({"symbol": "XRPUSDT", "action": "HOLD",
                        "reasoning": "XRP-Long aus diesem Signal bereits offen; 5m-Reclaim unbestätigt."})
    asyncio.run(broker.expire())
    assert broker.recent[-1]["status"] == "ungeprueft"


def test_trigger_skip_only_in_pruefer_mode_without_signal(monkeypatch):
    broker = sb.SignalBroker()
    monkeypatch.setattr(sb, "signal_broker", broker)
    assert ai_role.trigger_skip_reason({"ai_role": "frei"}, "BTCUSDT") is None
    assert "kein offenes Detektor-Signal" in ai_role.trigger_skip_reason(PRUEFER, "BTCUSDT")
    broker.signals.append(sb.build_signal("BTCUSDT", "crypto", _hit(), {}))
    assert ai_role.trigger_skip_reason(PRUEFER, "BTCUSDT") is None


def test_tf2_and_sweep_check_skip_without_signal(monkeypatch):
    from services import sweep_trigger, tf2_signal
    broker = sb.SignalBroker()
    monkeypatch.setattr(sb, "signal_broker", broker)
    calls = []

    class Scanner:
        @staticmethod
        def is_trading_session(_):
            return True

    class Eng:
        config = dict(PRUEFER)
        _analyzing = False
        symbols = ["BTCUSDT"]
        toggle_check = None
        scanner = Scanner()

        async def run_analysis(self, **kw):
            calls.append(kw)
            return {"status": "ok"}
    for mod, hit in ((tf2_signal, {"symbol": "BTCUSDT", "side": "SHORT", "chg_pct": -1.0, "rel_vol": 2.0,
                                   "sl": 1.0, "risk_pct": 0.5}),
                     (sweep_trigger, {"symbol": "BTCUSDT", "side": "LONG", "level": 1.0, "wick_atr": 1.2,
                                      "price": 1.0})):
        monkeypatch.setattr(mod, "scan", lambda engine, symbols, h=hit: [h])
        assert asyncio.run(mod.check(Eng())) is None
    assert calls == []


def test_news_targets_in_pruefer_mode(monkeypatch):
    broker = sb.SignalBroker()
    monkeypatch.setattr(sb, "signal_broker", broker)
    assert ai_role.news_targets({"ai_role": "frei"}, ["BTCUSDT"], "high") == (["BTCUSDT"], True)
    assert ai_role.news_targets(PRUEFER, ["BTCUSDT"], "medium") == ([], False)
    assert ai_role.news_targets(PRUEFER, ["BTCUSDT"], "high") == ([], False)
    broker.signals.append(sb.build_signal("ETHUSDT", "crypto", _hit(), {}))
    assert ai_role.news_targets(PRUEFER, ["BTCUSDT"], "high") == (["ETHUSDT"], False)
    assert ai_role.news_targets(PRUEFER, ["ETHUSDT", "BTCUSDT"], "medium") == (["ETHUSDT"], False)
