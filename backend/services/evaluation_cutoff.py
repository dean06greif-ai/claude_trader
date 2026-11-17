"""Bewertungs-Stichtag (Phase A, 15.11.2026): alte gegen neue Regeln trennen.

Mit den Kostenregeln vom 15.11.2026 (Fee-Faktor 10, Prüfer-Modus, kein
Gegentrend-Sammeln, Liquidations-Korrektur) wurden die alten KI-Trades unter
Bedingungen gemacht, die heute nicht mehr gelten (zu enge Stops, freie
KI-Trades). Würden Lernlauf, Live-Tore und Bilanzen sie weiter mitzählen,
„lernte“ die KI aus Trades, die es so nicht mehr gibt – und Verbesserungen
blieben unsichtbar im Altbestand vergraben.

Der Stichtag schneidet deshalb NUR die Bewertung ab: Trades werden nicht
gelöscht, Auswertungen können weiter „alles“ zeigen. Konsumenten rufen
`apply(lookback_iso)` und bekommen den späteren der beiden Zeitpunkte.

Gespeichert in settings._id='evaluation_since' ({"since": ISO | None}).
`None` = Stichtag aus (alte Logik, nur Rückschau-Fenster).
Der Wert liegt zusätzlich im Prozess-Cache, damit auch synchrone Stellen
(ai_playbook._stats_match) ihn ohne DB-Zugriff nutzen können.
"""
import logging
from datetime import datetime, timezone
from typing import Dict, Optional

logger = logging.getLogger(__name__)

SETTINGS_ID = "evaluation_since"
# Boot-Marker der Kostenregel-Migration: genau ab dann galten die neuen Regeln.
RULES_MARKER = "cost_guard_v1_at"

_STATE: Dict = {"since": None, "loaded": False}


def _parse(iso: Optional[str]) -> Optional[datetime]:
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def normalize(iso: Optional[str]) -> Optional[str]:
    """ISO-Zeitpunkt säubern (UTC, mit Offset) – ungültig/leer -> None (rein)."""
    dt = _parse(iso)
    return dt.astimezone(timezone.utc).isoformat() if dt else None


def cached_since() -> Optional[str]:
    """Wirksamer Stichtag aus dem Prozess-Cache (None = aus / noch nicht geladen)."""
    return _STATE.get("since")


def set_cache(since: Optional[str]) -> None:
    _STATE["since"] = normalize(since)
    _STATE["loaded"] = True


def apply(lookback_iso: str, since: Optional[str] = None) -> str:
    """Späteren Zeitpunkt aus Rückschau-Fenster und Stichtag liefern (rein).
    `since=None` nutzt den Cache. Bei Formatfehlern bleibt das Fenster."""
    s = since if since is not None else cached_since()
    s = normalize(s)
    if not s:
        return lookback_iso
    lb = _parse(lookback_iso)
    sd = _parse(s)
    if lb is None or sd is None:
        return lookback_iso
    # Vergleich über datetime (String-Vergleich wäre bei gemischten Offsets falsch)
    return sd.isoformat() if sd > lb else lookback_iso


def is_after(ts_iso: Optional[str], since: Optional[str] = None) -> bool:
    """Liegt `ts_iso` am/nach dem Stichtag? Ohne Stichtag immer True (rein)."""
    s = normalize(since if since is not None else cached_since())
    if not s:
        return True
    ts = _parse(ts_iso)
    return bool(ts and ts >= _parse(s))


def default_since(marker_doc: Optional[Dict], now_iso: Optional[str] = None) -> str:
    """Vorgabe: Zeitpunkt, an dem die Kostenregeln in Kraft traten (Boot-Marker
    der Migration cost_guard_v1), sonst jetzt (rein)."""
    marker = normalize((marker_doc or {}).get(RULES_MARKER))
    return marker or normalize(now_iso) or datetime.now(timezone.utc).isoformat()


async def load(db) -> Optional[str]:
    """Stichtag aus der DB in den Cache laden (fail-safe)."""
    if db is None:
        return cached_since()
    try:
        doc = await db.settings.find_one({"_id": SETTINGS_ID}) or {}
        set_cache(doc.get("since"))
    except Exception as e:  # noqa: BLE001 – Bewertung läuft ohne Stichtag weiter
        logger.warning(f"Bewertungs-Stichtag nicht lesbar: {e}")
    return cached_since()


async def status(db) -> Dict:
    doc = {}
    if db is not None:
        try:
            doc = await db.settings.find_one({"_id": SETTINGS_ID}) or {}
        except Exception:  # noqa: BLE001
            doc = {}
    since = normalize(doc.get("since"))
    return {"since": since, "enabled": bool(since), "set_by": doc.get("set_by"),
            "updated_at": doc.get("updated_at"), "note": doc.get("note")}


async def set_since(db, since: Optional[str], by: str = "trader", note: str = "") -> Dict:
    """Stichtag setzen (ISO) oder aufheben (None/''). Zukunft ist nicht erlaubt."""
    val = normalize(since) if since else None
    if since and not val:
        raise ValueError("Ungültiger Zeitpunkt (ISO erwartet, z. B. 2026-11-15T21:00:00Z)")
    now = datetime.now(timezone.utc)
    if val and _parse(val) > now:
        raise ValueError("Der Stichtag darf nicht in der Zukunft liegen")
    doc = {"since": val, "set_by": by, "updated_at": now.isoformat(), "note": str(note or "")[:300]}
    await db.settings.update_one({"_id": SETTINGS_ID}, {"$set": doc}, upsert=True)
    set_cache(val)
    try:
        from services import lesson_impact as _li
        _li.lesson_impact.invalidate()
    except Exception:  # noqa: BLE001 – Cache läuft nach TTL ab
        pass
    return await status(db)


async def ensure_default(db) -> Optional[str]:
    """Einmalig (Boot-Migration): Stichtag auf den Start der neuen Regeln setzen,
    wenn noch keiner gespeichert ist. Ein vom Trader gesetzter/aufgehobener Wert
    bleibt unangetastet (das Dokument existiert dann bereits)."""
    doc = await db.settings.find_one({"_id": SETTINGS_ID})
    if doc is not None:
        set_cache(doc.get("since"))
        return cached_since()
    marker = await db.settings.find_one({"_id": "boot_migrations"}) or {}
    since = default_since(marker)
    await db.settings.update_one(
        {"_id": SETTINGS_ID},
        {"$set": {"since": since, "set_by": "boot_migration",
                  "updated_at": datetime.now(timezone.utc).isoformat(),
                  "note": "Start der Kostenregeln vom 15.11.2026 (Fee-Faktor 10, Prüfer-Modus)"}},
        upsert=True)
    set_cache(since)
    logger.info(f"Bewertungs-Stichtag gesetzt: {since}")
    return since
