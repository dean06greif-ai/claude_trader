"""Dauerhaftes Kerzen-Archiv in Supabase Storage (Bucket `candle-archive`).

Problem: Der Disk-Cache (/tmp) ist auf Render flüchtig; nach jedem Deploy wird
die komplette Historie neu geladen und alles, was die Quelle nicht mehr liefert
(Bitunix: nur ab Kontrakt-Listing), wäre verloren. Das Archiv hält je Symbol
EINE komprimierte Matrix (`<symbol>.npy.gz`, 1m-Kerzen) – die Historie wächst
damit über die Zeit über das Quellen-Limit hinaus (Audit 03: Bulk-Daten raus aus
Mongo, Supabase als Ablage).

Upload höchstens einmal je UPLOAD_MIN_INTERVAL_S pro Symbol und nur, wenn die
Historie gewachsen ist. Ohne Supabase-Konfiguration ist alles ein No-Op.
"""
import asyncio
import gzip
import io
import logging
import os
import time
from typing import Dict, Optional

import numpy as np

from services import supabase_storage as storage
from services.candles import CandleArray

logger = logging.getLogger(__name__)

BUCKET = os.environ.get("CANDLE_ARCHIVE_BUCKET", "candle-archive")
ENABLED = os.environ.get("CANDLE_ARCHIVE", "1") != "0"
UPLOAD_MIN_INTERVAL_S = 6 * 3600
_LAST: Dict[str, Dict] = {}     # symbol -> {"at": ts, "count": n}


def enabled() -> bool:
    return ENABLED and storage.configured()


def _path(symbol: str) -> str:
    """18.11.2026: kompaktes CKC1-Format (~3x kleiner als gzip-float64)."""
    return f"{symbol}.ckc"


def _legacy_path(symbol: str) -> str:
    return f"{symbol}.npy.gz"


def _encode_gzip(m: np.ndarray) -> bytes:
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", compresslevel=6) as gz:
        np.save(gz, m, allow_pickle=False)
    return buf.getvalue()


def encode(candles: CandleArray) -> bytes:
    """CKC1 (kompakt); sind Werte nicht dezimal darstellbar, das kleinere von CKC1
    und gzip – decode() liest beide."""
    from services import candle_codec
    m = candles.matrix()
    blob = candle_codec.encode(m)
    if candle_codec.uses_raw(blob):
        gz = _encode_gzip(m)
        if len(gz) < len(blob):
            return gz
    return blob


def decode(data: bytes) -> Optional[CandleArray]:
    from services import candle_codec
    if candle_codec.is_ckc(data):
        try:
            return CandleArray.from_matrix(candle_codec.decode(data))
        except (ValueError, Exception) as e:  # noqa: BLE001
            logger.warning(f"candle_archive: CKC1 decode fehlgeschlagen: {e}")
            return None
    try:
        m = np.load(io.BytesIO(gzip.decompress(data)), allow_pickle=False)
    except (OSError, ValueError, EOFError) as e:
        logger.warning(f"candle_archive: decode fehlgeschlagen: {e}")
        return None
    if m.ndim != 2 or not m.shape[0] or m.shape[1] < 6:
        return None
    return CandleArray.from_matrix(m[:, :6])


def upload_due(symbol: str, count: int, now: Optional[float] = None) -> bool:
    """Nur hochladen, wenn gewachsen und Mindestabstand eingehalten (rein, testbar)."""
    last = _LAST.get(symbol)
    if not last:
        return True
    now = now if now is not None else time.time()
    return count > int(last["count"]) and (now - float(last["at"])) >= UPLOAD_MIN_INTERVAL_S


SHORT_SPAN_MS = 60 * 86400000      # neue Datei kürzer -> zusätzlich alte Datei prüfen
MAX_JOIN_GAP_MS = 10 * 60000       # nur bis 10 min Abstand gelten als zusammenhängend


def best_history(a: Optional[CandleArray], b: Optional[CandleArray]) -> Optional[CandleArray]:
    """Beste LÜCKENLOSE Historie aus zwei Ständen (rein): zusammenhängend -> vereinigt,
    sonst der Stand, der weiter zurückreicht (das Ende füllt der Cache von der Börse)."""
    parts = [x for x in (a, b) if x is not None and len(x)]
    if not parts:
        return None
    if len(parts) == 1:
        return parts[0]
    early, late = sorted(parts, key=lambda x: int(x.ts[0]))
    if int(early.ts[-1]) >= int(late.ts[0]) - MAX_JOIN_GAP_MS:
        return CandleArray.concat([early, late]).dedup_sorted()
    return early


