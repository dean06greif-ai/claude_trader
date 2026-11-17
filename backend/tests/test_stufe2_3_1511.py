"""Stufe 2 und 3 (Trade-Analyse 15.11.2026): ehrliches KI-Trader-Lab,
strengere Setup-Live-Freigabe, Veto-/Verpasst-Bilanz, Markt-Benchmark,
ML-Labor mit Hold-out, Prüfer-Modus als Standard, Endlossuche ohne
immer-wahre Regeln und mit sinnvollen Hinweisen."""
import asyncio

import pytest

from services import ai_ml_lab, ai_role, boot_migrations as bm, market_benchmark
from services import optimizer, veto_balance
from services.setup_backtest import runner, weights


# ---------------- KI-Trader-Lab ----------------
def _lab_trade(pnl, entry=100.0, sl=99.0):
    return {"realized_pnl": pnl, "entry": entry, "initial_sl": sl}


def test_lab_stats_carry_r_sums():
    st = runner.stats_of([_lab_trade(1.0), _lab_trade(-1.0), _lab_trade(2.0)])
    # Notional 100, SL 1 % -> Risiko 1 USDT -> R = PnL
    assert st["r_n"] == 3 and abs(st["r_sum"] - 2.0) < 1e-9 and abs(st["r_sq"] - 6.0) < 1e-9
    assert runner.trade_r({"realized_pnl": 1.0, "entry": 100.0}) is None


def _oos(mean, sd, n):
    return {"trades": n, "r_n": n, "r_sum": mean * n, "r_sq": n * (sd * sd + mean * mean)}


def test_lab_significance_hurdle_grows_with_trials():
    oos = _oos(0.3, 1.0, 60)                       # t ≈ 2,3
    assert runner.significance_of(oos, 1)["passed"] is True
    assert runner.significance_of(oos, 200)["passed"] is False
    res = {"passed": True, "oos": oos}
    runner.apply_significance(res, 200)
    assert res["passed"] is False and res["passed_basic"] is True and res["evidence"]["reason"]
    few = {"passed": True, "oos": _oos(1.0, 0.5, 12)}              # sehr stark, aber zu wenige
    assert runner.apply_significance(few, 1)["passed"] is False


def test_optimizer_selects_by_in_sample_not_test_data():
    base = {"passed": True, "is": {"trades": 50, "winrate": 50, "pnl": 10.0},
            "oos": {"trades": 20, "winrate": 50, "pnl": 1.0}}
    better_oos_only = {"passed": True, "is": {"trades": 50, "winrate": 50, "pnl": 9.0},
                       "oos": {"trades": 40, "winrate": 70, "pnl": 50.0}}
    assert runner.optimize_better(base, better_oos_only) is False


def test_compare_lab_paper_verdicts():
    lab = {"r_n": 100, "r_sum": 20.0}
    assert runner.compare_lab_paper(lab, {"r_n": 40, "r_sum": -12.0})["verdict"] == "widerspricht dem Lab"
    assert runner.compare_lab_paper(lab, {"r_n": 40, "r_sum": 8.0})["verdict"] == "stützt das Lab"
    assert runner.compare_lab_paper(lab, {"r_n": 5, "r_sum": 1.0})["verdict"] == "zu wenig echte Trades"
    assert runner.compare_lab_paper({}, None)["lab_avg_r"] is None


class _Agg:
    def __init__(self):
        self.pipeline = None

    def aggregate(self, pipeline):
        self.pipeline = pipeline

        class _C:
            async def to_list(self, n):
                return []
        return _C()


class _AggDB:
    def __init__(self):
        self.c = _Agg()

    def __getitem__(self, name):
        return self.c


def test_backtest_boost_only_from_lab_trades_with_evidence():
    db = _AggDB()
    asyncio.run(weights.class_backtest_stats(db, "crypto"))
    assert db.c.pipeline[0]["$match"]["lab_evidence"] is True
    assert weights.MAX_BACKTEST_WEIGHTED == 3


