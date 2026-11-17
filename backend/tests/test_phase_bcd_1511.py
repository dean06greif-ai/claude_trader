"""Phasen B–D (Leitstand-Plan 15.11.2026): Browser-Fehler, Systemarzt, Leitstand,
Nacht-Forschung, Kandidaten-Vorwärtstest, Lab wöchentlich, Prüf-Zuteilung nach
Veto-Wert, Live-Wächter, Tagesbericht, Autonomie-Takt."""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from services import (autonomy_loop, client_errors as ce, cockpit, daily_report, deep_explore,
                      evaluation_cutoff as ec, live_watchdog, night_research as nr,
                      research_pipeline as rp, review_allocation as ra, system_doctor as sd)
from services import boot_migrations as bm
from tests.phase_fakedb import FakeDB

BERLIN = ZoneInfo("Europe/Berlin")


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _clean():
    ce.reset_rate()
    ec.set_cache(None)
    yield
    ec.set_cache(None)


# =============================== Browser-Fehler ===============================
def test_sanitize_strips_query_ids_and_secrets():
    d = ce.sanitize({"kind": "api", "message": "Request failed Bearer abc.def.ghi token=xyz",
                     "url": "https://x.onrender.com/api/autotrade/trades/BTCUSDT-1794716811061?full=true",
                     "status": "500", "component": "Optimizer", "stack": "a\nb\nc\nd\ne\nf\ng\nh"})
    assert d["path"] == "/api/autotrade/trades/:id"
    assert "abc.def" not in d["message"] and "xyz" not in d["message"]
    assert d["status"] == 500 and d["stack"].count("\n") == 5
    assert ce.sanitize({"message": ""}) is None
    assert ce.sanitize({"kind": "evil", "message": "x"})["kind"] == "js"


def test_record_dedupes_and_groups():
    db = FakeDB()
    p = {"kind": "js", "message": "Cannot read properties of undefined (reading 'x') at 12",
         "component": "CockpitPanel"}
    assert run(ce.record(db, p))["status"] == "stored"
    assert run(ce.record(db, {**p, "message": p["message"].replace("12", "99")}))["status"] == "counted"
    s = run(ce.summary(db))
    assert s["total"] == 2 and s["sources"] == 1
    assert "CockpitPanel" in ce.describe(s["groups"][0])


def test_rate_limit_per_minute():
    now = 1_000_000.0
    assert all(ce.rate_ok(now) for _ in range(ce.MAX_PER_MIN))
    assert ce.rate_ok(now) is False
    assert ce.rate_ok(now + 61) is True


# =============================== Systemarzt ===============================
def test_doctor_selftest_and_safety():
    f = sd.judge_selftest({"checks": [{"ok": False, "label": "Gebühren", "detail": "falsch"}, {"ok": True}]})
    assert f[0]["level"] == "kritisch" and f[0]["action"]["kind"] == "selftest"
    assert sd.judge_selftest({"checks": [{"ok": True}]}) == []
    s = sd.judge_safety({"checks": [{"name": "db_storage", "level": "warn", "detail": "85 %"},
                                    {"name": "sl_missing", "level": "ok"}]})
    assert len(s) == 1 and s[0]["level"] == "warnung" and "512 MB" in s[0]["detail"]


def test_doctor_workers():
    now = 1000.0
    assert sd.judge_workers([], "1.29.0", now)[0]["id"] == "worker_offline"
    old = [{"version": "1.27.0", "last_seen": now - 1}]
    assert sd.judge_workers(old, "1.29.0", now)[0]["id"] == "worker_outdated"
    assert sd.judge_workers(old + [{"version": "1.29.0", "last_seen": now}], "1.29.0", now) == []
    gone = [{"version": "1.29.0", "last_seen": now - 100}]
    assert sd.judge_workers(gone, "1.29.0", now)[0]["id"] == "worker_offline"


def test_doctor_freshness_ignores_closed_markets():
    rows = [{"symbol": "EURUSD", "last_candle_age_min": 900, "market_closed": True},
            {"symbol": "BTCUSDT", "last_candle_age_min": 2, "market_closed": False}]
    assert sd.judge_freshness(rows) == []
    rows.append({"symbol": "GOLD", "last_candle_age_min": 75, "market_closed": False})
    f = sd.judge_freshness(rows)
    assert f[0]["level"] == "kritisch" and "GOLD" in f[0]["detail"]


