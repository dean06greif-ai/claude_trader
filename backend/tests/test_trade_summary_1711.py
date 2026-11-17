"""17.11.2026: Analyse-Statistik über ALLE Trades (vorher nur über geladene Trades)."""
import asyncio

from services import trade_summary as ts

ROWS = [
    {"id": "a", "status": "closed", "mode": "live", "strategy_id": "custom_1", "symbol": "BTCUSDT",
     "result": "win", "realized_pnl": 10.0},
    {"id": "b", "status": "closed", "mode": "paper", "strategy_id": "ai_trader", "symbol": "BTCUSDT",
     "result": "loss", "realized_pnl": -4.0},
    {"id": "c", "status": "closed", "mode": "paper", "strategy_id": "ai_trader", "symbol": "ETHUSDT",
     "result": "loss", "realized_pnl": -1.0, "data_collection": True},
    {"id": "d", "status": "open", "mode": "paper", "strategy_id": "ai_trader", "symbol": "BTCUSDT"},
    {"id": "e", "status": "closed", "mode": "live", "strategy_id": "external", "symbol": "BTCUSDT",
     "result": "loss", "realized_pnl": -100.0},
    {"id": "f", "status": "closed", "mode": "paper", "strategy_id": "geloescht", "symbol": "BTCUSDT",
     "result": "win", "realized_pnl": 99.0},
]
STALE = lambda sid: sid == "geloescht"   # noqa: E731


def test_filters_match_the_view():
    a = ts.summarize(ROWS, "all", "BTCUSDT", STALE)
    assert a["totals"] == {"open": 1, "closed": 3, "wins": 1, "losses": 2, "pnl": -94.0}
    assert a["coin"] == {"symbol": "BTCUSDT", "open": 1, "closed": 3, "pnl": -94.0}
    assert set(a["by_strategy"]) == {"custom_1", "ai_trader"}            # extern nicht im Strategie-Vergleich
    assert a["by_strategy"]["ai_trader"]["openCount"] == 1
    assert ts.summarize(ROWS, "live")["totals"]["closed"] == 2
    assert ts.summarize(ROWS, "paper", stale=STALE)["totals"]["closed"] == 1
    c = ts.summarize(ROWS, "collection")
    assert c["totals"]["closed"] == 1 and c["totals"]["pnl"] == -1.0
    assert ts.summarize(ROWS, "quatsch")["filter"] == "all"


def test_endpoint_reads_all_trades():
    import pytest
    pytest.importorskip("fastapi")              # Sandbox ohne fastapi: nur die Logik oben
    from core import state
    from routers import autotrade
    from services import trade_summary as ts
    from tests.phase_fakedb import FakeDB
    ts.CACHE.clear()
    db = FakeDB()
    for r in ROWS:
        asyncio.run(db.auto_trades.insert_one(dict(r)))
    old = state.db
    state.db = db
    try:
        res = asyncio.run(autotrade.trade_summary(filter="all", symbol="BTCUSDT"))
    finally:
        state.db = old
        ts.CACHE.clear()
    assert res["totals"]["closed"] >= 3 and res["coin"]["symbol"] == "BTCUSDT"


def test_row_cache_expires_after_ttl():
    from services.trade_summary import RowCache
    now = [100.0]
    c = RowCache(ttl=10, clock=lambda: now[0])
    assert c.get() is None
    rows = [{"id": "a"}]
    assert c.put(rows) is rows and c.get() is rows
    now[0] += 9.9
    assert c.get() is rows
    now[0] += 0.2
    assert c.get() is None
