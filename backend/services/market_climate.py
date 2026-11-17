"""Markt-Klima: langsames, marktweites Regime aus BTC-Tageskerzen (17.11.2026).

Warum ein weiteres Regime? Die bestehende Regime-Erkennung arbeitet je Coin auf
1h-Kerzen der letzten ~30 Tage (Stunden bis Wochen). Die Messung auf echten
Daten (26 Coins seit 2018, 1.625 Ausbruchs-Trades, docs/MODELLE_REGIME_FUNDING_
2026-11-17.md) zeigt den Nutzen aber auf der LANGSAMEN Ebene:

  * Trades MIT dem Klima (Long, wenn BTC über seinem 200-Tage-Schnitt liegt;
    Short, wenn darunter): Ø +0,49 R (t 4,1) – in allen drei Zeitabschnitten
    besser als Trades GEGEN das Klima (Ø +0,13 R; seit 2025 −0,25 R).
  * Shorts bei hoher BTC-Schwankung: Ø −0,19 R in allen drei Abschnitten.

Dieses Modul rechnet das Klima rein und ohne Blick in die Zukunft (nur
abgeschlossene Tageskerzen VOR dem Zeitpunkt) und misst den Effekt auf den
EIGENEN Trades der Website – erst messen, dann filtern. Es ändert keinen
Einstieg; ein Klima-Filter folgt nur, wenn die eigene Bilanz ihn stützt.

Nachtrag (Portfolio-Rechnung vom selben Tag): Auf Ebene des ganzen Portfolios
(höchstens 12 Positionen, stärkste Ausbrüche zuerst) war der Filter KEIN Gewinn –
Sharpe 1,27 mit Filter gegen 1,51 ohne. Das Portfolio handelt deshalb ohne ihn.
"""
import bisect
import logging
import math
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

SMA_DAYS = 200
VOL_DAYS = 30
VOL_REF_DAYS = 365
DAY_MS = 86_400_000
CACHE_S = 3600
MIN_TRADES_VERDICT = 50
BINANCE_URL = "https://data-api.binance.vision/api/v3/klines"
EVIDENCE = ("Echte Daten, 26 Coins seit 2018: einzelne Ausbruchs-Trades mit dem Klima Ø +0,49 R, gegen das "
            "Klima Ø +0,13 R. Im Portfolio mit begrenzter Positionszahl brachte ein Klima-Filter aber keinen "
            "Vorteil (Sharpe 1,27 mit Filter, 1,51 ohne). Deshalb: nur Anzeige und Messung, kein Filter.")

_cache: Dict = {"at": 0.0, "ts": [], "closes": []}


# ---------------------------------------------------------------------------
# rein
# ---------------------------------------------------------------------------
def _vol(closes: Sequence[float], end: int, n: int = VOL_DAYS) -> Optional[float]:
    """Streuung der Tagesrenditen über die n Tage bis einschließlich Index end-1."""
    if end - n - 1 < 0:
        return None
    rets = []
    for j in range(end - n, end):
        a, b = closes[j - 1], closes[j]
        if a <= 0 or b <= 0:
            return None
        rets.append(math.log(b / a))
    m = sum(rets) / n
    return math.sqrt(max(sum((r - m) ** 2 for r in rets) / n, 0.0))