def test_doctor_loop_and_flow():
    now = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)
    assert sd.judge_loop({"enabled": False}, None, False)[0]["id"] == "ai_disabled"
    stale = (now - timedelta(minutes=90)).isoformat()
    assert sd.judge_loop({"enabled": True, "interval_min": 10}, stale, False, now)[0]["level"] == "kritisch"
    assert sd.judge_loop({"enabled": True, "interval_min": 10}, stale, True, now) == []
    assert sd.judge_flow(3, 0, 70, []) == []
    q = sd.judge_flow(0, 0, 70.0, [{"reason": "Fee-Wächter", "count": 9}])
    assert q[0]["id"] == "trade_flow_quiet" and "Fee-Wächter (9×)" in q[0]["detail"] and "70" in q[0]["detail"]


def test_doctor_free_model_and_settings():
    f = sd.judge_providers({}, {}, {"nvidia/nemotron:free": 30, "gemini-flash": 10}, None)
    assert any(x["id"] == "free_model_decides" for x in f)
    assert sd.judge_providers({}, {}, {"gemini-flash": 40}, None) == []
    crit = sd.judge_providers({}, {"keys": [{"label": "OpenRouter", "level": "critical", "remaining": 0.2}]}, {}, None)
    assert crit[0]["level"] == "kritisch"
    assert sd.judge_settings({"live_gate_bypass_enabled": True})[0]["id"] == "live_bypass_on"


def test_doctor_first_seen_sort_overall():
    prev = {"findings": [{"id": "a", "first_seen": "2026-11-14T00:00:00+00:00"}]}
    fs = sd.merge_first_seen([sd.finding("a", "hinweis", "X", "t", "d", "f"),
                              sd.finding("b", "kritisch", "Y", "t", "d", "f")], prev, "NOW")
    assert fs[0]["first_seen"] == "2026-11-14T00:00:00+00:00" and fs[1]["first_seen"] == "NOW"
    assert [f["id"] for f in sd.sort_findings(fs)] == ["b", "a"]
    assert sd.overall(fs) == "kritisch" and sd.overall([]) == "ok"


def test_doctor_run_stores_report_and_survives_broken_check(monkeypatch):
    db = FakeDB()
    eng = SimpleNamespace(config={"enabled": True, "interval_min": 10, "live_gate_bypass_enabled": True},
                          last_run=datetime.now(timezone.utc).isoformat(), _analyzing=False, last_error=None)

    async def boom(_db, force=False):
        raise RuntimeError("Atlas weg")
    from services import safety_status
    monkeypatch.setattr(safety_status, "status", boom)
    rep = run(sd.run(db, eng, None, run_selftest=False))
    ids = {f["id"] for f in rep["findings"]}
    assert "check_sicherheit" in ids and "live_bypass_on" in ids and "worker_offline" in ids
    assert run(sd.latest(db))["counts"] == rep["counts"]
    assert len(db[sd.HISTORY].docs) == 1


# =============================== Leitstand ===============================
def test_activity_and_reasons():
    assert "ausgeschaltet" in cockpit.activity_text({"enabled": False}, False, None, None)
    txt = cockpit.activity_text({"enabled": True}, False, "2026-11-16T10:00:00+00:00", "pruefer")
    assert "Prüfer-Modus" in txt and "11:00" in txt
    assert "Schattentrade" in cockpit.trade_reason({"guard_shadow": {"guard": "fee_guard"}})
    assert "Lern-Trade" in cockpit.trade_reason({"signal_source": "regel"})
    s = cockpit.decision_sentence({"symbol": "BTCUSDT", "action": "LONG", "blocked_by": "Fee-Wächter: SL"})
    assert "blockiert" in s


def test_before_after_tile():
    since = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    old = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
    new = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    trades = [{"opened_at": old, "realized_pnl": -10, "risk_usdt": 10, "fees_paid": 2, "side": "LONG",
               "edge_filter": {"bias": "down"}},
              {"opened_at": new, "realized_pnl": 5, "risk_usdt": 10, "fees_paid": 0.5, "side": "LONG",
               "edge_filter": {"bias": "up"}}]
    ba = cockpit.before_after(trades, since)
    assert ba["before"]["avg_r"] == -1.0 and ba["before"]["fee_r"] == 0.2 and ba["before"]["counter_trend_pct"] == 100.0
    assert ba["after"]["avg_r"] == 0.5 and ba["after"]["counter_trend_pct"] == 0.0
    assert "zu wenige" in ba["note"]
    assert cockpit.before_after(trades, None) is None


