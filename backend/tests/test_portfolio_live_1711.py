"""Portfolio live (17.11.2026): Planer (rein) und Ausführer gegen eine nachgebaute Börse."""
import asyncio

import pytest

from services import portfolio_live as pl
from services import system_doctor as sd
from tests.phase_fakedb import FakeDB

DAY = 86_400_000
LAST = 1_794_787_200_000
META = {"BTCUSDT": {"qty_step": 0.0001, "min_qty": 0.0001, "max_lev": 200, "price_tick": 0.1},
        "ETHUSDT": {"qty_step": 0.001, "min_qty": 0.003, "max_lev": 200, "price_tick": 0.01},
        "NEARUSDT": {"qty_step": 1, "min_qty": 10, "max_lev": 50, "price_tick": 0.001},
        "DOTUSDT": {"qty_step": 0.1, "min_qty": 0.8, "max_lev": 75, "price_tick": 0.0001},
        "ADAUSDT": {"qty_step": 1, "min_qty": 15, "max_lev": 75, "price_tick": 0.0001},
        "XRPUSDT": {"qty_step": 0.1, "min_qty": 2, "max_lev": 100, "price_tick": 0.0001},
        "LINKUSDT": {"qty_step": 0.01, "min_qty": 0.1, "max_lev": 75, "price_tick": 0.001}}


def run(c):
    return asyncio.run(c)


def cfg(**kw):
    return pl.normalize_config({"mode": "live", "capital": 100.0, "risk_pct": 1.0, **kw})


def tp(sym, side, entry, stop, ts=LAST, notional=1000.0, init=None):
    return {"sleeve": "trend", "symbol": sym, "side": side, "entry": entry, "stop": stop,
            "init_stop": init if init is not None else stop, "entry_ts": ts, "notional": notional}


def cp(sym, side, ts=LAST, notional=500.0):
    return {"sleeve": "carry", "symbol": sym, "side": side, "entry_ts": ts, "notional": notional}


def pf(*positions, equity=10000.0, risk=0.25):
    return {"positions": list(positions), "equity": equity, "risk_pct": risk, "last_ts": LAST}


# ---------------- rein ----------------
def test_size_qty_never_silently_upsizes():
    m = META["NEARUSDT"]                                     # Mindestens 10 Stück
    assert pl.size_qty(60.0, 4.0, m, 2.0) == {"ok": True, "qty": 15.0, "factor": 1.0}
    assert pl.size_qty(62.0, 4.0, m, 2.0)["qty"] == 15.0          # 15,5 -> nächster Schritt 15 bzw. 16
    assert pl.size_qty(63.0, 4.0, m, 2.0)["qty"] == 16.0
    assert pl.size_qty(12.5, 70000.0, META["BTCUSDT"], 2.0)["qty"] == pytest.approx(0.0002)   # nicht 0,0001
    up = pl.size_qty(22.0, 4.0, META["NEARUSDT"], 2.0)     # 5,5 Stück -> 10 (Faktor 1,8)
    assert up["ok"] and up["qty"] == 10 and "aufgerundet" in up["note"] and up["factor"] == 1.82
    no = pl.size_qty(15.0, 4.0, m, 2.0)                    # 3,75 -> 10 wäre Faktor 2,7
    assert not no["ok"] and "unter Mindestmenge" in no["reason"]
    assert not pl.size_qty(10.0, 0, m, 2.0)["ok"]
    assert pl.size_qty(7.7, 77000.0, META["BTCUSDT"], 2.0)["qty"] == 0.0001


def test_leverage_keeps_liquidation_beyond_stop():
    assert pl.leverage_for(0.08) == 5 and pl.leverage_for(0.2) == 2 and pl.leverage_for(0.6) == 1
    assert pl.leverage_for(0.01, max_lev=3) == 3
    assert pl.leverage_for(0, carry=True) == pl.CARRY_LEVERAGE
    for stop in (0.03, 0.08, 0.15, 0.3):
        lev = pl.leverage_for(stop)
        assert 1.0 / lev >= 2 * stop or lev == 1


