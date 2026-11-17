"""Leitstand (15.11.2026): Übersicht, Systemarzt, Browser-Fehler, Stichtag,
Nacht-Forschung, Kandidaten, Live-Wächter, Tagesbericht.

Alle Lese-Endpunkte brauchen den Admin-Login. Aktionen laufen über eine feste
Liste gefahrloser Schritte (SAFE_ACTIONS) – nichts davon eröffnet, schließt
oder verändert Trades.
"""
import asyncio
import logging
from typing import Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response

from core.auth import require_admin

router = APIRouter(tags=["cockpit"])
logger = logging.getLogger(__name__)


def _db():
    from core import state
    if state.db is None:
        raise HTTPException(503, "DB nicht bereit")
    return state.db


def _ctx():
    from core import state
    from services.ai_engine import ai_engine
    return ai_engine, state.scanner, state.autotrader


@router.get("/api/cockpit")
async def cockpit_overview(_: bool = Depends(require_admin)):
    from services import cockpit
    engine, scanner, _at = _ctx()
    return await cockpit.build(_db(), engine, scanner)


@router.get("/api/cockpit/summary")
async def cockpit_summary(_: bool = Depends(require_admin)):
    from services import cockpit
    return await cockpit.summary(_db())


@router.get("/api/cockpit/doctor")
async def cockpit_doctor(_: bool = Depends(require_admin)):
    from services import system_doctor
    return await system_doctor.latest(_db()) or {"findings": [], "level": "unbekannt"}


@router.get("/api/cockpit/status")
async def cockpit_loop_status(_: bool = Depends(require_admin)):
    from services import autonomy_loop, night_research
    return {"loop": autonomy_loop.status(), "night_research": await night_research.get_state(_db())}


# ---- Bewertungs-Stichtag ----
@router.get("/api/cockpit/evaluation-since")
async def get_evaluation_since(_: bool = Depends(require_admin)):
    from services import evaluation_cutoff
    return await evaluation_cutoff.status(_db())


@router.put("/api/cockpit/evaluation-since")
async def put_evaluation_since(body: Dict, _: bool = Depends(require_admin)):
    from services import evaluation_cutoff
    try:
        return await evaluation_cutoff.set_since(_db(), (body or {}).get("since") or None,
                                                 by="trader", note=str((body or {}).get("note") or ""))
    except ValueError as e:
        raise HTTPException(400, str(e))


# ---- Nacht-Forschung / Live-Wächter Einstellungen ----
@router.put("/api/cockpit/night-research")
async def put_night_research(body: Dict, _: bool = Depends(require_admin)):
    from services import night_research
    return await night_research.update_config(_db(), body or {})


@router.get("/api/cockpit/live-watchdog")
async def get_live_watchdog(_: bool = Depends(require_admin)):
    from services import live_watchdog
    db = _db()
    return {"config": await live_watchdog.get_config(db), "strategies": list((await live_watchdog.load(db)).values())}


# ---- Kandidaten / Tagesberichte ----
@router.get("/api/cockpit/candidates")
async def get_candidates(_: bool = Depends(require_admin)):
    from services import research_pipeline
    return {"candidates": await research_pipeline.list_candidates(_db(), limit=50)}


@router.get("/api/cockpit/daily")
async def get_daily_reports(days: int = 30, _: bool = Depends(require_admin)):
    from services import daily_report
    return {"reports": await daily_report.history(_db(), days=max(1, min(180, int(days))))}


