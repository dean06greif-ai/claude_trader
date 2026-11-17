"""Prüfwerkzeug scripts/systemcheck.py (Gesamtanalyse 15.11.2026, Punkt 13)."""
from scripts import systemcheck as sc


def _t(sid, pnl, risk=10.0, mode="paper", setup=None, **extra):
    return {"strategy_id": sid, "realized_pnl": pnl, "risk_usdt": risk, "mode": mode,
            "setup": setup, "status": "closed", **extra}


def test_trade_r_and_origin():
    assert sc.trade_r(_t("ai_engine", 5.0)) == 0.5
    assert sc.trade_r(_t("ai_engine", 5.0, risk=0)) is None
    assert sc.origin_of(_t("ai_engine", 1)) == "KI-Trader"
    assert sc.origin_of(_t("manual", 1)) == "Manuell"
    assert sc.origin_of(_t("trend_surfer", 1)) == "Strategie trend_surfer"


def test_summarize_groups_and_statistics():
    trades = ([_t("ai_engine", -10.0, setup="pullback")] * 30 + [_t("ai_engine", 15.0, setup="pullback")] * 10
              + [_t("trend_surfer", 4.0, mode="live"), _t("trend_surfer", -1.0, mode="live")] * 20
              + [_t("manual", -50.0, risk=0, mode="live")])
    s = sc.summarize(trades)
    assert s["trades"] == 81 and s["without_risk"] == 1
    ki = [g for g in s["by_origin"] if g["origin"] == "KI-Trader"][0]
    assert ki["n"] == 40 and ki["mean_r"] == -0.375 and ki["t"] < -2
    tf = [g for g in s["by_origin"] if g["origin"].startswith("Strategie")][0]
    assert tf["mode"] == "live" and tf["mean_r"] == 0.15 and tf["t"] > 2 and tf["trades_for_t2"] < 40
    man = [g for g in s["by_origin"] if g["origin"] == "Manuell"][0]
    assert man["n"] == 0 and man["pnl"] == -50.0                      # PnL zählt, R nicht bestimmbar
    assert s["by_setup"][0]["setup"] == "pullback"
    txt = sc.format_summary(s)
    assert "KI-Trader" in txt and "Manuell" in txt and "pullback" in txt


def test_synthetic_candles_have_no_drift_and_are_consistent():
    import numpy as np
    c = sc.synth_candles(20, seed=3)
    assert len(c) == 20 * 1440
    assert np.all(c.hi >= np.maximum(c.op, c.cl) - 1e-9) and np.all(c.lo <= np.minimum(c.op, c.cl) + 1e-9)
    assert np.allclose(c.op[1:], c.cl[:-1])
    r = np.diff(np.log(c.cl))
    assert abs(r.mean() / (r.std() / np.sqrt(len(r)))) < 4           # kein nachweisbarer Trend