def test_recommendation_builders():
    v = {"s1": {"alarm": True, "name": "TrendFolge2", "trades": 352, "avg_r": -0.13, "t": -2.37, "lb": -0.22}}
    r = cockpit.rec_live_strategies(v)
    assert r[0]["prio"] == 1 and "blende diese empfehlung aus" in r[0]["detail"].lower()
    c = cockpit.rec_candidates([{"id": "x", "stage": "bestanden", "title": "RSI + EMA",
                                 "progress": {"trades": 40, "avg_r": 0.3, "lb": 0.05}}])
    assert c[0]["action"]["kind"] == "candidate_adopt"
    rr = cockpit.rec_research({"config": {"enabled": True}, "next": "Krypto 15m"}, False, "Worker fehlt",
                              {"enabled": False}, 0)
    assert {x["id"] for x in rr} == {"night_worker", "lab_auto"}
    soon = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
    ev = cockpit.rec_events([{"event": "cpi", "label": "CPI", "next_release_utc": soon},
                             {"event": "nfp", "label": "NFP", "next_release_utc": "2027-12-01T13:30:00+00:00"}])
    assert len(ev) == 1 and ev[0]["title"].startswith("CPI")
    assert cockpit.rec_cutoff(None, 0)[0]["id"] == "cutoff_off"
    assert cockpit.rec_cutoff("2026-11-15T21:00:00+00:00", 500) == []


def test_dismiss_roundtrip():
    db = FakeDB()
    run(cockpit.dismiss(db, "event_cpi_2026.12.10", days=3))
    active = cockpit.dismissed_active(run(db.settings.find_one({"_id": cockpit.DISMISS_ID})))
    assert cockpit._key("event_cpi_2026.12.10") in active
    run(cockpit.undismiss_all(db))
    assert cockpit.dismissed_active(run(db.settings.find_one({"_id": cockpit.DISMISS_ID}))) == {}


def test_recommendations_hide_dismissed(monkeypatch):
    db = FakeDB()
    from services import ai_playbook

    async def no_stats(*a, **kw):
        return {}
    monkeypatch.setattr(ai_playbook, "setup_stats", no_stats)
    recs = run(cockpit.recommendations(db))
    assert any(r["id"] == "lab_auto" for r in recs)
    run(cockpit.dismiss(db, "lab_auto"))
    assert not any(r["id"] == "lab_auto" for r in run(cockpit.recommendations(db)))


# =============================== Nacht-Forschung ===============================
def test_night_window_and_key():
    late = datetime(2026, 11, 16, 23, 30, tzinfo=BERLIN)
    early = datetime(2026, 11, 17, 2, 0, tzinfo=BERLIN)
    noon = datetime(2026, 11, 17, 12, 0, tzinfo=BERLIN)
    assert nr.in_window(late, 23, 5) and nr.in_window(early, 23, 5) and not nr.in_window(noon, 23, 5)
    assert nr.night_key(late, 5) == nr.night_key(early, 5) == "2026-11-16"


def test_night_rotation_and_body():
    # 17.11.2026: Trend-Slot steht vorn (einzige Vorteils-Quelle mit Beleg), Ziel t-Wert (R)
    assert nr.next_slot({})["key"] == "crypto_1h_trend"
    assert nr.next_slot({"last_slot": "crypto_1h"})["key"] == "crypto_15m"
    assert nr.next_slot({"last_slot": "forex_1h"})["key"] == "crypto_1h_trend"   # alter Slot (17.11.)
    assert nr.next_slot({"last_slot": nr.ROTATION[-1]["key"]})["key"] == "crypto_1h_trend"
    body = nr.build_body(nr.ROTATION[1], ["BTCUSDT", "ETHUSDT"], 300)
    assert body["mode"] == "explore" and body["execution"] == "local" and body["max_rules"] == 3
    assert body["min_trades"] == nr.NIGHT_MIN_TRADES and body["walk_forward"]["train_pct"] == 70
    assert body["explore"]["max_minutes"] == 300 and body["indicators"] is None
    syms = nr.symbols_for(("crypto",), 12, allowed=["BTCUSDT", "ETHUSDT", "EURUSD"])
    assert syms == ["BTCUSDT", "ETHUSDT"]


