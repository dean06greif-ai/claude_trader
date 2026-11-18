"""Kompaktes, verlustfreies Kerzen-Format „CKC1“ (18.11.2026).

Bisher lagen Kerzen im Archiv als float64-Matrix + gzip (~30–40 Byte je Kerze).
Lange 1m-Historien wurden dadurch so groß, dass Uploads an Datei-Grenzen scheitern
und das Laden nach einem Deploy unnötig lange dauert.

Dieses Format speichert
- Zeitstempel als Abstände zum Vorgänger (fast immer gleich -> fast 0 Byte),
- Preise und Volumen als ganze Zahlen (Dezimalstellen je Datei automatisch, aber
  NUR wenn die Umkehrung bitgenau dasselbe float64 ergibt),
- OHLC als kleine Differenzen (Open/Close zum vorigen Close, High/Low zur Kerze),
- die Bytes jeder Spalte nach Ebenen sortiert (Shuffle) und dann zlib-komprimiert.

Lässt sich eine Spalte nicht exakt als Dezimalzahl darstellen (z. B. umgerechnete
Kurse), wird sie roh (float64-Bits) gespeichert. Das Format ist damit immer verlustfrei:
decode(encode(m)) == m, Bit für Bit.
"""
import struct
import zlib
from typing import Optional

import numpy as np

MAGIC = b"CKC1"
VERSION = 1
MAX_DEC = 12
_HDR = struct.Struct("<4sBqqqbb")          # magic, version, n, ts0, base, dec_price, dec_vol
_SAMPLE = 20000


def _exact_decimals(x: np.ndarray, d: int) -> bool:
    scale = 10.0 ** d
    s = x * scale
    if s.size and float(np.max(np.abs(s))) >= 2.0 ** 53:
        return False
    return bool(np.array_equal(np.round(s) / scale, x))


def decimals(x: np.ndarray) -> int:
    """Kleinste Dezimalstellen-Zahl d, mit der x als ganze Zahl bitgenau umkehrbar ist;
    -1, wenn es keine gibt (dann Rohformat). Rein."""
    x = np.asarray(x, dtype=np.float64).ravel()
    if x.size == 0:
        return 0
    if not np.all(np.isfinite(x)):
        return -1
    probe = x if x.size <= _SAMPLE else x[np.linspace(0, x.size - 1, _SAMPLE).astype(np.int64)]
    for d in range(MAX_DEC + 1):
        if _exact_decimals(probe, d):
            for d2 in range(d, MAX_DEC + 1):
                if _exact_decimals(x, d2):
                    return d2
            return -1
    return -1


def _shuffle(a: np.ndarray) -> bytes:
    a = np.ascontiguousarray(a, dtype="<i8")
    return np.ascontiguousarray(a.view(np.uint8).reshape(-1, 8).T).tobytes()


def _unshuffle(b: bytes, n: int) -> np.ndarray:
    return np.frombuffer(b, dtype=np.uint8).reshape(8, n).T.copy().view("<i8").reshape(n)


def _bits(x: np.ndarray) -> np.ndarray:
    return np.ascontiguousarray(x, dtype="<f8").view("<i8")


def _from_bits(a: np.ndarray) -> np.ndarray:
    return np.ascontiguousarray(a, dtype="<i8").view("<f8")


def encode(m: np.ndarray, level: int = 6) -> bytes:
    """Matrix (N, >=6: ts, open, high, low, close, volume) -> Bytes."""
    m = np.asarray(m, dtype=np.float64)
    n = int(m.shape[0]) if m.ndim == 2 else 0
    if n == 0:
        return _HDR.pack(MAGIC, VERSION, 0, 0, 0, 0, 0)
    ts = m[:, 0].astype(np.int64)
    d_ts = np.diff(ts, prepend=ts[0])
    px = m[:, 1:5]
    dp = decimals(px)
    cols = [d_ts]
    base = 0
    if dp >= 0:
        ip = np.round(px * (10.0 ** dp)).astype(np.int64)
        o, h, lo, c = ip[:, 0], ip[:, 1], ip[:, 2], ip[:, 3]
        base = int(o[0])
        c_prev = np.concatenate(([base], c[:-1]))
        cols += [o - c_prev, c - c_prev, h - np.maximum(o, c), np.minimum(o, c) - lo]
    else:
        cols += [_bits(px[:, i]) for i in range(4)]
    vol = m[:, 5]
    dv = decimals(vol)
    cols.append(np.round(vol * (10.0 ** dv)).astype(np.int64) if dv >= 0 else _bits(vol))
    payload = zlib.compress(b"".join(_shuffle(col) for col in cols), level)
    return _HDR.pack(MAGIC, VERSION, n, int(ts[0]), base, dp, dv) + payload


def is_ckc(data: Optional[bytes]) -> bool:
    return bool(data) and data[:4] == MAGIC


def uses_raw(data: bytes) -> bool:
    """True, wenn Preise oder Volumen roh (float64-Bits) gespeichert sind – dann kann
    gzip über die ganze Matrix kleiner sein (Aufrufer wählt das kleinere Format)."""
    _m, _v, n, _t, _b, dp, dv = _HDR.unpack_from(data, 0)
    return bool(n) and (dp < 0 or dv < 0)


def decode(data: bytes) -> np.ndarray:
    """Bytes -> Matrix (N, 6) float64 (ts, open, high, low, close, volume)."""
    magic, ver, n, ts0, base, dp, dv = _HDR.unpack_from(data, 0)
    if magic != MAGIC or ver != VERSION:
        raise ValueError("kein CKC1-Kerzenformat")
    if n == 0:
        return np.zeros((0, 6), dtype=np.float64)
    raw = zlib.decompress(data[_HDR.size:])
    width = 8 * n
    if len(raw) != 6 * width:
        raise ValueError("CKC1: unerwartete Länge")
    col = [_unshuffle(raw[i * width:(i + 1) * width], n) for i in range(6)]
    out = np.empty((n, 6), dtype=np.float64)
    out[:, 0] = (ts0 + np.cumsum(col[0])).astype(np.float64)
    if dp >= 0:
        c = base + np.cumsum(col[2])
        c_prev = np.concatenate(([base], c[:-1]))
        o = c_prev + col[1]
        h = np.maximum(o, c) + col[3]
        lo = np.minimum(o, c) - col[4]
        scale = 10.0 ** dp
        out[:, 1], out[:, 2], out[:, 3], out[:, 4] = o / scale, h / scale, lo / scale, c / scale
    else:
        for i in range(4):
            out[:, 1 + i] = _from_bits(col[1 + i])
    out[:, 5] = col[5] / (10.0 ** dv) if dv >= 0 else _from_bits(col[5])
    return out