# ---- Aktionen (nur gefahrlose Schritte) ----
@router.post("/api/cockpit/action")
async def cockpit_action(body: Dict, _: bool = Depends(require_admin)):
    from services import cockpit
    body = body or {}
    kind = str(body.get("kind") or "")
    if kind not in cockpit.SAFE_ACTIONS:
        raise HTTPException(400, f"Unbekannte Aktion: {kind}")
    db = _db()
    engine, scanner, autotrader = _ctx()
    try:
        if kind == "doctor_run":
            from services import system_doctor
            return {"ok": True, "result": await system_doctor.run(db, engine, scanner, run_selftest=True)}
        if kind == "selftest":
            from services import selftest
            return {"ok": True, "result": await selftest.run_all(db)}
        if kind == "night_research_now":
            from services import night_research
            res = await night_research.tick(db, force=True)
            return {"ok": bool(res.get("planned")), "result": res,
                    "message": res.get("label") if res.get("planned") else res.get("reason")}
        if kind == "lab_auto_on":
            from services import boot_migrations
            from services.setup_backtest import auto as seed_auto
            return {"ok": True, "result": await seed_auto.save(db, boot_migrations.LAB_WEEKLY),
                    "message": "Lab-Automatik wöchentlich eingeschaltet"}
        if kind in ("candidate_adopt", "candidate_discard", "candidate_retest"):
            from services import research_pipeline
            cid = str(body.get("id") or "")
            if kind == "candidate_adopt":
                res = await research_pipeline.adopt(db, cid)
                return {"ok": True, "result": res, "message": "Als Strategie im Paper-Betrieb angelegt"}
            stage = "verworfen" if kind == "candidate_discard" else "vorwaertstest"
            return {"ok": True, "result": await research_pipeline.set_stage(db, cid, stage)}
        if kind == "dismiss":
            rid = str(body.get("id") or "")
            if not rid:
                raise HTTPException(400, "id fehlt")
            return {"ok": True, "result": await cockpit.dismiss(db, rid, int(body.get("days") or 14))}
        if kind == "undismiss_all":
            return {"ok": True, "result": await cockpit.undismiss_all(db)}
        if kind == "daily_report_now":
            from services import daily_report
            rep = await daily_report.make_and_store(db, send=bool(body.get("send")))
            return {"ok": True, "result": rep, "text": daily_report.format_text(rep)}
        if kind == "live_watchdog_auto_pause":
            from services import live_watchdog
            return {"ok": True, "result": await live_watchdog.set_config(db, {"auto_pause": bool(body.get("on"))})}
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(400, str(e))
    raise HTTPException(400, "Aktion nicht ausführbar")


# ---- Browser-Fehler ----
# ---------------- Portfolio (Trend + Funding auf Tagesebene, Paper) ----------------
@router.get("/api/portfolio")
async def get_portfolio(_: bool = Depends(require_admin)):
    from services import portfolio_engine
    return await portfolio_engine.get_state(_db())


@router.post("/api/portfolio/refresh")
async def refresh_portfolio(_: bool = Depends(require_admin)):
    from services import portfolio_engine
    return {"status": portfolio_engine.kick(_db(), force=True)}


@router.put("/api/portfolio/config")
async def put_portfolio_config(body: Dict, _: bool = Depends(require_admin)):
    from services import portfolio_engine
    cfg = await portfolio_engine.set_config(_db(), body or {})
    return {"config": cfg, "status": portfolio_engine.kick(_db(), force=True) if cfg["enabled"] else "aus"}


# ---------------- Portfolio live (Bitunix) ----------------
@router.get("/api/portfolio/live")
async def get_portfolio_live(_: bool = Depends(require_admin)):
    from services import portfolio_live
    return await portfolio_live.get_overview(_db())


@router.put("/api/portfolio/live/config")
async def put_portfolio_live_config(body: Dict, _: bool = Depends(require_admin)):
    from services import portfolio_live
    try:
        cfg = await portfolio_live.set_config(_db(), body or {})
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"config": cfg}


@router.post("/api/portfolio/live/sync")
async def post_portfolio_live_sync(_: bool = Depends(require_admin)):
    """Sofort einen Lauf: im Probelauf nur planen, im Live-Modus ausführen."""
    from services import portfolio_live
    return await portfolio_live.sync(_db(), force=True)


@router.post("/api/portfolio/live/flatten")
async def post_portfolio_live_flatten(body: Dict, _: bool = Depends(require_admin)):
    from services import portfolio_live
    try:
        return await portfolio_live.flatten(_db(), (body or {}).get("confirm"))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/api/client-errors")
async def post_client_error(request: Request):
    """Fehler, die die Website selbst bemerkt (JS, Server-Anfragen). Nur mit
    Admin-Token gespeichert – sonst still ignoriert (204), damit fremde Besucher
    die Datenbank nicht füllen können."""
    from core.auth import require_admin as _req
    try:
        await _req(request)
    except HTTPException:
        return Response(status_code=204)
    try:
        payload = await asyncio.wait_for(request.json(), timeout=5)
    except Exception:  # noqa: BLE001
        return Response(status_code=204)
    from services import client_errors
    items = payload if isinstance(payload, list) else [payload]
    out = [await client_errors.record(_db(), p) for p in items[:10] if isinstance(p, dict)]
    return {"received": len(out), "results": out}


@router.get("/api/client-errors")
async def get_client_errors(hours: int = 24, _: bool = Depends(require_admin)):
    from services import client_errors
    return await client_errors.summary(_db(), hours=max(1, min(168, int(hours))))
