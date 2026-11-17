"""Veto- und Verpasst-Bilanz der KI-Prüfung (Stufe 2/3, 11/2026).

Jeder Detektor-Treffer öffnet ein Signal-Fenster (signal_broker) und bekommt
– unabhängig von der KI – einen Regel-Paper-Trade (`signal_source="regel"`,
`signal_ref` = Fenster-ID). Damit ist für JEDES Signal bekannt, was ohne KI
passiert wäre. Daraus folgt ehrlich messbar:

  * Veto-Wert: Was brachten die Signale, die die KI VERWORFEN hat? Liegen sie
    im Minus, hat das Veto Geld gespart; im Plus = verpasste Chancen.
  * Auswahl-Wert: Regel-Ergebnis der GENOMMENEN gegenüber den verworfenen.
  * Timing-Wert: KI-Trade (ki_geprueft) gegenüber dem Regel-Trade desselben
    Signals (gleicher Treffer, nur anderer Einstieg/Ausstieg).

So lernt der KI-Trader auch dann, wenn er nicht handelt. Reine Funktionen oben,
DB-Anbindung unten (nur lesend).
"""
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

MIN_N = 10   # darunter: Bilanz nur anzeigen, kein Urteil


def _r(t: Dict) -> Optional[float]:
    try:
        risk = float(t.get("risk_usdt") or 0)
        return float(t.get("realized_pnl") or 0) / risk if risk > 0 else None
    except (TypeError, ValueError):
        return None


def _bucket(xs: List[float]) -> Dict:
    n = len(xs)
    if not n:
        return {"n": 0, "avg_r": None, "sum_r": 0.0, "wins": 0}
    return {"n": n, "avg_r": round(sum(xs) / n, 3), "sum_r": round(sum(xs), 2),
            "wins": sum(1 for x in xs if x > 0)}


def balance(windows: List[Dict], rule_trades: List[Dict], ki_trades: List[Dict]) -> Dict:
    """Bilanz je Setup und gesamt (rein).

    windows: [{id, setup, status}] (status genommen/verworfen/ungeprueft)
    rule_trades / ki_trades: geschlossene Trades mit signal_ref, realized_pnl, risk_usdt."""
    status = {w.get("id"): (w.get("status"), w.get("setup") or "-") for w in windows or []}
    rule_r = {}
    for t in rule_trades or []:
        r = _r(t)
        if r is not None and t.get("signal_ref") in status:
            rule_r[t["signal_ref"]] = r
    ki_r = {}
    for t in ki_trades or []:
        r = _r(t)
        if r is not None and t.get("signal_ref"):
            ki_r[t["signal_ref"]] = r
    per: Dict[str, Dict[str, List[float]]] = {}
    timing: Dict[str, List[float]] = {}
    for wid, (st, setup) in status.items():
        if wid not in rule_r:
            continue
        g = per.setdefault(setup, {"genommen": [], "verworfen": [], "ungeprueft": []})
        if st in g:
            g[st].append(rule_r[wid])
        if st == "genommen" and wid in ki_r:
            timing.setdefault(setup, []).append(ki_r[wid] - rule_r[wid])
    out = {}
    tot = {"genommen": [], "verworfen": [], "ungeprueft": []}
    tot_timing: List[float] = []
    for setup, g in per.items():
        out[setup] = _summary(g, timing.get(setup, []))
        for k in tot:
            tot[k] += g[k]
        tot_timing += timing.get(setup, [])
    return {"setups": out, "total": _summary(tot, tot_timing)}


def _summary(g: Dict[str, List[float]], timing: List[float]) -> Dict:
    rej, take = _bucket(g["verworfen"]), _bucket(g["genommen"])
    veto = None if rej["avg_r"] is None else round(-rej["avg_r"], 3)
    if rej["n"] < MIN_N:
        verdict = "zu wenig verworfene Signale"
    elif veto > 0.05:
        verdict = "Veto spart Verluste"
    elif veto < -0.05:
        verdict = "Veto verpasst Gewinne"
    else:
        verdict = "Veto ohne Wirkung"
    return {"taken": take, "rejected": rej, "unreviewed": _bucket(g["ungeprueft"]),
            "veto_value_r": veto,
            "missed_gain_r": round(sum(x for x in g["verworfen"] if x > 0), 2),
            "avoided_loss_r": round(-sum(x for x in g["verworfen"] if x < 0), 2),
            "timing": _bucket(timing), "verdict": verdict}


def prompt_text(bal: Dict, max_lines: int = 6) -> str:
    """Lern-Prompt-Block (nur Setups mit genug verworfenen Signalen)."""
    rows = [(s, v) for s, v in (bal.get("setups") or {}).items()
            if (v.get("rejected") or {}).get("n", 0) >= MIN_N]
    if not rows:
        return ""
    rows.sort(key=lambda p: abs(p[1].get("veto_value_r") or 0), reverse=True)
    lines = []
    for s, v in rows[:max_lines]:
        rej, take = v["rejected"], v["taken"]
        lines.append(
            f"- {s}: verworfen {rej['n']} Signale, ohne KI Ø {rej['avg_r']:+.2f} R "
            f"(verpasst +{v['missed_gain_r']:.1f} R, vermieden {v['avoided_loss_r']:.1f} R) -> "
            f"{v['verdict']}; genommen {take['n']}"
            + (f" (Regel Ø {take['avg_r']:+.2f} R)" if take["avg_r"] is not None else ""))
    return ("=== VETO-BILANZ (was die verworfenen Detektor-Signale ohne KI gebracht hätten) ===\n"
            + "\n".join(lines)
            + "\nVerpasst das Veto Gewinne, prüfe weniger streng; spart es Verluste, behalte die "
              "Prüfkriterien bei. Lerne daraus auch ohne eigenen Trade.")



def _cutoff_apply(lookback_iso: str) -> str:
    """Bewertungs-Stichtag (services/evaluation_cutoff) – fail-safe."""
    try:
        from services import evaluation_cutoff
        return evaluation_cutoff.apply(lookback_iso)
    except Exception:  # noqa: BLE001
        return lookback_iso

async def load(db, days: int = 30) -> Dict:
    """Bilanz der letzten `days` Tage aus ai_signal_windows + auto_trades (lesend)."""
    from services import signal_broker
    cutoff = _cutoff_apply((datetime.now(timezone.utc) - timedelta(days=days)).isoformat())
    windows = await db[signal_broker.COLLECTION].find(
        {"created_at": {"$gte": cutoff}, "status": {"$in": ["genommen", "verworfen", "ungeprueft"]}},
        {"_id": 0, "id": 1, "setup": 1, "status": 1}).to_list(50000)
    proj = {"_id": 0, "signal_ref": 1, "realized_pnl": 1, "risk_usdt": 1}
    base = {"strategy_id": "ai_trader", "status": "closed", "opened_at": {"$gte": cutoff}}
    rule = await db.auto_trades.find({**base, "signal_source": "regel"}, proj).to_list(50000)
    ki = await db.auto_trades.find({**base, "signal_source": "ki_geprueft"}, proj).to_list(20000)
    out = balance(windows, rule, ki)
    out["days"] = days
    return out
