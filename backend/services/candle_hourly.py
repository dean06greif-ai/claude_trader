"""Stunden-Kerzen als eigene Datenstufe für Backtests ab 1h (18.11.2026).

Messung in Produktion (Backtest-Benchmarks): Cloud-Läufe verbrachten 70 min bzw.
3 h damit, 9–32 Mio. 1m-Kerzen zu laden – die Simulation selbst dauerte 1–15 s.
Für Strategien ab 1h dienen die 1m-Kerzen nur dazu, daraus Stundenkerzen zu bauen.

Binance liefert Stundenkerzen direkt: 1000 Stück je Abruf = 41 Tage statt 17
Stunden, also 60× weniger Abrufe und 60× weniger Speicher. Die Kerzen sind dieselben
(UTC-Stunden, Open/High/Low/Close/Volumen aus denselben Trades); 4h/1d werden wie
bisher mit `aggregate_candles(..., base_ms=HOUR)` daraus gebaut.

Ablage wie beim 1m-Cache: RAM -> Platte (`<CANDLE_CACHE_DIR>/h1/<symbol>.npy`) ->
Supabase-Archiv (`h1/<symbol>.ckc`, kompaktes CKC1-Format) -> Binance. Symbole ohne
Binance-Quelle (Metalle, Indizes, Forex) bekommen weiter Stundenkerzen aus den
1m-Kerzen (gleiches Ergebnis, nur ohne Beschleunigung).
"""
import asyncio
import logging
import os
import time
from typing import Dict, Optional

import numpy as np

from core.loop_lock import LoopLock
from services.candles import CandleArray

logger = logging.getLogger(__name__)

HOUR = 3_600_000
DAY = 86_400_000
TAIL_TTL_SEC = 300
MAX_CANDLES_IN_MEMORY = int(os.environ.get("HOURLY_CACHE_MAX_CANDLES", "0") or 0) or 1_500_000
ARCHIVE_PREFIX = "h1/"
ARCHIVE_MIN_GROWTH = 24                 # erst nach >= 1 Tag neuer Stunden erneut sichern
HEAD_RETRY_SEC = 24 * 3600
PACE_S = 0.06

_MEM: Dict[str, Dict] = {}              # symbol -> {"candles", "last_refresh", "used_at"}
_LOCK = LoopLock()
_HEAD_DONE: Dict[str, float] = {}       # symbol -> Zeitpunkt: Quelle hat davor nichts mehr
_ARCHIVED: Dict[str, int] = {}          # symbol -> Anzahl Stunden im Archiv (bekannt)
_ARCH_START: Dict[str, Optional[int]] = {}   # symbol -> Archiv-Start (None = keins); fehlt = unbekannt
STATS = {"requests": 0, "candles": 0, "seconds": 0.0, "disk_hits": 0, "archive_hits": 0,
         "archive_uploads": 0, "fallback_1m": 0}


def supported(symbol: str) -> bool:
    """Native Stundenkerzen nur bei Binance-Quelle (Krypto)."""
    from services import history_sources
    try:
        return history_sources.source_of(symbol) == "binance"
    except Exception:  # noqa: BLE001
        return False


# ---------------------------------------------------------------------------
# Reine Bausteine
# ---------------------------------------------------------------------------
def closed_only(ca: CandleArray, now_ms: int) -> CandleArray:
    """Nur abgeschlossene Stunden (für Platte/Archiv; die laufende Stunde ändert sich)."""
    if not len(ca):
        return ca
    i = int(np.searchsorted(ca.ts, np.int64(now_ms - HOUR), side="right"))
    return ca[:i]


def merge(existing: CandleArray, new: CandleArray) -> CandleArray:
    """Zusammenführen; bei gleichem Zeitstempel gewinnt die neuere Kerze."""
    if existing is None or not len(existing):
        return new if new is not None else CandleArray.empty()
    if new is None or not len(new):
        return existing
    return CandleArray.concat([existing, new]).dedup_sorted()


def rows_to_matrix(rows) -> np.ndarray:
    """Binance-kline-Zeilen -> Matrix (N, 6)."""
    return np.array([[k[0], k[1], k[2], k[3], k[4], k[5]] for k in rows], dtype=np.float64)


# ---------------------------------------------------------------------------
# Platte / Archiv
# ---------------------------------------------------------------------------
def _disk_path(symbol: str) -> str:
    from services import candle_cache
    return os.path.join(candle_cache.CACHE_DIR, "h1", f"{symbol}.npy")