# ---------------- Veto-/Verpasst-Bilanz ----------------
def _t(ref, r):
    return {"signal_ref": ref, "realized_pnl": r * 10, "risk_usdt": 10}


def test_veto_balance_measures_rejected_signals():
    windows = [{"id": f"v{i}", "setup": "divergence", "status": "verworfen"} for i in range(12)]
    windows += [{"id": "g1", "setup": "divergence", "status": "genommen"}]
    rule = [_t(f"v{i}", -1.0 if i < 9 else 1.5) for i in range(12)] + [_t("g1", 0.5)]
    ki = [_t("g1", 1.0)]
    bal = veto_balance.balance(windows, rule, ki)
    d = bal["setups"]["divergence"]
    assert d["rejected"]["n"] == 12 and d["veto_value_r"] > 0
    assert d["verdict"] == "Veto spart Verluste"
    assert d["missed_gain_r"] == 4.5 and d["avoided_loss_r"] == 9.0
    assert d["timing"]["avg_r"] == 0.5
    assert "VETO-BILANZ" in veto_balance.prompt_text(bal)
    missed = veto_balance.balance(windows, [_t(f"v{i}", 1.0) for i in range(12)], [])
    assert missed["setups"]["divergence"]["verdict"] == "Veto verpasst Gewinne"
    assert veto_balance.prompt_text(veto_balance.balance(windows[:3], rule, [])) == ""


# ---------------- Markt-Benchmark ----------------
def test_market_benchmark_removes_direction_beta():
    rows = []
    for d in range(1, 21):
        day = f"2026-11-{d:02d}T10:00:00"
        rows.append({"setup": "breach", "side": "SHORT", "symbol": "BTCUSDT", "opened_at": day,
                     "realized_pnl": 5, "risk_usdt": 10})
        rows.append({"setup": "other", "side": "SHORT", "symbol": "ETHUSDT", "opened_at": day,
                     "realized_pnl": 5, "risk_usdt": 10})
    res = market_benchmark.excess(rows, lambda s: "crypto")
    assert res["breach"]["excess_r"] == 0.0
    assert res["breach"]["verdict"].startswith("wie der Markt")
    for r in rows:
        if r["setup"] == "other":
            r["realized_pnl"] = -5
    assert market_benchmark.excess(rows, lambda s: "crypto")["breach"]["verdict"] == "besser als der Markt"


# ---------------- ML-Labor ----------------
def test_ml_lab_reaches_prompts_only_with_holdout_evidence():
    assert ai_ml_lab.prompt_ready({"dataset": {"samples": 300}, "holdout_auc": 0.6}) is True
    assert ai_ml_lab.prompt_ready({"dataset": {"samples": 300}, "holdout_auc": 0.52}) is False
    assert ai_ml_lab.prompt_ready({"dataset": {"samples": 80}, "holdout_auc": 0.7}) is False
    assert ai_ml_lab.prompt_ready({"dataset": {"samples": 300}, "cv_auc": 0.9}) is False
    assert ai_ml_lab.cv_ready_for_holdout([1] * 120, [0, 1] * 60) is True
    assert ai_ml_lab.cv_ready_for_holdout(None, [0, 1] * 60) is False


def test_ml_train_reports_untouched_holdout():
    pytest.importorskip("xgboost")
    pytest.importorskip("optuna")
    import random
    rnd = random.Random(1)
    X = [{f: rnd.random() for f in ai_ml_lab.FEATURES} for _ in range(160)]
    y = [rnd.randint(0, 1) for _ in range(160)]
    ts = list(range(160))
    res = ai_ml_lab.train_sync(X, y, n_trials=5, timeout_sec=30, timestamps=ts)
    assert res["holdout_n"] == 32 and res["holdout_auc"] is not None


