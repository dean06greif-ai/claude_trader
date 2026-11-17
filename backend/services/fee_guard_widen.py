"""Fee-Wächter für Paper-Datensammel-Trades: erweitern statt verwerfen (10/2026).

Befund (Prod, 7 Tage): 440 Fee-Wächter-Blocks, davon 420 auf Paper-
Datensammel-Trades – der größte Posten im Guard-Cockpit. Ein Paper-Trade
riskiert kein Kapital; verworfen fehlt er aber in der Setup-Statistik. Statt
zu blocken wird der SL schrittweise bis zum Minimum des Wächters erweitert
(TPs skalieren mit, CRV bleibt) – genau so, wie der Trade live handelbar wäre.
Live-Trades bleiben unverändert hart geschützt.
"""
from typing import Callable, Optional, Tuple

# 16.11.2026: Mit Fee-Faktor 10 (Minimum ~1,2 % bei Krypto) reichte 2,5× für
# Sammel-Trades mit dem Mindest-SL 0,42 % (min_sl_rule) nicht mehr – ~17 % der
# Lern-Signale fielen weg. 3× deckt sie ab; Live bleibt unverändert hart.
STEPS = (1.15, 1.3, 1.5, 1.75, 2.0, 2.5, 3.0)


def widen(check: Callable[[float, float], bool], side: str, entry: float, sl: float,
          tp1: float, tpf: float) -> Optional[Tuple[float, float, float, str]]:
    """Kleinste Erweiterung (STEPS × Risiko), die `check(sl, tp1)` besteht (rein).
    None = auch mit 3-fachem Risiko nicht zulässig -> Block bleibt."""
    try:
        entry, sl, tp1, tpf = float(entry), float(sl), float(tp1), float(tpf)
    except (TypeError, ValueError):
        return None
    risk = abs(entry - sl)
    if entry <= 0 or risk <= 0:
        return None
    d = 1 if str(side).upper() == "LONG" else -1
    for fac in STEPS:
        n_sl = entry - d * risk * fac
        n_tp1 = entry + (tp1 - entry) * fac
        n_tpf = entry + (tpf - entry) * fac
        if check(n_sl, n_tp1):
            return n_sl, n_tp1, n_tpf, (f"Fee-Wächter (Paper): SL {risk / entry * 100:.3f}%→"
                                        f"{risk * fac / entry * 100:.3f}% erweitert, TPs ×{fac:g}")
    return None