def _load_disk(symbol: str) -> Optional[CandleArray]:
    from services import candle_cache
    if not candle_cache.DISK_ENABLED:
        return None
    p = _disk_path(symbol)
    try:
        if os.path.exists(p):
            m = np.load(p, allow_pickle=False)
            if m.ndim == 2 and m.shape[0] and m.shape[1] >= 6:
                return CandleArray.from_matrix(m[:, :6])
    except (OSError, ValueError) as e:
        logger.warning(f"candle_hourly: Platte {symbol}: {e}")
    return None


def _save_disk(symbol: str, ca: CandleArray):
    from services import candle_cache
    if not candle_cache.DISK_ENABLED or ca is None or not len(ca):
        return
    p = _disk_path(symbol)
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = p + ".tmp.npy"
        np.save(tmp, ca.matrix(), allow_pickle=False)
        os.replace(tmp, p)
    except OSError as e:
        logger.warning(f"candle_hourly: Platte speichern {symbol}: {e}")


async def _archive_download(symbol: str) -> Optional[CandleArray]:
    from services import candle_archive
    if not candle_archive.enabled():
        return None
    try:
        data = await candle_archive.storage.download_checked(candle_archive.BUCKET,
                                                             f"{ARCHIVE_PREFIX}{symbol}.ckc")
    except Exception as e:  # noqa: BLE001 – Stand unbekannt: später nicht überschreiben
        logger.warning(f"candle_hourly: Archiv laden {symbol}: {e}")
        return None
    ca = await asyncio.to_thread(candle_archive.decode, data) if data else None
    _ARCH_START[symbol] = int(ca.ts[0]) if ca is not None and len(ca) else None
    if ca is None or not len(ca):
        return None
    _ARCHIVED[symbol] = len(ca)
    STATS["archive_hits"] += 1
    return ca


async def _persist(symbol: str, ca: CandleArray):
    """Platte immer, Archiv nur bei spürbarem Zuwachs (kleine Dateien, ~100 KB/Jahr)."""
    closed = closed_only(ca, int(time.time() * 1000))
    if not len(closed):
        return
    await asyncio.to_thread(_save_disk, symbol, closed)
    from services import candle_archive
    if not candle_archive.enabled():
        return
    if symbol not in _ARCH_START:
        await _archive_download(symbol)            # Stand erst lesen, nie blind überschreiben
        if symbol not in _ARCH_START:
            return
    start = _ARCH_START.get(symbol)
    if start is not None and int(closed.ts[0]) > start + HOUR:
        return                                      # Archiv reicht weiter zurück
    known = _ARCHIVED.get(symbol)
    if known is not None and len(closed) - known < ARCHIVE_MIN_GROWTH:
        return
    try:
        blob = await asyncio.to_thread(candle_archive.encode, closed)
        ok = await candle_archive.storage.ensure_bucket(candle_archive.BUCKET) and \
            await candle_archive.storage.upload(candle_archive.BUCKET, f"{ARCHIVE_PREFIX}{symbol}.ckc",
                                                blob, "application/octet-stream")
        if ok:
            _ARCHIVED[symbol] = len(closed)
            STATS["archive_uploads"] += 1
    except Exception as e:  # noqa: BLE001
        logger.warning(f"candle_hourly: Archiv sichern {symbol}: {e}")


# ---------------------------------------------------------------------------
# Quelle (Binance, interval=1h)
# ---------------------------------------------------------------------------
async def _fetch(session, symbol: str, start_ms: int, end_ms: int, job: Dict = None) -> CandleArray:
    from services import history_sources as hs
    _src, ref = hs._resolve(symbol)
    blocks = []
    cur = int(start_ms)
    t0 = time.perf_counter()
    while cur < end_ms:
        await hs._check_cancel(job)
        params = {"symbol": ref, "interval": "1h", "startTime": cur, "endTime": int(end_ms) - 1,
                  "limit": 1000}
        data, last_err = None, ""
        for attempt in range(hs.BINANCE_ATTEMPTS):
            url = hs.BINANCE_HOSTS[attempt % len(hs.BINANCE_HOSTS)]
            try:
                data = await hs._get_json_checked(session, url, params)
                break
            except hs.RateLimited as e:
                last_err = str(e)
                await asyncio.sleep(min(e.retry_after, 180.0))
                continue
            except Exception as e:  # noqa: BLE001
                last_err = f"{type(e).__name__}: {e}" if str(e) else type(e).__name__
                if hs._invalid_symbol(last_err):
                    raise hs.SymbolUnavailable(f"{ref} ist bei Binance nicht gelistet")
                data = None
            await asyncio.sleep(min(1.5 * (attempt + 1), 10.0))
        STATS["requests"] += 1
        if data is None:
            raise hs.HistoryUnavailable(
                f"Download der Stundenkerzen von {ref} abgebrochen ({last_err or 'Netzwerk'}). "
                "Bereits geladene Etappen sind gespeichert – einfach erneut starten.")
        if not data:
            break
        blocks.append(rows_to_matrix(data))
        cur = int(data[-1][0]) + HOUR
        hs._progress(job, ref, cur, start_ms, end_ms)
        if len(data) < 1000:
            break
        await asyncio.sleep(PACE_S)
    dt = time.perf_counter() - t0
    STATS["seconds"] += dt
    if not blocks:
        return CandleArray.empty()
    ca = CandleArray.from_matrix(np.concatenate(blocks)).dedup_sorted()
    STATS["candles"] += len(ca)
    try:        # in der Backtest-Benchmark als „geladen“ sichtbar (Einheit = Basis-Kerzen)
        from services import candle_cache
        candle_cache.DOWNLOAD_STATS["candles"] += len(ca)
        candle_cache.DOWNLOAD_STATS["seconds"] += dt
    except Exception:  # noqa: BLE001
        pass
    return ca


