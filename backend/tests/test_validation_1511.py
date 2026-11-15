"""Validierungs-Reparaturen aus der Gesamtanalyse 15.11.2026 (Punkt 4):
Slippage im Backtest, R-Kennzahlen, Walk-Forward als Durchfall-Kriterium,
Signifikanz mit Versuchs-Korrektur, Such-Warnungen, Bootstrap."""
import math

from services import evidence_stats as es
from services import optimizer, robustness
from services.backtester import DEFAULT_SLIPPAGE_PCT, simulate_pair


def _candles(prices):
    out, ts = [], 1_700_000_000_000
    for i, p in enumerate(prices):
        prev = prices[i - 1] if i else p
        out.append({"timestamp": ts + i * 60_000, "open": prev, "high": max(prev, p) * 1.0005,
                    "low": min(prev, p) * 0.9995, "close": p, "volume": 10.0})
    return out


class _Once:
    STRATEGY_ID = "t"

    def __init__(self, at):
        self.at = at


def _sim(cfg_extra):
    prices = [100.0] * 100 + [100.0 + 0.05 * i for i in range(1, 120)]
    c = _candles(prices)
    cfg = {"max_capital": 100.0, "leverage": 2, "fee_percent": 0.0, "sl_mode": "percent",
           "sl_fixed_percent": 2.0, "tp1_crv": 1.0, "tp_full_crv": 2.0, **cfg_extra}
    prov = lambda i: {"type": "LONG", "entry_price": c[i]["close"]} if i == 105 else None  # noqa: E731
    return simulate_pair(_Once(105), c, "BTCUSDT", {}, cfg, signal_provider=prov)


def test_slippage_default_costs_and_zero_restores_old_numbers():
    r0 = _sim({"slippage_percent": 0.0})
    r1 = _sim({})                                   # Standard greift
    assert r0["trades"] == r1["trades"] == 1
    assert r0["slippage"] == 0.0
    assert r1["slippage_percent"] == DEFAULT_SLIPPAGE_PCT
    assert r1["slippage"] > 0
    assert math.isclose(r0["pnl"] - r1["pnl"], r1["slippage"], abs_tol=0.02)


def test_limit_take_profit_pays_no_slippage_on_exit():
    market = _sim({"slippage_percent": 0.1})
    limit = _sim({"slippage_percent": 0.1, "tp_order_type": "limit", "maker_fee_percent": 0.0})
    assert limit["slippage"] < market["slippage"]


def test_r_sums_are_reported_and_additive():
    r = _sim({"slippage_percent": 0.0})
    assert r["r_n"] == 1 and r["avg_r"] == round(r["r_sum"], 4)
    comb = robustness.combine_test_metrics([r, r])
    assert comb["r_n"] == 2 and math.isclose(comb["r_sum"], 2 * r["r_sum"], rel_tol=1e-6)


def test_required_t_rises_with_number_of_trials():
    assert 1.6 < es.required_t(1) < 1.7
    assert es.required_t(10) > es.required_t(1)
    assert es.required_t(1000) > 3.8


def test_significance_needs_r_sums_trades_and_t():
    assert es.significance({"trades": 50, "pnl": 10})["passed"] is False      # Alt-Ergebnis
    weak = {"r_n": 100, "r_sum": 5.0, "r_sq": 100.0}                           # Ø 0,05 R
    strong = {"r_n": 100, "r_sum": 40.0, "r_sq": 116.0}                        # Ø 0,4 R, sd 1
    assert es.significance(weak, n_trials=1)["passed"] is False
    assert es.significance(strong, n_trials=1)["passed"] is True
    assert es.significance(strong, n_trials=10 ** 6)["passed"] is False        # Hürde steigt
    few = {"r_n": 8, "r_sum": 8.0, "r_sq": 9.0}
    assert es.significance(few)["passed"] is False
    assert es.significance(weak)["trades_needed"] > 100


def test_walk_forward_is_a_fail_criterion_by_default():
    robust = robustness.parse_config({"walk_forward": {"enabled": True}})
    assert robust["wf_strict"] is True and robust["vault_pct"] == 15.0
    assert robustness.parse_config({})["vault_pct"] == 0.0
    loss = robustness.wf_verdict({"trades": 40, "pnl": -5.0}, robust)
    few = robustness.wf_verdict({"trades": 3, "pnl": 5.0}, robust)
    lucky = robustness.wf_verdict({"trades": 40, "pnl": 5.0, "r_n": 40, "r_sum": 2.0, "r_sq": 40.0}, robust)
    good = robustness.wf_verdict({"trades": 40, "pnl": 5.0, "r_n": 40, "r_sum": 24.0, "r_sq": 54.4}, robust)
    assert not loss["passed"] and not few["passed"] and good["passed"]
    assert not lucky["passed"] and "nicht belegt" in lucky["reasons"][0]
    only_pnl = robustness.parse_config({"walk_forward": {"enabled": True, "require_significance": False}})
    assert robustness.wf_verdict({"trades": 40, "pnl": 5.0}, only_pnl)["passed"]
    entry = {"wf": {"wf_score": 1.0, **loss}, "test_metrics": {"trades": 40, "pnl": -5.0}}
    chk = [c for c in robustness.build_checks_summary(entry, robust) if c["id"] == "walk_forward"][0]
    assert chk["is_filter"] is True and chk["passed"] is False
    legacy = robustness.parse_config({"walk_forward": {"enabled": True, "strict": False}})
    chk = [c for c in robustness.build_checks_summary(entry, legacy) if c["id"] == "walk_forward"][0]
    assert chk["is_filter"] is False and chk["passed"] is None


