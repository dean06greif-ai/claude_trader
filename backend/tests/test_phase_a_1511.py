"""Phase A (Leitstand-Plan 15.11.2026): Bewertungs-Stichtag, Nachprüfung statt
Löschen (Lektions-Kandidaten, Endlossuche-Bestenliste), aktuelle Diagnose-Texte,
Live-Bypass aus."""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from services import ai_edge_report, ai_playbook, boot_migrations as bm, deep_explore
from services import evaluation_cutoff as ec
from services import lesson_cleanup, setup_lifecycle
from tests.phase_fakedb import FakeDB


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _reset_cutoff():
    ec.set_cache(None)
    yield
    ec.set_cache(None)


# ---------------- Stichtag: reine Logik ----------------
def test_apply_takes_later_of_lookback_and_cutoff():
    lb = "2026-11-01T00:00:00+00:00"
    assert ec.apply(lb, "2026-11-15T21:00:00+00:00") == "2026-11-15T21:00:00+00:00"
    assert ec.apply(lb, "2026-10-01T00:00:00+00:00") == lb
    assert ec.apply(lb, None) == lb                      # Cache leer -> Fenster
    assert ec.apply(lb, "kein datum") == lb              # ungültig -> Fenster
    # gemischte Offsets: 22:00+01:00 == 21:00Z -> später als 20:00Z
    assert ec.apply("2026-11-15T20:00:00+00:00", "2026-11-15T22:00:00+01:00") \
        == "2026-11-15T21:00:00+00:00"


def test_apply_uses_cache_and_is_after():
    ec.set_cache("2026-11-15T21:00:00Z")
    assert ec.cached_since() == "2026-11-15T21:00:00+00:00"
    assert ec.apply("2026-11-01T00:00:00+00:00") == "2026-11-15T21:00:00+00:00"
    assert ec.is_after("2026-11-15T21:30:00+00:00") is True
    assert ec.is_after("2026-11-15T20:59:00+00:00") is False
    ec.set_cache(None)
    assert ec.is_after("2000-01-01T00:00:00+00:00") is True


def test_default_since_prefers_rules_marker():
    marker = {"cost_guard_v1": True, "cost_guard_v1_at": "2026-11-15T20:41:07.5+00:00"}
    assert ec.default_since(marker) == "2026-11-15T20:41:07.500000+00:00"
    assert ec.default_since({}, "2026-11-16T08:00:00+00:00") == "2026-11-16T08:00:00+00:00"


def test_ensure_default_sets_once_and_respects_trader_choice():
    db = FakeDB()
    run(db.settings.insert_one({"_id": "boot_migrations", "cost_guard_v1_at": "2026-11-15T20:41:00+00:00"}))
    assert run(ec.ensure_default(db)) == "2026-11-15T20:41:00+00:00"
    # Trader hebt den Stichtag auf -> ein späterer Lauf setzt ihn NICHT neu
    run(ec.set_since(db, None, by="trader"))
    assert run(ec.ensure_default(db)) is None and ec.cached_since() is None


def test_set_since_validates():
    db = FakeDB()
    with pytest.raises(ValueError):
        run(ec.set_since(db, "morgen"))
    future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    with pytest.raises(ValueError):
        run(ec.set_since(db, future))
    st = run(ec.set_since(db, "2026-11-15T21:00:00Z", note="test"))
    assert st["enabled"] and st["since"] == "2026-11-15T21:00:00+00:00"
    assert ec.cached_since() == "2026-11-15T21:00:00+00:00"


def test_playbook_stats_match_honours_cutoff():
    ec.set_cache(None)
    m0 = ai_playbook._stats_match(30, False, None, False, None, None)
    ec.set_cache(datetime.now(timezone.utc).isoformat())
    m1 = ai_playbook._stats_match(30, False, None, False, None, None)
    assert m1["opened_at"]["$gte"] > m0["opened_at"]["$gte"]


# ---------------- Profil-Hinweis (Fee-Minimum) ----------------
def _profile(sl):
    return {"versions": [{"v": 3, "params": {"sl_pct": sl, "tp_ratio": 2.0}, "stats": {"trades": 12},
                          "since": "2026-11-01", "note": "auto"}]}


