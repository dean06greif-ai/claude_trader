"""Portfolio (17.11.2026): Rechenkern (Trend + Funding-Korb), Dienst, Tagesplan."""
import asyncio
import math

import pytest

from services import cockpit, portfolio_core as pc, portfolio_engine as pe
from tests.phase_fakedb import FakeDB

DAY = pc.DAY_MS
T0 = 1_546_300_800_000          # 01.01.2019


def run(coro):
    return asyncio.run(coro)


def bars(closes, spread=0.01, t0=T0):
    out, prev = [], closes[0]
    for i, c in enumerate(closes):
        o = prev
        out.append([t0 + i * DAY, o, max(o, c) * (1 + spread), min(o, c) * (1 - spread), c])
        prev = c
    return out


def flat(n, price=100.0, wiggle=0.002):
    return [price * (1 + wiggle * math.sin(i)) for i in range(n)]


def syn(n_syms=14, n_days=700, mom=0.003):
    """Deterministische Kunstdaten (gleicher Generator wie im Browser-Abgleich)."""
    c, f = {}, {}
    for k in range(n_syms + 1):
        name = "BTCUSDT" if k == n_syms else f"S{k}USDT"
        x = [1000 + k * 77]

        def nx():
            x[0] = (x[0] * 48271) % 2147483647
            return x[0] / 2147483647
        p, reg, rows, fs = 100.0, 1, [], {}
        for i in range(n_days):
            if i % 120 == 0:
                reg = 1 if nx() < 0.6 else -1
            u1, u2, u3 = nx(), nx(), nx()
            o = p
            p = p * (1 + reg * mom + (u1 - 0.5) * 0.08)
            rows.append([T0 + i * DAY, o, max(o, p) * (1 + u2 * 0.02), min(o, p) * (1 - u3 * 0.02), p])
            fs[T0 + i * DAY] = 0.0001 * ((k % 5) - 2) + (nx() - 0.5) * 0.0004
        c[name], f[name] = rows, fs
    return c, f


TREND_ONLY = {"carry": {"enabled": False}, "trend": {"climate": False}}


# ---------------- Rechenkern ----------------
def test_reference_numbers_match_browser_port():
    """Abgleich mit der unabhängigen JS-Portierung (gleiche Kunstdaten, 17.11.2026):
    beide Rechnungen kamen auf den Cent auf dasselbe Ergebnis."""
    c, f = {}, {}
    cc, ff = syn(14, 1500)
    for k, v in cc.items():
        name = "BTC" if k == "BTCUSDT" else k[:-4]
        c[name], f[name] = v, ff[k]
    r = pc.run(c, f, {"btc": "BTC"}, mark_ms=T0 + 1400 * DAY)
    assert r["equity"] == 27009.08
    assert r["trend_trades"]["trades"] == 259 and r["trend_trades"]["avg_r"] == 0.674
    assert r["parts"] == {"trend": 11133.21, "carry": 3858.17} and r["carry_rebalances"] == 213
    assert r["stats"]["max_dd_pct"] == 11.7 and r["stats"]["sharpe"] == 2.49
    assert {y["year"]: y["pct"] for y in r["years"]} == {2019: 7.2, 2020: 51.5, 2021: 33.6, 2022: 14.6, 2023: 8.6}


def test_replay_is_deterministic_and_prefix_stable():
    c, f = syn(10, 500)
    a = pc.run(c, f, None)
    assert pc.run(c, f, None)["equity"] == a["equity"]
    # Kein Blick in die Zukunft: der Verlauf bis Tag 400 ändert sich nicht, wenn später Daten dazukommen
    short = {s: b[:400] for s, b in c.items()}
    b = pc.run(short, f, None)
    assert [x[1] for x in a["curve"][:len(b["curve"])]] == [x[1] for x in b["curve"]]


