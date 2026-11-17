"""F1–F3 (17.11.2026): strengere Champion-Prüfung, Versuchs-Konto, Rückwärtstest,
Ziel „t-Wert (R)“, Trend-Slot der Nacht-Forschung, Trendfolge-Vorgaben,
Übernahme-Fix (Paper-Modus) und Lern-Limit 10."""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from services import boot_migrations as bm, champion_checks as cc, cockpit, deep_explore
from services import evidence_stats, night_research as nr, optimizer as opt
from services import research_pipeline as rp
from tests.phase_fakedb import FakeDB


def run(coro):
    return asyncio.run(coro)


def m(n, mean, sd=1.0, pnl=None):
    return {"trades": n, "pnl": mean * n if pnl is None else pnl, "r_n": n, "r_sum": mean * n,
            "r_sq": n * (sd * sd + mean * mean)}


# ---------------- reine Urteile ----------------
def test_r_summary_and_missing_r():
    s = cc.r_summary(m(100, 0.2))
    assert s["known"] and s["trades"] == 100 and s["avg_r"] == 0.2 and s["t"] > 1.9
    assert s["lb"] < 0.2 < s["ub"]
    assert cc.r_summary({"trades": 7})["known"] is False
    assert cc.r_summary(None)["trades"] == 0


def test_train_must_be_positive_in_r():
    ok, why = cc.train_ok(m(100, -0.05, pnl=230.0))
    assert not ok and "Positionsgrößen" in why
    assert cc.train_ok(m(100, 0.1))[0]
    assert cc.train_ok({"trades": 50, "pnl": 10.0})[0]          # Alt-Ergebnis ohne R: Gewinn entscheidet
    assert not cc.train_ok({"trades": 50, "pnl": -10.0})[0]


def test_vault_needs_trades_and_positive_r():
    assert not cc.vault_ok(m(4, 0.9), 3)[0]                      # früher bestanden: 4 Trades im Plus
    assert not cc.vault_ok(m(25, -0.1, pnl=50.0), 3)[0]          # Gewinn in USDT, aber R negativ
    assert cc.vault_ok(m(25, 0.1), 3)[0]
    assert not cc.vault_ok(m(12, 0.3), 20)[0]                    # eigener Mindestwert des Laufs gilt weiter
    assert cc.vault_ok({"trades": 15, "pnl": 5.0}, 3)[0]         # ohne R-Kennzahlen: Gewinn


def test_back_verdict_states():
    assert cc.back_verdict(None)["state"] == "nicht_pruefbar" and cc.back_verdict(None)["passed"]
    few = cc.back_verdict(m(8, -0.5), 180)
    assert few["state"] == "nicht_pruefbar" and few["passed"]
    bad = cc.back_verdict(m(80, -0.1), 180)
    assert bad["state"] == "durchgefallen" and not bad["passed"] and "Rückwärtstest" in bad["reason"]
    good = cc.back_verdict(m(80, 0.15), 180)
    assert good["state"] == "bestanden" and good["passed"] and good["days"] == 180.0


def test_side_split_flags_one_sided_edge():
    assert cc.side_split(m(50, 0.4), m(50, -0.1))["one_sided"]
    assert cc.side_split(m(50, -0.2), m(50, 0.3))["note"].startswith("Vorteil nur auf der Short")
    assert not cc.side_split(m(50, 0.3), m(50, 0.2))["one_sided"]
    assert cc.side_split(m(60, 0.3), m(2, 0.2))["one_sided"]      # fast nur eine Richtung gehandelt


def test_combined_unseen_adds_sums():
    u = cc.combined_unseen([m(20, 0.1), None, m(80, 0.2)])
    assert u["trades"] == 100 and abs(u["avg_r"] - 0.18) < 1e-6


# ---------------- Versuchs-Konto ----------------
def test_trial_account_window_and_hurdle():
    now = datetime(2026, 11, 17, tzinfo=timezone.utc)
    doc = {"keys": {"crypto|15m": [{"at": (now - timedelta(days=40)).isoformat(), "n": 500},
                                   {"at": (now - timedelta(days=3)).isoformat(), "n": 141},
                                   {"at": (now - timedelta(days=1)).isoformat(), "n": 96}]}}
    assert cc.prior_from_doc(doc, "crypto|15m", now) == 237       # der 40 Tage alte Lauf zählt nicht mehr
    assert cc.prior_from_doc(doc, "forex|1h", now) == 0
    assert evidence_stats.required_t(100 + 237) > evidence_stats.required_t(100)