def test_plan_opens_new_trend_with_risk_and_stop():
    p = pf(tp("BTCUSDT", "SHORT", 70000.0, 75600.0))       # 8 % Stop-Abstand
    acts = pl.plan_actions(cfg(), p, [], set(), [], {"BTCUSDT": 70000.0}, META, 500.0)
    o = [a for a in acts if a["kind"] == "open"]
    assert len(o) == 1 and o[0]["side"] == "SHORT" and o[0]["sl"] == 75600.0 and o[0]["leverage"] == 5
    assert 0.75 <= o[0]["risk"] <= 1.3                      # ~1 % von 100 USDT (Mengenschritt BTC)
    assert o[0]["qty"] == 0.0001 * round(o[0]["qty"] / 0.0001)


def test_plan_late_entry_rules():
    late = tp("ETHUSDT", "LONG", 2000.0, 1840.0, ts=LAST - 3 * DAY)        # 1 R = 160
    near = pl.plan_actions(cfg(), pf(late), [], set(), [], {"ETHUSDT": 2050.0}, META, 500.0)
    assert [a["kind"] for a in near] == ["open"] and near[0]["late"]
    far = pl.plan_actions(cfg(), pf(late), [], set(), [], {"ETHUSDT": 2200.0}, META, 500.0)
    assert far[0]["kind"] == "skip" and "R gelaufen" in far[0]["reason"]
    off = pl.plan_actions(cfg(late_entry=False), pf(late), [], set(), [], {"ETHUSDT": 2010.0}, META, 500.0)
    assert off[0]["kind"] == "skip" and "nur neue" in off[0]["reason"]
    beyond = pl.plan_actions(cfg(), pf(late), [], set(), [], {"ETHUSDT": 1800.0}, META, 500.0)
    assert beyond[0]["kind"] == "skip" and "jenseits" in beyond[0]["reason"]


def test_plan_skips_below_minimum_and_foreign_and_done():
    p = pf(tp("NEARUSDT", "LONG", 4.0, 3.0))               # 25 % Stop -> 4 USDT Ziel, Minimum 40 USDT
    acts = pl.plan_actions(cfg(), p, [], set(), [], {"NEARUSDT": 4.0}, META, 500.0)
    assert acts[0]["kind"] == "skip" and "Mindestmenge" in acts[0]["reason"]
    p2 = pf(tp("BTCUSDT", "LONG", 70000.0, 64400.0))
    exch = [{"bitunix_symbol": "BTCUSDT", "side": "LONG", "qty": 0.01, "position_id": "x9"}]
    f = pl.plan_actions(cfg(), p2, [], set(), exch, {"BTCUSDT": 70000.0}, META, 500.0)
    assert f[0]["kind"] == "skip" and "fremde Position" in f[0]["reason"]
    key = pl.trend_key(p2["positions"][0])
    d = pl.plan_actions(cfg(), p2, [], {key}, [], {"BTCUSDT": 70000.0}, META, 500.0)
    assert d[0]["kind"] == "skip" and "ausgestoppt" in d[0]["reason"]


def test_plan_close_and_move_stop():
    pos = tp("BTCUSDT", "SHORT", 70000.0, 72000.0)
    book = [{"key": pl.trend_key(pos), "symbol": "BTCUSDT", "side": "SHORT", "sleeve": "trend", "qty": 0.0003,
             "position_id": "p1", "sl_price": 75600.0},
            {"key": "trend:ETHUSDT:LONG:1", "symbol": "ETHUSDT", "side": "LONG", "sleeve": "trend", "qty": 0.01,
             "position_id": "p2", "sl_price": 1800.0}]
    acts = pl.plan_actions(cfg(), pf(pos), book, set(), [], {"BTCUSDT": 69000.0, "ETHUSDT": 1900.0}, META, 500.0)
    kinds = {(a["kind"], a["symbol"]) for a in acts}
    assert ("close", "ETHUSDT") in kinds and ("move_sl", "BTCUSDT") in kinds
    mv = next(a for a in acts if a["kind"] == "move_sl")
    assert mv["old"] == 75600.0 and mv["new"] == 72000.0
    worse = pl.plan_actions(cfg(), pf(tp("BTCUSDT", "SHORT", 70000.0, 76000.0)),
                            [dict(book[0], key=pl.trend_key(tp("BTCUSDT", "SHORT", 70000.0, 76000.0)))],
                            set(), [], {"BTCUSDT": 69000.0}, META, 500.0)
    assert not [a for a in worse if a["kind"] == "move_sl"]                 # Stop nie lockern
    gap = pl.plan_actions(cfg(), pf(pos), book[:1], set(), [], {"BTCUSDT": 72500.0}, META, 500.0)
    assert gap[0]["kind"] == "close" and "jenseits" in gap[0]["reason"]


