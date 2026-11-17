"""Guthaben-Wächter für bezahlte OpenRouter-Keys (Paid-Modelle).

Fragt periodisch das Rest-Guthaben (total_credits - total_usage, Endpoint
/api/v1/credits) aller konfigurierten OpenRouter-Keys ab (Haupt + Copilot,
inkl. Backups). Schwellen (vom Trader festgelegt):
  < WARN_USD  (2.00 $)  -> Warnung   (gelbes Banner + Telegram)
  < CRIT_USD  (0.50 $)  -> Kritisch  (rotes Banner + Telegram)
Free-Tier-Keys ohne jemals geladenes Guthaben werden NICHT gewarnt (dort gibt
es kein Guthaben, nur Tageslimits – dafür existiert die Key-Ampel).
Telegram: höchstens 1 Meldung je Key & Stufe pro 24h (settings-Dedupe)."""
import asyncio
import logging
import os
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

WARN_USD = 2.0
CRIT_USD = 0.5
CHECK_EVERY_MIN = 30
NOTIFY_COOLDOWN_H = 24
STATE_ID = "key_credits_state"
USAGE_ID = "key_credits_usage"     # Verlauf der Nutzung je Key -> Verbrauch pro Tag
USAGE_KEEP_DAYS = 14
USAGE_SAMPLE_MIN = 55              # höchstens ein Messpunkt pro Stunde
BURN_WINDOW_H = 72                 # Verbrauch über die letzten 3 Tage
BURN_MIN_H = 12                    # erst ab 12 h Verlauf eine Aussage
RUNWAY_WARN_DAYS = 14

_snapshot: Dict = {"checked_at": None, "keys": [], "worst_level": "ok",
                   "warn_below_usd": WARN_USD, "critical_below_usd": CRIT_USD}


def level_for(remaining: Optional[float], has_credits: bool) -> str:
    """Warn-Stufe (rein & testbar). Keys ohne je geladenes Guthaben: 'free'."""
    if remaining is None:
        return "unknown"
    if not has_credits:
        return "free"
    if remaining < CRIT_USD:
        return "critical"
    if remaining < WARN_USD:
        return "warning"
    return "ok"


def _watched_keys() -> List[Tuple[str, str]]:
    """(Label, Key) aller OpenRouter-Keys: Haupt + Copilot inkl. Backups."""
    out, seen = [], set()
    for env, label in (("OPENROUTER_API_KEY", "OpenRouter"),
                       ("COPILOT_OPENROUTER_API_KEY", "Copilot")):
        for suffix in [""] + [f"_BACKUP{i}" if i else "_BACKUP" for i in range(0, 11)]:
            k = (os.environ.get(f"{env}{suffix}") or "").strip()
            if k and k not in seen:
                seen.add(k)
                n = suffix.replace("_BACKUP", "Backup ") or "Haupt"
                out.append((f"{label} {n}".strip(), k))
    return out


async def _fetch_credits(client, key: str) -> Dict:
    r = await client.get("https://openrouter.ai/api/v1/credits",
                         headers={"Authorization": f"Bearer {key}"})
    d = (r.json() or {}).get("data") or {}
    total = float(d.get("total_credits") or 0)
    usage = float(d.get("total_usage") or 0)
    return {"total_credits": total, "usage": round(usage, 4),
            "remaining": round(total - usage, 4)}


def burn_rate(samples: List[List[float]], now_ts: float) -> Optional[float]:
    """Verbrauch in $/Tag aus [ts, usage]-Messpunkten (rein). None = zu wenig Verlauf
    oder Zähler zurückgesetzt."""
    pts = sorted((float(t), float(u)) for t, u in (samples or []) if t is not None and u is not None)
    if len(pts) < 2:
        return None
    recent = [p for p in pts if p[0] >= now_ts - BURN_WINDOW_H * 3600] or pts[-2:]
    t0, u0 = recent[0]
    t1, u1 = pts[-1]
    if t1 - t0 < BURN_MIN_H * 3600 or u1 < u0:
        return None
    return (u1 - u0) / ((t1 - t0) / 86400.0)


def runway_days(remaining: Optional[float], burn: Optional[float]) -> Optional[float]:
    if remaining is None or burn is None or burn <= 0.005:
        return None
    return max(0.0, float(remaining)) / burn


async def _record_usage(db, rows: List[Dict]) -> None:
    """Nutzung je Key mitschreiben und Verbrauch/Reichweite in die Zeilen eintragen."""
    now = time.time()
    try:
        doc = await db.settings.find_one({"_id": USAGE_ID}) or {}
        hist = doc.get("hist") or {}
        changed = False
        for r in rows:
            if r.get("usage") is None or not r.get("total_credits"):
                continue
            k = r["key_masked"]
            pts = [p for p in (hist.get(k) or []) if now - float(p[0]) <= USAGE_KEEP_DAYS * 86400]
            if not pts or now - float(pts[-1][0]) >= USAGE_SAMPLE_MIN * 60:
                pts.append([round(now, 1), float(r["usage"])])
                changed = True
            hist[k] = pts
            burn = burn_rate(pts, now)
            if burn is not None:
                r["burn_usd_day"] = round(burn, 3)
                rd = runway_days(r.get("remaining"), burn)
                if rd is not None:
                    r["runway_days"] = round(rd, 1)
        if changed:
            await db.settings.update_one({"_id": USAGE_ID}, {"$set": {"hist": hist}}, upsert=True)
    except Exception as e:  # noqa: BLE001 – Zusatz-Anzeige, darf die Prüfung nie stören
        logger.debug(f"key credits usage history: {e}")