def test_breakout_long_stop_and_r_accounting():
    closes = flat(60) + [100 * (1.03 ** i) for i in range(1, 15)] + [100 * (1.03 ** 14) * (0.90 ** i) for i in range(1, 6)]
    c = {"AUSDT": bars(closes), "BTCUSDT": bars(flat(len(closes)))}
    r = pc.run(c, {}, {**TREND_ONLY, "start_equity": 10000.0, "trend": {"climate": False, "risk_pct": 1.0}})
    t = [x for x in r["trades"] if x["symbol"] == "AUSDT"]
    assert len(t) >= 1 and t[0]["side"] == "LONG" and t[0]["reason"] == "Stop"
    assert t[0]["r"] > 1.0 and t[0]["pnl"] > 0                       # der Trail sichert den Trend-Gewinn
    assert t[0]["exit_ts"] > t[0]["entry_ts"]
    # Konto = Start + Summe der Trades (keine offene Position mehr)
    if not r["positions"]:
        assert abs(r["equity"] - (10000.0 + sum(x["pnl"] for x in r["trades"]))) < 0.05


def test_fixed_risk_per_trade_and_gross_cap():
    c, f = syn(14, 400)
    cfg = {"carry": {"enabled": False}, "trend": {"climate": False, "risk_pct": 0.5, "max_gross": 0.3}}
    r = pc.run(c, {}, cfg)
    peak_gross = 0.0
    for p in r["positions"]:
        assert p["risk"] <= r["equity"] * 0.02
    # Verlust-Trades kosten etwa 1 R (plus Kosten/Lücken), nie ein Vielfaches
    losers = [t["r"] for t in r["trades"] if t["r"] < 0]
    assert losers and min(losers) > -3.5 and sum(losers) / len(losers) < -0.3
    assert sum(p["notional"] for p in r["positions"] if p["sleeve"] == "trend") <= r["equity"] * 0.3 * 1.6 + peak_gross


def test_climate_blocks_longs_in_bear_market():
    up = flat(230) + [100 * (1.03 ** i) for i in range(1, 12)]
    btc_down = [100 * (0.997 ** i) for i in range(len(up))]
    c = {"AUSDT": bars(up), "BTCUSDT": bars(btc_down, spread=0.0005)}
    on = pc.run(c, {}, {"carry": {"enabled": False}, "trend": {"climate": True}})
    off = pc.run(c, {}, {"carry": {"enabled": False}, "trend": {"climate": False}})
    a_on = [t for t in on["trades"] if t["symbol"] == "AUSDT"] + [p for p in on["positions"] if p["symbol"] == "AUSDT"]
    a_off = [t for t in off["trades"] if t["symbol"] == "AUSDT"] + [p for p in off["positions"] if p["symbol"] == "AUSDT"]
    assert not [x for x in a_on if x["side"] == "LONG"] and [x for x in a_off if x["side"] == "LONG"]
    assert on["climate"] == {"bull": False, "known": True}


def test_carry_is_market_neutral_and_earns_funding_spread():
    n = 120
    c, f = {}, {}
    for k in range(14):
        s = f"C{k:02d}USDT"
        c[s] = bars(flat(n, wiggle=0.0))
        f[s] = {T0 + i * DAY: (0.002 if k >= 9 else (-0.001 if k < 5 else 0.0)) for i in range(n)}
    c["BTCUSDT"] = bars(flat(n, wiggle=0.0))
    f["BTCUSDT"] = {T0 + i * DAY: 0.0 for i in range(n)}
    r = pc.run(c, f, {"trend": {"enabled": False}, "fee_pct": 0.0, "slippage_pct": 0.0})
    carry = [p for p in r["positions"] if p["sleeve"] == "carry"]
    longs = {p["symbol"] for p in carry if p["side"] == "LONG"}
    shorts = {p["symbol"] for p in carry if p["side"] == "SHORT"}
    assert longs == {f"C{k:02d}USDT" for k in range(5)} and shorts == {f"C{k:02d}USDT" for k in range(9, 14)}
    assert abs(sum(p["notional"] for p in carry if p["side"] == "LONG")
               - sum(p["notional"] for p in carry if p["side"] == "SHORT")) < 0.01
    assert r["parts"]["carry"] > 0 and r["equity"] > 10000.0           # Long bekommt, Short bekommt
    assert r["trend_trades"]["trades"] == 0


