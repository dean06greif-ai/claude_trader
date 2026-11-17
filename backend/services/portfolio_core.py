"""Portfolio-Kern (rein, nur Standardbibliothek): Trend + Funding-Carry auf Tageskerzen.

Die einzigen Vorteils-Quellen mit Beleg auf echten Daten (26 Coins seit 2018/2020,
docs/PORTFOLIO_2026-11-17.md) liegen auf der Tagesebene – dort, wo der Minuten-
Scanner der Website nicht hinsieht:

  Trend   Ausbruch über das 20-Tage-Hoch (Long) bzw. unter das 20-Tage-Tief (Short),
          nur MIT dem Markt-Klima (BTC über/unter 200-Tage-Schnitt), Stop 2 ATR,
          danach nachgezogener Stop 3 ATR. Einsatz so, dass jeder Trade denselben
          Anteil des Kontos riskiert.
  Carry   marktneutral: wöchentlich die Coins mit dem niedrigsten Funding kaufen und
          die mit dem höchsten leerverkaufen (gleicher Betrag je Seite).

Dieser Kern rechnet den gesamten Verlauf aus Tageskerzen DETERMINISTISCH nach
(„Replay“): gleiche Daten + gleiche Einstellungen = gleiches Ergebnis. Der Dienst
(services/portfolio_engine) ruft ihn täglich auf; der heutige Stand ist einfach
das Ende des Replays. Dadurch gibt es keinen versteckten Zustand, der driften kann.

Kein Blick in die Zukunft: Signale entstehen am Tagesschluss aus Daten bis zu
diesem Schluss; Stops wirken ab dem Folgetag.
"""
import math
import time
from typing import Dict, List, Optional, Sequence, Tuple

DAY_MS = 86_400_000

DEFAULTS: Dict = {
    "start_equity": 10000.0,
    "btc": "BTCUSDT",
    "fee_pct": 0.06,              # Taker je Seite
    "slippage_pct": 0.02,         # je Seite
    "default_funding_day": 0.0003,  # ohne Funding-Daten: Long zahlt 0,03 %/Tag
    "trend": {"enabled": True, "breakout_days": 20, "atr_days": 20, "stop_atr": 2.0,
              "trail_atr": 3.0, "risk_pct": 0.5, "max_positions": 12, "max_gross": 1.5,
              "climate": True, "sma_days": 200, "sides": "both"},
    "carry": {"enabled": True, "lookback_days": 7, "n_side": 5, "hold_days": 7,
              "gross": 0.5, "min_coins": 12},
}


def merged(cfg: Optional[Dict]) -> Dict:
    """Einstellungen mit Standardwerten auffüllen und begrenzen (rein)."""
    cfg = cfg or {}
    out = {k: v for k, v in DEFAULTS.items() if not isinstance(v, dict)}
    for k in out:
        if cfg.get(k) is not None:
            out[k] = cfg[k]
    for part in ("trend", "carry"):
        out[part] = {**DEFAULTS[part], **(cfg.get(part) or {})}
    t, c = out["trend"], out["carry"]
    t["risk_pct"] = min(max(float(t["risk_pct"]), 0.05), 2.0)
    t["max_positions"] = min(max(int(t["max_positions"]), 1), 40)
    t["max_gross"] = min(max(float(t["max_gross"]), 0.1), 3.0)
    t["breakout_days"] = min(max(int(t["breakout_days"]), 5), 120)
    t["atr_days"] = min(max(int(t["atr_days"]), 5), 60)
    c["gross"] = min(max(float(c["gross"]), 0.0), 1.5)
    c["n_side"] = min(max(int(c["n_side"]), 1), 15)
    c["hold_days"] = min(max(int(c["hold_days"]), 1), 30)
    c["lookback_days"] = min(max(int(c["lookback_days"]), 1), 60)
    out["start_equity"] = max(float(out["start_equity"]), 100.0)
    return out


def _atr_series(bars: Sequence[Sequence[float]], n: int) -> List[Optional[float]]:
    out: List[Optional[float]] = [None] * len(bars)
    a = None
    for i in range(1, len(bars)):
        h, lo, pc = bars[i][2], bars[i][3], bars[i - 1][4]
        tr = max(h - lo, abs(h - pc), abs(lo - pc))
        a = tr if a is None else (a * (n - 1) + tr) / n
        out[i] = a
    return out


def _sma_flags(bars: Sequence[Sequence[float]], n: int) -> Dict[int, Optional[bool]]:
    """Tag -> True (Schluss über n-Tage-Schnitt), False (darunter), None (zu wenig Daten)."""
    out: Dict[int, Optional[bool]] = {}
    run = 0.0
    for i, b in enumerate(bars):
        run += b[4]
        if i >= n:
            run -= bars[i - n][4]
        out[int(b[0])] = (b[4] > run / n) if i >= n - 1 else None
    return out


