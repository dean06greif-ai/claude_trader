"""17.11.2026: TP1 und TP-Full fielen zusammen (Detektor 1 R/1,5 R + CRV-Minimum 1,5)."""
from types import SimpleNamespace

from core.utils import _rr
from services.ai_engine import AIEngine


def _frame(sl, tp1, tpf, crv_min=1.5, crv_max=10, swing=False):
    eng = SimpleNamespace(config={"crv_min": crv_min, "crv_max": crv_max})
    return AIEngine._apply_crv_frame(eng, sl, tp1, tpf, swing)


def test_tp_full_follows_raised_tp1():
    tp1, tpf = _frame(0.01, 0.01, 0.015)          # Detektor: 1 R / 1,5 R
    assert abs(tp1 - 0.015) < 1e-12 and abs(tpf - 0.0225) < 1e-12 and tpf > tp1
    tp1, tpf = _frame(0.0116, 0.0116 * 0.46, 0.0116 * 0.82)   # DOT-Fall 0,46 R / 0,82 R
    assert abs(tp1 / 0.0116 - 1.5) < 1e-9 and tpf / 0.0116 > 2.6


def test_unchanged_cases():
    assert _frame(0.01, 0.02, 0.04) == (0.02, 0.04)               # TP1 schon über dem Minimum
    tp1, tpf = _frame(0.01, 0.01, 0.01)                           # Detektor ohne Abstand
    assert tp1 == tpf == 0.015
    tp1, tpf = _frame(0.01, 0.01, 0.015, crv_max=2)               # Deckel bleibt: max 2 × crv_max
    assert tp1 == 0.015 and abs(tpf - 0.0225) < 1e-12
    tp1, tpf = _frame(0.01, 0.01, 0.03, crv_max=1.0)              # crv_max < crv_min: kein Deckel
    assert tp1 == 0.015 and abs(tpf - 0.045) < 1e-12


def test_real_r_multiples_for_display():
    assert _rr(100.0, 98.0, 103.0) == 1.5
    assert _rr(100.0, 102.0, 96.0, 9) == 2.0                      # Short
    assert _rr(100.0, 0, 103.0, 1.5) == 1.5                       # ohne SL -> Einstellung
    assert _rr(None, 98.0, 103.0, "x") == "x"