def test_night_plan_decision():
    cfg = nr.settings({})
    night = datetime(2026, 11, 16, 23, 30, tzinfo=BERLIN).astimezone(timezone.utc)
    assert nr.plan_decision({**cfg, "enabled": False}, {}, night, True, "", False)[0] is False
    assert nr.plan_decision(cfg, {}, night.replace(hour=11), True, "", False)[1].startswith("außerhalb")
    assert nr.plan_decision(cfg, {"last_night": "2026-11-16"}, night, True, "", False)[1] == "diese Nacht schon eingeplant"
    assert nr.plan_decision(cfg, {}, night, False, "Worker veraltet", False)[1] == "Worker veraltet"
    assert nr.plan_decision(cfg, {}, night, True, "", True)[0] is False
    assert nr.plan_decision(cfg, {}, night, True, "", False) == (True, "bereit")


def test_night_tick_plans_once(monkeypatch):
    db = FakeDB()
    monkeypatch.setattr(nr, "worker_status", lambda: (True, "ok"))
    from services import job_series

    async def add_item(_db, kind, body, label=None):
        item = {"id": "it1", "kind": kind, "body": body, "label": label, "status": "queued",
                "created_at": datetime.now(timezone.utc).isoformat()}
        await _db.job_series.insert_one(item)
        return item
    monkeypatch.setattr(job_series, "add_item", add_item)

    async def not_busy(_db):          # andere Tests können Optimizer-Jobs im Speicher hinterlassen
        return False
    monkeypatch.setattr(nr, "_busy", not_busy)
    night = datetime(2026, 11, 16, 23, 30, tzinfo=BERLIN).astimezone(timezone.utc)
    res = run(nr.tick(db, now_utc=night))
    assert res["planned"] and res["label"].startswith("Nacht-Forschung: Krypto 1h Trend")
    again = run(nr.tick(db, now_utc=night + timedelta(minutes=30)))
    assert again["planned"] is False
    st = run(nr.get_state(db))
    assert st["last_slot"] == "crypto_1h_trend" and st["next"] == "Krypto 1h"


# =============================== Kandidaten ===============================
def test_r_stats_and_verdict():
    st = rp.r_stats(40, 40 * 0.4, 40 * (1.0 + 0.16))         # Ø 0,4 R, SD ~1
    assert st["avg_r"] == 0.4 and st["lb"] > 0
    assert rp.verdict(st, datetime.now(timezone.utc).isoformat()) == "bestanden"
    bad = rp.r_stats(40, -40 * 0.3, 40 * (1.0 + 0.09))
    assert rp.verdict(bad, datetime.now(timezone.utc).isoformat()) == "durchgefallen"
    few = rp.r_stats(10, 3.0, 12.0)
    assert rp.verdict(few, datetime.now(timezone.utc).isoformat()) == "vorwaertstest"
    old = (datetime.now(timezone.utc) - timedelta(days=rp.FORWARD_MAX_DAYS + 1)).isoformat()
    assert rp.verdict(few, old) == "abgelaufen"
    assert rp.r_stats(0, 0, 0)["avg_r"] is None


def _best_item(key, passed=True, symbols=("BTCUSDT",), tf="15m"):
    return {"labels": [key], "definition": {"long_rules": [{"indicator": key}]}, "wf": {"wf_score": 3},
            "evidence": {"passed": passed, "t": 3.4, "t_required": 3.1, "engine": deep_explore.EXPLORE_ENGINE},
            "vault": {"passed": True},
            "symbols": list(symbols), "timeframe": tf, "found_at": datetime.now(timezone.utc).isoformat()}


def test_sync_champions_only_passed_and_once():
    db = FakeDB()
    run(db.settings.insert_one({"_id": "deep_explore_best", "items": [
        _best_item("rsi"), _best_item("adx", passed=False), _best_item("ema", symbols=())]}))
    assert run(rp.sync_champions(db)) == 1
    assert run(rp.sync_champions(db)) == 0
    c = db[rp.COLLECTION].docs[0]
    assert c["title"] == "rsi" and c["stage"] == "vorwaertstest" and c["search_evidence"]["passed"]
    assert rp.needs_eval(c) is True


