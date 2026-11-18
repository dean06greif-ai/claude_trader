"""18.11.2026: Setup-Trigger baut Merkmale nur bei neuer geschlossener 5m-Kerze."""
import asyncio
from types import SimpleNamespace

import numpy as np

from services import setup_trigger as st
from services.candles import CandleArray
from services.timeframes import aggregate_candles


def _buf(n=800, start=1_700_000_100_000, gaps=()):   # auf 5 min ausgerichtet
    rng = np.random.default_rng(4)
    ts = start + np.arange(n, dtype=np.int64) * 60000
    for g in gaps:
        ts[g:] += 60000 * 3
    c = 100 + np.cumsum(rng.normal(0, 0.1, n))
    return [{"timestamp": int(t), "open": float(x), "high": float(x) + 0.1, "low": float(x) - 0.1,
             "close": float(x), "volume": 1.0} for t, x in zip(ts, c)]


def test_quick_bar_check_equals_full_aggregation():
    for gaps in ((), (797,), (400, 798)):
        full = _buf(gaps=gaps)
        for cut in range(790, 801):
            buf = full[:cut]
            c5 = aggregate_candles(CandleArray.from_dicts(buf), "5m", drop_partial=True)
            assert st.last_closed_5m(buf) == int(c5.ts[-1])
    assert st.last_closed_5m([]) is None


def test_scan_skips_feature_build_without_new_bar(monkeypatch):
    trig = st.SetupTrigger()
    buf = _buf(n=803)                       # letzte 5m-Kerze noch offen
    trig.engine = SimpleNamespace(scanner=SimpleNamespace(candle_buffer={"BTCUSDT": buf}))
    calls = []
    monkeypatch.setattr(trig, "_features", lambda s, c: calls.append(s))
    trig._last_bar["BTCUSDT"] = st.last_closed_5m(buf)
    assert trig.scan_symbol("BTCUSDT", "crypto", {}) == (False, []) and not calls
    buf.extend(_buf(n=806)[803:])           # 5m-Kerze schließt
    trig.scan_symbol("BTCUSDT", "crypto", {})
    assert calls == ["BTCUSDT"]


def test_scan_runs_symbols_in_a_thread(monkeypatch):
    import threading
    trig = st.SetupTrigger()
    trig.engine = SimpleNamespace(symbols=["BTCUSDT"], toggle_check=None,
                                  scanner=SimpleNamespace(candle_buffer={}))
    seen = []

    def fake_scan(sym, cls, state):
        seen.append(threading.current_thread() is threading.main_thread())
        return False, []

    async def no_classes():
        return {}
    monkeypatch.setattr(trig, "scan_symbol", fake_scan)
    monkeypatch.setattr(trig, "_class_state", no_classes)
    asyncio.run(trig.scan())
    assert seen == [False]