def test_carry_needs_enough_coins_and_full_lookback():
    c, f = syn(6, 200)
    assert not [p for p in pc.run(c, f, None)["positions"] if p["sleeve"] == "carry"]


def test_merged_clamps_and_sample_curve():
    m = pc.merged({"trend": {"risk_pct": 50, "max_positions": 0}, "carry": {"n_side": 99}, "start_equity": 1})
    assert m["trend"]["risk_pct"] == 2.0 and m["trend"]["max_positions"] == 1
    assert m["carry"]["n_side"] == 15 and m["start_equity"] == 100.0
    curve = [(T0 + i * DAY, 100.0 + i) for i in range(2000)]
    s = pc.sample_curve(curve, 400)
    assert len(s) <= 401 and s[0][0] == curve[0][0] and s[-1] == [curve[-1][0], curve[-1][1]]
    assert pc.sample_curve(curve[:10]) == [[a, b] for a, b in curve[:10]]


def test_stats_and_empty_input():
    st = pc._stats([(T0 + i * DAY, 100.0 * (1.001 ** i)) for i in range(400)])
    assert st["max_dd_pct"] == 0.0 and 40 < st["cagr_pct"] < 46
    empty = pc.run({}, {}, None)
    assert empty["days"] == 0 and empty["positions"] == [] and empty["equity"] == 10000.0


# ---------------- Dienst ----------------
def test_config_normalize_and_hash():
    cfg = pe.normalize_config({"risk_level": "x", "start_equity": "abc", "symbols": ["btcusdt"], "start": "kaputt"})
    assert cfg == pe.default_config()
    cfg = pe.normalize_config({"risk_level": "normal", "start_equity": 2500, "carry": False, "start": "2022-01-01"})
    assert cfg["risk_level"] == "normal" and cfg["start_equity"] == 2500.0 and cfg["carry"] is False
    h = pe.strategy_hash(cfg)
    assert pe.strategy_hash({**cfg, "start_equity": 99999.0}) == h           # Kontogröße ändert den Verlauf nicht
    assert pe.strategy_hash({**cfg, "risk_level": "offensiv"}) != h
    core_cfg = pe.core_config(cfg)
    assert core_cfg["trend"]["risk_pct"] == 0.5 and core_cfg["carry"]["enabled"] is False
    assert set(pe.BACKTEST) == set(pe.RISK_LEVELS) == set(pe.EXPECTATION)


def test_merge_bars_only_closed_days_and_valid_rows():
    now = T0 + 10 * DAY + 3600_000
    old = [[T0, 1, 2, 0.5, 1.5]]
    new = [[T0 + DAY, "1", "2", "1", "1.8"], [T0 + 10 * DAY, 1, 2, 1, 2],        # letzte Kerze läuft noch
           ["x"], [T0 + 2 * DAY, 0, 1, 0, 1], [T0, 1, 3, 0.5, 1.6]]
    out = pe.merge_bars(old, new, now)
    assert [b[0] for b in out] == [T0, T0 + DAY] and out[0][2] == 3.0 and out[1][4] == 1.8
    assert pe.last_closed_day(now) == T0 + 9 * DAY


def test_daily_sums_and_months():
    rows = {T0 + 1: 0.0001, T0 + 8 * 3600_000: 0.0002, T0 + DAY + 5: -0.0003}
    assert pe.daily_sums(rows) == {T0: pytest.approx(0.0003), T0 + DAY: pytest.approx(-0.0003)}
    m = pe._months(T0, T0 + 400 * DAY)
    assert m[0] == "2019-01" and m[-1] == "2020-02" and len(m) == 14 and len(set(m)) == 14


CLOCK = {"ms": None}


def _fake_net(monkeypatch, c, f):
    """Wie die echte Schnittstelle: liefert nie Kerzen aus der Zukunft (CLOCK)."""
    async def fake_klines(session, sym, limit, end_ms=None):
        rows = [b for b in c.get(sym, []) if CLOCK["ms"] is None or b[0] <= CLOCK["ms"]]
        if end_ms:
            rows = [b for b in rows if b[0] <= end_ms]
        return rows[-limit:]

    def fake_month(sym, ym):
        return {}

    async def fake_recent(session, sym):
        return {ts + 1: v for ts, v in (f.get(sym) or {}).items()}
    monkeypatch.setattr(pe, "_fetch_klines", fake_klines)
    monkeypatch.setattr(pe, "_archive_month", fake_month)
    monkeypatch.setattr(pe, "_recent_funding", fake_recent)


