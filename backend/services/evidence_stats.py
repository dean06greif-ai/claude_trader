"""Statistik-Kern für Strategie-/Regime-Evidenz (rein, ohne DB, testbar).

Antwort auf das Problem „wenige Trades“ (ANALYSE_DYNAMIK_REGIME_0626, D2–D5):
statt harter Schwellen (3 Trades = bestanden, 30 Trades = freigegeben)
werden Ergebnisse nach ihrer Glaubwürdigkeit gewichtet.

- credibility(n, k):   Gewicht der eigenen Daten n / (n + k)
- shrink(...):         Ø je Regime Richtung Gesamt-Ø gezogen (Bühlmann/Empirical Bayes)
- lower_bound(...):    Ø − z · Standardfehler (vorsichtige Untergrenze)
- prob_greater(...):   Bootstrap-Wahrscheinlichkeit Ø(a) > Ø(b)
- size_factor(...):    Positionsgrößen-Faktor 0..1 aus Evidenz
"""
import math
import random
from typing import Dict, List, Optional, Sequence

PRIOR_TRADES = 20          # k: bei 20 Trades zählt das Regime zur Hälfte
LB_Z = 1.0                 # Untergrenze = Ø − 1 Standardfehler (~84 % einseitig)
MIN_SIZE_FACTOR = 0.25
BOOT_ITERS = 2000


def _clean(values: Optional[Sequence]) -> List[float]:
    out = []
    for v in values or []:
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if math.isfinite(f):
            out.append(f)
    return out


def mean_std(values: Sequence) -> Dict:
    v = _clean(values)
    n = len(v)
    if not n:
        return {"n": 0, "mean": 0.0, "std": 0.0, "se": None}
    m = sum(v) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in v) / (n - 1)) if n > 1 else 0.0
    return {"n": n, "mean": m, "std": sd, "se": sd / math.sqrt(n) if n > 1 else None}


def credibility(n: int, k: float = PRIOR_TRADES) -> float:
    n = max(int(n or 0), 0)
    return n / (n + max(float(k), 1e-9)) if n else 0.0


def shrink(mean_own: float, n: int, mean_prior: float, k: float = PRIOR_TRADES) -> float:
    w = credibility(n, k)
    return w * float(mean_own or 0.0) + (1.0 - w) * float(mean_prior or 0.0)


def lower_bound(mean: float, std: float, n: int, z: float = LB_Z) -> Optional[float]:
    if not n or n < 2:
        return None
    return float(mean) - z * float(std) / math.sqrt(n)


def lower_bound_of(values: Sequence, z: float = LB_Z) -> Optional[float]:
    s = mean_std(values)
    return lower_bound(s["mean"], s["std"], s["n"], z)


def robust_mean(values: Sequence, trim_top: int = 2) -> float:
    """Ø ohne die `trim_top` besten Werte (Ausreißer-robust, D4)."""
    v = sorted(_clean(values))
    if len(v) > trim_top + 2:
        v = v[:len(v) - trim_top]
    return sum(v) / len(v) if v else 0.0


def prob_greater(a: Sequence, b: Sequence, iters: int = BOOT_ITERS,
                 seed: int = 7) -> Optional[float]:
    """Bootstrap: Anteil der Ziehungen mit Ø(a) > Ø(b). b leer = gegen 0."""
    va, vb = _clean(a), _clean(b)
    if len(va) < 2:
        return None
    rng = random.Random(seed)
    na, nb = len(va), len(vb)
    wins = 0
    for _ in range(int(iters)):
        ma = sum(va[rng.randrange(na)] for _ in range(na)) / na
        mb = (sum(vb[rng.randrange(nb)] for _ in range(nb)) / nb) if nb else 0.0
        if ma > mb:
            wins += 1
    return round(wins / iters, 4)


def size_factor(n: int, shrunk_mean: float, k: float = PRIOR_TRADES,
                floor: float = MIN_SIZE_FACTOR) -> float:
    """Positionsgröße nach Evidenz: kein positiver Erwartungswert -> 0,
    sonst Glaubwürdigkeit (mindestens `floor`)."""
    if shrunk_mean is None or shrunk_mean <= 0 or not n:
        return 0.0
    return round(max(credibility(n, k), floor), 3)


def validation_ok(pnls: Sequence, min_trades: int, z: float = LB_Z) -> bool:
    """Robuste Validierung: genug Trades UND Untergrenze des Ø > 0."""
    s = mean_std(pnls)
    if s["n"] < max(int(min_trades), 5):
        return False
    lb = lower_bound(s["mean"], s["std"], s["n"], z)
    return lb is not None and lb > 0


