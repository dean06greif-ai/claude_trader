"""Nacht-Forschung (Phase C, 15.11.2026): jede Nacht EINE Endlossuche mit den
empfohlenen Einstellungen – rotierend über Anlageklasse und Timeframe.

Warum so: Ein echter Vorteil lässt sich nur mit genug Test-Trades nachweisen
(viele Assets einer Klasse, 15m/1h, 180–365 Tage, 2–3 Regeln). Von Hand lief
die Suche selten und mit wechselnden Einstellungen; jetzt arbeitet sie jede
Nacht systematisch eine Liste ab. Die Suche selbst prüft ehrlich (Signifikanz
mit Mindest-Hürde, Tresor-Daten) – ein Champion ist danach erst ein Kandidat
für den Vorwärtstest (services/research_pipeline), nie automatisch live.

Läuft über die bestehende Nacht-Serie (job_series, Art „optimizer“, mode
„explore“) auf dem lokalen Worker – nur, wenn er verbunden und aktuell ist
(ältere Pakete rechnen mit der alten Prüfung, siehe local_exec).
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

SETTINGS_ID = "night_research"
BERLIN = ZoneInfo("Europe/Berlin")
LABEL_PREFIX = "Nacht-Forschung"
DEFAULTS = {"enabled": True, "start_hour": 23, "end_hour": 5, "max_minutes": 300,
            "max_assets": 12}

TREND_INDICATORS = ["ema_slow", "ema_fast", "macd_hist", "macd", "donchian_high", "supertrend_dir",
                    "ema_slope_pct", "roc", "adx", "plus_di", "dist_ema200_pct", "channel_slope_pct",
                    "market_structure", "bos_up", "aroon_up", "chop", "atr_pct", "price_change_pct",
                    "keltner_upper", "bb_upper"]
NIGHT_OBJECTIVE = "t_r"      # dieselbe Größe, die die Signifikanz-Prüfung verlangt
NIGHT_MIN_TRADES = 60        # Kombis mit weniger Trades können die Hürde nie nehmen

# Rotation: genug Assets je Lauf, Zeitebenen mit Kosten-Spielraum (Fee-Faktor 10)
ROTATION: Tuple[Dict, ...] = (
    # F3 (17.11.2026): Trendfolge auf längerer Sicht ist die einzige Vorteils-Quelle
    # mit Beleg auf echten Daten (26 Coins seit 2018, siehe docs/UMSETZUNG_ZIEL_2026-11-17.md):
    # je länger der Ausbruchs-Horizont, desto größer der Vorteil je Trade. Dieser
    # Slot sucht deshalb nur mit Trend-Indikatoren, mehr Coins und längerer Historie.
    {"key": "crypto_1h_trend", "label": "Krypto 1h Trend", "classes": ("crypto",), "timeframe": "1h",
     "days": 540, "max_assets": 20, "indicators": TREND_INDICATORS,
     "optimize": {"tpsl": True, "trail": True}},
    # 17.11.2026 (Abend): Rotation auf Krypto mit Kosten-Spielraum gekürzt. Forex 1h und
    # Rohstoffe/Indizes 1h fallen raus: „Live nur Krypto“ ist an, ein Fund dort könnte nie
    # live gehen (und alle Nicht-Krypto-Trades lagen bei −0,45 bis −0,77 R). Krypto 5m fällt
    # raus: Gebühren je Risiko zu hoch. Jede Nacht ist damit ein Krypto-Lauf, Trend jede 3.
    {"key": "crypto_1h", "label": "Krypto 1h", "classes": ("crypto",), "timeframe": "1h", "days": 365},
    {"key": "crypto_15m", "label": "Krypto 15m", "classes": ("crypto",), "timeframe": "15m", "days": 180},
)


def settings(doc: Optional[Dict]) -> Dict:
    doc = doc or {}
    out = {k: doc.get(k, v) for k, v in DEFAULTS.items()}
    for k in ("start_hour", "end_hour"):
        try:
            out[k] = max(0, min(23, int(out[k])))
        except (TypeError, ValueError):
            out[k] = DEFAULTS[k]
    try:
        out["max_minutes"] = max(30, min(600, int(out["max_minutes"])))
    except (TypeError, ValueError):
        out["max_minutes"] = DEFAULTS["max_minutes"]
    out["enabled"] = bool(out["enabled"])
    return out


def in_window(now_local: datetime, start_hour: int, end_hour: int) -> bool:
    """Nachtfenster über Mitternacht (z. B. 23–5 Uhr) – rein."""
    h = now_local.hour
    if start_hour <= end_hour:
        return start_hour <= h < end_hour
    return h >= start_hour or h < end_hour


def night_key(now_local: datetime, end_hour: int) -> str:
    """Eine Nacht = Datum des Abends (nach Mitternacht zählt der Vortag) – rein."""
    d = now_local.date()
    if now_local.hour < end_hour:
        d = d - timedelta(days=1)
    return d.isoformat()


def symbols_for(classes, max_assets: int, allowed: Optional[List[str]] = None) -> List[str]:
    from services import setup_asset_class as ac
    if allowed is None:
        from core.config import BACKTEST_SYMBOLS
        allowed = list(BACKTEST_SYMBOLS)
    out: List[str] = []
    for c in classes:
        out += [s for s in ac.symbols_of(c) if s in allowed and s not in out]
    return out[:max_assets]


def build_body(slot: Dict, symbols: List[str], max_minutes: int) -> Dict:
    """Request wie der Knopf „Empfohlene Einstellungen“ im Optimizer (rein)."""
    return {
        "mode": "explore", "symbols": symbols, "days": int(slot["days"]),
        "timeframe": slot["timeframe"], "objective": NIGHT_OBJECTIVE,
        "min_trades": NIGHT_MIN_TRADES, "max_rules": 3,
        # Standard: alle Indikatoren (Volumen-Filter für FX greift im Optimizer)
        "indicators": list(slot["indicators"]) if slot.get("indicators") else None,
        "optimize": dict(slot.get("optimize") or {"tpsl": True}), "include_trade_params": True,
        "walk_forward": {"enabled": True, "train_pct": 70, "mode": "single"},
        "explore": {"target_champions": 5, "max_minutes": int(max_minutes)},
        "execution": "local",
        "night_research": slot["key"],
    }


def next_slot(state: Dict) -> Dict:
    """Nächster Rotations-Eintrag nach dem zuletzt geplanten (rein)."""
    keys = [s["key"] for s in ROTATION]
    last = state.get("last_slot")
    idx = (keys.index(last) + 1) % len(keys) if last in keys else 0
    return ROTATION[idx]


def plan_decision(cfg: Dict, state: Dict, now_utc: datetime, worker_ok: bool,
                  worker_why: str, busy: bool) -> Tuple[bool, str]:
    """Soll JETZT die Nacht-Suche eingeplant werden? (rein) -> (ja, Grund)."""
    if not cfg.get("enabled"):
        return False, "Nacht-Forschung ist ausgeschaltet"
    local = now_utc.astimezone(BERLIN)
    if not in_window(local, cfg["start_hour"], cfg["end_hour"]):
        return False, f"außerhalb des Nachtfensters ({cfg['start_hour']}–{cfg['end_hour']} Uhr)"
    if state.get("last_night") == night_key(local, cfg["end_hour"]):
        return False, "diese Nacht schon eingeplant"
    if not worker_ok:
        return False, worker_why
    if busy:
        return False, "ein anderer Optimizer-/Serien-Job läuft"
    return True, "bereit"


def worker_status() -> Tuple[bool, str]:
    from services import local_exec
    if not local_exec.worker_online():
        return False, "lokaler Worker nicht verbunden"
    if not local_exec.worker_supports_validation():
        return False, f"Worker veraltet (mind. {local_exec.OPTIMIZER_MIN_WORKER_STR})"
    if not local_exec.worker_supports_explore():
        return False, "Worker kennt die Endlossuche nicht"
    return True, "ok"


async def get_state(db) -> Dict:
    doc = await db.settings.find_one({"_id": SETTINGS_ID}) or {}
    return {"config": settings(doc), "last_night": doc.get("last_night"), "last_slot": doc.get("last_slot"),
            "last_item_id": doc.get("last_item_id"), "last_reason": doc.get("last_reason"),
            "history": list(doc.get("history") or [])[-14:], "next": next_slot(doc)["label"]}


async def update_config(db, updates: Dict) -> Dict:
    cur = await db.settings.find_one({"_id": SETTINGS_ID}) or {}
    cfg = settings({**cur, **{k: v for k, v in (updates or {}).items() if k in DEFAULTS}})
    await db.settings.update_one({"_id": SETTINGS_ID}, {"$set": cfg}, upsert=True)
    return await get_state(db)


async def _busy(db) -> bool:
    from services import job_series
    from services import optimizer as opt
    if any(j.get("status") == "running" for j in opt.JOBS.values()):
        return True
    if job_series.any_job_running():
        return True
    n = await db.job_series.count_documents({"status": {"$in": ["queued", "running"]},
                                            "label": {"$regex": f"^{LABEL_PREFIX}"}})
    return n > 0


async def tick(db, now_utc: Optional[datetime] = None, force: bool = False) -> Dict:
    """Einmal prüfen und ggf. die Suche in die Nacht-Serie einreihen."""
    from services import job_series
    now_utc = now_utc or datetime.now(timezone.utc)
    doc = await db.settings.find_one({"_id": SETTINGS_ID}) or {}
    cfg = settings(doc)
    w_ok, w_why = worker_status()
    busy = await _busy(db)
    if force:   # Knopf im Leitstand: sofort einplanen (Worker-/Busy-Prüfung bleibt)
        ok, why = ((False, w_why) if not w_ok else
                   (False, "ein anderer Optimizer-/Serien-Job läuft") if busy else (True, "manuell"))
    else:
        ok, why = plan_decision(cfg, doc, now_utc, w_ok, w_why, busy)
    if not ok:
        if why != doc.get("last_reason"):
            await db.settings.update_one({"_id": SETTINGS_ID}, {"$set": {"last_reason": why}}, upsert=True)
        return {"planned": False, "reason": why}
    slot = next_slot(doc)
    syms = symbols_for(slot["classes"], max(int(cfg["max_assets"]), int(slot.get("max_assets") or 0)))
    if len(syms) < 2:
        return {"planned": False, "reason": f"zu wenige Assets für {slot['label']}"}
    body = build_body(slot, syms, cfg["max_minutes"])
    label = f"{LABEL_PREFIX}: {slot['label']} ({len(syms)} Assets, {slot['days']} Tage)"
    item = await job_series.add_item(db, "optimizer", body, label=label)
    local = now_utc.astimezone(BERLIN)
    entry = {"night": night_key(local, cfg["end_hour"]), "slot": slot["key"], "label": label,
             "item_id": item["id"], "planned_at": now_utc.isoformat()}
    hist = (list(doc.get("history") or []) + [entry])[-30:]
    await db.settings.update_one(
        {"_id": SETTINGS_ID},
        {"$set": {"last_night": entry["night"], "last_slot": slot["key"], "last_item_id": item["id"],
                  "last_reason": "eingeplant", "history": hist}}, upsert=True)
    logger.info(f"Nacht-Forschung eingeplant: {label}")
    return {"planned": True, "item": item, "label": label}


async def last_runs(db, limit: int = 7) -> List[Dict]:
    """Letzte Nacht-Suchen mit Ergebnis-Kurzfassung (für den Leitstand)."""
    rows = await db.job_series.find({"label": {"$regex": f"^{LABEL_PREFIX}"}}, {"_id": 0}) \
        .sort("created_at", -1).limit(limit).to_list(limit)
    return [{"label": r.get("label"), "status": r.get("status"), "created_at": r.get("created_at"),
             "finished_at": r.get("finished_at"), "summary": r.get("summary"),
             "error": r.get("error"), "job_id": r.get("job_id")} for r in rows]
