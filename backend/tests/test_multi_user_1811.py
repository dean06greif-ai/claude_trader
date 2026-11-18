"""18.11.2026: zwei Nutzer / zwei Worker gleichzeitig."""
from services import job_ownership as jo
from services import local_exec as le
from services import parallel_sim as ps


def _jobs():
    return {"a": {"id": "a", "status": "running", "created_at": "2026-11-18T20:00", "execution": "local"},
            "b": {"id": "b", "status": "running", "created_at": "2026-11-18T20:05", "execution": "local"},
            "c": {"id": "c", "status": "done", "created_at": "2026-11-18T19:00"}}


def test_active_prefers_own_run():
    act, others = jo.pick_active(_jobs(), ["a"])
    assert act["id"] == "a" and [o["id"] for o in others] == ["b"]
    act, _ = jo.pick_active(_jobs(), [])
    assert act["id"] == "b"                                   # wie bisher: neuester
    assert jo.parse_mine("a, b,,c") == ["a", "b", "c"]


def test_reset_hits_only_own_or_stale():
    jobs = _jobs()
    assert [j["id"] for j in jo.reset_targets(jobs, "a", lambda j: True)] == ["a"]
    assert jo.reset_targets(jobs, "c", lambda j: True) == []      # nicht laufend
    assert [j["id"] for j in jo.reset_targets(jobs, None, lambda j: j["id"] == "b")] == ["b"]


def test_stale_detection_keeps_healthy_remote_job(monkeypatch):
    now = 1000.0
    monkeypatch.setattr(le, "_now", lambda: now)
    monkeypatch.setattr(le, "worker_is_online", lambda wid: wid == "kumpel")
    le.LOCAL_JOBS["x"] = {"state": "claimed", "worker_id": "kumpel", "last_update": 950.0}
    le.LOCAL_JOBS["y"] = {"state": "claimed", "worker_id": "weg", "last_update": 990.0}
    le.LOCAL_JOBS["z"] = {"state": "queued", "worker_id": None}
    try:
        assert not le.job_is_stale({"id": "x", "execution": "local"})
        assert le.job_is_stale({"id": "y", "execution": "local"})
        assert not le.job_is_stale({"id": "z", "execution": "local"})
        assert le.job_is_stale({"id": "q", "execution": "cloud"})
    finally:
        for k in ("x", "y", "z"):
            le.LOCAL_JOBS.pop(k, None)


def test_data_jobs_go_to_the_chosen_worker():
    le.DATA_QUEUE.clear()
    j1 = le.create_data_job("data_download", {"symbols": ["BTCUSDT"], "days": 90}, target="meiner")
    j2 = le.create_data_job("data_update", {})
    try:
        got = le.claim("kumpel", want_compute=False, want_data=True)
        assert got["job_id"] == j2["id"]                       # nicht der für „meiner“
        assert le.DATA_QUEUE == [j1["id"]]
        got = le.claim("meiner", want_compute=False, want_data=True)
        assert got["job_id"] == j1["id"]
    finally:
        le.DATA_QUEUE.clear()
        for j in (j1, j2):
            le.DATA_JOBS.pop(j["id"], None)
            le.LOCAL_JOBS.pop(j["id"], None)


def test_variant_jobs_need_new_worker():
    payload = {"args": {"body": {"mode": "params", "strategy_id": "variant_1"}},
               "custom_definitions": [{"kind": "variant", "id": "variant_1", "base_id": "x"}]}
    assert le.uses_variant({"kind": "optimizer", "payload": payload})
    payload["args"]["body"]["mode"] = "explore"                # Regel-Suche: Kandidaten sind Definitionen
    assert not le.uses_variant({"kind": "optimizer", "payload": payload})
    bt = {"args": {"strategy_ids": ["variant_1"]}, "custom_definitions": payload["custom_definitions"]}
    assert le.uses_variant({"kind": "backtest", "payload": bt})


def test_variant_strategy_resolves_in_child_process():
    from strategies.registry import StrategyRegistry, registry
    base_id = next(sid for sid in registry.list_ids()
                   if not registry.is_variant(sid) and not getattr(registry.get(sid), "IS_CUSTOM", False)
                   and not registry.is_dynamic(sid))
    job_reg = StrategyRegistry()                                # Worker: eigene Registry je Job
    job_reg.load_custom([{"kind": "variant", "id": "variant_test1811", "base_id": base_id,
                          "name": "Kopie"}])
    strat = job_reg.get("variant_test1811")
    spec = ps.strategy_spec(strat)
    assert spec.get("variant", {}).get("id") == "variant_test1811"
    assert registry.get("variant_test1811") is None            # Kind kennt sie nicht ...
    try:
        got = ps._strategy_from_spec(spec)                     # ... bekommt sie aus der Spec
        assert got.STRATEGY_ID == "variant_test1811" and got.IS_VARIANT
    finally:
        registry.remove_variant("variant_test1811")


def test_process_count_respects_free_ram():
    assert ps.ram_capped_workers(12, 0) == 12                  # unbekannt: wie eingestellt
    assert ps.ram_capped_workers(12, 100) == 1                 # PC voll: sequenziell
    assert ps.ram_capped_workers(12, 4000) == 5
    assert ps.ram_capped_workers(4, 64000) == 4


def test_binance_host_sticks_to_last_working_one():
    import asyncio
    from services import history_sources as hs
    hs._BINANCE_PREF[0] = 0
    calls = []

    async def fake_get(session, url, params, timeout=30):
        calls.append(url)
        if url == hs.BINANCE_HOSTS[0]:
            raise RuntimeError("attempt failed")            # Mirror im Netz gesperrt
        return []

    orig, orig_sleep = hs._get_json_checked, hs.asyncio.sleep

    async def no_sleep(*_a, **_k):
        return None
    hs._get_json_checked = fake_get
    hs.asyncio.sleep = no_sleep
    try:
        asyncio.run(hs.fetch_binance(None, "BTCUSDT", 0, 60000))
        asyncio.run(hs.fetch_binance(None, "BTCUSDT", 0, 60000))
    finally:
        hs._get_json_checked, hs.asyncio.sleep = orig, orig_sleep
        hs._BINANCE_PREF[0] = 0
    assert calls == [hs.BINANCE_HOSTS[0], hs.BINANCE_HOSTS[1], hs.BINANCE_HOSTS[1]]