async def check_once(db=None, telegram=None) -> Dict:
    import httpx
    rows = []
    async with httpx.AsyncClient(timeout=15) as client:
        for label, key in _watched_keys():
            entry = {"label": label, "key_masked": f"{key[:14]}…{key[-4:]}"}
            try:
                c = await _fetch_credits(client, key)
                lvl = level_for(c["remaining"], c["total_credits"] > 0)
                entry.update({**c, "level": lvl})
            except Exception as e:  # noqa: BLE001
                entry.update({"level": "unknown", "error": str(e)[:100]})
            rows.append(entry)
    if db is not None:
        await _record_usage(db, rows)
    order = {"critical": 3, "warning": 2, "ok": 1, "free": 0, "unknown": 0}
    worst = max(rows, key=lambda r: order.get(r["level"], 0), default=None)
    runways = [r["runway_days"] for r in rows if r.get("runway_days") is not None]
    _snapshot.update({
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "keys": rows,
        "worst_level": (worst or {}).get("level", "ok")
        if worst and order.get(worst["level"], 0) >= 2 else "ok",
        "runway_min_days": round(min(runways), 1) if runways else None,
        "runway_warn_days": RUNWAY_WARN_DAYS,
    })
    if db is not None:
        await _maybe_notify(db, telegram, rows)
    return dict(_snapshot)


async def _maybe_notify(db, telegram, rows: List[Dict]) -> None:
    alerts = [r for r in rows if r.get("level") in ("warning", "critical")]
    if not alerts:
        return
    try:
        state = await db.settings.find_one({"_id": STATE_ID}) or {}
        sent = state.get("sent") or {}
        now = time.time()
        fresh = []
        for r in alerts:
            k = f"{r['key_masked']}:{r['level']}"
            if now - float(sent.get(k) or 0) > NOTIFY_COOLDOWN_H * 3600:
                sent[k] = now
                fresh.append(r)
        if not fresh:
            return
        await db.settings.update_one({"_id": STATE_ID},
                                     {"$set": {"sent": sent}}, upsert=True)
        lines = [("🔴" if r["level"] == "critical" else "🟡")
                 + f" {r['label']} ({r['key_masked']}): nur noch "
                 + f"{r.get('remaining', 0):.2f} $ Guthaben"
                 for r in fresh]
        from services import notifications
        await notifications.telegram_notify(
            db, telegram, "key_credits",
            "⚠️ *KEY-GUTHABEN NIEDRIG* (Paid-Modelle)\n" + "\n".join(lines)
            + f"\n\nSchwellen: Warnung < {WARN_USD:.2f} $, kritisch < {CRIT_USD:.2f} $. "
              "Guthaben aufladen: openrouter.ai/settings/credits")
    except Exception as e:
        logger.warning(f"key credits notify failed: {e}")


def snapshot() -> Dict:
    return dict(_snapshot)


async def run_loop():
    await asyncio.sleep(90)     # Boot abwarten
    while True:
        try:
            from core import state
            await check_once(state.db, state.telegram)
        except Exception as e:
            logger.error(f"key credits loop error: {e}")
        await asyncio.sleep(CHECK_EVERY_MIN * 60)


# ---------------- Copilot (06/2026): Anzeige + Sofort-Meldung bei 402 ----------------
PAYMENT_NOTIFY_COOLDOWN_H = 6


def view_for(prefix: str, snap: Optional[Dict] = None) -> Dict:
    """Ausschnitt des Snapshots für eine Key-Gruppe (rein): 'Copilot' oder 'OpenRouter'."""
    snap = snap or _snapshot
    order = {"critical": 3, "warning": 2, "ok": 1, "free": 0, "unknown": 0}
    keys = [dict(k, empty=(k.get("remaining") is not None and k.get("total_credits", 0) > 0
                           and float(k["remaining"]) <= 0.01))
            for k in snap.get("keys") or [] if str(k.get("label", "")).startswith(prefix)]
    worst = max((order.get(k["level"], 0) for k in keys), default=0)
    level = {3: "critical", 2: "warning"}.get(worst, "ok")
    return {"checked_at": snap.get("checked_at"), "keys": keys, "worst_level": level,
            "any_empty": any(k["empty"] for k in keys),
            "warn_below_usd": WARN_USD, "critical_below_usd": CRIT_USD}


async def notify_payment_error(db, telegram, source: str, model: str, fallback: Optional[str]) -> bool:
    """Sofort-Meldung, wenn ein Bezahl-Modell 402 liefert (Guthaben leer) – Dedupe je Quelle/Modell."""
    if db is None:
        return False
    key = f"402:{source}:{model}"
    try:
        state = await db.settings.find_one({"_id": STATE_ID}) or {}
        sent = state.get("sent") or {}
        now = time.time()
        if now - float(sent.get(key) or 0) < PAYMENT_NOTIFY_COOLDOWN_H * 3600:
            return False
        sent[key] = now
        await db.settings.update_one({"_id": STATE_ID}, {"$set": {"sent": sent}}, upsert=True)
        from services import notifications
        alt = f" Antwort kam stattdessen vom Free-Modell {fallback}." if fallback else \
            " Es konnte auch kein Free-Modell antworten."
        await notifications.telegram_notify(
            db, telegram, "key_credits",
            f"💳 *BEZAHL-GUTHABEN LEER* ({source})\nModell {model} lieferte 402 (Payment Required)."
            + alt + "\n\nGuthaben aufladen: openrouter.ai/settings/credits")
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning(f"402-Meldung fehlgeschlagen: {e}")
        return False
