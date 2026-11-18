"""18.11.2026: kompaktes Kerzen-Format CKC1 – immer bitgenau verlustfrei."""
import gzip
import io

import numpy as np

from services import candle_codec as cc


def _market(n=20000, price=100000.0, tick=0.1, vol_dec=3, seed=1, step=60000):
    rng = np.random.default_rng(seed)
    ts = 1_700_000_000_000 + np.arange(n, dtype=np.int64) * step
    ts[n // 2:] += 5 * step                                   # Lücke (Börsen-Pause)
    c = np.round(price * np.exp(np.cumsum(rng.normal(0, 4e-4, n))) / tick) * tick
    o = np.concatenate(([c[0]], c[:-1]))
    h = np.maximum(o, c) + np.round(np.abs(rng.normal(0, 3e-4 * price, n)) / tick) * tick
    lo = np.minimum(o, c) - np.round(np.abs(rng.normal(0, 3e-4 * price, n)) / tick) * tick
    v = np.round(np.abs(rng.lognormal(2, 1, n)), vol_dec)
    # Preise wie aus Text geparst (z. B. "97000.10000000")
    o, h, lo, c = (np.array([float(f"{x:.{8}f}") for x in a]) for a in (o, h, lo, c))
    return np.column_stack([ts.astype(np.float64), o, h, lo, c, v])


def _gz(m):
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", compresslevel=6) as gz:
        np.save(gz, m, allow_pickle=False)
    return len(buf.getvalue())


def test_roundtrip_is_bit_exact_and_much_smaller():
    for price, tick, vd in ((97000.0, 0.1, 3), (0.000012, 1e-8, 0), (1.0853, 1e-5, 2)):
        m = _market(price=price, tick=tick, vol_dec=vd)
        blob = cc.encode(m)
        back = cc.decode(blob)
        assert back.shape == m.shape and np.array_equal(back, m)
        assert cc.is_ckc(blob) and len(blob) * 2.5 < _gz(m)       # deutlich kleiner als bisher


def test_raw_fallback_for_non_decimal_values():
    m = _market(n=500)
    m[:, 1:5] *= 1.0000003731                                   # umgerechnete Kurse
    m[:, 5] = np.random.default_rng(3).random(500)
    blob = cc.encode(m)
    assert np.array_equal(cc.decode(blob), m)
    m[7, 2] = np.nan                                             # auch NaN bleibt erhalten
    assert np.array_equal(cc.decode(cc.encode(m)), m, equal_nan=True)


def test_empty_and_single_and_decimals():
    assert cc.decode(cc.encode(np.zeros((0, 6)))).shape == (0, 6)
    one = np.array([[1.7e12, 1.5, 1.6, 1.4, 1.55, 10.0]])
    assert np.array_equal(cc.decode(cc.encode(one)), one)
    assert cc.decimals(np.array([1.5, 2.25])) == 2
    assert cc.decimals(np.array([0.1 + 0.2])) == -1 or cc.decimals(np.array([0.1 + 0.2])) > 10
    assert not cc.is_ckc(b"\x1f\x8b...")