def _stats(daily: List[Tuple[int, float]]) -> Dict:
    """Kennzahlen einer Konto-Kurve [(ts, equity)] (rein)."""
    if len(daily) < 3:
        return {"days": len(daily)}
    rets, peak, dd = [], daily[0][1], 0.0
    for i in range(1, len(daily)):
        a, b = daily[i - 1][1], daily[i][1]
        rets.append(b / a - 1.0 if a > 0 else 0.0)
        peak = max(peak, b)
        dd = max(dd, 1.0 - b / peak if peak > 0 else 0.0)
    n = len(rets)
    m = sum(rets) / n
    sd = math.sqrt(sum((r - m) ** 2 for r in rets) / max(n - 1, 1))
    years = max((daily[-1][0] - daily[0][0]) / DAY_MS / 365.25, 1e-9)
    total = daily[-1][1] / daily[0][1] - 1.0
    cagr = (daily[-1][1] / daily[0][1]) ** (1.0 / years) - 1.0 if daily[0][1] > 0 and years >= 0.05 else None
    return {"days": n, "total_pct": round(total * 100, 1),
            "cagr_pct": round(cagr * 100, 1) if cagr is not None else None,
            "vol_pct": round(sd * math.sqrt(365) * 100, 1),
            "sharpe": round(m / sd * math.sqrt(365), 2) if sd > 1e-12 else None,
            "t": round(m / sd * math.sqrt(n), 2) if sd > 1e-12 else None,
            "max_dd_pct": round(dd * 100, 1)}


def _years(daily: List[Tuple[int, float]]) -> List[Dict]:
    out, cur, start = [], None, None
    for ts, eq in daily:
        y = time.gmtime(ts / 1000.0).tm_year
        if y != cur:
            if cur is not None:
                out.append({"year": cur, "pct": round((prev / start - 1.0) * 100, 1)})
            cur, start = y, (prev if cur is not None else eq)
        prev = eq
    if cur is not None and start:
        out.append({"year": cur, "pct": round((prev / start - 1.0) * 100, 1)})
    return out


