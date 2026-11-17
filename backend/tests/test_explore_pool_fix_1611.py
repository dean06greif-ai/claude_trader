"""Fix 16.11.2026: Im Multi-Core-Pool (lokaler Worker, SIM_WORKERS) liefen Test und
Tresor der Endlossuche auf den TRAININGS-Kerzen – Tasks bekommen nur Symbol-Namen
und rechnen auf den Daten, mit denen der Pool gestartet wurde. Produktion: alle
5 Champions vom 16.11. hatten identische Trainings-, Test- und Tresor-Werte."""
import asyncio

from services import boot_migrations as bm, deep_explore, optimizer as opt, parallel_sim
from services import research_pipeline as rp
from tests.phase_fakedb import FakeDB


def run(coro):
    return asyncio.run(coro)


class _Pool:
    pass


def test_pool_has_data_identity():
    train = {"A": [1], "B": [2]}
    pool = _Pool()
    parallel_sim._POOL_DATA[id(pool)] = train
    try:
        assert parallel_sim.pool_has_data(pool, train)
        assert parallel_sim.pool_has_data(pool, {"A": train["A"]})        # Teilmenge derselben Serien
        assert not parallel_sim.pool_has_data(pool, {"A": [1], "B": [2]})  # gleicher Inhalt, andere Serien
        assert not parallel_sim.pool_has_data(pool, {"C": [3]})
        assert not parallel_sim.pool_has_data(pool, {})
    finally:
        parallel_sim._POOL_DATA.pop(id(pool), None)
    assert not parallel_sim.pool_has_data(_Pool(), train)                  # unbekannter Pool


def test_evaluate_batch_uses_given_data_when_pool_has_other(monkeypatch):
    train = {"A": ["train"]}
    test = {"A": ["test"]}
    pool = _Pool()
    parallel_sim._POOL_DATA[id(pool)] = train
    seen = []

    def fake_evaluate(st, histories, s, c, fs_map, should_stop):
        seen.append(histories["A"][0])
        return {"trades": 1, "pnl": 1.0}
    monkeypatch.setattr(opt, "_evaluate", fake_evaluate)

    async def no_pause(job):
        return None
    monkeypatch.setattr(opt.job_control, "wait_if_paused", no_pause)
    try:
        out = run(opt._evaluate_batch({}, pool, [(object(), {}, {})], test, None, None))
    finally:
        parallel_sim._POOL_DATA.pop(id(pool), None)
    assert out == [{"trades": 1, "pnl": 1.0}] and seen == ["test"]


def test_champions_without_engine_are_legacy():
    old = {"labels": ["x"], "definition": {"long_rules": [{"indicator": "x"}]}, "wf": {"wf_score": 9},
           "evidence": {"passed": True, "t": 3.8}}
    new = {"labels": ["y"], "definition": {"long_rules": [{"indicator": "y"}]}, "wf": {"wf_score": 1},
           "evidence": {"passed": True, "t": 3.5, "engine": deep_explore.EXPLORE_ENGINE}}
    cur, legacy = deep_explore.split_best({"items": [old, new]})
    assert [c["labels"] for c in cur] == [["y"]] and [c["labels"] for c in legacy] == [["x"]]
    assert "Trainingsdaten" in legacy[0]["legacy_reason"]


def test_migration_discards_candidates_from_buggy_runs():
    db = FakeDB()
    old = rp.candidate_from_champion({"labels": ["x"], "definition": {}, "evidence": {"passed": True},
                                      "symbols": ["BTCUSDT"], "timeframe": "15m"})
    new = rp.candidate_from_champion({"labels": ["y"], "definition": {"long_rules": [{"indicator": "y"}]},
                                      "evidence": {"passed": True, "engine": deep_explore.EXPLORE_ENGINE},
                                      "symbols": ["BTCUSDT"], "timeframe": "15m"})
    run(db[rp.COLLECTION].insert_one(old))
    run(db[rp.COLLECTION].insert_one(new))
    run(bm.migrate_explore_pool_fix(db))
    stages = {d["title"]: d["stage"] for d in db[rp.COLLECTION].docs}
    assert stages == {"x": "verworfen", "y": "vorwaertstest"}
    assert any("Tresor" in c["text"] for c in db.ai_chat.docs)


def test_worker_gate_requires_fixed_package():
    from services import local_exec
    assert local_exec.OPTIMIZER_MIN_WORKER >= (1, 30)
    assert local_exec.REQUIRED_WORKER_VERSION >= (1, 30, 0)
