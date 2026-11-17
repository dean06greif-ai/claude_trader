"""Markt-Benchmark je Setup (Stufe 2, 11/2026).

Befund: crypto_security_breach sah mit +0,42 R brutto (90 Trades) wie ein
Vorteil aus – es waren aber ausschließlich SHORTs an 11 Tagen eines fallenden
Marktes. Das ist Markt-Beta, kein Setup-Vorteil.

Vergleich: jeder Trade eines Setups gegen den Durchschnitt ALLER anderen
KI-Trader-Trades derselben Richtung und Anlageklasse am selben Tag (± 1 Tag).
Übrig bleibt der Mehrwert des Setups gegenüber „einfach in diese Richtung
handeln“. Reine Funktion + dünne DB-Anbindung (nur lesend).
"""
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

MIN_N = 15


def _r(t: Dict) -> Optional[float]:
    try:
        risk = float(t.get("risk_usdt") or 0)
        return float(t.get("realized_pnl") or 0) / risk if risk > 0 else None
    except (TypeError, ValueError):
        return None


def _day(ts) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(ts)[:10])
    except (TypeError, ValueError):
        return None


def excess(trades: List[Dict], asset_class_of) -> Dict[str, Dict]:
    """Je Setup: Ø R, Ø R der Vergleichsgruppe (gleiche Richtung, Klasse, ±1 Tag,
    anderes Setup) und der Mehrwert (rein)."""
    rows = []
    for t in trades or []:
        r = _r(t)
        d = _day(t.get("opened_at"))
        if r is None or d is None or not t.get("setup"):
            continue
        rows.append((t["setup"], str(t.get("side") or "").upper(), asset_class_of(t.get("symbol")), d, r))
    by_key: Dict[tuple, List[tuple]] = {}
    for row in rows:
        by_key.setdefault((row[1], row[2], row[3]), []).append(row)
    out: Dict[str, Dict] = {}
    for setup, side, cls, d, r in rows:
        peers = []
        for dd in (-1, 0, 1):
            for o in by_key.get((side, cls, d + timedelta(days=dd)), []):
                if o[0] != setup:
                    peers.append(o[4])
        if not peers:
            continue
        base = sum(peers) / len(peers)
        acc = out.setdefault(setup, {"n": 0, "r": 0.0, "base": 0.0})
        acc["n"] += 1
        acc["r"] += r
        acc["base"] += base
    res = {}
    for setup, a in out.items():
        n = a["n"]
        avg, base = a["r"] / n, a["base"] / n
        ex = avg - base
        if n < MIN_N:
            verdict = "zu wenig vergleichbare Trades"
        elif ex > 0.1:
            verdict = "besser als der Markt"
        elif ex < -0.1:
            verdict = "schlechter als der Markt"
        else:
            verdict = "wie der Markt (kein eigener Vorteil)"
        res[setup] = {"n": n, "avg_r": round(avg, 3), "market_r": round(base, 3),
                      "excess_r": round(ex, 3), "verdict": verdict}
    return res



def _cutoff_apply(lookback_iso: str) -> str:
    """Bewertungs-Stichtag (services/evaluation_cutoff) – fail-safe."""
    try:
        from services import evaluation_cutoff
        return evaluation_cutoff.apply(lookback_iso)
    except Exception:  # noqa: BLE001
        return lookback_iso

async def load(db, days: int = 60) -> Dict[str, Dict]:
    from services.setup_asset_class import asset_class_of
    cutoff = _cutoff_apply((datetime.now(timezone.utc) - timedelta(days=days)).isoformat())
    trades = await db.auto_trades.find(
        {"strategy_id": "ai_trader", "status": "closed", "opened_at": {"$gte": cutoff}},
        {"_id": 0, "setup": 1, "side": 1, "symbol": 1, "opened_at": 1,
         "realized_pnl": 1, "risk_usdt": 1}).to_list(50000)
    return excess(trades, asset_class_of)
