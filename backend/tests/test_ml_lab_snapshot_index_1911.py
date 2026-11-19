"""19.11.2026: Auto-Training hielt alle ~30 min den Event-Loop 4–5 s an (loop-health:
ai_ml_lab.nearest_snapshot <- build_dataset). Der sortierte SnapshotIndex muss exakt
dieselben Snapshots wählen wie die bisherige lineare Suche."""
import asyncio
import random
import time
from datetime import datetime, timedelta, timezone

from services import ai_ml_lab as mlab

T0 = datetime(2026, 11, 1, tzinfo=timezone.utc)


def _snaps(rng, sym, n):
    out = []
    for i in range(n):
        ts = T0 + timedelta(minutes=rng.randrange(0, 60 * 24 * 10, 5))   # 5-min-Raster -> Duplikate
        v = ts.isoformat() if rng.random() > 0.05 else None              # ein paar ohne Zeit
        out.append({"symbol": sym, "ts": v, "features": {"rsi": rng.random() * 100, "i": i}})
    rng.shuffle(out)
    return out


def _decisions(rng, syms, n):
    out = []
    for _ in range(n):
        ts = T0 + timedelta(minutes=rng.randrange(-120, 60 * 24 * 10 + 120))
        out.append({"symbol": rng.choice(syms), "ts": ts.isoformat(), "action": rng.choice(["LONG", "SHORT"]),
                    "trade_pnl": rng.choice([-1.0, 2.0]), "confidence": 60})
    return out


def test_index_matches_linear_search_exactly():
    rng = random.Random(7)
    syms = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "NOSNAPS"]
    snaps = [s for sym in syms[:3] for s in _snaps(rng, sym, 400)]
    decs = _decisions(rng, syms, 1500)
    by_sym = {}
    for s in snaps:
        by_sym.setdefault(s["symbol"], []).append(s)
    idx = {k: mlab.SnapshotIndex(v) for k, v in by_sym.items()}
    hits = 0
    for d in decs:
        ts = mlab._ts(d["ts"])
        old = mlab.nearest_snapshot(by_sym.get(d["symbol"]) or [], ts)
        new = idx[d["symbol"]].nearest(ts) if d["symbol"] in idx else None
        assert old is new
        hits += old is not None
    assert hits > 300                                     # Test deckt echte Treffer ab


def test_build_dataset_unchanged_and_fast():
    rng = random.Random(3)
    syms = [f"C{i}USDT" for i in range(25)]
    snaps = [s for sym in syms for s in _snaps(rng, sym, 1200)]       # 30.000 wie in Produktion
    decs = _decisions(rng, syms, 6000)
    t0 = time.perf_counter()
    X, y, tss, meta = mlab.build_dataset(decs, snaps)
    dt = time.perf_counter() - t0
    # Referenz: alte lineare Suche je Entscheidung (nur Stichprobe, sonst dauert der Test)
    by_sym = {}
    for s in snaps:
        by_sym.setdefault(s["symbol"], []).append(s)
    for i in range(0, len(decs), 60):
        d = decs[i]
        ref = mlab.feature_row(d, mlab.nearest_snapshot(by_sym.get(d["symbol"]) or [], mlab._ts(d["ts"])))
        assert X[i] == ref
    assert meta["samples"] == 6000 and dt < 1.5           # vorher ~4–5 s in Produktion


def test_naive_and_aware_times_do_not_crash():
    naive = datetime(2026, 11, 1, 12, 0)
    idx = mlab.SnapshotIndex([{"ts": naive.isoformat(), "features": {"rsi": 1}},
                              {"ts": (T0 + timedelta(hours=12, minutes=5)).isoformat(), "features": {"rsi": 2}}])
    got = idx.nearest(T0 + timedelta(hours=12, minutes=10))
    assert got["features"]["rsi"] == 2


def test_load_training_data_builds_in_thread(monkeypatch):
    seen = {}
    real = asyncio.to_thread

    async def spy(fn, *a, **k):
        seen.setdefault("fns", []).append(getattr(fn, "__name__", ""))
        return await real(fn, *a, **k)
    monkeypatch.setattr(mlab.asyncio, "to_thread", spy)

    class _Cur:
        def __init__(self, rows):
            self.rows = rows

        def sort(self, *a, **k):
            return self

        def limit(self, *a, **k):
            return self

        async def to_list(self, n):
            return self.rows

    class _Col:
        def __init__(self, rows):
            self.rows = rows

        def find(self, *a, **k):
            return _Cur(self.rows)

    class _DB:
        ai_decisions = _Col([{"symbol": "BTCUSDT", "ts": T0.isoformat(), "action": "LONG", "trade_pnl": 1.0}])
        signals = _Col([])
        ai_market_snapshots = _Col([{"symbol": "BTCUSDT", "ts": T0.isoformat(), "features": {"rsi": 5}}])

    lab = mlab.MLLab()
    lab.setup(type("E", (), {"db": _DB()})())
    X, y, tss, meta = asyncio.run(lab.load_training_data())
    assert "build_dataset" in seen["fns"] and meta["samples"] == 1 and X[0]["rsi"] == 5.0