def test_refresh_end_to_end_and_paper_mark(monkeypatch):
    c, f = syn(14, 700)
    _fake_net(monkeypatch, c, f)
    db = FakeDB()
    run(pe.set_config(db, {"symbols": sorted(c), "start": "2019-06-01", "risk_level": "normal"}))
    now = T0 + 650 * DAY + 600_000                     # Tag 649 ist die letzte abgeschlossene Kerze
    CLOCK["ms"] = now
    res = run(pe.refresh(db, notify=False, now_ms=now))
    assert res["status"] == "neu gerechnet" and res["last_ts"] == T0 + 649 * DAY
    st = run(pe.get_state(db))["state"]
    assert st["paper_since"] == T0 + 649 * DAY and st["since_paper"]["days"] == 0
    assert st["stats"]["days"] > 300 and len(st["curve"]) <= 401 and st["symbols"] == sorted(c)
    assert st["expectation"].startswith("Realistische Erwartung") and "geschönt" in st["caveat"]
    assert run(pe.refresh(db, notify=False, now_ms=now))["status"] == "aktuell"      # kein zweiter Lauf am selben Tag
    assert run(pe.tick(db, now_ms=now)) == "aktuell"
    # 20 Tage später: Paper-Start bleibt, der Verlauf seit Start wächst
    later = now + 20 * DAY
    CLOCK["ms"] = later
    assert run(pe.refresh(db, notify=False, now_ms=later))["status"] == "neu gerechnet"
    st2 = run(pe.get_state(db))["state"]
    assert st2["paper_since"] == st["paper_since"] and st2["since_paper"]["days"] == 20
    assert st2["last_ts"] == T0 + 669 * DAY
    # nur die Kontogröße geändert: Paper-Start bleibt; Risiko-Stufe geändert: Neustart
    run(pe.set_config(db, {"start_equity": 2000}))
    run(pe.refresh(db, notify=False, now_ms=later))
    st3 = run(pe.get_state(db))["state"]
    assert st3["paper_since"] == st["paper_since"] and st3["start_equity"] == 2000.0
    assert abs(st3["stats"]["cagr_pct"] - st2["stats"]["cagr_pct"]) < 0.2
    run(pe.set_config(db, {"risk_level": "vorsichtig"}))
    run(pe.refresh(db, notify=False, now_ms=later))
    assert run(pe.get_state(db))["state"]["paper_since"] == T0 + 669 * DAY
    CLOCK["ms"] = None


def test_refresh_fails_safe_on_missing_or_stale_data(monkeypatch):
    c, f = syn(14, 300)
    _fake_net(monkeypatch, {k: v for k, v in c.items() if k != "BTCUSDT"}, f)
    db = FakeDB()
    run(pe.set_config(db, {"symbols": sorted(c), "start": "2019-03-01"}))
    assert run(pe.refresh(db, notify=False, now_ms=T0 + 290 * DAY))["status"] == "fehler"     # ohne BTC kein Lauf
    _fake_net(monkeypatch, c, f)
    stale = run(pe.refresh(db, notify=False, now_ms=T0 + 400 * DAY))                          # Daten enden bei Tag 299
    assert stale["status"] == "fehler" and "älter" in stale["detail"]
    assert run(pe.get_state(db))["state"] is None
    run(pe.set_config(db, {"enabled": False}))
    assert run(pe.refresh(db, notify=False, now_ms=T0 + 290 * DAY))["status"] == "aus"


