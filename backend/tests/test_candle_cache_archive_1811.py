"""18.11.2026: Archiv nur für lange Zeiträume; Kopf aus dem Archiv, Lücke von der Börse."""
import asyncio
import time

import numpy as np
import pytest

from services import candle_archive, candle_cache as cc
from services.candles import CandleArray

M = 60000


def _ca(a_ms, b_ms):
    ts = np.arange(a_ms // M * M, b_ms, M, dtype=np.int64)
    c = 100 + (ts - ts[0]) / 1e9
    return CandleArray(ts, c, c + 0.1, c - 0.1, c, np.ones(len(ts)))


@pytest.fixture
def env(monkeypatch):
    from services import history_sources
    now = int(time.time() * 1000)
    calls = {"archive": 0, "fetch": []}
    monkeypatch.setattr(cc, "DISK_ENABLED", False)
    monkeypatch.setattr(history_sources, "days_cap", lambda s, d: d)
    monkeypatch.setattr(candle_archive, "enabled", lambda: True)
    monkeypatch.setattr(candle_archive, "schedule_persist", lambda *a, **k: False)
    arch = _ca(now - 200 * 86400000, now - 40 * 86400000)          # Archiv endet vor 40 Tagen

    async def fake_download(sym):
        calls["archive"] += 1
        return arch
    monkeypatch.setattr(candle_archive, "download", fake_download)

    async def fake_fetch(session, sym, a, b, job=None, pace=None, workers=0):
        calls["fetch"].append((a, b))
        return _ca(a, b)
    monkeypatch.setattr(cc, "_fetch_range_parallel", fake_fetch)
    monkeypatch.setattr(cc, "_fetch_range", fake_fetch)
    cc.clear()
    yield now, calls, arch
    cc.clear()


def test_short_request_skips_archive(env):
    now, calls, _arch = env
    got = asyncio.run(cc.get_candles(None, "BTCUSDT", 14))
    assert calls["archive"] == 0 and len(calls["fetch"]) == 1 and len(got) >= 14 * 1440 - 2


def test_long_request_extends_head_from_archive_and_fills_gap(env):
    now, calls, arch = env
    asyncio.run(cc.get_candles(None, "BTCUSDT", 14))                 # Boot-Backfill
    got = asyncio.run(cc.get_candles(None, "BTCUSDT", 100))
    assert calls["archive"] == 1
    gaps = np.diff(got.ts)
    assert gaps.max() == M                                           # lückenlos
    assert int(got.ts[0]) <= now - 100 * 86400000 + M
    # Börse lud nur: 14 Tage, die Lücke Archiv-Ende -> Cache-Anfang (und ggf. das Ende)
    big = [b - a for a, b in calls["fetch"] if b - a > 2 * 86400000]
    assert len(big) == 2 and big[1] < 30 * 86400000
    asyncio.run(cc.get_candles(None, "BTCUSDT", 150))                # Archiv nicht erneut
    assert calls["archive"] == 1


def test_persist_never_replaces_longer_archive(env, monkeypatch):
    now, calls, arch = env                                  # Archiv endet vor 40 Tagen
    asyncio.run(cc.get_candles(None, "BTCUSDT", 14))        # Boot-Backfill, Archiv ungelesen
    assert "BTCUSDT" not in cc._ARCHIVE_KNOWN
    assert asyncio.run(cc._persist_source("BTCUSDT")) is None          # Lücke: nicht sichern
    assert cc._ARCHIVE_KNOWN["BTCUSDT"] == int(arch.ts[0])
    assert asyncio.run(cc._persist_source("BTCUSDT")) is None          # auch später nicht


def test_persist_joins_contiguous_archive(env, monkeypatch):
    now, calls, _arch = env
    near = _ca(now - 300 * 86400000, now - 13 * 86400000)   # schließt an den 14-Tage-Cache an

    async def dl(sym):
        return near
    monkeypatch.setattr(candle_archive, "download", dl)
    asyncio.run(cc.get_candles(None, "BTCUSDT", 14))
    out = asyncio.run(cc._persist_source("BTCUSDT"))
    assert out is not None and int(out.ts[0]) == int(near.ts[0]) and np.diff(out.ts).max() == M


def test_persist_skips_when_archive_unreadable(env, monkeypatch):
    async def broken(sym):
        raise RuntimeError("HTTP 500")
    monkeypatch.setattr(candle_archive, "download", broken)
    asyncio.run(cc.get_candles(None, "BTCUSDT", 14))
    assert asyncio.run(cc._persist_source("BTCUSDT")) is None
    assert "BTCUSDT" not in cc._ARCHIVE_KNOWN
