"""Fehlermeldungen direkt aus dem Browser (Leitstand Phase B, 15.11.2026).

Die Website meldet eigene Abstürze (JS-Fehler, React-Fehlergrenze) und
fehlgeschlagene Server-Anfragen (Netzwerkfehler, HTTP 5xx). So findet der
Systemarzt Fehlerquellen, die kein Server-Check sieht – ohne teuren
„Website-Agenten“.

Schutz (Atlas-Free-Tier 512 MB, offene Website):
  * nur mit Admin-Token (sonst still ignoriert),
  * Felder gekürzt, URL ohne Query-String (keine Tokens/Parameter speichern),
  * gleiche Meldung binnen DEDUPE_S zählt hoch statt neu anzulegen,
  * Drossel je Minute und je Tag, Aufbewahrung 7 Tage.
"""
import hashlib
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

COLLECTION = "client_errors"
KEEP_DAYS = 7
DEDUPE_S = 3600            # gleiche Meldung innerhalb 1 h -> Zähler +1
MAX_PER_MIN = 30
MAX_PER_DAY = 500
KINDS = ("js", "promise", "react", "api", "network")
_MAX = {"message": 300, "component": 120, "path": 160, "stack": 900, "ua": 120, "method": 8}

_rate = {"minute": 0, "minute_n": 0, "day": "", "day_n": 0, "last_cleanup": 0.0}

_SECRET_RE = re.compile(r"(Bearer\s+)[A-Za-z0-9._\-]+|((?:token|key|secret|password)=)[^&\s]+",
                        re.IGNORECASE)


def _clip(v, n: int) -> str:
    s = str(v or "").strip()
    return s[:n]


def _scrub(s: str) -> str:
    """Tokens/Schlüssel aus Texten entfernen (rein)."""
    return _SECRET_RE.sub(lambda m: (m.group(1) or m.group(2) or "") + "***", s or "")


def _path_only(url: str) -> str:
    """Nur Pfad ohne Host/Query/Fragment (rein) – Parameter können Daten enthalten."""
    s = str(url or "")
    s = re.sub(r"^[a-z]+://[^/]+", "", s, flags=re.IGNORECASE)
    s = s.split("?", 1)[0].split("#", 1)[0]
    # IDs in Pfaden vereinheitlichen, damit gleiche Fehler zusammenfallen
    s = re.sub(r"/[0-9a-f]{8,}(?=/|$)", "/:id", s)
    s = re.sub(r"/[A-Z0-9]{2,}-\d{6,}(?=/|$)", "/:id", s)
    return s[:_MAX["path"]] or "/"


def sanitize(payload: Optional[Dict]) -> Optional[Dict]:
    """Eingabe der Website auf ein sicheres, kleines Dokument bringen (rein).
    None = unbrauchbar (leer)."""
    p = payload if isinstance(payload, dict) else {}
    kind = str(p.get("kind") or "js").lower()
    if kind not in KINDS:
        kind = "js"
    msg = _scrub(_clip(p.get("message"), _MAX["message"]))
    if not msg:
        return None
    try:
        status = int(p.get("status")) if p.get("status") not in (None, "") else None
    except (TypeError, ValueError):
        status = None
    stack_lines = [ln.strip() for ln in str(p.get("stack") or "").splitlines() if ln.strip()][:6]
    doc = {
        "kind": kind,
        "message": msg,
        "component": _scrub(_clip(p.get("component"), _MAX["component"])) or None,
        "path": _path_only(p.get("path") or p.get("url") or ""),
        "page": _path_only(p.get("page") or ""),
        "status": status,
        "method": _clip(p.get("method"), _MAX["method"]).upper() or None,
        "stack": _scrub("\n".join(stack_lines))[:_MAX["stack"]] or None,
        "ua": _clip(p.get("ua"), _MAX["ua"]) or None,
    }
    doc["fingerprint"] = fingerprint(doc)
    return doc


def fingerprint(doc: Dict) -> str:
    """Gleiche Fehlerquelle = gleicher Schlüssel (Zahlen im Text egal)."""
    msg = re.sub(r"\d+", "#", str(doc.get("message") or ""))[:160]
    base = "|".join(str(x or "") for x in (doc.get("kind"), doc.get("component"),
                                             doc.get("path"), doc.get("status"), msg))
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:16]