def test_trial_account_roundtrip_and_key():
    db = FakeDB()
    key = cc.trial_key(["BTCUSDT", "ETHUSDT"], "15m")
    assert key.endswith("|15m") and "." not in key
    assert cc.trial_key(["ETHUSDT"], "15m") == key                # gleiche Klasse + Zeitebene = ein Konto
    assert cc.trial_key(["BTCUSDT"], "1h") != key
    assert run(cc.prior_trials(db, ["BTCUSDT"], "15m")) == 0
    res = {"symbols": ["BTCUSDT", "ETHUSDT"], "timeframe": "15m", "explore_report": {"wf_checked": 141}}
    assert run(cc.record_trials(db, res)) == 141
    assert run(cc.record_trials(db, {**res, "explore_report": {"wf_checked": 9}})) == 9
    assert run(cc.prior_trials(db, ["SOLUSDT"], "15m")) == 150
    assert run(cc.record_trials(db, {"explore_report": {"wf_checked": 0}})) == 0
    assert run(cc.prior_trials(None, ["BTCUSDT"], "15m")) == 0


def test_persist_best_books_trials_even_without_champion():
    db = FakeDB()
    run(deep_explore.persist_best(db, {"symbols": ["BTCUSDT"], "timeframe": "15m",
                                       "explore_report": {"wf_checked": 72, "champions": []}}))
    assert run(cc.prior_trials(db, ["BTCUSDT"], "15m")) == 72
    assert run(db.settings.find_one({"_id": "deep_explore_best"})) is None


# ---------------- Optimizer ----------------
def test_objective_t_r_prefers_steady_edge():
    steady = m(200, 0.2, sd=1.0)
    lumpy = m(200, 0.2, sd=4.0)                                    # gleicher Ø, nur Ausreißer
    assert opt._score(steady, "t_r", 30) > opt._score(lumpy, "t_r", 30) > 0
    assert opt._score(m(200, -0.1), "t_r", 30) < 0
    assert opt._score(m(10, 0.5), "t_r", 30) < -1e8               # zu wenige Trades
    assert opt._score({"trades": 50, "pnl": 12.0, "win_rate": 50.0}, "t_r", 30) == 12.0   # Alt-Ergebnis: Rückfall


def test_backward_days_only_for_local_explore():
    assert opt.backward_days({"execution": "local"}, "explore", 180) == 180
    assert opt.backward_days({"execution": "local"}, "explore", 540) == opt.BACKWARD_MAX_DAYS
    assert opt.backward_days({"execution": "cloud"}, "explore", 180) == 0      # Cloud: RAM-Grenze
    assert opt.backward_days({"execution": "local"}, "combo", 180) == 0
    assert opt.backward_days({"execution": "local", "explore": {"backward": False}}, "explore", 180) == 0
    assert opt.backward_days({"execution": "local", "explore": {"backward_days": 60}}, "explore", 180) == 60
    assert opt.backward_days({"execution": "local", "explore": {"backward_days": "x"}}, "explore", 90) == 90


def test_search_warning_for_usdt_objective_in_explore():
    w = opt.search_warnings({"mode": "explore", "walk_forward": {"enabled": True}, "symbols": ["A"] * 8,
                             "timeframe": "15m", "max_rules": 3}, 180, 60, "combo")
    assert any("t-Wert (R)" in x for x in w)
    w2 = opt.search_warnings({"mode": "explore", "walk_forward": {"enabled": True}, "symbols": ["A"] * 8,
                              "timeframe": "15m", "max_rules": 3}, 180, 60, "t_r")
    assert not any("t-Wert (R)" in x for x in w2)


def test_engine_3_required_for_best_list():
    assert deep_explore.EXPLORE_ENGINE == 3
    assert not deep_explore.is_validated({"evidence": {"passed": True, "engine": 2}})
    assert deep_explore.is_validated({"evidence": {"passed": True, "engine": 3}})


# ---------------- Nacht-Forschung ----------------
def test_night_trend_slot_first_and_honest_objective():
    slot = nr.ROTATION[0]
    assert slot["key"] == "crypto_1h_trend" and "donchian_high" in slot["indicators"]
    body = nr.build_body(slot, ["BTCUSDT", "ETHUSDT"], 300)
    assert body["objective"] == "t_r" and body["min_trades"] == nr.NIGHT_MIN_TRADES
    assert body["indicators"] == nr.TREND_INDICATORS and body["optimize"] == {"tpsl": True, "trail": True}
    plain = nr.build_body(nr.ROTATION[1], ["BTCUSDT", "ETHUSDT"], 300)
    assert plain["indicators"] is None and plain["optimize"] == {"tpsl": True}
    assert nr.next_slot({"last_slot": "crypto_1h_trend"})["key"] == "crypto_1h"
    assert {s["classes"] for s in nr.ROTATION} == {("crypto",)}   # 17.11.: nur Krypto (Live nur Krypto)
    assert "5m" not in {s["timeframe"] for s in nr.ROTATION}
    known = {c["ind"] for c in opt.build_candidates(None)}
    assert set(nr.TREND_INDICATORS) <= known                      # keine Tippfehler in der Liste


