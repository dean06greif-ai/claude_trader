"""System-Check: macht prüfbar, was sich von außen nicht prüfen lässt.

Entstanden aus der Gesamtanalyse vom 15.11.2026 (Punkt 13). Vier Prüfungen,
alle NUR LESEND bzw. lokal – nichts davon ändert Daten oder Einstellungen:

  python -m scripts.systemcheck stats   Kennzahlen der echten Trades aus der
                                        Datenbank (Ø R, Streuung, t-Wert je
                                        Quelle/Modus/Setup). Braucht MONGO_URL
                                        und DB_NAME in der Umgebung.
  python -m scripts.systemcheck live    Fragt eine laufende Instanz ab
                                        (--url https://…): Health, Hintergrund-
                                        Schleifen, KI-Anbieter.
  python -m scripts.systemcheck noise   Zufalls-Benchmark: lässt die ECHTE
                                        Such-Pipeline auf künstlichen Kursen
                                        ohne jeden Vorteil laufen. Jeder
                                        "Champion" dort ist ein Fehlalarm.
  python -m scripts.systemcheck selftest  Selbsttest der Kernlogik (wie GET /api/selftest,
                                        nur ohne die Laufzeitprüfungen).
  python -m scripts.systemcheck tests   Offline-Tests (ohne laufenden Server).

Aufruf aus dem Ordner backend/. Ergebnis jeweils als Text; mit --json FILE
zusätzlich als Datei (z.B. zum Weitergeben an die Analyse).
"""
import argparse
import asyncio
import json
import math
import os
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


# --------------------------------------------------------------------------
# stats – Kennzahlen echter Trades (rein + DB-Leser)
# --------------------------------------------------------------------------
def trade_r(t: Dict) -> Optional[float]:
    """Ergebnis eines Trades in R (PnL / geplantes Risiko). None ohne Risiko."""
    try:
        risk = float(t.get("risk_usdt") or 0)
        pnl = float(t.get("realized_pnl") if t.get("realized_pnl") is not None else t.get("pnl") or 0)
    except (TypeError, ValueError):
        return None
    return pnl / risk if risk > 0 else None


def origin_of(t: Dict) -> str:
    sid = str(t.get("strategy_id") or "")
    if sid == "ai_engine":
        return "KI-Trader"
    if sid in ("manual", "") or t.get("manual"):
        return "Manuell"
    if sid.startswith("dyn") or t.get("dynamic_id"):
        return "Dynamisch"
    return f"Strategie {sid}"


def _stat(rs: List[float], pnl: float) -> Dict:
    n = len(rs)
    if not n:
        return {"n": 0, "mean_r": None, "sd_r": None, "t": None, "pnl": round(pnl, 2)}
    mean = sum(rs) / n
    var = sum((r - mean) ** 2 for r in rs) / (n - 1) if n > 1 else 0.0
    sd = math.sqrt(var)
    t = mean / (sd / math.sqrt(n)) if sd > 0 else 0.0
    need = int(math.ceil((2.0 * sd / mean) ** 2)) if mean > 0 and sd > 0 else None
    return {"n": n, "mean_r": round(mean, 3), "sd_r": round(sd, 3), "t": round(t, 2),
            "pnl": round(pnl, 2), "trades_for_t2": need}


