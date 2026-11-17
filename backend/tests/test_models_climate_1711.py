"""17.11.2026 (2): Aufgaben-Team v2, Markt-Klima, Funding-Bilanz im Radar,
Live-Wächter nur bei nachgewiesenem Verlust, Entscheidungen-Migration."""
import asyncio
import math
from datetime import datetime, timedelta, timezone

from services import ai_providers, ai_roles, boot_migrations as bm, funding_fade
from services import live_watchdog as lw, market_climate as mc, research_pipeline as rp
from tests.phase_fakedb import FakeDB

DAY = mc.DAY_MS


def run(coro):
    return asyncio.run(coro)


# ---------------- Aufgaben-Team v2 ----------------
def test_team_v2_models_exist_and_chains_cross_providers():
    assert ai_roles.TASK_TEAM_MARKER == "_task_team_v2"
    for role, p in ai_roles.ROLE_PRESETS.items():
        for pk, mk in (("provider", "model"), ("fallback_provider", "fallback_model"),
                       ("fallback2_provider", "fallback2_model")):
            assert p[mk] in ai_providers.ALLOWED_MODELS[p[pk]], (role, p[mk])
        # jede Kette endet bei einem anderen Anbieter-Schlüssel als sie beginnt
        assert len({p["provider"], p["fallback_provider"], p["fallback2_provider"]}) >= 2, role


def test_team_v2_decisions():
    p = ai_roles.ROLE_PRESETS
    # Prüfer: nie auf ein Gratis-Modell als zweite Stufe
    assert p["analyst"]["model"] == "openai/gpt-6-luna-pro"
    assert p["analyst"]["fallback_model"] == "anthropic/claude-haiku-5.5"
    assert not p["analyst"]["fallback_model"].endswith(":free")
    assert "anthropic/claude-haiku-5.5" in ai_providers.PAID_MODELS_NO_FALLBACK
    # gpt-oss-20b scheiterte in Produktion an der JSON-Prüfung -> nirgends mehr gesetzt
    for role, cfg in p.items():
        assert "openai/gpt-oss-20b" not in (cfg["model"], cfg["fallback_model"], cfg["fallback2_model"]), role
    assert p["learner"]["model"] == p["research_analyst"]["model"] == "deepseek/deepseek-v4.1-flash"
    assert p["trade_manager"]["model"] == "deepseek/deepseek-v4-flash"


# ---------------- Markt-Klima ----------------
def series(n, start=100.0, drift=0.0, amp=0.0):
    ts = [1_700_000_000_000 + i * DAY for i in range(n)]
    closes = [start * math.exp(drift * i + amp * math.sin(i / 3.0)) for i in range(n)]
    return ts, closes


def test_classify_uses_only_closed_days():
    ts, closes = series(260, drift=0.004)
    t = ts[-1] + DAY + 1
    c = mc.classify_at(ts, closes, t)
    assert c["trend"] == "bull" and c["dist_pct"] > 0 and c["days"] == 260
    # die noch laufende Tageskerze zählt nicht
    assert mc.classify_at(ts, closes, ts[-1] + 5)["days"] == 259
    # ein Absturz NACH dem Zeitpunkt ändert das Klima von gestern nicht
    crashed = closes[:-1] + [closes[-1] * 0.2]
    assert mc.classify_at(ts, crashed, ts[-1] + 5)["trend"] == "bull"
    assert mc.classify_at(ts, crashed, t)["trend"] == "bear"


def test_classify_needs_history_and_detects_bear_and_vol():
    ts, closes = series(150, drift=-0.003)
    assert mc.classify_at(ts, closes, ts[-1] + DAY)["trend"] is None        # < 200 Tage
    ts, closes = series(700, drift=-0.002)
    c = mc.classify_at(ts, closes, ts[-1] + DAY)
    assert c["trend"] == "bear" and c["vol_high"] is False                   # gleichmäßig -> nicht hoch
    wild = closes[:660] + [closes[659] * math.exp(0.08 * ((-1) ** i)) for i in range(40)]
    assert mc.classify_at(ts, wild, ts[-1] + DAY)["vol_high"] is True
    assert "Bärenmarkt" in mc.describe(c) and "unter dem 200-Tage-Schnitt" in mc.describe(c)
    assert "unbekannt" in mc.describe({"trend": None})


def test_aligned():
    assert mc.aligned("LONG", "bull") is True and mc.aligned("SHORT", "bull") is False
    assert mc.aligned("SHORT", "bear") is True and mc.aligned("BUY", "bear") is False
    assert mc.aligned("LONG", None) is None and mc.aligned(None, "bull") is None


def test_split_trades_and_verdict():
    ts, closes = series(400, drift=0.003)                                    # Bullenklima
    when = datetime.fromtimestamp((ts[-1] + 2 * DAY) / 1000, timezone.utc).isoformat()
    trades = ([{"opened_at": when, "side": "LONG", "realized_pnl": 3.0, "risk_usdt": 10.0}] * 60
              + [{"opened_at": when, "side": "SHORT", "realized_pnl": -2.0, "risk_usdt": 10.0}] * 55
              + [{"opened_at": when, "side": "LONG", "realized_pnl": 1.0, "risk_usdt": 0}]      # ohne Risiko
              + [{"opened_at": "kaputt", "side": "LONG", "realized_pnl": 1.0, "risk_usdt": 1}])
    out = mc.split_trades(trades, ts, closes)
    assert out["mit"]["trades"] == 60 and out["mit"]["avg_r"] == 0.3
    assert out["gegen"]["trades"] == 55 and out["gegen"]["avg_r"] == -0.2
    assert "würde auf den eigenen Trades helfen" in out["verdict"]
    assert out["short_vol_hoch"]["trades"] + out["short_vol_normal"]["trades"] == 55
    few = mc.split_trades(trades[:20], ts, closes)
    assert few["verdict"].startswith("noch kein Urteil")
    assert mc.verdict({"trades": 80, "avg_r": 0.0}, {"trades": 80, "avg_r": 0.3}).startswith("Trades gegen")
    assert mc.verdict({"trades": 80, "avg_r": 0.1}, {"trades": 80, "avg_r": 0.08}).startswith("kein klarer")