def test_plan_carry_neutral_and_disaster_stop():
    p = pf(cp("ETHUSDT", "LONG"), cp("XRPUSDT", "LONG"), cp("LINKUSDT", "SHORT"),
           cp("NEARUSDT", "SHORT", notional=50.0))         # NEAR zu klein -> Long-Seite wird gekürzt
    px = {"ETHUSDT": 2000.0, "XRPUSDT": 1.5, "LINKUSDT": 10.0, "NEARUSDT": 4.0}
    acts = pl.plan_actions(cfg(), p, [], set(), [], px, META, 500.0)
    opens = [a for a in acts if a["kind"] == "open"]
    assert sum(1 for o in opens if o["side"] == "LONG") == sum(1 for o in opens if o["side"] == "SHORT") == 1
    link = next(o for o in opens if o["symbol"] == "LINKUSDT")
    assert link["sl"] == pytest.approx(12.5) and link["leverage"] == pl.CARRY_LEVERAGE
    assert any("marktneutral" in a.get("reason", "") for a in acts)
    assert not [a for a in pl.plan_actions(cfg(carry=False), p, [], set(), [], px, META, 500.0) if a["kind"] == "open"]


def test_plan_carry_does_not_collide_with_trend():
    p = pf(tp("ETHUSDT", "LONG", 2000.0, 1840.0), cp("ETHUSDT", "LONG"), cp("XRPUSDT", "SHORT"))
    acts = pl.plan_actions(cfg(), p, [], set(), [], {"ETHUSDT": 2000.0, "XRPUSDT": 1.5}, META, 500.0)
    assert any(a["kind"] == "skip" and a["sleeve"] == "carry" and "Trend-Position" in a["reason"] for a in acts)
    assert [a["sleeve"] for a in acts if a["kind"] == "open" and a["symbol"] == "ETHUSDT"] == ["trend"]
    # Trend-Position wird live NICHT eröffnet (zu spät) -> der Funding-Leg darf
    late = tp("ETHUSDT", "LONG", 1500.0, 1340.0, ts=LAST - 9 * DAY)
    acts2 = pl.plan_actions(cfg(), pf(late, cp("ETHUSDT", "LONG"), cp("XRPUSDT", "SHORT")), [], set(), [],
                            {"ETHUSDT": 2000.0, "XRPUSDT": 1.5}, META, 500.0)
    assert [a["sleeve"] for a in acts2 if a["kind"] == "open" and a["symbol"] == "ETHUSDT"] == ["carry"]
    # Funding-Leg hält die Seite live -> neue Trend-Position derselben Seite wartet
    book = [{"key": "carry:ETHUSDT:LONG", "symbol": "ETHUSDT", "side": "LONG", "sleeve": "carry", "qty": 0.01,
             "position_id": "c1"}]
    acts3 = pl.plan_actions(cfg(), pf(tp("ETHUSDT", "LONG", 2000.0, 1840.0)), book, set(), [],
                            {"ETHUSDT": 2000.0}, META, 500.0)
    assert any(a["kind"] == "skip" and "Funding-Leg hält" in a["reason"] for a in acts3)


def test_plan_limits_halt_margin_and_gross():
    p = pf(tp("BTCUSDT", "SHORT", 70000.0, 75600.0))
    h = pl.plan_actions(cfg(halted=True), p, [], set(), [], {"BTCUSDT": 70000.0}, META, 500.0)
    assert h[0]["kind"] == "skip" and "Not-Aus" in h[0]["reason"]
    m = pl.plan_actions(cfg(), p, [], set(), [], {"BTCUSDT": 70000.0}, META, 0.5)
    assert m[0]["kind"] == "skip" and "Margin" in m[0]["reason"]
    tight = pf(tp("BTCUSDT", "SHORT", 70000.0, 71400.0))      # 2 % Stop -> ~100 USDT Positionsgröße
    g = pl.plan_actions(cfg(max_gross=0.5, risk_pct=2.0), tight, [], set(), [], {"BTCUSDT": 70000.0}, META, 500.0)
    assert g[0]["kind"] == "skip" and "Gesamtgröße" in g[0]["reason"]