def test_expectancy_objective_is_leverage_neutral():
    a = {"trades": 50, "pnl": 100.0, "win_rate": 50, "r_n": 50, "r_sum": 10.0, "r_sq": 60.0}
    b = {**a, "pnl": 1000.0}                         # 10× Hebel: gleicher Vorteil in R
    assert optimizer._score(a, "expectancy_r", 10) == optimizer._score(b, "expectancy_r", 10)
    assert optimizer._score(b, "pnl", 10) > optimizer._score(a, "pnl", 10)


def test_search_warnings():
    w = optimizer.search_warnings({"optimize": {"leverage": True, "sessions": True}}, 7, 10, "combo")
    txt = " ".join(w)
    assert "7 Tage" in txt and "Hebel" in txt and "Walk-Forward ist aus" in txt and "Handelsrichtung" in txt
    ok = optimizer.search_warnings({"optimize": {"tpsl": True}, "walk_forward": {"enabled": True}},
                                   365, 100, "expectancy_r")
    assert ok == []


def test_monte_carlo_reports_bootstrap_loss_probability():
    mc = robustness.monte_carlo([5.0, -4.0, 6.0, -5.0, 3.0, -2.0, 4.0, -3.0], 200, 1000.0)
    assert 0.0 < mc["boot_loss_prob_pct"] < 100.0 and mc["boot_pnl_p05"] < mc["total_pnl"]


def test_regime_breakdown_uses_entry_time():
    c = _candles([100.0 + i for i in range(400)])
    row = robustness._TradeRow(("X", c[-1]["timestamp"], 1.0))
    row.opened_ts = c[0]["timestamp"]
    s, _ts, _p = row                                 # entpackt wie bisher
    assert s == "X"
    agg, _ = robustness.regime_breakdown_with_symbols([row], {"X": c})
    first = robustness.classify_regimes(c)[0]
    assert agg[first]["trades"] == 1


# ---------------- D3/D4: Daten-Herkunft & tatsächliche Historie ----------------
def test_source_info_and_data_warnings():
    from services import history_sources as hs
    orig = hs._ibkr_available
    hs._ibkr_available = lambda: False
    try:
        btc, eur = hs.source_info("BTCUSDT"), hs.source_info("EURUSD")
        assert btc["source"] == "binance" and btc["matches_traded"] is False and btc["volume"] == "echt"
        assert eur["volume"] == "ersatz" and eur["backup"] == "Dukascopy" and eur["backup_scaled"] is False
        w = " ".join(hs.data_warnings(["BTCUSDT", "EURUSD"], ["rsi", "rel_volume"]))
        assert "Binance Spot" in w and "rel_volume" in w
        assert hs.data_warnings(["EURUSD"], ["rsi"]) == []           # kein Volumen-Indikator genutzt
        keep, dropped = hs.real_volume_only(["EURUSD"], ["rsi", "vwap", "rel_volume"])
        assert keep == ["rsi"] and dropped == ["vwap", "rel_volume"]
        assert hs.real_volume_only(["BTCUSDT"], ["rsi", "vwap"]) == (["rsi", "vwap"], [])
    finally:
        hs._ibkr_available = orig


def test_span_days_measures_real_history():
    c = _candles([100.0] * (3 * 1440 + 1))
    assert abs(robustness.span_days(c) - 3.0) < 1e-6
    assert robustness.span_days([]) == 0.0


def test_forex_backup_uses_same_volume_definition_as_live():
    import numpy as np
    from services import history_sources as hs
    orig = hs._ibkr_available
    hs._ibkr_available = lambda: False
    try:
        m = np.array([[0, 1.10, 1.1011, 1.1000, 1.1005, 321.0]])
        fx = hs.harmonize_volume(m, "EURUSD")
        assert abs(fx[0, 5] - hs.activity_volume(1.1011, 1.1000, 1.1005)) < 1e-6
        assert m[0, 5] == 321.0                                     # Eingabe bleibt unberührt
        assert hs.harmonize_volume(m, "BTCUSDT")[0, 5] == 321.0     # echtes Volumen bleibt
    finally:
        hs._ibkr_available = orig