def rate_ok(now: Optional[float] = None) -> bool:
    """Drossel je Minute und Tag (Prozess-lokal, rein bis auf den Zähler)."""
    now = now or time.time()
    minute = int(now // 60)
    day = datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m-%d")
    if _rate["minute"] != minute:
        _rate["minute"], _rate["minute_n"] = minute, 0
    if _rate["day"] != day:
        _rate["day"], _rate["day_n"] = day, 0
    if _rate["minute_n"] >= MAX_PER_MIN or _rate["day_n"] >= MAX_PER_DAY:
        return False
    _rate["minute_n"] += 1
    _rate["day_n"] += 1
    return True


def reset_rate() -> None:
    _rate.update(minute=0, minute_n=0, day="", day_n=0, last_cleanup=0.0)


async def record(db, payload: Optional[Dict]) -> Dict:
    """Meldung speichern (dedupliziert). Rückgabe {"stored"| "counted"| "ignored"}."""
    doc = sanitize(payload)
    if doc is None:
        return {"status": "ignored", "reason": "leer"}
    if not rate_ok():
        return {"status": "ignored", "reason": "gedrosselt"}
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    recent = (now - timedelta(seconds=DEDUPE_S)).isoformat()
    res = await db[COLLECTION].update_one(
        {"fingerprint": doc["fingerprint"], "last_ts": {"$gte": recent}},
        {"$inc": {"count": 1}, "$set": {"last_ts": now_iso}})
    if getattr(res, "matched_count", 0):
        status = "counted"
    else:
        await db[COLLECTION].insert_one({**doc, "count": 1, "first_ts": now_iso, "last_ts": now_iso})
        status = "stored"
    if time.time() - _rate["last_cleanup"] > 3600:
        _rate["last_cleanup"] = time.time()
        try:
            await db[COLLECTION].delete_many(
                {"last_ts": {"$lt": (now - timedelta(days=KEEP_DAYS)).isoformat()}})
        except Exception:  # noqa: BLE001
            pass
    return {"status": status, "fingerprint": doc["fingerprint"]}


def group(rows: List[Dict]) -> List[Dict]:
    """Zusammenfassen je Fehlerquelle, häufigste zuerst (rein)."""
    by: Dict[str, Dict] = {}
    for r in rows or []:
        fp = r.get("fingerprint") or fingerprint(r)
        g = by.setdefault(fp, {"fingerprint": fp, "kind": r.get("kind"), "message": r.get("message"),
                               "component": r.get("component"), "path": r.get("path"),
                               "page": r.get("page"), "status": r.get("status"), "count": 0,
                               "first_ts": r.get("first_ts"), "last_ts": r.get("last_ts")})
        g["count"] += int(r.get("count") or 1)
        if str(r.get("last_ts") or "") > str(g.get("last_ts") or ""):
            g["last_ts"] = r.get("last_ts")
        if str(r.get("first_ts") or "9") < str(g.get("first_ts") or "9"):
            g["first_ts"] = r.get("first_ts")
    return sorted(by.values(), key=lambda g: (-g["count"], str(g.get("last_ts") or "")))


def describe(g: Dict) -> str:
    """Verständlicher Satz für den Leitstand (rein)."""
    where = g.get("component") or g.get("page") or "Website"
    if g.get("kind") in ("api", "network"):
        what = (f"Server-Anfrage {g.get('path')} " +
                (f"antwortet mit Fehler {g.get('status')}" if g.get("status") else "nicht erreichbar"))
    else:
        what = f"Absturz im Fenster „{where}“: {g.get('message')}"
    return f"{what} ({g.get('count')}× seit {str(g.get('first_ts') or '')[:16].replace('T', ' ')} UTC)"


async def summary(db, hours: int = 24, limit: int = 20) -> Dict:
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    rows = await db[COLLECTION].find({"last_ts": {"$gte": since}}, {"_id": 0}).to_list(2000)
    groups = group(rows)
    return {"hours": hours, "total": sum(g["count"] for g in groups),
            "sources": len(groups), "groups": groups[:limit]}