def test_pnl_kill_and_slippage():
    pnl = pl.live_pnl([{"net_pnl": -10.0}, {"net_pnl": 4.0}],
                      [{"symbol": "BTCUSDT", "side": "SHORT", "fill_price": 70000.0, "qty": 0.001}],
                      {"BTCUSDT": 71000.0})
    assert pnl == {"realized": -6.0, "unrealized": -1.0, "total": -7.0}
    assert pl.kill_check(cfg(max_loss_pct=30), -29.9) is None
    assert "Grenze" in pl.kill_check(cfg(max_loss_pct=30), -30.0)
    assert pl.slippage_pct("LONG", 100.0, 100.2) == 0.2 and pl.slippage_pct("SHORT", 100.0, 100.2) == -0.2


def test_config_live_needs_confirmation():
    db = FakeDB()
    assert run(pl.get_config(db))["mode"] == "probe"
    with pytest.raises(ValueError):
        run(pl.set_config(db, {"mode": "live"}))
    c = run(pl.set_config(db, {"mode": "live", "confirm": "LIVE", "capital": 130, "started_at": "manipuliert"}))
    assert c["mode"] == "live" and c["capital"] == 130.0 and c["started_at"] != "manipuliert"
    c2 = run(pl.set_config(db, {"risk_pct": 50, "last_synced_ts": 5}))
    assert c2["risk_pct"] == 2.0 and c2["last_synced_ts"] is None and c2["started_at"] == c["started_at"]


# ---------------- Ausführer gegen nachgebaute Börse ----------------
class FakeClient:
    """Verhält sich wie BitunixTradeClient (Antwortformen aus der Produktion)."""

    def __init__(self, sl_works=True, liq=0.0):
        self._pairs_meta = dict(META)
        self.positions = {}          # pid -> row
        self.tpsl = {}               # pid -> [rows]
        self.calls = []
        self.sl_works = sl_works
        self.liq = liq
        self.prices = {"BTCUSDT": 70000.0, "ETHUSDT": 2000.0, "XRPUSDT": 1.5, "LINKUSDT": 10.0}
        self.history = {}
        self._n = 0

    def configured(self):
        return True

    def to_bitunix_symbol(self, s):
        return s

    def contract_meta(self, s):
        return META.get(s, {})

    async def load_trading_pairs(self):
        pass

    async def get_positions(self, symbol=None):
        rows = [r for r in self.positions.values() if symbol is None or r["symbol"] == symbol]
        return {"code": 0, "data": rows}

    async def get_all_mark_prices(self):
        return dict(self.prices)

    async def get_balance(self):
        return {"code": 0, "data": {"available": "120.5"}}

    async def set_leverage(self, symbol, lev, margin_mode="ISOLATION"):
        self.calls.append(("lev", symbol, lev))
        return {"code": 0}

    async def place_order(self, symbol, side, qty, order_type="MARKET", **kw):
        self.calls.append(("order", symbol, side, qty))
        self._n += 1
        pid = f"pid{self._n}"
        px = self.prices[symbol] * (1.0005 if side == "BUY" else 0.9995)
        self.positions[pid] = {"symbol": symbol, "side": side, "qty": str(qty), "positionId": pid,
                               "avgOpenPrice": str(px), "leverage": "5", "liqPrice": str(self.liq),
                               "ctime": "1794787200000"}
        return {"code": 0, "data": {"orderId": f"o{self._n}"}}

    async def get_pending_tpsl(self, symbol, position_id=None):
        return {"code": 0, "data": list(self.tpsl.get(position_id, []))}

    async def place_position_tp_sl(self, symbol, pid, side, sl_price=None, sl_qty=None, **kw):
        self.calls.append(("sl", symbol, sl_price))
        if self.sl_works:
            self.tpsl.setdefault(pid, []).append({"id": f"s{pid}", "slPrice": str(sl_price)})
        return {"code": 0}

    async def modify_tpsl_order(self, symbol, oid, side="LONG", sl_price=None, sl_qty=None, **kw):
        self.calls.append(("mod", symbol, sl_price))
        for rows in self.tpsl.values():
            for r in rows:
                if r["id"] == oid:
                    r["slPrice"] = str(sl_price)
        return {"code": 0}

    async def cancel_tpsl_order(self, symbol, oid):
        for pid in self.tpsl:
            self.tpsl[pid] = [r for r in self.tpsl[pid] if r["id"] != oid]
        return {"code": 0}

    async def flash_close(self, symbol, pid, side, qty, full=False):
        self.calls.append(("close", symbol, pid))
        row = self.positions.pop(pid, None)
        if row:
            self.history[pid] = {"positionId": pid, "realizedPNL": "-0.8", "fee": "0.01", "funding": "0",
                                 "closePrice": str(self.prices[symbol]), "entryPrice": row["avgOpenPrice"],
                                 "maxQty": row["qty"], "side": row["side"]}
        return {"code": 0}

    async def get_history_positions(self, symbol=None, position_id=None, limit=20):
        h = self.history.get(position_id)
        return {"code": 0, "data": {"positionList": [h] if h else []}}