def run(candles: Dict[str, Sequence[Sequence[float]]],
        funding: Optional[Dict[str, Dict[int, float]]] = None,
        cfg: Optional[Dict] = None, start_ms: Optional[int] = None,
        mark_ms: Optional[int] = None) -> Dict:
    """Replay über alle Tage.

    candles  {Symbol: [[ts, open, high, low, close], ...]} – abgeschlossene Tageskerzen
    funding  {Symbol: {Tages-ts: Summe der Funding-Sätze des Tages}} (optional)
    start_ms erster Handelstag (davor nur Aufwärmen)
    mark_ms  Zeitpunkt, ab dem die Kurve getrennt als „seit Start (Paper)“ zählt
    """
    cfg = merged(cfg)
    funding = funding or {}
    tc, cc = cfg["trend"], cfg["carry"]
    cost = (float(cfg["fee_pct"]) + float(cfg["slippage_pct"])) / 100.0
    fund_default = float(cfg["default_funding_day"])
    syms = sorted(s for s, b in candles.items() if b and len(b) > 30)
    idx = {s: {int(b[0]): i for i, b in enumerate(candles[s])} for s in syms}
    atr = {s: _atr_series(candles[s], tc["atr_days"]) for s in syms}
    days = sorted({int(b[0]) for s in syms for b in candles[s]})
    btc = cfg["btc"] if cfg["btc"] in candles else None
    climate = _sma_flags(candles[btc], int(tc["sma_days"])) if btc else {}
    warm = max(tc["breakout_days"], tc["atr_days"]) + 2

    equity = float(cfg["start_equity"])       # realisiert
    open_pos: Dict[str, Dict] = {}            # Trend: Symbol -> Position
    carry_pos: Dict[str, float] = {}          # Carry: Symbol -> Notional (+ Long / − Short)
    trades: List[Dict] = []
    curve: List[Tuple[int, float]] = []
    parts = {"trend": 0.0, "carry": 0.0}
    rebalances = 0
    last_carry = None

    def fund_rate(s: str, day: int, side: int) -> float:
        f = (funding.get(s) or {}).get(day)
        if f is None:
            return fund_default if side > 0 else 0.0
        return f

    for day in days:
        if start_ms is not None and day < start_ms:
            continue
        # ---- 1) offene Trend-Positionen: Stop prüfen, Funding, Trail --------------
        for s in list(open_pos):
            i = idx[s].get(day)
            if i is None:
                # Coin ohne Kurse seit mehr als 3 Tagen (z. B. delistet): zum letzten
                # bekannten Kurs schließen, statt die Position ewig offen zu halten.
                lb = candles[s][-1]
                if day - int(lb[0]) > 3 * DAY_MS:
                    p = open_pos.pop(s)
                    px = float(lb[4])
                    gross = p["side"] * (px - p["entry"]) / p["entry"] * p["notional"]
                    pnl = gross - cost * p["notional"] * 2 + p["funding"]
                    equity += pnl
                    parts["trend"] += pnl
                    trades.append({"sleeve": "trend", "symbol": s, "side": "LONG" if p["side"] > 0 else "SHORT",
                                   "entry_ts": p["entry_ts"], "exit_ts": day, "entry": p["entry"],
                                   "exit": px, "notional": round(p["notional"], 2), "pnl": round(pnl, 2),
                                   "r": round(pnl / p["risk"], 3) if p["risk"] > 0 else None,
                                   "days": p["days"], "reason": "keine Kurse mehr"})
                continue
            p, b = open_pos[s], candles[s][i]
            if day <= p["entry_ts"]:
                continue
            p["days"] += 1
            fr = fund_rate(s, day, p["side"])
            fpay = -p["side"] * fr * p["notional"]           # Long zahlt positives Funding
            p["funding"] += fpay
            hit = (b[3] <= p["stop"]) if p["side"] > 0 else (b[2] >= p["stop"])
            if hit:
                px = min(p["stop"], b[1]) if p["side"] > 0 else max(p["stop"], b[1])
                gross = p["side"] * (px - p["entry"]) / p["entry"] * p["notional"]
                pnl = gross - cost * p["notional"] * 2 + p["funding"]
                equity += pnl
                parts["trend"] += pnl
                trades.append({"sleeve": "trend", "symbol": s, "side": "LONG" if p["side"] > 0 else "SHORT",
                               "entry_ts": p["entry_ts"], "exit_ts": day, "entry": p["entry"],
                               "exit": round(px, 10), "notional": round(p["notional"], 2),
                               "pnl": round(pnl, 2), "r": round(pnl / p["risk"], 3) if p["risk"] > 0 else None,
                               "days": p["days"], "reason": "Stop"})
                del open_pos[s]
                continue
            a = atr[s][i]
            if a:
                if p["side"] > 0:
                    p["best"] = max(p["best"], b[4])
                    p["stop"] = max(p["stop"], p["best"] - tc["trail_atr"] * a)
                else:
                    p["best"] = min(p["best"], b[4])
                    p["stop"] = min(p["stop"], p["best"] + tc["trail_atr"] * a)
            p["last"] = b[4]

        # ---- 2) Carry: Tagesergebnis der bestehenden Körbe ------------------------
        if carry_pos:
            cp = 0.0
            for s, notional in carry_pos.items():
                i = idx[s].get(day)
                if i is None or i == 0:
                    continue
                b, pb = candles[s][i], candles[s][i - 1]
                side = 1 if notional > 0 else -1
                cp += notional * (b[4] / pb[4] - 1.0)
                cp += -side * fund_rate(s, day, side) * abs(notional)
            equity += cp
            parts["carry"] += cp

        # Konto-Stand zum Tagesschluss (realisiert + offene Trend-Gewinne)
        def unreal() -> float:
            u = 0.0
            for s2, p2 in open_pos.items():
                u += p2["side"] * (p2.get("last", p2["entry"]) - p2["entry"]) / p2["entry"] * p2["notional"]
                u += p2["funding"] - cost * p2["notional"]
            return u
        eq_now = equity + unreal()

        # ---- 3) Trend-Einstiege am Tagesschluss -----------------------------------
        if tc["enabled"] and eq_now > 0:
            cands = []
            bull = climate.get(day) if btc else None
            for s in syms:
                if s in open_pos:
                    continue
                i = idx[s].get(day)
                if i is None or i < warm or not atr[s][i]:
                    continue
                bars = candles[s]
                n = tc["breakout_days"]
                hi = max(x[2] for x in bars[i - n:i])
                lo = min(x[3] for x in bars[i - n:i])
                c = bars[i][4]
                side = 1 if c > hi else (-1 if c < lo else 0)
                if not side:
                    continue
                if tc["sides"] == "long" and side < 0 or tc["sides"] == "short" and side > 0:
                    continue
                if tc["climate"]:
                    if bull is None or (side > 0) != bull:
                        continue
                a = atr[s][i]
                strength = (c - hi) / a if side > 0 else (lo - c) / a
                cands.append((-strength, s, side, c, a))
            cands.sort()
            gross = sum(p["notional"] for p in open_pos.values())
            for _, s, side, c, a in cands:
                if len(open_pos) >= tc["max_positions"]:
                    break
                dist = tc["stop_atr"] * a
                if dist <= 0 or dist / c > 0.5:
                    continue
                risk = eq_now * tc["risk_pct"] / 100.0
                notional = risk / (dist / c)
                room = tc["max_gross"] * eq_now - gross
                if room <= 0:
                    break
                if notional > room:
                    notional, risk = room, room * (dist / c)
                gross += notional
                open_pos[s] = {"side": side, "entry": c, "entry_ts": day, "stop": c - side * dist,
                               "init_stop": c - side * dist,
                               "best": c, "last": c, "notional": notional, "risk": risk,
                               "funding": 0.0, "days": 0, "atr": a}

        # ---- 4) Carry-Umschichtung --------------------------------------------------
        if cc["enabled"] and cc["gross"] > 0 and (day // DAY_MS) % cc["hold_days"] == 0 and eq_now > 0:
            scores = []
            for s in syms:
                if idx[s].get(day) is None:
                    continue
                fs = funding.get(s) or {}
                vals = [fs.get(day - k * DAY_MS) for k in range(cc["lookback_days"])]
                if any(v is None for v in vals):
                    continue
                scores.append((sum(vals) / len(vals), s))
            if len(scores) >= max(cc["min_coins"], 2 * cc["n_side"] + 2):
                scores.sort()
                per = eq_now * cc["gross"] / (2 * cc["n_side"])
                target = {s: per for _, s in scores[:cc["n_side"]]}
                target.update({s: -per for _, s in scores[-cc["n_side"]:]})
                turn = sum(abs(target.get(s, 0.0) - carry_pos.get(s, 0.0))
                           for s in set(target) | set(carry_pos))
                fee = turn * cost
                equity -= fee
                parts["carry"] -= fee
                carry_pos = target
                rebalances += 1
                last_carry = day
            elif carry_pos:
                turn = sum(abs(v) for v in carry_pos.values())
                equity -= turn * cost
                parts["carry"] -= turn * cost
                carry_pos = {}

        curve.append((day, equity + unreal()))

    # ---------------- Ergebnis ----------------
    closed = [t for t in trades if t.get("r") is not None]
    rs = [t["r"] for t in closed]
    n = len(rs)
    mean_r = sum(rs) / n if n else None
    sd_r = math.sqrt(sum((x - mean_r) ** 2 for x in rs) / (n - 1)) if n > 1 else None
    last_day = days[-1] if days else None
    positions = []
    for s, p in sorted(open_pos.items()):
        last = p.get("last", p["entry"])
        positions.append({"sleeve": "trend", "symbol": s, "side": "LONG" if p["side"] > 0 else "SHORT",
                          "entry_ts": p["entry_ts"], "entry": p["entry"], "stop": round(p["stop"], 10),
                          "init_stop": round(p.get("init_stop", p["stop"]), 10),
                          "last": last, "notional": round(p["notional"], 2), "risk": round(p["risk"], 2),
                          "open_r": round(p["side"] * (last - p["entry"]) / p["entry"] * p["notional"]
                                          / p["risk"], 2) if p["risk"] > 0 else None,
                          "days": p["days"], "new": p["entry_ts"] == last_day})
    for s, notional in sorted(carry_pos.items()):
        positions.append({"sleeve": "carry", "symbol": s, "side": "LONG" if notional > 0 else "SHORT",
                          "entry_ts": last_carry, "notional": round(abs(notional), 2)})
    since = [x for x in curve if mark_ms is not None and x[0] >= mark_ms]
    bull_now = climate.get(last_day) if (btc and last_day is not None) else None
    return {
        "config": cfg, "symbols": syms, "days": len(curve),
        "first_ts": curve[0][0] if curve else None, "last_ts": last_day,
        "equity": round(curve[-1][1], 2) if curve else cfg["start_equity"],
        "stats": _stats(curve), "years": _years(curve),
        "since_mark": {**_stats(since), "from_ts": since[0][0]} if len(since) >= 3 else
                      {"days": len(since), "from_ts": mark_ms},
        "parts": {k: round(v, 2) for k, v in parts.items()},
        "trend_trades": {"trades": n, "avg_r": round(mean_r, 3) if n else None,
                         "t": round(mean_r / (sd_r / math.sqrt(n)), 2) if sd_r else None,
                         "win_pct": round(100.0 * sum(1 for x in rs if x > 0) / n, 1) if n else None},
        "carry_rebalances": rebalances,
        "climate": {"bull": bull_now, "known": bull_now is not None},
        "positions": positions, "trades": trades, "curve": curve,
    }


def sample_curve(curve: Sequence[Tuple[int, float]], max_points: int = 400) -> List[List[float]]:
    """Kurve für die Anzeige ausdünnen (erster und letzter Punkt bleiben)."""
    n = len(curve)
    if n <= max_points:
        return [[int(a), round(b, 2)] for a, b in curve]
    step = (n - 1) / float(max_points - 1)
    pick = sorted({int(round(i * step)) for i in range(max_points)} | {n - 1})
    return [[int(curve[i][0]), round(curve[i][1], 2)] for i in pick]
