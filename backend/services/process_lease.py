"""Prozessübergreifende Sperre (Lease) in MongoDB (17.11.2026).

Bei jedem Render-Deploy startet der neue Prozess, bevor der alte beendet ist. Am
17.11. antworteten danach rund zehn Minuten lang BEIDE Prozesse (abwechselnd, an
Speicher und Zählern unterscheidbar). Eine asyncio.Lock schützt nur innerhalb eines
Prozesses: Fiel in diese Überlappung ein neuer Portfolio-Tag, könnten beide Prozesse
gleichzeitig planen und dieselbe Position zweimal eröffnen.

Diese Sperre lässt Börsen-Schritte immer nur in EINEM Prozess laufen. Sie läuft nach
`ttl_s` ab, damit ein abgestürzter Prozess nichts dauerhaft blockiert.
"""
import contextlib
import logging
import os
import socket
import time
import uuid
from typing import Optional

logger = logging.getLogger(__name__)

OWNER = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:6]}"


async def acquire(db, lease_id: str, ttl_s: float = 600.0, owner: str = OWNER,
                  now: Optional[float] = None) -> bool:
    """Sperre holen oder (eigene) verlängern. False = ein anderer Prozess hält sie."""
    now = time.time() if now is None else float(now)
    until = now + float(ttl_s)
    coll = db.settings
    res = await coll.update_one(
        {"_id": lease_id, "$or": [{"until": {"$lt": now}}, {"by": owner}]},
        {"$set": {"until": until, "by": owner, "at": now}})
    if getattr(res, "matched_count", 0):
        return True
    if await coll.find_one({"_id": lease_id}, {"_id": 1}):
        return False                                   # gültige fremde Sperre
    try:
        await coll.insert_one({"_id": lease_id, "until": until, "by": owner, "at": now})
        return True
    except Exception:  # noqa: BLE001 – DuplicateKeyError: anderer Prozess war schneller
        return False


async def release(db, lease_id: str, owner: str = OWNER) -> None:
    """Eigene Sperre freigeben (fremde bleibt unberührt)."""
    await db.settings.update_one({"_id": lease_id, "by": owner}, {"$set": {"until": 0}})


@contextlib.asynccontextmanager
async def hold(db, lease_id: str, ttl_s: float = 600.0, owner: str = OWNER):
    """`async with hold(db, id) as ok:` – ok False: nichts tun (anderer Prozess läuft)."""
    try:
        ok = await acquire(db, lease_id, ttl_s=ttl_s, owner=owner)
    except Exception as e:  # noqa: BLE001 – ohne Datenbank lieber nicht an der Börse handeln
        logger.warning(f"Sperre {lease_id} nicht prüfbar: {e}")
        ok = False
    try:
        yield ok
    finally:
        if ok:
            try:
                await release(db, lease_id, owner=owner)
            except Exception as e:  # noqa: BLE001 – läuft sonst nach ttl_s ab
                logger.warning(f"Sperre {lease_id} nicht freigegeben: {e}")