@pytest.fixture
def env(monkeypatch):
    db = FakeDB()
    client = FakeClient()
    monkeypatch.setattr(pl, "_client", lambda: client)
    real_sleep = asyncio.sleep

    async def no_wait(*_a, **_k):
        await real_sleep(0)
    monkeypatch.setattr(pl.asyncio, "sleep", no_wait)
    sent = []

    async def fake_notify(db_, text):
        sent.append(text)
    monkeypatch.setattr(pl, "_notify", fake_notify)

    async def pf_state(state):
        from services import portfolio_engine
        await db.settings.update_one({"_id": portfolio_engine.STATE_ID}, {"$set": state}, upsert=True)
    return db, client, sent, pf_state


def test_probe_mode_sends_nothing(env):
    db, client, sent, pf_state = env
    run(pf_state(pf(tp("BTCUSDT", "SHORT", 70000.0, 75600.0), cp("ETHUSDT", "LONG"), cp("XRPUSDT", "SHORT"))))
    res = run(pl.sync(db))
    assert res["status"] == "ok" and res["mode"] == "probe" and res["open"] == 3
    assert not [c for c in client.calls if c[0] in ("order", "lev", "sl", "close")]
    prev = run(pl.get_overview(db))["preview"]
    assert prev["summary"]["open"] == 3 and prev["available"] == 120.5 and not sent


def test_live_open_sets_verified_stop_and_books(env):
    db, client, sent, pf_state = env
    run(pl.set_config(db, {"mode": "live", "confirm": "LIVE", "capital": 100}))
    run(pf_state(pf(tp("BTCUSDT", "SHORT", 70000.0, 75600.0))))
    res = run(pl.sync(db))
    assert res["open"] == 1 and res["errors"] == 0
    assert [c[0] for c in client.calls] == ["lev", "order", "sl"]
    book = run(db[pl.BOOK].find_one({"status": "open"}))
    assert book["sl_price"] == 75600.0 and book["first_sl"] == 75600.0 and book["position_id"] == "pid1"
    assert book["slippage_pct"] == pytest.approx(0.05, abs=1e-3)
    assert pl.owns("pid1") and pl.holds("BTCUSDT", "SHORT") and not pl.holds("BTCUSDT", "LONG")
    assert sent and "BTCUSDT SHORT eröffnet" in sent[-1]
    assert run(pl.tick(db)) == "aktuell"                      # gleicher Portfolio-Tag: kein zweiter Lauf


def test_live_open_without_stop_is_closed_immediately(env):
    db, client, sent, pf_state = env
    client.sl_works = False
    run(pl.set_config(db, {"mode": "live", "confirm": "LIVE"}))
    run(pf_state(pf(tp("BTCUSDT", "SHORT", 70000.0, 75600.0))))
    res = run(pl.sync(db))
    assert res["errors"] == 1 and not client.positions                    # nie ungeschützt
    assert ("close", "BTCUSDT", "pid1") in client.calls
    assert run(db[pl.BOOK].count_documents({"status": "open"})) == 0


def test_live_open_with_liquidation_before_stop_is_closed(env):
    db, client, sent, pf_state = env
    client.liq = 74000.0                                                  # Short: Liquidation unter dem Stop 75.600
    run(pl.set_config(db, {"mode": "live", "confirm": "LIVE"}))
    run(pf_state(pf(tp("BTCUSDT", "SHORT", 70000.0, 75600.0))))
    assert run(pl.sync(db))["errors"] == 1 and not client.positions