# ---------------- Prüfer-Modus ----------------
class _Coll:
    def __init__(self):
        self.docs = {}

    async def find_one(self, q):
        d = self.docs.get(q["_id"])
        return dict(d) if d else None

    async def update_one(self, q, upd, upsert=False):
        self.docs.setdefault(q["_id"], {"_id": q["_id"]}).update(upd.get("$set", {}))


class _DB:
    def __init__(self):
        self.settings = _Coll()


class _Eng:
    def __init__(self):
        self.config = {}


def test_pruefer_is_default_and_migrated_once():
    assert ai_role.DEFAULTS["ai_role"] == "pruefer"
    db, eng = _DB(), _Eng()
    db.settings.docs["ai_trader_config"] = {"_id": "ai_trader_config", "ai_role": "frei"}
    asyncio.run(bm.migrate_ai_role_pruefer(db, eng))
    assert db.settings.docs["ai_trader_config"]["ai_role"] == "pruefer" == eng.config["ai_role"]
    db.settings.docs["ai_trader_config"]["ai_role"] = "frei"            # Trader stellt zurück
    asyncio.run(bm.migrate_ai_role_pruefer(db, eng))
    assert db.settings.docs["ai_trader_config"]["ai_role"] == "frei"


# ---------------- Endlossuche ----------------
def test_discovery_pool_has_no_fixed_volatility_thresholds():
    cands = optimizer.build_candidates(None, None)
    labels = [c["label"] for c in cands]
    assert not any(lbl.startswith("BB Breite >") or lbl.startswith("ATR >") for lbl in labels)
    rel = [c for c in cands if c["ind"] == "atr_pct"]
    assert rel and all(c["long"]["value"] == "atr_pct(100)" for c in rel)


def test_search_warnings_point_to_sensible_settings():
    body = {"mode": "explore", "max_rules": 5, "symbols": ["BTCUSDT", "ETHUSDT"],
            "timeframe": "1m", "walk_forward": {"enabled": True}}
    w = " ".join(optimizer.search_warnings(body, 180, 30, "expectancy_r"))
    assert "2–3 Regeln" in w and "8–15 Assets" in w and "15m" in w
    ok = {"mode": "explore", "max_rules": 3, "symbols": [f"S{i}" for i in range(10)],
          "timeframe": "15m", "walk_forward": {"enabled": True}}
    assert optimizer.search_warnings(ok, 180, 30, "expectancy_r") == []


def test_endless_search_hurdle_does_not_start_low():
    from services import deep_explore, evidence_stats
    assert deep_explore.MIN_TRIALS_BUDGET >= 50
    # 1. geprüfter Kandidat muss schon die Hürde für >= 100 Versuche nehmen
    assert evidence_stats.required_t(max(1, deep_explore.MIN_TRIALS_BUDGET)) > 3.2


def test_endless_search_drawdown_filter_not_applied_during_search():
    # Prod 11/2026: 250.000 Kombis, 0 verfeinert – der DD-Filter wirkte schon in
    # der Suche. Er gilt jetzt nur auf den Testdaten (test_dd_ok).
    import inspect
    from services import deep_explore
    src = inspect.getsource(deep_explore.run_explore) if hasattr(deep_explore, "run_explore") \
        else inspect.getsource(deep_explore)
    assert "search_dd = None" in src
    assert "opt._score(m, objective, min_trades, search_dd)" in src
    assert "robustness.dd_check(test_m, dd_max_pct)" in src


def test_old_worker_cannot_run_searches_with_old_validation():
    import time
    from services import local_exec
    saved = dict(local_exec.WORKERS)
    try:
        local_exec.WORKERS.clear()
        local_exec.WORKERS["w"] = {"last_seen": time.time(), "version": "1.27.0"}
        assert local_exec.worker_supports_validation() is False
        local_exec.WORKERS["w"]["version"] = local_exec.OPTIMIZER_MIN_WORKER_STR
        assert local_exec.worker_supports_validation() is True
    finally:
        local_exec.WORKERS.clear()
        local_exec.WORKERS.update(saved)