def test_persist_best_keeps_run_context():
    db = FakeDB()
    champ = {"labels": ["rsi"], "definition": {"long_rules": [{"indicator": "rsi"}]},
             "wf": {"wf_score": 2.0}, "evidence": {"passed": True, "engine": deep_explore.EXPLORE_ENGINE}}
    run(deep_explore.persist_best(db, {"symbols": ["BTCUSDT", "ETHUSDT"], "timeframe": "15m", "days": 180,
                                       "explore_report": {"champions": [champ]}}))
    item = run(db.settings.find_one({"_id": "deep_explore_best"}))["items"][0]
    assert item["symbols"] == ["BTCUSDT", "ETHUSDT"] and item["timeframe"] == "15m"


def test_set_stage_whitelist():
    db = FakeDB()
    run(db[rp.COLLECTION].insert_one({"id": "c1", "stage": "durchgefallen"}))
    with pytest.raises(ValueError):
        run(rp.set_stage(db, "c1", "bestanden"))
    assert run(rp.set_stage(db, "c1", "vorwaertstest"))["stage"] == "vorwaertstest"


def test_setup_progress_rows():
    stats = {"divergence": {"r_n": 35, "r_sum": 35 * 0.35, "r_sq": 35 * 1.1},
             "momentum_news": {"r_n": 12, "r_sum": -2.0, "r_sq": 14.0},
             "liquidity_sweep": {"r_n": 0}}
    rows = rp.setup_progress_rows(stats, {}, 30)
    by = {r["setup"]: r for r in rows}
    assert by["divergence"]["state"] == "live-reif"
    assert by["momentum_news"]["need"] == 18 and "noch 18 Trades" in by["momentum_news"]["state"]
    assert "liquidity_sweep" not in by


# =============================== Lab wöchentlich ===============================
def test_lab_weekly_migration_first_run_at_night():
    db = FakeDB()
    run(db.settings.insert_one({"_id": "setup_backtest_state",
                                "auto": {"enabled": False, "last_run_at": "2026-09-01T00:00:00+00:00"}}))
    run(bm.migrate_lab_auto_weekly(db))
    auto = run(db.settings.find_one({"_id": "setup_backtest_state"}))["auto"]
    assert auto["enabled"] is True and auto["interval_hours"] == 168 and auto["ai_rounds"] == 2
    nxt = datetime.fromisoformat(auto["last_run_at"]) + timedelta(hours=168)
    assert nxt.astimezone(BERLIN).hour == 2 and nxt > datetime.now(timezone.utc)
    run(db.settings.update_one({"_id": "setup_backtest_state"}, {"$set": {"auto.enabled": False}}))
    run(bm.migrate_lab_auto_weekly(db))                    # Marker: Trader-Entscheidung bleibt
    assert run(db.settings.find_one({"_id": "setup_backtest_state"}))["auto"]["enabled"] is False


# =============================== Prüf-Zuteilung ===============================
def _bal(take_n, take_r, rej_n, rej_r):
    return {"taken": {"n": take_n, "avg_r": take_r}, "rejected": {"n": rej_n, "avg_r": rej_r}}


def test_review_decide():
    assert ra.decide(None, 1)[0] is True
    assert ra.decide(_bal(5, 0.1, 50, -0.3), 1)[0] is True               # zu wenig genommen
    assert ra.decide(_bal(20, 0.2, 40, -0.3), 2)[0] is True              # Auswahl hilft
    no_value = _bal(20, -0.38, 177, -0.30)                               # Prod 11/2026
    assert [ra.decide(no_value, n)[0] for n in range(1, 7)] == [False, False, True, False, False, True]
    assert "gespart" in ra.decide(no_value, 1)[1]


def test_review_should_review_respects_switch():
    db = FakeDB()
    ok, why = run(ra.should_review(db, "divergence", {"signal_review_by_value": False}))
    assert ok and "aus" in why


# =============================== Live-Wächter ===============================
def _live(sid, r, n, name="TrendFolge2"):
    return [{"strategy_id": sid, "strategy_name": name, "realized_pnl": r * 10 + (1 if i % 2 else -1) * 8,
             "risk_usdt": 10} for i in range(n)]