def test_report_filters_crypto_and_survives_without_data(monkeypatch):
    db = FakeDB()
    ts, closes = series(400, drift=0.003)
    now = datetime.now(timezone.utc)

    async def fake_daily(session=None, now=None):
        return ts, closes
    monkeypatch.setattr(mc, "btc_daily", fake_daily)
    for sym in ("BTCUSDT", "EURUSD"):
        run(db.auto_trades.insert_one({"status": "closed", "symbol": sym, "side": "LONG",
                                       "opened_at": (now - timedelta(days=2)).isoformat(),
                                       "realized_pnl": 5.0, "risk_usdt": 10.0}))
    rep = run(mc.report(db))
    assert rep["available"] and rep["own"]["mit"]["trades"] + rep["own"]["gegen"]["trades"] == 1

    async def no_data(session=None, now=None):
        return [], []
    monkeypatch.setattr(mc, "btc_daily", no_data)
    assert run(mc.report(db))["available"] is False


def test_parse_klines_skips_broken_rows():
    ts, closes = mc.parse_klines([[1, "1", "2", "0.5", "1.5"], ["x"], [2, "1", "2", "1", "bad"], [3, 1, 2, 1, 2]])
    assert ts == [1, 3] and closes == [1.5, 2.0]


# ---------------- Funding-Radar ----------------
def test_funding_radar_carries_history():
    lines = funding_fade.context_lines({"BTCUSDT": {"funding_rate": 0.0008},
                                        "ETHUSDT": {"funding_rate": -0.0007},
                                        "SOLUSDT": {"funding_rate": 0.0001}})
    hot = next(x for x in lines if x.startswith("- BTCUSDT"))
    cold = next(x for x in lines if x.startswith("- ETHUSDT"))
    assert "Fade-Richtung SHORT" in hot and "stieg der Kurs in 3 Tagen im Schnitt weiter" in hot
    assert "Fade-Richtung LONG" in cold and "belegte Seite" in cold
    assert not any(x.startswith("- SOLUSDT") for x in lines)
    assert funding_fade.context_lines({"SOLUSDT": {"funding_rate": 0.0001}}) == []


# ---------------- Live-Wächter + Migration ----------------
class _Auto:
    def __init__(self, overrides, coins=None):
        self.config = {"strategy_overrides": overrides, "strategy_coin_configs": coins or {}}


def _trades(sid, n, r):
    return [{"mode": "live", "status": "closed", "strategy_id": sid, "strategy_name": sid,
             "realized_pnl": r * 10.0 + (0.5 if i % 2 else -0.5), "risk_usdt": 10.0} for i in range(n)]


def test_auto_pause_only_for_proven_loss():
    db = FakeDB()
    for t in _trades("verlierer", 80, -0.3) + _trades("unsicher", 60, 0.0) + _trades("jung", 10, -1.0):
        run(db.auto_trades.insert_one(t))
    v = run(lw.load(db))
    assert v["verlierer"]["state"] == lw.PROVEN_LOSS and v["unsicher"]["state"] == "Vorteil nicht belegt"
    auto = _Auto({s: {"mode": "live"} for s in ("verlierer", "unsicher", "jung")},
                 {"verlierer_BTCUSDT": {"mode": "live"}, "unsicher_BTCUSDT": {"mode": "live"}})
    assert run(lw.enforce(db, auto)) == []                                    # ohne Freigabe nichts
    run(lw.set_config(db, {"auto_pause": True}))
    changed = run(lw.enforce(db, auto))
    assert [c["strategy_id"] for c in changed] == ["verlierer"]
    ov = auto.config["strategy_overrides"]
    assert ov["verlierer"]["mode"] == "paper" and ov["unsicher"]["mode"] == "live" and ov["jung"]["mode"] == "live"
    assert auto.config["strategy_coin_configs"]["verlierer_BTCUSDT"]["mode"] == "paper"
    assert auto.config["strategy_coin_configs"]["unsicher_BTCUSDT"]["mode"] == "live"


def test_decisions_migration_once():
    db = FakeDB()
    run(rp.ensure_presets(db, ["BTCUSDT", "ETHUSDT"]))
    run(db[rp.COLLECTION].update_many({}, {"$set": {"adoptable": True}}))
    run(bm.migrate_decisions_1711(db))
    assert run(lw.get_config(db))["auto_pause"] is True
    assert run(db[rp.COLLECTION].find_one({"ref": "preset:trend_basis_4h"}))["adoptable"] is False
    run(lw.set_config(db, {"auto_pause": False}))                             # Trader schaltet wieder ab
    run(bm.migrate_decisions_1711(db))
    assert run(lw.get_config(db))["auto_pause"] is False