def test_live_trail_stop_then_exchange_stop_then_no_reentry(env):
    db, client, sent, pf_state = env
    run(pl.set_config(db, {"mode": "live", "confirm": "LIVE"}))
    pos = tp("BTCUSDT", "SHORT", 70000.0, 75600.0)
    run(pf_state(pf(pos)))
    run(pl.sync(db))
    # nächster Tag: Paper zieht den Stop nach
    nxt = {**pf(dict(pos, stop=72000.0)), "last_ts": LAST + DAY}
    run(pf_state(nxt))
    client.prices["BTCUSDT"] = 68000.0
    res = run(pl.sync(db))
    assert res["move_sl"] == 1 and ("mod", "BTCUSDT", 72000.0) in client.calls
    assert run(db[pl.BOOK].find_one({"status": "open"}))["sl_price"] == 72000.0
    # Stop an der Börse ausgelöst; Paper hält die Position noch (anderer Preis-Feed)
    row = client.positions.pop("pid1")
    client.history["pid1"] = {"positionId": "pid1", "realizedPNL": "-0.5", "fee": "0", "funding": "0",
                              "closePrice": "72000", "entryPrice": row["avgOpenPrice"], "maxQty": row["qty"],
                              "side": "SELL"}
    run(pf_state({**nxt, "last_ts": LAST + 2 * DAY}))
    res = run(pl.sync(db))
    assert res["closed_at_exchange"] == 1 and res["open"] == 0          # nicht wieder einsteigen
    closed = run(db[pl.BOOK].find_one({"status": "closed"}))
    assert closed["net_pnl"] == -0.5 and closed["close_reason"].startswith("an der Börse")
    assert not pl.holds("BTCUSDT", "SHORT")


def test_live_closes_when_paper_closes_and_kill_switch(env):
    db, client, sent, pf_state = env
    run(pl.set_config(db, {"mode": "live", "confirm": "LIVE", "capital": 10, "max_loss_pct": 5}))
    run(pf_state(pf(cp("ETHUSDT", "LONG", notional=5000.0), cp("XRPUSDT", "SHORT", notional=5000.0))))
    run(pl.sync(db))
    assert run(db[pl.BOOK].count_documents({"status": "open"})) == 2
    run(pf_state({**pf(), "last_ts": LAST + DAY}))                       # Korb leer -> beide schließen
    res = run(pl.sync(db))
    assert res["close"] == 2 and not client.positions
    run(pl.set_config(db, {}))
    run(pl._save(db, {**run(pl.get_config(db)), "last_check_at": 0}))
    assert run(pl.health(db))["status"] == "ok"                        # Not-Aus greift auch in der Stundenprüfung
    c = run(pl.get_config(db))
    assert c["halted"] and "Grenze" in c["halt_reason"]                 # 2 × −0,81 USDT > 5 % von 10
    assert any("Not-Aus" in t for t in sent)
    run(pf_state({**pf(cp("ETHUSDT", "LONG", notional=5000.0)), "last_ts": LAST + 2 * DAY}))
    res = run(pl.sync(db))
    assert res["open"] == 0 and not client.positions
    doc = run(db.settings.find_one({"_id": pl.CONFIG_ID}))
    assert not [d for d in (doc.get("done") or []) if d.startswith("carry:")]   # planmäßig = keine Sperre


def test_health_restores_missing_stop_and_flatten(env):
    db, client, sent, pf_state = env
    run(pl.set_config(db, {"mode": "live", "confirm": "LIVE"}))
    run(pf_state(pf(tp("BTCUSDT", "SHORT", 70000.0, 75600.0))))
    run(pl.sync(db))
    client.tpsl["pid1"] = []                                            # SL an der Börse verschwunden
    r = run(pl.health(db))
    assert r["sl_restored"] == 1 and client.tpsl["pid1"]
    with pytest.raises(ValueError):
        run(pl.flatten(db, "ja"))
    out = run(pl.flatten(db, "ALLES SCHLIESSEN"))
    assert out["closed"][0]["ok"] and not client.positions
    c = run(pl.get_config(db))
    assert c["mode"] == "probe" and c["halted"]


def test_doctor_live_findings():
    assert sd.judge_portfolio_live({"mode": "probe", "halted": True}, {}, 0) == []
    f = sd.judge_portfolio_live({"mode": "live", "halted": True, "halt_reason": "Verlust", "last_check_at": 100},
                                {"errors": 2}, 100 + 4 * 3600)
    assert [x["id"] for x in f] == ["portfolio_live_halt", "portfolio_live_errors", "portfolio_live_stale"]
