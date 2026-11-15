"""KI-Trader-Befunde aus der Gesamtanalyse 15.11.2026 (Punkt 6.1):
Live-Freigabe mit t-Wert (C3), Edge-Filter fail-closed für Live (C10),
vorsichtige Boot-Migration der neuen Standards (C2/C11)."""
import asyncio

from services import boot_migrations as bm
from services import edge_filter as ef
from services import position_sizing, signal_broker


def _t(i, pnl, ok=True):
    return {"opened_at": f"2026-11-{1 + i // 40:02d}T{i % 24:02d}:{i % 60:02d}:00",
            "realized_pnl": pnl, "risk_usdt": 10, "edge_filter": {"ok": ok}}


def test_readiness_requires_statistical_evidence_not_only_average():
    # Ø +0,15 R, aber Streuung ~2,2 R: 60 Trades reichen dafür nicht (t≈0,5)
    noisy = [_t(i, 45 if i % 4 == 0 else -13) for i in range(60)]
    out = ef.readiness(noisy)
    assert out["exp_r"] >= ef.READY_MIN_R and out["recent_half_r"] > 0
    assert out["ready"] is False and out["t"] < ef.READY_MIN_T
    assert "nicht belegt" in out["text"] and out["trades_needed"] > 60
    steady = [_t(i, 4 if i % 2 else -1) for i in range(60)]          # Ø +0,15 R, kleine Streuung
    assert ef.readiness(steady)["ready"] is True


class _Checks:
    def __init__(self):
        self.rows = []

    def record(self, name, ok, why=""):
        self.rows.append((name, ok, why))


def _run_edge_step(mode, collection=False, bypass=()):
    from services.bitunix_trade import AutoTradeManager
    at = AutoTradeManager.__new__(AutoTradeManager)
    checks, signal = _Checks(), {}
    orig = ef.evaluate
    ef.evaluate = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("kaputt"))
    try:
        blocked = asyncio.run(at._edge_filter_step(
            signal, [], {"edge_filter_enabled": True}, {}, "BTCUSDT", "LONG", 100.0, 99.0,
            mode, collection, set(bypass), checks))
    finally:
        ef.evaluate = orig
    return blocked, checks.rows, signal


def test_edge_filter_error_blocks_live_but_not_paper():
    blocked, rows, signal = _run_edge_step("live")
    assert blocked is True and rows[-1][1] is False and "vorsorglich blockiert" in signal["_reject_reason"]
    blocked, rows, _ = _run_edge_step("paper")
    assert blocked is False and rows[-1][1] is True and "Fehler" in rows[-1][2]
    assert _run_edge_step("live", collection=True)[0] is False      # Sammel-Trade: nur Markierung


class _Coll:
    def __init__(self):
        self.docs = {}

    async def find_one(self, q):
        d = self.docs.get(q["_id"])
        return dict(d) if d else None

    async def update_one(self, q, upd, upsert=False):
        self.docs.setdefault(q["_id"], {"_id": q["_id"]}).update(upd.get("$set", {}))


class _DB:
    def __init__(self):
        self.settings = _Coll()


class _Eng:
    def __init__(self):
        self.config = {}


def test_migration_only_replaces_untouched_old_defaults_and_runs_once():
    db, eng = _DB(), _Eng()
    db.settings.docs["ai_trader_config"] = {"_id": "ai_trader_config", "signal_min_ki_trades": 5,
                                            "risk_per_trade_pct": 2.0}
    asyncio.run(bm.migrate_evidence_gates(db, eng))
    doc = db.settings.docs["ai_trader_config"]
    assert doc["signal_min_ki_trades"] == signal_broker.DEFAULTS["signal_min_ki_trades"] == 30
    assert doc["risk_per_trade_pct"] == position_sizing.DEFAULTS["risk_per_trade_pct"] == 1.0
    assert eng.config["risk_per_trade_pct"] == 1.0
    doc.update(signal_min_ki_trades=5, risk_per_trade_pct=2.0)      # Trader stellt zurück
    asyncio.run(bm.migrate_evidence_gates(db, eng))                 # Marker gesetzt -> kein 2. Lauf
    assert doc["signal_min_ki_trades"] == 5 and doc["risk_per_trade_pct"] == 2.0

    db2 = _DB()                                                     # bewusst gewählte Werte bleiben
    db2.settings.docs["ai_trader_config"] = {"_id": "ai_trader_config", "signal_min_ki_trades": 10,
                                             "risk_per_trade_pct": 3.0}
    asyncio.run(bm.migrate_evidence_gates(db2, _Eng()))
    assert db2.settings.docs["ai_trader_config"]["signal_min_ki_trades"] == 10
    assert db2.settings.docs["ai_trader_config"]["risk_per_trade_pct"] == 3.0