def test_day_plan_and_texts():
    last = T0 + 10 * DAY
    res = {"last_ts": last,
           "trades": [{"sleeve": "trend", "symbol": "SOLUSDT", "side": "LONG", "exit_ts": last, "r": -1.02, "pnl": -51.0},
                      {"sleeve": "trend", "symbol": "XRPUSDT", "side": "LONG", "exit_ts": last - DAY, "r": 2.0, "pnl": 100.0}],
           "positions": [{"sleeve": "trend", "symbol": "ETHUSDT", "side": "SHORT", "new": True, "notional": 640.0,
                          "stop": 2010.5, "risk": 50.0},
                         {"sleeve": "trend", "symbol": "BTCUSDT", "side": "LONG", "new": False, "notional": 900.0,
                          "stop": 61234.0, "risk": 50.0},
                         {"sleeve": "carry", "symbol": "ADAUSDT", "side": "LONG", "entry_ts": last, "notional": 500.0},
                         {"sleeve": "carry", "symbol": "DOGEUSDT", "side": "SHORT", "entry_ts": last, "notional": 500.0}]}
    plan = pe.day_plan(res, prev_carry=["ADAUSDT:LONG", "TRXUSDT:SHORT"])
    assert [p["kind"] for p in plan] == ["schliessen", "eroeffnen", "carry", "stop"]
    assert "SOLUSDT LONG wurde am Stop geschlossen (-1,02 R, -51 USDT)" in plan[0]["text"]
    assert "ETHUSDT SHORT eröffnen: 640 USDT" in plan[1]["text"] and "Stop bei 2.010,50 (Risiko 50 USDT)" in plan[1]["text"]
    assert "Long ADA · Short DOGE" in plan[2]["text"]
    assert not [p for p in pe.day_plan(res, prev_carry=["ADAUSDT:LONG", "DOGEUSDT:SHORT"]) if p["kind"] == "carry"]
    txt = pe.plan_text({"plan": plan, "last_ts": last, "equity": 10250.0, "open_trend": 2})
    assert "Portfolio (Paper)" in txt and "1 Stops nachziehen" in txt and "ETHUSDT SHORT eröffnen" in txt
    assert "Konto: 10.250 USDT" in txt
    assert "Keine neue Order heute." in pe.plan_text({"plan": [], "last_ts": last})
    assert pe._de(1234567.891, 2) == "1.234.567,89" and pe._fmt_px(0.012345678) == "0,012346"
    assert pe.summary_line(None) is None
    assert "Seit Paper-Start (20 Tage): +3,0 %" in pe.summary_line(
        {"stats": {"days": 5}, "open_trend": 3, "open_carry": 10, "since_paper": {"start": 100.0, "now": 103.0, "days": 20}})


def test_cockpit_recommendation_for_portfolio():
    assert cockpit.rec_portfolio({"config": {"enabled": False}}) == []
    setup = cockpit.rec_portfolio({"config": {"enabled": True}, "state": None})
    assert len(setup) == 1 and "eingerichtet" in setup[0]["title"]
    st = {"last_ts": T0, "plan": [{"kind": "eroeffnen", "text": "ETHUSDT SHORT eröffnen"}, {"kind": "stop", "text": "x"}]}
    recs = cockpit.rec_portfolio({"config": {"enabled": True}, "state": st})
    assert len(recs) == 1 and "1 neue Order" in recs[0]["title"] and "ETHUSDT SHORT" in recs[0]["detail"]
    assert cockpit.rec_portfolio({"config": {"enabled": True}, "state": {"last_ts": T0, "plan": [{"kind": "stop", "text": "x"}]}}) == []


def test_update_candles_backfills_once_then_only_new_days(monkeypatch):
    calls = []
    series = [[T0 + i * DAY, 1.0, 1.1, 0.9, 1.0 + i * 0.001] for i in range(1400)]   # Coin erst seit T0 gelistet

    clock = {"ms": T0 + 1300 * DAY + 5}

    async def fake_klines(session, sym, limit, end_ms=None):
        calls.append((limit, end_ms))
        rows = [b for b in series if b[0] <= clock["ms"] and (end_ms is None or b[0] <= end_ms)]
        return rows[-limit:]
    monkeypatch.setattr(pe, "_fetch_klines", fake_klines)
    db = FakeDB()
    start = T0 - 500 * DAY                                  # Bedarf beginnt VOR dem Listing
    now = clock["ms"]
    bars = run(pe.update_candles(db, None, "NEUUSDT", start, now))
    assert len(bars) == 1300 and bars[0][0] == T0 and bars[-1][0] == T0 + 1299 * DAY
    assert len(calls) == 2 and calls[0] == (1000, None)     # 1000 neueste + Rest bis zum Listing
    calls.clear()
    assert run(pe.update_candles(db, None, "NEUUSDT", start, now)) == bars and calls == []   # aktuell: kein Abruf
    clock["ms"] = now + 3 * DAY
    bars2 = run(pe.update_candles(db, None, "NEUUSDT", start, now + 3 * DAY))
    assert len(bars2) == 1303 and calls == [(5, None)]      # nur die fehlenden Tage, kein erneuter Voll-Abruf