# ---------------- Vorgaben + Übernahme ----------------
def test_presets_created_once_and_forward_tested():
    db = FakeDB()
    assert run(rp.ensure_presets(db, ["BTCUSDT", "ETHUSDT"])) == len(rp.PRESETS)
    assert run(rp.ensure_presets(db, ["BTCUSDT", "ETHUSDT"])) == 0
    rows = run(rp.list_candidates(db))
    by = {r["ref"]: r for r in rows}
    c4 = by["preset:trend_basis_4h"]
    # 17.11. abends: 4h nicht mehr per Klick startbar (Speicher-Risiko im Live-Scanner)
    assert c4["kind"] == "vorgabe" and c4["stage"] == "vorwaertstest" and not c4["can_adopt"]
    assert c4["max_days"] == rp.PRESET_MAX_DAYS and c4["history_evidence"]["trades"] == 3677
    assert not by["preset:trend_basis_1d"]["can_adopt"]          # Tageskerzen: Live-Puffer reicht nicht
    full = run(db[rp.COLLECTION].find_one({"ref": "preset:trend_basis_4h"}))
    assert rp.needs_eval(full)
    assert full["definition"]["indicators"]["donchian_period"] == 60
    assert full["trade_params"]["sl_mode"] == "atr" and full["trade_params"]["be_mode"] == "off"
    assert run(rp.ensure_presets(db, ["BTCUSDT"])) == 0           # zu wenige Assets


def test_verdict_respects_candidate_max_days():
    found = (datetime.now(timezone.utc) - timedelta(days=200)).isoformat()
    prog = rp.r_stats(12, 3.0, 40.0)
    assert rp.verdict(prog, found) == "abgelaufen"
    assert rp.verdict(prog, found, max_days=rp.PRESET_MAX_DAYS) == "vorwaertstest"


def test_can_adopt_rules():
    assert rp.can_adopt({"stage": "bestanden", "kind": "champion"})
    assert not rp.can_adopt({"stage": "vorwaertstest", "kind": "champion"})
    assert rp.can_adopt({"stage": "vorwaertstest", "kind": "vorgabe", "adoptable": True})
    assert not rp.can_adopt({"stage": "vorwaertstest", "kind": "vorgabe", "adoptable": False})
    assert not rp.can_adopt({"stage": "verworfen", "kind": "vorgabe", "adoptable": True})


def test_candidate_carries_backward_result():
    item = {"labels": ["a"], "definition": {"long_rules": [{"indicator": "rsi", "op": "<", "value": 30}]},
            "evidence": {"t": 4.1, "t_required": 3.3, "passed": True, "engine": 3},
            "backward": {"state": "bestanden", "trades": 90, "avg_r": 0.12, "t": 1.4, "days": 180.0,
                         "reason": "ok", "lb": 0.0},
            "sides": {"note": "Vorteil nur auf der Long-Seite – kann Marktrichtung sein"},
            "symbols": ["BTCUSDT"], "timeframe": "15m"}
    c = rp.candidate_from_champion(item)
    assert c["backward"]["state"] == "bestanden" and "lb" not in c["backward"]
    assert c["one_sided"].startswith("Vorteil nur")
    assert rp.candidate_from_champion({**item, "backward": None, "sides": None})["backward"] is None


def test_cockpit_recommends_preset_with_evidence():
    cands = [{"id": "p1", "kind": "vorgabe", "stage": "vorwaertstest", "adoptable": True,
              "title": "Trend-Basis 4h", "progress": rp.r_stats(0, 0, 0),
              "history_evidence": {"trades": 3677, "avg_r": 0.2, "t": 3.6, "since": "2021", "recent": "x"}},
             {"id": "p2", "kind": "vorgabe", "stage": "vorwaertstest", "adoptable": False,
              "title": "Trend-Basis 1d", "progress": rp.r_stats(12, 3.0, 40.0),
              "history_evidence": {"trades": 1669, "avg_r": 0.34, "t": 4.6, "since": "2018", "recent": "y"}}]
    recs = cockpit.rec_candidates(cands)
    assert len(recs) == 2
    a, b = recs
    assert a["action"]["kind"] == "candidate_adopt" and "+0.20 R" in a["detail"] and "3677" in a["detail"]
    assert b["action"] is None and "12 Trades" in b["detail"] and "Tageskerzen" in b["detail"]


