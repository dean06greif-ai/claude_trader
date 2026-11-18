"""Mehrere Nutzer und Worker gleichzeitig (18.11.2026).

Vorher zeigte /api/{optimizer,backtest}/active immer den NEUESTEN laufenden Job – bei
zwei Nutzern also oft den Lauf des anderen, und „Abbrechen“/„Notfall-Reset“ trafen ihn
mit. Jetzt: Die Website merkt sich im Browser, welche Läufe sie selbst gestartet hat
(`mine`), und der Notfall-Reset trifft nur den eigenen bzw. wirklich hängende Läufe.
"""
from typing import Callable, Dict, Iterable, List, Optional, Tuple


def running(jobs: Dict[str, Dict]) -> List[Dict]:
    return sorted([j for j in (jobs or {}).values() if j.get("status") == "running"],
                  key=lambda j: str(j.get("created_at") or ""))


def parse_mine(raw: Optional[str]) -> List[str]:
    return [x.strip() for x in str(raw or "").split(",") if x.strip()][:50]


def pick_active(jobs: Dict[str, Dict], mine: Iterable[str]) -> Tuple[Optional[Dict], List[Dict]]:
    """(anzuzeigender Lauf, andere laufende Läufe) – eigene Läufe zuerst (rein)."""
    run = running(jobs)
    own_ids = {m for m in (mine or []) if m}
    own = [j for j in run if j.get("id") in own_ids]
    active = (own or run or [None])[-1]
    return active, [j for j in run if j is not active]


def reset_targets(jobs: Dict[str, Dict], job_id: Optional[str],
                  is_stale: Callable[[Dict], bool]) -> List[Dict]:
    """Mit job_id nur dieser Lauf; ohne nur hängende Läufe (rein)."""
    if job_id:
        j = (jobs or {}).get(job_id)
        return [j] if j and j.get("status") == "running" else []
    return [j for j in running(jobs) if is_stale(j)]


def other_summary(j: Dict) -> Dict:
    p = j.get("params") or {}
    return {"id": j.get("id"), "phase": j.get("phase"), "progress": j.get("progress"),
            "strategy_id": p.get("strategy_id") or (p.get("strategy_ids") or [None])[0],
            "execution": j.get("execution"), "worker_target": j.get("worker_target")}