def test_doctor_judges_portfolio():
    from services import system_doctor as sd
    now = T0 + 100 * DAY + 3600_000
    fresh = {"last_ts": T0 + 99 * DAY, "symbols": ["A"] * 26, "funding_coverage": 26}
    assert sd.judge_portfolio(False, None, {}, now) == []
    assert sd.judge_portfolio(True, fresh, {"phase": "fertig"}, now) == []
    assert sd.judge_portfolio(True, None, {}, now, running=True) == []
    assert [f["id"] for f in sd.judge_portfolio(True, None, {}, now)] == ["portfolio_missing"]
    stale = sd.judge_portfolio(True, {**fresh, "last_ts": T0 + 96 * DAY}, {}, now)
    assert [f["id"] for f in stale] == ["portfolio_stale"] and "3 Tagen" in stale[0]["title"]
    assert sd.judge_portfolio(True, {**fresh, "last_ts": T0 + 98 * DAY}, {}, now) == []     # 1 Tag Verzug ist normal
    low = sd.judge_portfolio(True, {**fresh, "funding_coverage": 4}, {}, now)
    assert [f["id"] for f in low] == ["portfolio_funding"] and low[0]["level"] == "hinweis"
    err = sd.judge_portfolio(True, fresh, {"phase": "Fehler: zu wenige Daten"}, now)
    assert [f["id"] for f in err] == ["portfolio_error"]


def test_position_of_delisted_coin_is_closed_at_last_price():
    up = flat(60) + [100 * (1.03 ** i) for i in range(1, 12)]          # Ausbruch, dann enden die Daten
    n = len(up) + 30
    c = {"DEADUSDT": bars(up), "BTCUSDT": bars(flat(n))}
    r = pc.run(c, {}, {**TREND_ONLY})
    dead = [t for t in r["trades"] if t["symbol"] == "DEADUSDT"]
    assert dead and dead[-1]["reason"] == "keine Kurse mehr" and dead[-1]["exit"] == pytest.approx(up[-1])
    assert not [p for p in r["positions"] if p["symbol"] == "DEADUSDT"]
    assert all(p.get("init_stop") is not None for p in r["positions"] if p["sleeve"] == "trend")


def test_engine_universe_and_level_settings():
    assert len(pe.UNIVERSE) == 64 and len(set(pe.UNIVERSE)) == 64
    cc = pe.core_config(pe.normalize_config({"risk_level": "normal"}))
    assert cc["trend"]["max_positions"] == 20 and cc["trend"]["max_gross"] == 3.0 and cc["carry"]["n_side"] == 8
    assert pe.normalize_config({"symbols": pe.UNIVERSE})["symbols"] == sorted(pe.UNIVERSE)


def test_migration_universe_only_for_old_default():
    from services import boot_migrations as bm
    db = FakeDB()
    run(db.settings.insert_one({"_id": pe.CONFIG_ID, "symbols": list(pe.UNIVERSE_26), "risk_level": "normal"}))
    run(bm.migrate_portfolio_universe_64(db))
    assert len(run(pe.get_config(db))["symbols"]) == 64 and run(pe.get_config(db))["risk_level"] == "normal"
    db2 = FakeDB()
    own = pe.UNIVERSE_26[:10]
    run(db2.settings.insert_one({"_id": pe.CONFIG_ID, "symbols": own}))
    run(bm.migrate_portfolio_universe_64(db2))
    assert run(pe.get_config(db2))["symbols"] == sorted(own)