async def download(symbol: str) -> Optional[CandleArray]:
    """Archiv lesen. Wirft bei Speicher-Fehlern (nicht bei „nicht vorhanden“), damit
    niemand nach einem Lesefehler eine längere Historie überschreibt."""
    if not enabled():
        return None
    data = await storage.download_checked(BUCKET, _path(symbol))
    new = await asyncio.to_thread(decode, data) if data else None
    old = None
    if new is None or not len(new) or int(new.ts[-1]) - int(new.ts[0]) < SHORT_SPAN_MS:
        # alte Datei (gzip-float64) lesen: Übernahme bzw. Wiederherstellung, falls die neue
        # Datei nur einen kurzen Stand enthält (18.11.2026: Boot-Backfill hatte 14 Tage
        # über übernommene lange Historien geschrieben – die alten Dateien sind erhalten)
        legacy = await storage.download_checked(BUCKET, _legacy_path(symbol))
        old = await asyncio.to_thread(decode, legacy) if legacy else None
    ca = best_history(new, old)
    if ca is not None and len(ca):
        _LAST[symbol] = {"at": time.time(), "count": len(ca)}
        if old is not None and len(old) and ca is not new:
            _MIGRATE.add(symbol)
        logger.info(f"candle_archive: {symbol} aus Supabase geladen ({len(ca)} Kerzen"
                    f"{', mit altem Format' if old is not None and len(old) else ''})")
    return ca


# ---------------------------------------------------------------------------
# 18.11.2026: automatisch sichern, was von der Börse geladen wurde
# ---------------------------------------------------------------------------
# Vorher sicherte nur der Setup-Backtest ins Archiv. Normale Backtests/Optimizer
# luden nach jedem Deploy alles neu von Binance (gemessen: 70 min bzw. 3 h).
PERSIST_MIN_NEW = 1440          # erst ab einem Tag neuer 1m-Kerzen erneut sichern
_DIRTY: Dict[str, int] = {}     # symbol -> neu geladene Kerzen seit dem letzten Sichern
_MIGRATE = set()                # Symbole, deren Archiv noch im alten Format liegt
_UPLOAD_LOCK = None
STATS = {"scheduled": 0, "uploaded": 0, "failed": 0, "migrated": 0}


def note_fetched(symbol: str, n: int) -> None:
    if n and n > 0:
        _DIRTY[symbol] = _DIRTY.get(symbol, 0) + int(n)


def persist_due(symbol: str, now: Optional[float] = None) -> bool:
    """Sichern lohnt (rein): genug neue Kerzen oder altes Format – und nicht öfter
    als UPLOAD_MIN_INTERVAL_S je Symbol (Migration sofort)."""
    if symbol in _MIGRATE:
        return True
    if _DIRTY.get(symbol, 0) < PERSIST_MIN_NEW:
        return False
    last = _LAST.get(symbol)
    now = now if now is not None else time.time()
    return not last or (now - float(last["at"])) >= UPLOAD_MIN_INTERVAL_S


async def _persist_now(symbol: str, get_candles):
    global _UPLOAD_LOCK
    from core.loop_lock import LoopLock
    if _UPLOAD_LOCK is None:
        _UPLOAD_LOCK = LoopLock()
    async with _UPLOAD_LOCK:            # nacheinander: Kodieren braucht kurz RAM
        if not persist_due(symbol):
            return
        candles = get_candles()
        if asyncio.iscoroutine(candles):
            candles = await candles
        if candles is None or not len(candles):
            return
        # Kodieren braucht kurz ~4x die Rohgröße (48 Byte/Kerze): nur mit genug freiem RAM,
        # sonst beim nächsten Mal (nichts geht verloren, nur später gesichert)
        try:
            from services import ram_queue
            need_mb = len(candles) * 48 * 4 / 1e6 + 80
            if not await ram_queue.wait_for_ram(need_mb, 120, f"archiv-{symbol}"):
                STATS["failed"] += 1
                return
        except Exception:  # noqa: BLE001 – ohne RAM-Messung (Worker) einfach sichern
            pass
        ok = await upload(symbol, candles, force=True)
        if ok:
            STATS["uploaded"] += 1
            _DIRTY.pop(symbol, None)
            if symbol in _MIGRATE:
                _MIGRATE.discard(symbol)
                STATS["migrated"] += 1
        else:
            STATS["failed"] += 1


def schedule_persist(symbol: str, get_candles) -> bool:
    """Im Hintergrund sichern, falls fällig (blockiert den Aufrufer nicht).
    `get_candles`: Funktion, die den aktuellen Stand liefert (erst beim Sichern gelesen)."""
    if not enabled() or not persist_due(symbol):
        return False
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return False
    STATS["scheduled"] += 1
    task = loop.create_task(_persist_now(symbol, get_candles))
    task.add_done_callback(lambda t: t.cancelled() or t.exception())
    return True


async def upload(symbol: str, candles: CandleArray, force: bool = False) -> bool:
    if not enabled() or candles is None or not len(candles):
        return False
    if not force and not upload_due(symbol, len(candles)):
        return False
    blob = await asyncio.to_thread(encode, candles)
    ok = await storage.ensure_bucket(BUCKET) and await storage.upload(BUCKET, _path(symbol), blob, "application/gzip")
    if ok:
        _LAST[symbol] = {"at": time.time(), "count": len(candles)}
        logger.info(f"candle_archive: {symbol} gesichert ({len(candles)} Kerzen, {len(blob) / 1e6:.1f} MB)")
    return ok