# ---------------------------------------------------------------------------
# Signifikanz einer Strategie auf UNBEKANNTEN Daten (Analyse 15.11.2026, A1/A5)
#
# Problem: Eine Suche, die viele Kandidaten gegen dieselben Testdaten prüft,
# findet auch im reinen Zufall "Gewinner" (gemessen: ~27 % der Kandidaten
# bestanden den Walk-Forward auf einem Random Walk). Abhilfe: der Erwartungswert
# je Trade (in R) muss auf den Testdaten statistisch von 0 unterscheidbar sein,
# und die Hürde steigt mit der Zahl der geprüften Kandidaten (Bonferroni).
# ---------------------------------------------------------------------------
SIG_ALPHA = 0.05           # Irrtumswahrscheinlichkeit über ALLE geprüften Kandidaten
SIG_MIN_TRADES = 30        # darunter ist ein t-Wert nicht belastbar


def t_from_sums(n: int, r_sum: float, r_sq: float) -> Dict:
    """Mittelwert, Streuung und t-Wert aus additiven Summen (n, Σr, Σr²)."""
    n = int(n or 0)
    if n < 2:
        return {"n": n, "mean_r": (float(r_sum) / n) if n else 0.0, "std_r": 0.0, "t": 0.0}
    mean = float(r_sum) / n
    var = max((float(r_sq) - n * mean * mean) / (n - 1), 0.0)
    sd = math.sqrt(var)
    t = mean / (sd / math.sqrt(n)) if sd > 1e-12 else 0.0
    return {"n": n, "mean_r": mean, "std_r": sd, "t": t}


def required_t(n_trials: int, alpha: float = SIG_ALPHA) -> float:
    """Einseitige Hürde für den t-Wert bei n_trials geprüften Kandidaten
    (Bonferroni: alpha / n_trials; Normal-Näherung, ab ~30 Trades tragfähig)."""
    from statistics import NormalDist
    n_trials = max(int(n_trials or 1), 1)
    a = min(max(float(alpha) / n_trials, 1e-12), 0.5)
    return NormalDist().inv_cdf(1.0 - a)


def trades_needed(mean_r: float, std_r: float, t_req: float) -> Optional[int]:
    """Wie viele Trades bräuchte dieser Erwartungswert, um die Hürde zu nehmen?"""
    if mean_r is None or mean_r <= 0 or not std_r or std_r <= 0:
        return None
    return int(math.ceil((t_req * std_r / mean_r) ** 2))


def significance(metrics: Optional[Dict], n_trials: int = 1, alpha: float = SIG_ALPHA,
                 min_trades: int = SIG_MIN_TRADES) -> Dict:
    """Urteil über Kennzahlen eines Testabschnitts (braucht r_n/r_sum/r_sq aus
    backtester.simulate_pair). Fehlen die Summen (Alt-Ergebnis), ist das Urteil
    'unbekannt' und `passed` False – nie stillschweigend bestanden."""
    m = metrics or {}
    n = int(m.get("r_n") or 0)
    if not n or m.get("r_sum") is None or m.get("r_sq") is None:
        return {"known": False, "passed": False, "n": n, "n_trials": int(n_trials or 1),
                "reason": "keine R-Kennzahlen im Ergebnis"}
    st = t_from_sums(n, m.get("r_sum"), m.get("r_sq"))
    t_req = required_t(n_trials, alpha)
    enough = n >= int(min_trades)
    passed = bool(enough and st["mean_r"] > 0 and st["t"] >= t_req)
    if passed:
        reason = "Vorteil statistisch belegt"
    elif not enough:
        reason = f"nur {n} Test-Trades (mind. {int(min_trades)})"
    elif st["mean_r"] <= 0:
        reason = "kein positiver Erwartungswert auf Testdaten"
    else:
        reason = (f"t={st['t']:.2f} unter der Hürde {t_req:.2f} "
                  f"(bei {int(n_trials or 1)} geprüften Kandidaten)")
    return {"known": True, "passed": passed, "n": n, "n_trials": int(n_trials or 1),
            "mean_r": round(st["mean_r"], 4), "std_r": round(st["std_r"], 4),
            "t": round(st["t"], 3), "t_required": round(t_req, 3),
            "trades_needed": trades_needed(st["mean_r"], st["std_r"], t_req),
            "alpha": alpha, "reason": reason}