def test_profile_line_flags_sl_below_fee_minimum():
    line = setup_lifecycle.profile_line("divergence", _profile(0.5), 1.2)
    assert "unter dem Fee-Minimum 1.20%" in line and "SL mind. 1.20%" in line
    assert "Fee-Minimum" not in setup_lifecycle.profile_line("divergence", _profile(1.4), 1.2)
    assert "Fee-Minimum" not in setup_lifecycle.profile_line("divergence", _profile(0.5))
    head, row = setup_lifecycle.context_lines({"divergence": _profile(0.5)}, 1.2)
    assert "SETUP-PROFILE" in head and "Fee-Minimum" in row


def test_fee_min_hint_per_class():
    cfg = {"fee_guard_enabled": True, "fee_guard_mult": 10}
    assert ai_playbook._fee_min_sl_hint(cfg, "crypto") == 1.2
    assert ai_playbook._fee_min_sl_hint(cfg, "forex") is None
    assert ai_playbook._fee_min_sl_hint({"fee_guard_enabled": False}, "crypto") is None


# ---------------- Lektions-Kandidaten nachprüfen ----------------
def test_recheck_candidates_archives_problems_and_caps_old_confirmations():
    active = [{"title": "Kein LONG gegen Tagestrend", "detail": "LONG bei Tages-Bias down meiden"}]
    cands = [
        {"key": "a", "title": "Scalp 10m", "detail": "Auf dem 10m-Chart Trend prüfen",
         "confirmations": 2, "updated_at": "2026-11-10T00:00:00+00:00"},
        {"key": "b", "title": "Kein LONG gegen Tagestrend", "detail": "x", "confirmations": 1,
         "updated_at": "2026-11-10T00:00:00+00:00"},
        {"key": "c", "title": "Volumen-Bestätigung", "detail": "Breakout nur mit Volumen > Ø",
         "confirmations": 3, "updated_at": "2026-11-10T00:00:00+00:00"},
        {"key": "d", "title": "Spread meiden", "detail": "Bei Spread > 0,1 % kein Einstieg",
         "confirmations": 3, "updated_at": "2026-11-16T00:00:00+00:00"},
    ]
    updates, archive = lesson_cleanup.recheck_candidates(cands, active, "2026-11-15T21:00:00+00:00")
    assert {a["key"] for a in archive} == {"a", "b"}
    assert all(a["archive_reason"] for a in archive)
    assert updates == [{"key": "c", "set": {
        "confirmations": 1, "evidence_ts": "2026-11-15T21:00:00+00:00",
        "recheck_note": "vor dem Stichtag 3× bestätigt – braucht eine Bestätigung mit neuen Trades"}}]


def test_migrate_lesson_candidates_recheck_moves_to_archive_not_delete():
    db = FakeDB()
    ec.set_cache("2026-11-15T21:00:00+00:00")
    run(db.ai_lesson_candidates.insert_one({"key": "a", "title": "Scalp 10m", "detail": "10m-Trend",
                                            "confirmations": 2, "updated_at": "2026-11-10"}))
    run(db.ai_lesson_candidates.insert_one({"key": "c", "title": "Volumen", "detail": "Breakout mit Volumen",
                                            "confirmations": 3, "updated_at": "2026-11-10"}))
    run(bm.migrate_lesson_candidates_recheck(db))
    assert [d["key"] for d in db.ai_lesson_candidates.docs] == ["c"]
    assert db.ai_lesson_candidates.docs[0]["confirmations"] == 1
    assert [d["key"] for d in db.ai_lesson_candidates_archive.docs] == ["a"]
    run(bm.migrate_lesson_candidates_recheck(db))          # Marker: kein zweiter Lauf
    assert len(db.ai_lesson_candidates_archive.docs) == 1


