"""Hintergrund-Takt für Leitstand und Autonomie (Phasen B–D, 15.11.2026).

Ein einziger Loop statt sechs: Jede Aufgabe hat ihren eigenen Takt und ist
einzeln abgesichert – ein Fehler in einer Aufgabe stoppt die anderen nicht.

  Systemarzt            alle 15 min (Self-Test höchstens stündlich)
  Nacht-Forschung       alle 10 min prüfen, plant höchstens 1 Suche je Nacht
  Kandidaten-Pipeline   alle 6 h (neue Champions übernehmen, fällige Vorwärtstests)
  Live-Wächter          stündlich (wirkt nur mit Freigabe „automatisch pausieren“)
  Tagesbericht          einmal täglich ab 8 Uhr (Berlin)
  Stichtag-Cache        alle 10 min aus der DB nachladen
"""
import asyncio
import logging
import time
from typing import Callable, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

TICK_S = 60
EVERY = {"doctor": 900, "selftest": 3600, "night": 600, "pipeline": 6 * 3600,
         "watchdog": 3600, "daily": 900, "cutoff": 600, "review": 1800, "portfolio": 900, "portfolio_live": 300}
START_DELAY_S = 150

_last: Dict[str, float] = {}
_status: Dict[str, Dict] = {}


def due(name: str, now: Optional[float] = None) -> bool:
    now = now or time.time()
    return now - _last.get(name, 0.0) >= EVERY[name]


def status() -> Dict:
    return {k: dict(v) for k, v in _status.items()}


async def _run(name: str, coro):
    t0 = time.time()
    try:
        res = await coro
        _status[name] = {"ok": True, "at": t0, "seconds": round(time.time() - t0, 2),
                         "info": str(res)[:160] if res is not None else None}
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Autonomie-Takt {name}: {e}")
        _status[name] = {"ok": False, "at": t0, "error": f"{type(e).__name__}: {str(e)[:160]}"}
    finally:
        _last[name] = t0


async def step(db, ctx: Callable[[], Tuple]) -> None:
    from services import (daily_report, evaluation_cutoff, live_watchdog, night_research,
                          research_pipeline, review_allocation, system_doctor)
    engine, scanner, autotrader = ctx()
    now = time.time()
    if due("cutoff", now):
        await _run("cutoff", evaluation_cutoff.load(db))
    if due("doctor", now):
        with_selftest = due("selftest", now)
        await _run("doctor", system_doctor.run(db, engine, scanner, run_selftest=with_selftest))
        if with_selftest:
            _last["selftest"] = now
    if due("night", now):
        await _run("night", night_research.tick(db))
    if due("pipeline", now):
        async def _pipe():
            added = await research_pipeline.sync_champions(db)
            done = await research_pipeline.evaluate_due(db, dict(getattr(scanner, "settings", {}) or {}))
            return {"added": added, "evaluated": len(done)}
        await _run("pipeline", _pipe())
    if due("watchdog", now):
        await _run("watchdog", live_watchdog.enforce(db, autotrader))
    if due("review", now):
        await _run("review", review_allocation.refresh(db, force=True))
    if due("portfolio", now):
        from services import portfolio_engine
        await _run("portfolio", portfolio_engine.tick(db))
    if due("portfolio_live", now):
        from services import portfolio_live
        await _run("portfolio_live", portfolio_live.tick(db))
    if due("daily", now):
        async def _daily():
            doc = await db.settings.find_one({"_id": "cockpit_daily_state"}) or {}
            if not daily_report.is_due(doc.get("last_day")):
                return "nicht fällig"
            rep = await daily_report.make_and_store(db, send=True)
            await db.settings.update_one({"_id": "cockpit_daily_state"},
                                         {"$set": {"last_day": rep["day"], "sent": rep.get("sent")}},
                                         upsert=True)
            return f"Bericht {rep['day']} (Telegram: {rep.get('sent')})"
        await _run("daily", _daily())


async def run_loop(db, ctx: Callable[[], Tuple]) -> None:
    await asyncio.sleep(START_DELAY_S)       # Boot abwarten (Kerzen, Migrationen, Worker)
    while True:
        try:
            await step(db, ctx)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Autonomie-Takt: {e}")
        await asyncio.sleep(TICK_S)
