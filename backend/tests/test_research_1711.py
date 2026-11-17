"""17.11.2026 (Nachmittag): Zusatz-Coins für Backtests, Funding-Wächter, Übernahme-Schutz."""
import asyncio

import pytest

from core import instruments as ins
from services import cockpit, portfolio_engine as pe, research_pipeline as rp
from tests.phase_fakedb import FakeDB

DAY = 86_400_000


def test_research_coins_backtest_only():
    assert set(pe.UNIVERSE) <= set(ins.BACKTEST_SYMBOLS)
    assert not set(ins.RESEARCH_SYMBOLS) & set(ins.ALL_SYMBOLS)          # nie im Live-Scanner
    assert len(set(ins.BACKTEST_SYMBOLS)) == len(ins.BACKTEST_SYMBOLS)
    g = ins.research_groups()[0]
    assert g["research"] and {s["symbol"] for s in g["symbols"]} == set(ins.RESEARCH_SYMBOLS)
    from services import history_sources, setup_asset_class
    assert history_sources._resolve("NEARUSDT") == ("binance", "NEARUSDT")
    assert setup_asset_class.asset_class_of("NEARUSDT") == "crypto"
    assert ins.history_days_cap("NEARUSDT", 365) == 365


def test_funding_harvest_detection():
    last = 1_794_787_200_000
    docs = [{"_id": "HOTUSDT", "days": {str(last - k * DAY): 0.002 for k in range(3)}},
            {"_id": "WARMUSDT", "days": {str(last - k * DAY): 0.0012 for k in range(3)}},
            {"_id": "GAPUSDT", "days": {str(last): 0.01, str(last - DAY): 0.01}}]
    c = cockpit.funding_harvest(docs, last)
    assert [x["symbol"] for x in c] == ["HOTUSDT"] and c[0]["annual_pct"] == 73.0
    recs = cockpit.rec_harvest(c, last)
    assert len(recs) == 1 and "HOT (73 % p. a.)" in recs[0]["detail"] and recs[0]["action"] is None
    assert cockpit.rec_harvest([], last) == []


def test_adopt_refuses_candidate_only_on_research_coins(monkeypatch):
    import sys
    import types
    db = FakeDB()
    asyncio.run(db[rp.COLLECTION].insert_one({"id": "c1", "kind": "champion", "stage": "bestanden",
                                              "symbols": ["NEARUSDT", "AAVEUSDT"], "definition": {},
                                              "title": "x", "timeframe": "1h"}))
    monkeypatch.setitem(sys.modules, "routers.optimizer", types.SimpleNamespace(optimizer_apply=None))
    with pytest.raises(ValueError, match="Zusatzcoins"):
        asyncio.run(rp.adopt(db, "c1"))


def test_backtest_runs_on_research_coin(monkeypatch):
    """Zusatz-Coin läuft durch denselben Backtest-Pfad wie der Worker (Kerzen gemockt)."""
    import math
    from services import backtester as bt, candle_cache
    from strategies.registry import registry
    t0 = 1_760_000_000_000
    candles = []
    for i in range(20 * 1440):
        p = 5 + math.sin(i / 700) * 0.6 + i * 0.00001
        candles.append({"timestamp": t0 + i * 60_000, "open": p, "high": p * 1.002, "low": p * 0.998,
                        "close": p, "volume": 1000.0})
    seen = []

    async def fake(session, symbol, days, job=None, start_ms=None, **kw):
        seen.append(symbol)
        return candles
    monkeypatch.setattr(candle_cache, "get_candles", fake)
    jid = bt.create_job({"execution": "local"})
    cfg = {"capital": 1000, "fee_pct": 0.06, "risk_pct": 1, "leverage": 1}
    asyncio.run(bt.run_backtest(jid, ["rsi_only"], ["NEARUSDT"], 20, cfg, registry, {}, default_timeframe="15m"))
    job = bt.JOBS[jid]
    assert seen == ["NEARUSDT"]
    assert job.get("status") in ("done", "completed", "finished"), (job.get("status"), job.get("error"))