def summarize(trades: Iterable[Dict]) -> Dict:
    """Geschlossene Trades -> Kennzahlen je (Herkunft, Modus) und je Setup (rein)."""
    groups: Dict[tuple, List[float]] = defaultdict(list)
    pnls: Dict[tuple, float] = defaultdict(float)
    setups: Dict[tuple, List[float]] = defaultdict(list)
    spnl: Dict[tuple, float] = defaultdict(float)
    all_r: List[float] = []
    total = no_risk = 0
    for t in trades:
        total += 1
        mode = "live" if str(t.get("mode") or "") == "live" and not t.get("paper") else "paper"
        key = (origin_of(t), mode)
        try:
            pnl = float(t.get("realized_pnl") if t.get("realized_pnl") is not None else t.get("pnl") or 0)
        except (TypeError, ValueError):
            pnl = 0.0
        pnls[key] += pnl
        r = trade_r(t)
        if r is None:
            no_risk += 1
            continue
        groups[key].append(r)
        all_r.append(r)
        if t.get("setup"):
            sk = (str(t.get("setup")), mode)
            setups[sk].append(r)
            spnl[sk] += pnl
    return {
        "trades": total, "without_risk": no_risk,
        "overall": _stat(all_r, sum(pnls.values())),
        "by_origin": [{"origin": k[0], "mode": k[1], **_stat(groups.get(k, []), pnls[k])}
                      for k in sorted(pnls, key=lambda k: -len(groups.get(k, [])))],
        "by_setup": [{"setup": k[0], "mode": k[1], **_stat(v, spnl[k])}
                     for k, v in sorted(setups.items(), key=lambda kv: -len(kv[1]))],
    }


def format_summary(s: Dict) -> str:
    lines = [f"Geschlossene Trades: {s['trades']} (ohne Risiko-Angabe, nicht in R auswertbar: "
             f"{s['without_risk']})"]
    o = s["overall"]
    if o["n"]:
        lines.append(f"Gesamt: Ø {o['mean_r']:+.3f} R · Streuung {o['sd_r']:.2f} R · t={o['t']:+.2f} · "
                     f"PnL {o['pnl']:+.2f}")
        lines.append("  (t ≥ 2 = Vorteil statistisch belegt; t ≤ −2 = Nachteil belegt)")
    lines.append("")
    lines.append(f"{'Herkunft':28s} {'Modus':6s} {'n':>5s} {'Ø R':>8s} {'Streu.':>7s} {'t':>6s} {'PnL':>10s}  nötig für t=2")
    for g in s["by_origin"]:
        lines.append(_row(g["origin"], g))
    if s["by_setup"]:
        lines.append("")
        lines.append(f"{'Setup':28s} {'Modus':6s} {'n':>5s} {'Ø R':>8s} {'Streu.':>7s} {'t':>6s} {'PnL':>10s}  nötig für t=2")
        for g in s["by_setup"]:
            lines.append(_row(g["setup"], g))
    return "\n".join(lines)


def _row(name: str, g: Dict) -> str:
    if not g["n"]:
        return f"{name[:28]:28s} {g['mode']:6s} {0:5d} {'–':>8s} {'–':>7s} {'–':>6s} {g['pnl']:+10.2f}"
    need = g.get("trades_for_t2")
    return (f"{name[:28]:28s} {g['mode']:6s} {g['n']:5d} {g['mean_r']:+8.3f} {g['sd_r']:7.2f} "
            f"{g['t']:+6.2f} {g['pnl']:+10.2f}  {need if need else '–'}")