async def _evict(keep: str):
    while sum(len(v["candles"]) for v in _MEM.values()) > MAX_CANDLES_IN_MEMORY and len(_MEM) > 1:
        oldest = min((k for k in _MEM if k != keep), key=lambda k: _MEM[k]["used_at"], default=None)
        if oldest is None:
            return
        _MEM.pop(oldest)            # liegt bereits auf Platte (_persist)


# ---------------------------------------------------------------------------
# Öffentliche API
# ---------------------------------------------------------------------------
async def get_hourly(session, symbol: str, days: int, job: Dict = None,
                     start_ms: Optional[int] = None) -> CandleArray:
    """Stundenkerzen der letzten `days` Tage (inkl. laufender Stunde, wie die
    Aggregation aus 1m-Kerzen)."""
    from services import history_sources
    from services.timeframes import aggregate_candles
    if not supported(symbol):
        from services import candle_cache
        STATS["fallback_1m"] += 1
        ca1 = await candle_cache.get_candles(session, symbol, days, job=job, start_ms=start_ms)
        return aggregate_candles(ca1, "1h")
    days = history_sources.days_cap(symbol, days)
    now_ms = int(time.time() * 1000)
    start = now_ms - int(days) * DAY
    if start_ms:
        start = min(start, int(start_ms))
    start = start // HOUR * HOUR

    async with _LOCK:
        entry = _MEM.get(symbol)
        if entry is None:
            ca = await asyncio.to_thread(_load_disk, symbol)
            if ca is not None and len(ca):
                STATS["disk_hits"] += 1
            else:
                ca = await _archive_download(symbol)
                if ca is not None and len(ca):
                    await asyncio.to_thread(_save_disk, symbol, ca)
            if ca is not None and len(ca):
                entry = _MEM[symbol] = {"candles": ca, "last_refresh": 0.0, "used_at": time.time()}
        cached = entry["candles"] if entry else CandleArray.empty()
        last_refresh = entry["last_refresh"] if entry else 0.0

    dirty = False
    now_s = time.time()
    head_done = now_s - _HEAD_DONE.get(symbol, 0.0) < HEAD_RETRY_SEC
    if not len(cached):
        cached = await _fetch(session, symbol, start, now_ms + HOUR, job)
        dirty = bool(len(cached))
        if not len(cached) or int(cached.ts[0]) > start + DAY:
            _HEAD_DONE[symbol] = now_s
    else:
        if start < int(cached.ts[0]) - HOUR and not head_done:
            head = await _fetch(session, symbol, start, int(cached.ts[0]), job)
            if len(head):
                cached = merge(head, cached)
                dirty = True
            if not len(head) or int(head.ts[0]) > start + DAY:
                _HEAD_DONE[symbol] = now_s
        if now_ms > int(cached.ts[-1]) + 60_000 and now_s - last_refresh > TAIL_TTL_SEC:
            # letzte (evtl. noch laufende) Stunde erneut holen und ersetzen
            tail = await _fetch(session, symbol, int(cached.ts[-1]), now_ms + HOUR, job)
            if len(tail):
                cached = merge(cached, tail)
                dirty = True
    async with _LOCK:
        _MEM[symbol] = {"candles": cached, "last_refresh": now_s if dirty else last_refresh,
                        "used_at": now_s}
        await _evict(symbol)
    if dirty:
        try:
            await _persist(symbol, cached)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"candle_hourly: sichern {symbol}: {e}")
    return cached.slice_from_ts(start)


def stats() -> Dict:
    return {**STATS, "symbols": len(_MEM),
            "candles_in_memory": sum(len(v["candles"]) for v in _MEM.values())}


def clear():
    _MEM.clear()
    _HEAD_DONE.clear()
    _ARCHIVED.clear()
    _ARCH_START.clear()
