"""18.11.2026: Archiv sichert automatisch, kompakt, und übernimmt alte Dateien."""
import asyncio
import gzip
import io

import numpy as np

from services import candle_archive as ar
from services.candles import CandleArray


def _ca(n=3000):
    ts = 1_700_000_000_000 + np.arange(n, dtype=np.int64) * 60000
    c = np.round(100 + np.cumsum(np.random.default_rng(1).normal(0, 0.05, n)), 2)
    txt = lambda a: np.array([float(f"{x:.8f}") for x in a])   # noqa: E731 – wie aus der API
    return CandleArray(ts, txt(c), txt(c + 0.05), txt(c - 0.05), txt(c), np.round(np.abs(c) / 7, 3))


def test_archive_picks_smaller_format_for_non_decimal_data():
    ts = 1_700_000_000_000 + np.arange(3000, dtype=np.int64) * 60000
    c = 100 + np.cumsum(np.random.default_rng(1).normal(0, 0.05, 3000))      # nicht dezimal
    ca = CandleArray(ts, c, c + 0.05, c - 0.05, c, np.ones(3000))
    blob = ar.encode(ca)
    assert np.array_equal(ar.decode(blob).hi, ca.hi)
    assert len(blob) <= len(ar._encode_gzip(ca.matrix()))


class FakeStorage:
    def __init__(self):
        self.files = {}

    async def download(self, bucket, path):
        return self.files.get(path)

    async def download_checked(self, bucket, path):
        if getattr(self, "broken", False):
            raise RuntimeError("HTTP 500")
        return self.files.get(path)

    async def upload(self, bucket, path, data, content_type=None):
        self.files[path] = data
        return True

    async def ensure_bucket(self, bucket):
        return True


def _setup(monkeypatch):
    from services import ram_queue
    st = FakeStorage()
    monkeypatch.setattr(ar, "storage", st)
    monkeypatch.setattr(ar, "enabled", lambda: True)

    async def ram_ok(*_a, **_k):
        return True
    monkeypatch.setattr(ram_queue, "wait_for_ram", ram_ok)
    for d in (ar._LAST, ar._DIRTY):
        d.clear()
    ar._MIGRATE.clear()
    return st


def test_legacy_file_is_read_and_migrated(monkeypatch):
    st = _setup(monkeypatch)
    ca = _ca()
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb") as gz:
        np.save(gz, ca.matrix(), allow_pickle=False)
    st.files["BTCUSDT.npy.gz"] = buf.getvalue()
    got = asyncio.run(ar.download("BTCUSDT"))
    assert np.array_equal(got.cl, ca.cl) and "BTCUSDT" in ar._MIGRATE
    assert ar.persist_due("BTCUSDT")                       # Migration sofort fällig

    async def run():
        assert ar.schedule_persist("BTCUSDT", lambda: got)
        await asyncio.sleep(0.05)
    asyncio.run(run())
    new = st.files["BTCUSDT.ckc"]
    assert new[:4] == b"CKC1" and len(new) < len(st.files["BTCUSDT.npy.gz"])
    assert np.array_equal(ar.decode(new).cl, ca.cl) and "BTCUSDT" not in ar._MIGRATE
    assert np.array_equal(asyncio.run(ar.download("BTCUSDT")).cl, ca.cl)   # jetzt neues Format


def test_saves_only_after_a_day_of_new_candles(monkeypatch):
    st = _setup(monkeypatch)
    ca = _ca()
    ar.note_fetched("ETHUSDT", 500)
    assert not ar.persist_due("ETHUSDT")
    ar.note_fetched("ETHUSDT", 1000)
    assert ar.persist_due("ETHUSDT")

    async def run():
        ar.schedule_persist("ETHUSDT", lambda: ca)
        await asyncio.sleep(0.05)
    asyncio.run(run())
    assert "ETHUSDT.ckc" in st.files and not ar.persist_due("ETHUSDT")
    ar.note_fetched("ETHUSDT", 5000)
    assert not ar.persist_due("ETHUSDT", now=ar._LAST["ETHUSDT"]["at"] + 60)   # Drossel 6 h


def _gz(ca):
    return ar._encode_gzip(ca.matrix())


def test_short_new_file_does_not_hide_long_old_history(monkeypatch):
    """18.11.2026: Boot-Backfill hatte 14 Tage über die übernommene lange Historie
    geschrieben – die alte Datei ist erhalten und wird wieder genutzt."""
    st = _setup(monkeypatch)
    old = _ca(5000)                                                    # lange, ältere Historie
    t0 = int(old.ts[-1]) + 40 * 86400000                               # 40 Tage Lücke
    short = CandleArray(np.arange(t0, t0 + 1440 * 60000, 60000, dtype=np.int64),
                        *(np.ones(1440),) * 5)
    st.files["BTCUSDT.npy.gz"] = _gz(old)
    st.files["BTCUSDT.ckc"] = ar.encode(short)
    got = asyncio.run(ar.download("BTCUSDT"))
    assert int(got.ts[0]) == int(old.ts[0]) and len(got) == len(old)  # lange Historie zurück
    st.files["BTCUSDT.ckc"] = ar.encode(CandleArray.concat([old, short[:0]]))
    assert len(asyncio.run(ar.download("BTCUSDT"))) == len(old)


def test_overlapping_files_are_joined_and_errors_raise(monkeypatch):
    st = _setup(monkeypatch)
    ca = _ca(6000)
    st.files["ETHUSDT.npy.gz"] = _gz(ca[:4000])
    st.files["ETHUSDT.ckc"] = ar.encode(ca[3000:])
    got = asyncio.run(ar.download("ETHUSDT"))
    assert len(got) == 6000 and np.array_equal(got.ts, ca.ts)
    st.broken = True
    try:
        asyncio.run(ar.download("ETHUSDT"))
        raise AssertionError("Lesefehler muss werfen")
    except RuntimeError:
        pass