async def _load_closed_trades(days: int) -> List[Dict]:
    from motor.motor_asyncio import AsyncIOMotorClient   # nur hier nötig
    url, name = os.environ.get("MONGO_URL"), os.environ.get("DB_NAME")
    if not url or not name:
        raise SystemExit("MONGO_URL und DB_NAME müssen in der Umgebung gesetzt sein.")
    cli = AsyncIOMotorClient(url, serverSelectionTimeoutMS=15000)
    q: Dict = {"status": "closed"}
    if days > 0:
        from datetime import datetime, timedelta, timezone
        q["closed_at"] = {"$gte": (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()}
    proj = {"_id": 0, "strategy_id": 1, "mode": 1, "paper": 1, "setup": 1, "symbol": 1,
            "realized_pnl": 1, "pnl": 1, "risk_usdt": 1, "manual": 1, "dynamic_id": 1}
    return await cli[name].auto_trades.find(q, proj).to_list(None)   # reine Leseabfrage


def cmd_stats(args) -> int:
    trades = asyncio.run(_load_closed_trades(args.days))
    s = summarize(trades)
    print(format_summary(s))
    _dump(args, s)
    return 0


# --------------------------------------------------------------------------
# live – laufende Instanz abfragen (nur GET)
# --------------------------------------------------------------------------
def cmd_live(args) -> int:
    import requests
    base = args.url.rstrip("/")
    headers = {"Authorization": f"Bearer {args.token}"} if args.token else {}
    out, bad = {}, 0
    for path in ("/api/health", "/api/debug/status", "/api/system/loop-health",
                 "/api/ai/providers/health", "/api/localworker/status"):
        try:
            r = requests.get(base + path, headers=headers, timeout=20)
            body = r.json() if "json" in r.headers.get("content-type", "") else r.text[:200]
            out[path] = {"status": r.status_code, "body": body}
            note = ""
            if r.status_code in (401, 403):
                note = " (Login nötig: --token <Admin-JWT>)"
            elif r.status_code >= 400:
                bad += 1
            print(f"{r.status_code}  {path}{note}")
            if path.endswith("loop-health") and isinstance(body, dict):
                for name, st in (body.get("loops") or body).items():
                    if isinstance(st, dict):
                        print(f"      {name:28s} {json.dumps(st, ensure_ascii=False)[:110]}")
        except Exception as e:  # noqa: BLE001
            bad += 1
            out[path] = {"error": str(e)}
            print(f"FEHLER  {path}: {e}")
    _dump(args, out)
    return 1 if bad else 0


# --------------------------------------------------------------------------
# noise – Zufalls-Benchmark der Such-Pipeline
# --------------------------------------------------------------------------
def synth_candles(days: int, seed: int, base_vol: float = 0.0005):
    """Künstliche 1m-Kerzen: driftloser Random Walk mit Volatilitäts-Clustern.
    Per Konstruktion ist darin KEIN Vorteil enthalten."""
    import numpy as np
    from services.candles import CandleArray
    rng = np.random.default_rng(seed)
    n = days * 1440
    eps = rng.normal(0, 0.03, n)
    h = np.empty(n)
    x = 0.0
    for i in range(n):
        x = 0.9995 * x + eps[i]
        h[i] = x
    sig = base_vol * np.exp(np.clip(h, -1.5, 1.5))
    sub = rng.normal(0, 1, (n, 4)) * (sig[:, None] / 2.0)
    sub -= (sig[:, None] / 2.0) ** 2 / 2.0
    cum = np.cumsum(sub, axis=1)
    logc = np.log(30000.0) + np.cumsum(cum[:, -1])
    logo = np.concatenate([[np.log(30000.0)], logc[:-1]])
    hi = logo + np.maximum(cum.max(axis=1), 0.0)
    lo = logo + np.minimum(cum.min(axis=1), 0.0)
    vol = np.exp(rng.normal(3.0, 0.6, n)) * (1.0 + np.abs(cum[:, -1]) / base_vol)
    ts = (1_700_000_000_000 + np.arange(n) * 60_000).astype(np.int64)
    return CandleArray(ts, np.exp(logo), np.exp(hi), np.exp(lo), np.exp(logc), vol)


async def _noise_run(seed: int, days: int, tf: str, minutes: float) -> Dict:
    import logging
    logging.disable(logging.CRITICAL)
    from services import optimizer as opt
    from services.bitunix_trade import DEFAULT_COIN_CFG
    from strategies.registry import registry
    candles = synth_candles(days, seed)

    async def fake_fetch(session, symbol, d, job=None, start_ms=None):
        return candles
    orig = opt.fetch_history
    opt.fetch_history = fake_fetch
    try:
        body = {"mode": "explore", "symbols": ["SYNTHUSDT"], "days": days, "timeframe": tf,
                "objective": "combo", "min_trades": 20, "iterations": 30, "max_rules": 3,
                "optimize": {"tpsl": True, "breakeven": True, "trail": True},
                "walk_forward": {"enabled": True, "mode": "single", "train_pct": 75},
                "explore": {"target_champions": 5, "max_minutes": minutes, "seed": 1000 + seed},
                "execution": "local"}
        jid = opt.create_job(dict(body))
        t0 = time.time()
        await opt.run_optimizer(jid, body, registry, {"strategy_params": {}, "coin_params": {}},
                                dict(DEFAULT_COIN_CFG), None)
        job = opt.JOBS[jid]
        rep = ((job.get("result") or {}).get("explore_report")) or {}
        return {"seed": seed, "status": job.get("status"), "error": job.get("error"),
                "seconds": round(time.time() - t0, 1), "tested": rep.get("tested"),
                "wf_checked": rep.get("wf_checked"), "champions": rep.get("champions_found"),
                "t_required": rep.get("t_required")}
    finally:
        opt.fetch_history = orig
        logging.disable(logging.NOTSET)


def cmd_noise(args) -> int:
    os.environ.setdefault("KI_LOCAL_WORKER", "1")
    rows = []
    for seed in range(1, args.runs + 1):
        r = asyncio.run(_noise_run(seed, args.days, args.timeframe, args.minutes))
        rows.append(r)
        print(f"Lauf {seed}: {r['status']} · {r['seconds']} s · geprüft im Walk-Forward: "
              f"{r['wf_checked']} · Champions: {r['champions']}"
              + (f" · Fehler: {r['error']}" if r.get("error") else ""))
    champs = sum(int(r.get("champions") or 0) for r in rows)
    checked = sum(int(r.get("wf_checked") or 0) for r in rows)
    print(f"\nErgebnis: {champs} Champions aus {checked} geprüften Kandidaten auf reinem Zufall.")
    print("Erwartet: 0. Jeder Champion hier ist ein Fehlalarm der Validierung."
          if champs else "In Ordnung: die Validierung lässt Zufall nicht durch.")
    _dump(args, {"runs": rows, "champions": champs, "wf_checked": checked})
    return 1 if champs else 0


# --------------------------------------------------------------------------
# tests – Offline-Tests
# --------------------------------------------------------------------------
def cmd_tests(args) -> int:
    cmd = [sys.executable, "-m", "pytest", "tests", "-m", "not live", "-q", "-p", "no:cacheprovider"]
    print("Starte:", " ".join(cmd))
    return subprocess.call(cmd, cwd=str(BACKEND))


def cmd_selftest(args) -> int:
    from services import selftest
    res = selftest.run_logic()
    for c in res["checks"]:
        print(f"{'OK    ' if c['ok'] else 'FEHLER'}  {c['label']} — {c['detail']}")
    print("\n" + res["text"])
    _dump(args, res)
    return 0 if res["ok"] else 1


def _dump(args, data) -> None:
    if getattr(args, "json", None):
        Path(args.json).write_text(json.dumps(data, indent=1, ensure_ascii=False, default=str),
                                   encoding="utf-8")
        print(f"\nGespeichert: {args.json}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("stats", help="Kennzahlen echter Trades (nur lesend)")
    s.add_argument("--days", type=int, default=0, help="nur die letzten N Tage (0 = alles)")
    s.add_argument("--json")
    s.set_defaults(fn=cmd_stats)
    s = sub.add_parser("live", help="laufende Instanz abfragen (nur GET)")
    s.add_argument("--url", required=True)
    s.add_argument("--token", default=os.environ.get("ADMIN_TOKEN"))
    s.add_argument("--json")
    s.set_defaults(fn=cmd_live)
    s = sub.add_parser("noise", help="Zufalls-Benchmark der Suche")
    s.add_argument("--runs", type=int, default=4)
    s.add_argument("--days", type=int, default=365)
    s.add_argument("--timeframe", default="15m")
    s.add_argument("--minutes", type=float, default=1.0, help="Laufzeit je Lauf")
    s.add_argument("--json")
    s.set_defaults(fn=cmd_noise)
    s = sub.add_parser("selftest", help="Selbsttest der Kernlogik (offline)")
    s.add_argument("--json")
    s.set_defaults(fn=cmd_selftest)
    s = sub.add_parser("tests", help="Offline-Tests")
    s.set_defaults(fn=cmd_tests)
    args = p.parse_args(argv)
    return int(args.fn(args) or 0)


if __name__ == "__main__":
    sys.exit(main())