def test_adopt_sets_paper_mode_and_limits_assets(monkeypatch):
    import sys
    import types
    db = FakeDB()
    run(rp.ensure_presets(db, ["BTCUSDT", "ETHUSDT"]))
    cid = run(db[rp.COLLECTION].find_one({"ref": "preset:trend_basis_4h"}))["id"]
    run(db[rp.COLLECTION].update_one({"id": cid}, {"$set": {"adoptable": True}}))   # Regel selbst prüfen
    calls = {}

    async def fake_apply(body, _admin):
        calls["apply"] = body
        return {"status": "success", "id": "custom_abc12345"}       # optimizer_apply liefert "id"

    async def fake_set(sid, cfg, _admin):
        calls["mode"] = (sid, cfg)
    monkeypatch.setitem(sys.modules, "routers.optimizer", types.SimpleNamespace(optimizer_apply=fake_apply))
    monkeypatch.setitem(sys.modules, "routers.autotrade", types.SimpleNamespace(set_strategy_autotrade=fake_set))
    res = run(rp.adopt(db, cid))
    assert res["strategy_id"] == "custom_abc12345"
    assert calls["mode"] == ("custom_abc12345", {"mode": "paper", "enabled": True})
    excl = calls["apply"]["exclude_symbols"]
    assert "BTCUSDT" not in excl and "ETHUSDT" not in excl and len(excl) > 5
    assert calls["apply"]["timeframe"] == "4h" and calls["apply"]["name"] == "Trend-Basis 4h"
    doc = run(db[rp.COLLECTION].find_one({"id": cid}))
    assert doc["stage"] == "uebernommen" and doc["strategy_id"] == "custom_abc12345"
    cid1 = run(db[rp.COLLECTION].find_one({"ref": "preset:trend_basis_1d"}))["id"]
    with pytest.raises(ValueError):
        run(rp.adopt(db, cid1))


# ---------------- Migrationen ----------------
class _Eng:
    def __init__(self, cfg):
        self.config = cfg


def test_migration_collection_limit_respects_own_value():
    db = FakeDB()
    eng = _Eng({"collection_max_same_direction": 5})
    run(db.settings.insert_one({"_id": "ai_trader_config", "collection_max_same_direction": 5}))
    run(bm.migrate_collection_direction_10(db, eng))
    assert run(db.settings.find_one({"_id": "ai_trader_config"}))["collection_max_same_direction"] == 10
    assert eng.config["collection_max_same_direction"] == 10
    db2 = FakeDB()
    eng2 = _Eng({"collection_max_same_direction": 3})
    run(db2.settings.insert_one({"_id": "ai_trader_config", "collection_max_same_direction": 3}))
    run(bm.migrate_collection_direction_10(db2, eng2))
    assert run(db2.settings.find_one({"_id": "ai_trader_config"}))["collection_max_same_direction"] == 3
    run(db.settings.update_one({"_id": "ai_trader_config"}, {"$set": {"collection_max_same_direction": 5}}))
    run(bm.migrate_collection_direction_10(db, eng))             # nur einmal
    assert run(db.settings.find_one({"_id": "ai_trader_config"}))["collection_max_same_direction"] == 5


def test_migration_v3_discards_old_candidates_and_adds_presets():
    db = FakeDB()
    run(db[rp.COLLECTION].insert_one({"id": "old", "kind": "champion", "stage": "vorwaertstest",
                                      "search_evidence": {"engine": 2}}))
    run(db[rp.COLLECTION].insert_one({"id": "new", "kind": "champion", "stage": "vorwaertstest",
                                      "search_evidence": {"engine": 3}}))
    run(bm.migrate_champion_checks_v3(db))
    assert run(db[rp.COLLECTION].find_one({"id": "old"}))["stage"] == "verworfen"
    assert run(db[rp.COLLECTION].find_one({"id": "new"}))["stage"] == "vorwaertstest"
    assert run(db[rp.COLLECTION].count_documents({"kind": "vorgabe"})) == len(rp.PRESETS)
    run(bm.migrate_champion_checks_v3(db))
    assert run(db[rp.COLLECTION].count_documents({"kind": "vorgabe"})) == len(rp.PRESETS)