def test_live_watchdog_judge():
    v = live_watchdog.judge(_live("s1", -0.13, 352) + _live("s2", 0.05, 20, "Neu")
                            + [{"strategy_id": "ai_trader", "realized_pnl": -5, "risk_usdt": 5}])
    assert v["s1"]["alarm"] is True and v["s1"]["trades"] == 352
    assert v["s2"]["state"] == "zu wenig Live-Trades" and "ai_trader" not in v


def test_live_watchdog_enforce_only_with_permission():
    db = FakeDB()
    for t in _live("s1", -0.4, 60):
        run(db.auto_trades.insert_one({**t, "mode": "live", "status": "closed"}))
    at = SimpleNamespace(config={"strategy_overrides": {"s1": {"mode": "live", "enabled": True}},
                                 "strategy_coin_configs": {"s1_BTCUSDT": {"mode": "live"}}})
    assert run(live_watchdog.enforce(db, at)) == []                     # Standard: aus
    run(live_watchdog.set_config(db, {"auto_pause": True}))
    changed = run(live_watchdog.enforce(db, at))
    assert changed and at.config["strategy_overrides"]["s1"]["mode"] == "paper"
    assert at.config["strategy_coin_configs"]["s1_BTCUSDT"]["mode"] == "paper"


# =============================== Tagesbericht ===============================
def test_daily_trade_block_and_due():
    b = daily_report.trade_block([{"realized_pnl": 10, "risk_usdt": 10, "fees_paid": 1},
                                  {"realized_pnl": -10, "risk_usdt": 10, "fees_paid": 1,
                                   "guard_shadow": {"guard": "fee_guard"}, "data_collection": True}])
    assert b["avg_r"] == 0.0 and b["fee_r"] == 0.1 and b["shadows"] == 1 and b["collection"] == 1
    morning = datetime(2026, 11, 16, 9, 0, tzinfo=BERLIN)
    assert daily_report.is_due(None, morning) and not daily_report.is_due("2026-11-15", morning)
    assert not daily_report.is_due(None, morning.replace(hour=6))


def test_daily_make_and_store(monkeypatch):
    db = FakeDB()

    async def no_recs(_db):
        return [{"title": "Lab-Automatik ist aus"}]
    monkeypatch.setattr(cockpit, "recommendations", no_recs)
    ec.set_cache("2026-11-15T21:00:00+00:00")
    day = datetime(2026, 11, 16, tzinfo=BERLIN).date()
    run(db.auto_trades.insert_one({"strategy_id": "ai_trader", "status": "closed",
                                   "opened_at": "2026-11-16T09:00:00+00:00",
                                   "closed_at": "2026-11-16T10:00:00+00:00",
                                   "realized_pnl": 5, "risk_usdt": 10, "fees_paid": 0.5}))
    rep = run(daily_report.make_and_store(db, send=False, day_local=day))
    assert rep["yesterday"]["trades"] == 1 and rep["since_cutoff"]["avg_r"] == 0.5
    txt = daily_report.format_text(rep)
    assert "Tagesbericht 2026-11-16" in txt and "Lab-Automatik" in txt
    assert run(daily_report.history(db))[0]["day"] == "2026-11-16"


# =============================== Autonomie-Takt ===============================
def test_autonomy_due():
    autonomy_loop._last.clear()
    assert autonomy_loop.due("doctor", 10_000.0)
    autonomy_loop._last["doctor"] = 10_000.0
    assert not autonomy_loop.due("doctor", 10_100.0) and autonomy_loop.due("doctor", 10_000.0 + 901)


# =============================== Lern-Signale bei Fee-Faktor 10 ===============================
def test_collection_widen_covers_min_sl_at_factor_10():
    from services import fee_guard_widen
    # Krypto-Minimum 1,2 % (10 × 0,12 %); Sammel-Signal mit Mindest-SL 0,42 % und CRV 1,5
    check = lambda sl, tp: abs(100.0 - sl) / 100.0 * 100 >= 1.2 - 1e-9
    out = fee_guard_widen.widen(check, "LONG", 100.0, 99.58, 100.63, 101.26)
    assert out is not None and abs((100.0 - out[0]) - 1.26) < 1e-6      # 3× erweitert, CRV bleibt
    assert abs((out[1] - 100.0) / (100.0 - out[0]) - 1.5) < 1e-6
