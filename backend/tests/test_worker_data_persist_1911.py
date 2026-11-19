"""19.11.2026: Der lokale Worker sichert, was er von der Börse lädt, sofort auf Platte.

Befund (Produktion, ANTON-PC): Die Endlossuche lud nach jedem Worker-Neustart 365 Tage
neu – geladene 1m-Kerzen lagen nur im RAM, auf Platte kamen sie nur beim Auslagern.
Dazu: Daten-Ordner aus einer früheren Installation war im neuen Worker-Ordner unsichtbar.
"""
import ast
import asyncio
import time
from pathlib import Path

import numpy as np
import pytest

from services import candle_archive, candle_cache as cc, candle_hourly
from services.candles import CandleArray

M = 60000
DAY = 86400000
WORKER = Path(__file__).resolve().parents[2] / "local_worker" / "worker.py"


def _ca(a_ms, b_ms, step=M):
    ts = np.arange(a_ms // step * step, b_ms, step, dtype=np.int64)
    c = 100 + (ts - ts[0]) / 1e9
    return CandleArray(ts, c, c + 0.1, c - 0.1, c, np.ones(len(ts)))


def _worker_funcs(*names):
    """Reine Helfer aus worker.py laden, ohne das Modul zu importieren (Import liest
    Konfiguration, legt Ordner an und fragt ggf. nach dem Token)."""
    tree = ast.parse(WORKER.read_text(encoding="utf-8"))
    ns = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in names:
            exec(compile(ast.Module([node], []), str(WORKER), "exec"), ns)  # noqa: S102
    return [ns[n] for n in names]


# ---------------------------------------------------------------- reine Regel
def test_disk_save_due_rule():
    now = 10_000 * DAY
    assert cc.disk_save_due(None, now - DAY, now)                          # nichts auf Platte
    assert cc.disk_save_due((now - 7 * DAY, now), now - 365 * DAY, now)    # Kopf gewachsen
    assert not cc.disk_save_due((now - 7 * DAY, now), now - 7 * DAY, now + 30 * M)  # 30 min Schwanz
    assert cc.disk_save_due((now - 7 * DAY, now), now - 7 * DAY, now + DAY)         # 1 Tag Schwanz


# ---------------------------------------------------------------- Cache mit Platte
@pytest.fixture
def disk_env(monkeypatch, tmp_path):
    from services import history_sources
    calls = {"fetch": []}
    monkeypatch.setattr(cc, "CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(cc, "DISK_ENABLED", True)
    monkeypatch.setattr(history_sources, "days_cap", lambda s, d: d)
    monkeypatch.setattr(candle_archive, "enabled", lambda: False)
    monkeypatch.setattr(candle_archive, "schedule_persist", lambda *a, **k: False)

    async def fake_fetch(session, sym, a, b, job=None, pace=None, workers=0):
        calls["fetch"].append((a, b))
        return _ca(a, b)
    monkeypatch.setattr(cc, "_fetch_range_parallel", fake_fetch)
    monkeypatch.setattr(cc, "_fetch_range", fake_fetch)
    cc.clear()
    yield tmp_path, calls
    cc.clear()


def _restart():
    """Neustart des Workers simulieren: RAM weg, Platte bleibt."""
    cc._MEM.clear()
    cc._DISK_SPAN.clear()
    cc._HEAD_EXHAUSTED.clear()


def test_worker_keeps_fetched_candles_across_restart(disk_env, monkeypatch):
    tmp, calls = disk_env
    monkeypatch.setattr(cc, "SAVE_ON_FETCH", True)
    got = asyncio.run(cc.get_candles(None, "HYPEUSDT", 30))
    assert len(got) >= 30 * 1440 - 2 and (tmp / "HYPEUSDT.npy").exists()
    _restart()
    n_fetch = len(calls["fetch"])
    again = asyncio.run(cc.get_candles(None, "HYPEUSDT", 30))
    # nur der Schwanz (wenige Minuten seit dem ersten Lauf), kein erneuter 30-Tage-Download
    assert len(again) >= 30 * 1440 - 2
    assert all(b - a < DAY for a, b in calls["fetch"][n_fetch:])


def test_head_extension_is_saved(disk_env, monkeypatch):
    tmp, calls = disk_env
    monkeypatch.setattr(cc, "SAVE_ON_FETCH", True)
    asyncio.run(cc.get_candles(None, "ADAUSDT", 7))            # Download „7 Tage“
    asyncio.run(cc.get_candles(None, "ADAUSDT", 365))          # Endlossuche braucht 365 Tage
    meta = cc.disk_meta("ADAUSDT")
    assert meta["last_ts"] - meta["first_ts"] >= 364 * DAY     # Platte hat jetzt das ganze Jahr
    _restart()
    n_fetch = len(calls["fetch"])
    asyncio.run(cc.get_candles(None, "ADAUSDT", 365))
    assert all(b - a < DAY for a, b in calls["fetch"][n_fetch:])


def test_server_default_unchanged(disk_env, monkeypatch):
    """Ohne Worker-Schalter (Render) schreibt ein Download nichts zusätzlich auf Platte."""
    tmp, _calls = disk_env
    monkeypatch.setattr(cc, "SAVE_ON_FETCH", False)
    asyncio.run(cc.get_candles(None, "BTCUSDT", 10))
    assert not (tmp / "BTCUSDT.npy").exists()


def test_small_tail_does_not_rewrite(disk_env, monkeypatch):
    tmp, calls = disk_env
    monkeypatch.setattr(cc, "SAVE_ON_FETCH", True)
    monkeypatch.setattr(cc, "TAIL_TTL_SEC", 0)
    asyncio.run(cc.get_candles(None, "ETHUSDT", 10))
    e = cc._MEM["ETHUSDT"]                                       # Platte/RAM enden vor 30 min
    e["candles"], e["last_refresh"] = e["candles"][:-30], 0
    cc._note_disk("ETHUSDT", e["candles"])
    saves = []
    real = cc._save_disk
    monkeypatch.setattr(cc, "_save_disk", lambda s, c: (saves.append(s), real(s, c)))
    n_fetch = len(calls["fetch"])
    asyncio.run(cc.get_candles(None, "ETHUSDT", 10))           # 30 Minuten Schwanz neu
    assert len(calls["fetch"]) == n_fetch + 1                   # Schwanz wurde wirklich geladen
    assert saves == []                                          # < 1 Tag Zuwachs: nicht neu schreiben


def test_parallel_saves_use_own_temp_files(disk_env):
    """Zwei Jobs sichern dasselbe Symbol: kein gemeinsamer Temp-Name, Datei bleibt lesbar."""
    tmp, _calls = disk_env
    now = int(time.time() * 1000)
    a, b = _ca(now - 3 * DAY, now), _ca(now - 5 * DAY, now)
    import threading
    th = [threading.Thread(target=cc._save_disk, args=("SOLUSDT", x)) for x in (a, b, a, b)]
    [t.start() for t in th]
    [t.join() for t in th]
    meta = cc.disk_meta("SOLUSDT")
    assert meta and meta["candles"] in (len(a), len(b))
    assert not [p for p in tmp.iterdir() if p.name.endswith(".tmp.npy")]


# ---------------------------------------------------------------- Stundenkerzen auf Platte
def test_hourly_listing_meta_and_remove(monkeypatch, tmp_path):
    monkeypatch.setattr(cc, "CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(cc, "DISK_ENABLED", True)
    now = int(time.time() * 1000)
    h = _ca(now - 540 * DAY, now - 3600_000, step=3600_000)
    candle_hourly._save_disk("BTCUSDT", h)
    (tmp_path / "h1" / "XRPUSDT.npy.1-2.tmp.npy").write_bytes(b"x")       # halbe Datei ignorieren
    rows = candle_hourly.list_disk_symbols()
    assert [r["symbol"] for r in rows] == ["BTCUSDT"] and rows[0]["bytes"] > 0
    meta = candle_hourly.disk_meta("BTCUSDT")
    assert meta["candles"] == len(h) and meta["first_ts"] == int(h.ts[0])
    candle_hourly.remove_symbol("BTCUSDT")
    assert candle_hourly.disk_meta("BTCUSDT") is None


# ---------------------------------------------------------------- Worker-Helfer (rein)
def test_data_dir_note_only_outside_worker_folder():
    (note,) = _worker_funcs("data_dir_note")
    assert note(r"C:\anton2\Crypto_Claude\krypto_local_worker\worker_data",
                r"C:\anton2\Crypto_Claude\krypto_local_worker") is None
    assert note(r"c:\Anton2\CRYPTO_Claude\krypto_local_worker\worker_data\\",
                r"C:\anton2\Crypto_Claude\krypto_local_worker") is None        # Groß/klein egal
    txt = note(r"C:\anton2\Crypto\krypto_local_worker\worker_data",
               r"C:\anton2\Crypto_Claude\krypto_local_worker")
    assert txt and r"C:\anton2\Crypto\krypto_local_worker\worker_data" in txt
    # Nachbar-Ordner mit gleichem Anfang ist NICHT „innen“
    assert note(r"C:\w\krypto_local_worker_alt\data", r"C:\w\krypto_local_worker")


def test_merge_data_rows_shows_hourly_and_hourly_only_symbols():
    (merge,) = _worker_funcs("merge_data_rows")
    rows = merge(
        [{"symbol": "ADAUSDT", "bytes": 500, "mtime": 10.0, "candles": 10085, "first_ts": 1, "last_ts": 2}],
        [{"symbol": "ADAUSDT", "bytes": 70, "mtime": 20.0, "candles": 13000, "first_ts": 0, "last_ts": 2},
         {"symbol": "BNBUSDT", "bytes": 60, "mtime": 5.0, "candles": 8760, "first_ts": 0, "last_ts": 2}])
    assert [r["symbol"] for r in rows] == ["ADAUSDT", "BNBUSDT"]
    ada, bnb = rows
    assert ada["candles"] == 10085 and ada["h1_candles"] == 13000 and ada["h1_bytes"] == 70
    assert ada["mtime"] == 20.0                                    # jüngste Änderung zählt
    assert bnb["bytes"] == 0 and bnb["h1_candles"] == 8760 and "candles" not in bnb


def test_worker_sets_save_on_fetch_and_version():
    src = WORKER.read_text(encoding="utf-8")
    assert 'os.environ.setdefault("CANDLE_CACHE_SAVE_ON_FETCH", "1")' in src
    assert 'VERSION = "1.33.0"' in src
    from services import local_exec
    assert local_exec.REQUIRED_WORKER_VERSION_STR == "1.33.0"