# ---------------- Live-Bypass aus ----------------
def test_migrate_live_bypass_off_once():
    db = FakeDB()
    run(db.settings.insert_one({"_id": "ai_trader_config", "live_gate_bypass_enabled": True}))
    eng = SimpleNamespace(config={"live_gate_bypass_enabled": True})
    run(bm.migrate_live_bypass_off(db, eng))
    cfg = run(db.settings.find_one({"_id": "ai_trader_config"}))
    assert cfg["live_gate_bypass_enabled"] is False and eng.config["live_gate_bypass_enabled"] is False
    assert any("Live-Bypass" in c["text"] for c in db.ai_chat.docs)
    # spätere Entscheidung des Traders bleibt
    run(db.settings.update_one({"_id": "ai_trader_config"}, {"$set": {"live_gate_bypass_enabled": True}}))
    run(bm.migrate_live_bypass_off(db, eng))
    assert run(db.settings.find_one({"_id": "ai_trader_config"}))["live_gate_bypass_enabled"] is True


def test_migrate_evaluation_since_writes_feed_once():
    db = FakeDB()
    run(db.settings.insert_one({"_id": "boot_migrations", "cost_guard_v1_at": "2026-11-15T20:41:00+00:00"}))
    run(bm.migrate_evaluation_since(db))
    run(bm.migrate_evaluation_since(db))
    assert ec.cached_since() == "2026-11-15T20:41:00+00:00"
    assert sum("Bewertungs-Stichtag" in c["text"] for c in db.ai_chat.docs) == 1


# ---------------- Endlossuche-Bestenliste ----------------
def _champ(key, wf, evidence=True):
    c = {"labels": [key], "definition": {"long_rules": [{"indicator": key}]}, "wf": {"wf_score": wf},
         "rules": [key]}
    if evidence:
        c["evidence"] = {"passed": True, "t": 3.1, "engine": deep_explore.EXPLORE_ENGINE}
    return c


def test_split_best_keeps_legacy_separate():
    doc = {"items": [_champ("atr", 999.0, evidence=False), _champ("rsi", 5.0)]}
    cur, legacy = deep_explore.split_best(doc)
    assert [c["labels"] for c in cur] == [["rsi"]]
    assert [c["labels"] for c in legacy] == [["atr"]] and legacy[0]["legacy_reason"]


def test_persist_best_legacy_no_longer_blocks_new_champions():
    db = FakeDB()
    old = [_champ(f"old{i}", 900.0 + i, evidence=False) for i in range(5)]
    run(db.settings.insert_one({"_id": "deep_explore_best", "items": old}))
    run(deep_explore.persist_best(db, {"explore_report": {"champions": [
        _champ("ema", 4.0), _champ("noevidence", 50.0, evidence=False)]}}))
    doc = run(db.settings.find_one({"_id": "deep_explore_best"}))
    assert [c["labels"] for c in doc["items"]] == [["ema"]]
    assert len(doc["legacy_items"]) == 5                    # nichts gelöscht


# ---------------- Diagnose-Texte ----------------
def _overall(fee):
    return {"with_risk": 40, "exp_r": -0.1, "gross_r": 0.05, "fee_r": fee}


def test_fee_finding_recommends_current_rule():
    low = ai_edge_report.edge_findings(_overall(0.2), {}, {}, {}, {}, {"fee_guard_mult": 4}, None)
    txt = " ".join(f["text"] for f in low)
    assert "Faktor 10" in txt and "≥ 6" not in txt
    hi = ai_edge_report.edge_findings(_overall(0.2), {}, {}, {}, {}, {"fee_guard_mult": 10}, None)
    assert any("schon auf Faktor 10" in f["text"] for f in hi)


# ---------------- Lernlauf ----------------
def test_learning_outcomes_text_ignores_trades_before_cutoff():
    from services import ai_learning
    db = FakeDB()
    svc = ai_learning.AILearning(SimpleNamespace(config={}, db=db))
    run(db.auto_trades.insert_one({"id": "t1", "strategy_id": "ai_trader", "status": "closed",
                                       "opened_at": "2026-11-10T00:00:00+00:00",
                                       "closed_at": "2026-11-10T01:00:00+00:00",
                                       "symbol": "BTCUSDT", "realized_pnl": -5}))
    ec.set_cache("2026-11-15T21:00:00+00:00")
    txt = run(svc._recent_outcomes_text())
    assert "seit dem Bewertungs-Stichtag" in txt
