"""Selbsttest (services/selftest.py): besteht auf gesundem Code, meldet Abweichungen
verständlich und stört den Betrieb nicht."""
import asyncio

from services import selftest


def test_logic_selftest_passes_and_is_fast():
    res = selftest.run_logic()
    assert res["ok"], res["text"]
    assert res["passed"] == len(selftest.LOGIC_CHECKS) and res["seconds"] < 15


def test_broken_logic_is_reported_not_raised(monkeypatch):
    from services import position_sizing
    monkeypatch.setitem(position_sizing.DEFAULTS, "risk_per_trade_pct", 25.0)
    res = selftest.run_logic()
    assert res["ok"] is False and res["failed"] == 1
    assert "Risiko" in res["text"] and "FEHLGESCHLAGEN" in res["text"]


class _Coll:
    def __init__(self, doc=None, n=3):
        self.doc, self.n = doc, n

    async def find_one(self, q):
        return self.doc

    async def estimated_document_count(self):
        return self.n

    async def count_documents(self, q):
        return 0


class _Settings:
    async def find_one(self, q):
        return {"ai_trader_config": {"risk_per_trade_pct": 1.0, "signal_min_ki_trades": 5},
                "autotrade_config": {"mode": "paper"}}.get(q["_id"])


class _DB:
    settings, auto_trades = _Settings(), _Coll()

    async def command(self, name):
        return {"ok": 1}


def test_runtime_checks_with_fake_db_and_without_db():
    res = asyncio.run(selftest.run_all(_DB()))
    by = {c["id"]: c for c in res["checks"]}
    assert by["db"]["ok"] and "3 Trades" in by["db"]["detail"]
    assert "ACHTUNG" in by["ai_config"]["detail"]                 # Live-Tor nach 5 Trades fällt auf
    assert "paper" in by["trade_mode"]["detail"]
    res = asyncio.run(selftest.run_all(None))                     # ohne DB: Fehler gemeldet, kein Absturz
    assert res["ok"] is False and not {c["id"]: c for c in res["checks"]}["db"]["ok"]


def test_startup_run_never_raises():
    asyncio.run(selftest.run_at_startup(None, delay=0))