def classify_at(ts: Sequence[int], closes: Sequence[float], t_ms: int) -> Dict:
    """Klima zum Zeitpunkt t_ms aus Tageskerzen, die VOR t_ms geschlossen haben.

    ts = Öffnungszeiten der Tageskerzen (aufsteigend), closes = Schlusskurse.
    Rückgabe: trend 'bull'|'bear'|None, vol_high True|False|None, dist_pct."""
    # Kerze i ist geschlossen, wenn ts[i] + 1 Tag <= t_ms
    end = bisect.bisect_right(ts, int(t_ms) - DAY_MS)
    out = {"trend": None, "vol_high": None, "dist_pct": None, "days": end}
    if end >= SMA_DAYS:
        sma = sum(closes[end - SMA_DAYS:end]) / SMA_DAYS
        last = closes[end - 1]
        if sma > 0:
            out["trend"] = "bull" if last > sma else "bear"
            out["dist_pct"] = round((last / sma - 1.0) * 100.0, 1)
    v = _vol(closes, end)
    if v is not None:
        ref = [x for x in (_vol(closes, j) for j in range(end - VOL_REF_DAYS, end, 5) if j > 0)
               if x is not None]
        if len(ref) >= 30:
            ref.sort()
            out["vol_high"] = v > ref[len(ref) // 2]
    return out


def aligned(side: Optional[str], trend: Optional[str]) -> Optional[bool]:
    """Läuft der Trade mit dem Klima? (Long im Bullen-, Short im Bärenklima)"""
    s = str(side or "").upper()
    if trend not in ("bull", "bear") or s not in ("LONG", "SHORT", "BUY", "SELL"):
        return None
    is_long = s in ("LONG", "BUY")
    return is_long == (trend == "bull")


def describe(c: Optional[Dict]) -> str:
    c = c or {}
    if c.get("trend") is None:
        return "Markt-Klima unbekannt (zu wenig Tagesdaten)"
    side = "Bullenmarkt" if c["trend"] == "bull" else "Bärenmarkt"
    d = c.get("dist_pct")
    where = (f"BTC {abs(d):.0f} % {'über' if d >= 0 else 'unter'} dem 200-Tage-Schnitt"
             if d is not None else "BTC gegen 200-Tage-Schnitt")
    vol = ("" if c.get("vol_high") is None
           else ", Schwankung hoch" if c["vol_high"] else ", Schwankung normal")
    return f"{side} ({where}){vol}"


def _r(t: Dict) -> Optional[float]:
    try:
        risk = float(t.get("risk_usdt") or 0)
        return float(t.get("realized_pnl") or 0) / risk if risk > 0 else None
    except (TypeError, ValueError):
        return None


def _ms(iso) -> Optional[int]:
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def _stats(rs: List[float]) -> Dict:
    n = len(rs)
    if not n:
        return {"trades": 0, "avg_r": None, "t": None}
    m = sum(rs) / n
    if n > 1:
        sd = math.sqrt(sum((x - m) ** 2 for x in rs) / (n - 1))
        t = m / (sd / math.sqrt(n)) if sd > 1e-12 else 0.0
    else:
        t = 0.0
    return {"trades": n, "avg_r": round(m, 3), "t": round(t, 2)}


def split_trades(trades: Sequence[Dict], ts: Sequence[int], closes: Sequence[float]) -> Dict:
    """Eigene, geschlossene Trades nach Klima beim Einstieg aufteilen (rein)."""
    groups: Dict[str, List[float]] = {"mit": [], "gegen": [], "short_vol_hoch": [], "short_vol_normal": []}
    for t in trades or []:
        r, at = _r(t), _ms(t.get("opened_at"))
        if r is None or at is None:
            continue
        c = classify_at(ts, closes, at)
        al = aligned(t.get("side"), c["trend"])
        if al is not None:
            groups["mit" if al else "gegen"].append(r)
        if str(t.get("side") or "").upper() in ("SHORT", "SELL") and c["vol_high"] is not None:
            groups["short_vol_hoch" if c["vol_high"] else "short_vol_normal"].append(r)
    out = {k: _stats(v) for k, v in groups.items()}
    out["verdict"] = verdict(out["mit"], out["gegen"])
    return out


def verdict(mit: Dict, gegen: Dict) -> str:
    """Klartext-Urteil über den Klima-Effekt auf den eigenen Trades (rein)."""
    n1, n2 = int(mit.get("trades") or 0), int(gegen.get("trades") or 0)
    if n1 < MIN_TRADES_VERDICT or n2 < MIN_TRADES_VERDICT:
        need = max(MIN_TRADES_VERDICT - n1, MIN_TRADES_VERDICT - n2)
        return f"noch kein Urteil – es fehlen etwa {need} Trades in der kleineren Gruppe"
    diff = float(mit["avg_r"]) - float(gegen["avg_r"])
    if diff >= 0.1:
        return (f"Trades mit dem Klima liegen {diff:+.2f} R vor denen dagegen – "
                "ein Klima-Filter würde auf den eigenen Trades helfen")
    if diff <= -0.1:
        return (f"Trades gegen das Klima liegen {-diff:+.2f} R vorn – "
                "auf den eigenen Trades kein Nutzen eines Klima-Filters")
    return "kein klarer Unterschied auf den eigenen Trades"


# ---------------------------------------------------------------------------
# Daten + Bericht
# ---------------------------------------------------------------------------
def parse_klines(rows) -> Tuple[List[int], List[float]]:
    ts, closes = [], []
    for k in rows or []:
        try:
            t, c = int(k[0]), float(k[4])
        except (TypeError, ValueError, IndexError):
            continue
        ts.append(t)
        closes.append(c)
    return ts, closes


async def btc_daily(session=None, now: Optional[float] = None) -> Tuple[List[int], List[float]]:
    """BTC-Tageskerzen (bis 1000 Tage), 1 h im Speicher. Fehler -> letzter Stand."""
    now = now or time.time()
    if _cache["ts"] and now - _cache["at"] < CACHE_S:
        return _cache["ts"], _cache["closes"]
    import aiohttp
    own = session is None
    sess = session or aiohttp.ClientSession()
    try:
        async with sess.get(BINANCE_URL, params={"symbol": "BTCUSDT", "interval": "1d", "limit": 1000},
                            timeout=aiohttp.ClientTimeout(total=15)) as r:
            if r.status == 200:
                ts, closes = parse_klines(await r.json())
                if len(ts) >= SMA_DAYS:
                    _cache.update({"at": now, "ts": ts, "closes": closes})
    except Exception as e:  # noqa: BLE001 – reine Zusatz-Info, nie blockierend
        logger.info(f"Markt-Klima: BTC-Tagesdaten nicht ladbar: {e}")
    finally:
        if own:
            await sess.close()
    return _cache["ts"], _cache["closes"]


async def report(db, days: int = 365) -> Dict:
    """Aktuelles Klima + Bilanz der eigenen Krypto-Trades nach Klima."""
    from datetime import timedelta
    from services import setup_asset_class
    ts, closes = await btc_daily()
    if not ts:
        return {"available": False, "text": "Markt-Klima: keine Tagesdaten erreichbar"}
    now_ms = int(time.time() * 1000)
    cur = classify_at(ts, closes, now_ms)
    lo = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rows = await db.auto_trades.find(
        {"status": "closed", "opened_at": {"$gte": lo}},
        {"_id": 0, "opened_at": 1, "side": 1, "realized_pnl": 1, "risk_usdt": 1, "symbol": 1}).to_list(30000)
    rows = [t for t in rows if setup_asset_class.asset_class_of(t.get("symbol")) == "crypto"]
    return {"available": True, "now": cur, "text": describe(cur), "evidence": EVIDENCE,
            "own": split_trades(rows, ts, closes), "days": days}
