"""18.11.2026: Stundenkerzen-Stufe – gleiche Kerzen, 60x weniger Daten."""
import asyncio
import time

import numpy as np
import pytest

from services import backtester as bt
from services import candle_cache, candle_hourly as ch
from services.candles import CandleArray
from services.timeframes import aggregate_candles

H = ch.HOUR


def _minutes(start_ms, n, seed=2):
    rng = np.random.default_rng(seed)
    ts = start_ms + np.arange(n, dtype=np.int64) * 60000
    c = np.round(50000 * np.exp(np.cumsum(rng.normal(0, 5e-4, n))), 1)
    o = np.concatenate(([c[0]], c[:-1]))
    h = np.maximum(o, c) + np.round(np.abs(rng.normal(0, 8, n)), 1)
    lo = np.minimum(o, c) - np.round(np.abs(rng.normal(0, 8, n)), 1)
    v = np.round(np.abs(rng.normal(5, 2, n)), 3)
    return CandleArray(ts, o, h, lo, c, v)


def test_base_choice_and_minimum():
    assert bt.history_base([60, 240]) == "1h"
    assert bt.history_base([15, 240]) == "1m"
    assert bt.history_base([]) == "1m"
    assert bt.history_base([240], {"hourly_base": False}) == "1m"
    assert bt.enough_history(range(101)) and not bt.enough_history(range(100))
    assert bt.enough_history(range(2), "1h") and not bt.enough_history(range(1), "1h")


def test_hourly_bars_give_identical_higher_timeframes():
    ca1 = _minutes(1_700_000_000_000 // H * H, 10 * 1440)
    h1 = aggregate_candles(ca1, "1h")
    for tf in ("1h", "4h", "1d"):
        a = aggregate_candles(ca1, tf)
        b = aggregate_candles(h1, tf, base_ms=H)
        assert np.array_equal(a.ts, b.ts) and np.array_equal(a.op, b.op)
        assert np.array_equal(a.hi, b.hi) and np.array_equal(a.lo, b.lo)
        assert np.array_equal(a.cl, b.cl) and np.allclose(a.vol, b.vol, rtol=1e-12)


@pytest.fixture
def hourly_env(monkeypatch, tmp_path):
    from services import history_sources
    monkeypatch.setattr(candle_cache, "CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(candle_cache, "DISK_ENABLED", True)
    monkeypatch.setattr(history_sources, "source_of", lambda s: "binance")
    monkeypatch.setattr(history_sources, "days_cap", lambda s, d: d)
    from services import candle_archive
    monkeypatch.setattr(candle_archive, "enabled", lambda: False)
    ch.clear()
    now = int(time.time() * 1000)
    full = aggregate_candles(_minutes((now - 40 * 86400000) // H * H, 40 * 1440), "1h")
    calls = []

    async def fake_fetch(session, symbol, a, b, job=None):
        calls.append((a, b))
        return full.slice_range(a, b - 1)
    monkeypatch.setattr(ch, "_fetch", fake_fetch)
    yield full, calls
    ch.clear()


def test_get_hourly_caches_persists_and_reloads(hourly_env):
    full, calls = hourly_env
    got = asyncio.run(ch.get_hourly(None, "BTCUSDT", 10))
    assert len(calls) == 1 and 230 <= len(got) <= 242
    assert np.array_equal(got.cl, full.slice_from_ts(int(got.ts[0])).cl)
    asyncio.run(ch.get_hourly(None, "BTCUSDT", 10))                    # RAM, kein neuer Abruf
    assert len(calls) == 1
    more = asyncio.run(ch.get_hourly(None, "BTCUSDT", 30))             # nur der Kopf wird geladen
    assert len(calls) == 2 and calls[1][1] == int(got.ts[0]) and len(more) > len(got)
    ch._MEM.clear()                                                      # Neustart: von Platte
    again = asyncio.run(ch.get_hourly(None, "BTCUSDT", 30))
    assert ch.STATS["disk_hits"] >= 1 and len(again) == len(more)
    assert len(calls) == 3                                               # nur das Ende neu


def test_non_binance_symbols_use_the_minute_cache(monkeypatch):
    from services import history_sources
    monkeypatch.setattr(history_sources, "source_of", lambda s: "bitunix")
    ca1 = _minutes(1_700_000_000_000 // H * H, 3 * 1440)

    async def fake_get(session, symbol, days, job=None, start_ms=None):
        return ca1
    monkeypatch.setattr(candle_cache, "get_candles", fake_get)
    got = asyncio.run(ch.get_hourly(None, "XAUTUSDT", 3))
    assert len(got) == 72 and np.array_equal(got.cl, aggregate_candles(ca1, "1h").cl)
