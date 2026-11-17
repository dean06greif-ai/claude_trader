"""Leitstand-Tagesbericht (Phase D, 15.11.2026) – deterministisch, 0 KI-Kosten.

Jeden Morgen eine Momentaufnahme des Vortags (Berliner Tag): KI-Trades in R,
Gebühren, Lern-/Schattentrades, Stand seit dem Bewertungs-Stichtag, offene
Mängel und die wichtigsten Empfehlungen. Gespeichert in `cockpit_daily`
(Verlauf für die Vorher/Nachher-Kurve im Leitstand), optional als
Telegram-Nachricht (Toggle „cockpit_daily“, Standard aus).

Bewusst ohne LLM: Die bestehende KI-Tageszusammenfassung (Mitternacht, im
KI-Chat) bleibt; dieser Bericht liefert nur nachprüfbare Zahlen.
"""
import asyncio
import logging
from datetime import datetime, time as dtime, timedelta, timezone
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

COLLECTION = "cockpit_daily"
BERLIN = ZoneInfo("Europe/Berlin")
SEND_HOUR = 8               # Berliner Zeit
KEEP_DAYS = 180


def _r(t: Dict) -> Optional[float]:
    try:
        risk = float(t.get("risk_usdt") or 0)
        return float(t.get("realized_pnl") or 0) / risk if risk > 0 else None
    except (TypeError, ValueError):
        return None


def _fee_r(t: Dict) -> Optional[float]:
    try:
        risk = float(t.get("risk_usdt") or 0)
        return float(t.get("fees_paid") or 0) / risk if risk > 0 else None
    except (TypeError, ValueError):
        return None


def trade_block(trades: List[Dict]) -> Dict:
    """Kennzahlen einer Trade-Menge (rein)."""
    rs = [x for x in (_r(t) for t in trades) if x is not None]
    fs = [x for x in (_fee_r(t) for t in trades) if x is not None]
    shadows = sum(1 for t in trades if isinstance(t.get("guard_shadow"), dict))
    coll = sum(1 for t in trades if t.get("data_collection"))
    return {"trades": len(trades), "with_r": len(rs),
            "avg_r": round(sum(rs) / len(rs), 3) if rs else None,
            "sum_r": round(sum(rs), 2) if rs else 0.0,
            "fee_r": round(sum(fs) / len(fs), 3) if fs else None,
            "wins": sum(1 for x in rs if x > 0),
            "liquidations": sum(1 for t in trades if t.get("liquidated")),
            "shadows": shadows, "collection": coll}


def day_bounds(day_local) -> tuple:
    start = datetime.combine(day_local, dtime(0, 0), BERLIN).astimezone(timezone.utc)
    end = start + timedelta(days=1)
    return start.isoformat(), end.isoformat()


def format_text(rep: Dict) -> str:
    d = rep.get("day")
    y = rep.get("yesterday") or {}
    s = rep.get("since_cutoff") or {}

    def r(v):
        return "–" if v is None else f"{v:+.2f} R"

    fee = "–" if y.get("fee_r") is None else f"{y['fee_r']:.2f} R"
    lines = [f"📋 Leitstand – Tagesbericht {d}",
             f"KI-Trades gestern: {y.get('trades', 0)} (Ø {r(y.get('avg_r'))}, Gebühren {fee})",
             f"Seit Stichtag: {s.get('trades', 0)} Trades, Ø {r(s.get('avg_r'))}"]
    doc = rep.get("doctor") or {}
    c = doc.get("counts") or {}
    lines.append(f"Systemarzt: {c.get('kritisch', 0)} kritisch, {c.get('warnung', 0)} Warnung(en)")
    for f in (doc.get("top") or [])[:3]:
        lines.append(f"• {f}")
    recs = rep.get("recommendations") or []
    if recs:
        lines.append("Empfehlungen:")
        lines += [f"• {x}" for x in recs[:3]]
    cand = rep.get("candidates") or {}
    if cand.get("active") or cand.get("passed"):
        lines.append(f"Kandidaten: {cand.get('active', 0)} im Vorwärtstest, {cand.get('passed', 0)} bestanden")
    return "\n".join(lines)


async def build(db, day_local=None) -> Dict:
    from services import evaluation_cutoff, research_pipeline, system_doctor
    now_local = datetime.now(BERLIN)
    day_local = day_local or (now_local - timedelta(days=1)).date()
    a, b = day_bounds(day_local)
    proj = {"_id": 0, "realized_pnl": 1, "risk_usdt": 1, "fees_paid": 1, "guard_shadow": 1,
            "data_collection": 1, "liquidated": 1, "opened_at": 1}
    y = await db.auto_trades.find({"strategy_id": "ai_trader", "status": "closed",
                                   "closed_at": {"$gte": a, "$lt": b}}, proj).to_list(5000)
    since = evaluation_cutoff.cached_since()
    sc = await db.auto_trades.find({"strategy_id": "ai_trader", "status": "closed",
                                    **({"opened_at": {"$gte": since}} if since else {})},
                                   proj).to_list(20000) if since else []
    doc = await system_doctor.latest(db) or {}
    top = [f"{f.get('title')}" for f in (doc.get("findings") or []) if f.get("level") in ("kritisch", "warnung")]
    cands = await db[research_pipeline.COLLECTION].find({}, {"_id": 0, "stage": 1}).to_list(200)
    rep = {"_id": day_local.isoformat(), "day": day_local.isoformat(),
           "generated_at": datetime.now(timezone.utc).isoformat(),
           "evaluation_since": since, "yesterday": trade_block(y),
           "since_cutoff": trade_block(sc) if since else None,
           "doctor": {"level": doc.get("level"), "counts": doc.get("counts"), "top": top[:5]},
           "candidates": {"active": sum(1 for c in cands if c.get("stage") == "vorwaertstest"),
                          "passed": sum(1 for c in cands if c.get("stage") == "bestanden")}}
    try:
        from services import cockpit
        rep["recommendations"] = [r.get("title") for r in (await cockpit.recommendations(db))[:5]]
    except Exception as e:  # noqa: BLE001
        logger.debug(f"Tagesbericht: Empfehlungen nicht verfügbar: {e}")
        rep["recommendations"] = []
    return rep


async def make_and_store(db, send: bool = True, day_local=None) -> Dict:
    rep = await build(db, day_local)
    await db[COLLECTION].replace_one({"_id": rep["_id"]}, rep, upsert=True)
    try:
        cut = (datetime.now(timezone.utc) - timedelta(days=KEEP_DAYS)).date().isoformat()
        await db[COLLECTION].delete_many({"_id": {"$lt": cut}})
    except Exception:  # noqa: BLE001
        pass
    rep["sent"] = False
    if send:
        try:
            from core import state
            from services import notifications
            rep["sent"] = bool(await notifications.telegram_notify(
                db, getattr(state, "telegram", None), "cockpit_daily", format_text(rep)))
        except Exception as e:  # noqa: BLE001
            logger.debug(f"Tagesbericht Telegram: {e}")
    return rep


def is_due(last_day: Optional[str], now_local: Optional[datetime] = None) -> bool:
    """Nach SEND_HOUR Uhr, einmal je Tag (Bericht über den Vortag) – rein."""
    now_local = now_local or datetime.now(BERLIN)
    if now_local.hour < SEND_HOUR:
        return False
    return last_day != (now_local - timedelta(days=1)).date().isoformat()


async def history(db, days: int = 30) -> List[Dict]:
    rows = await db[COLLECTION].find({}, {"_id": 0}).sort("day", -1).limit(days).to_list(days)
    return list(reversed(rows))
