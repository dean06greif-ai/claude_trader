"""KI-Prüfungen dort einsetzen, wo sie nachweislich helfen (Phase D, 15.11.2026).

Jeder Detektor-Treffer bekommt ohnehin einen Regel-Paper-Trade (Lernbasis).
Die zusätzliche LLM-Prüfung kostet einen KI-Aufruf. Die Veto-Bilanz
(services/veto_balance) misst je Setup, ob die KI-Auswahl besser ist als ihre
Absagen: Ø R der GENOMMENEN Signale gegen Ø R der VERWORFENEN (beides als
Regel-Trade gemessen, also gleiche Bedingungen).

Regel:
  * zu wenig Daten (je < MIN_EACH genommen/verworfen)  -> prüfen (messen)
  * Auswahl-Vorteil > +0,05 R                          -> immer prüfen
  * sonst (KI wählt nicht besser aus)                  -> nur jede EXPLORE_EVERY-te
    Prüfung (Stichprobe, damit der Wert weiter gemessen wird); die übrigen
    Signale laufen nur als Regel-Paper – das spart KI-Aufrufe, ohne die
    Datensammlung zu verringern.
Abschaltbar: `signal_review_by_value` (Standard an).
"""
import logging
import time
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

MIN_EACH = 10
EDGE_MIN_R = 0.05
EXPLORE_EVERY = 3
REFRESH_S = 1800

_cache: Dict = {"ts": 0.0, "setups": {}}
_counter: Dict[str, int] = {}
_stats: Dict = {"day": "", "reviewed": 0, "saved": 0, "by_setup": {}}


def decide(setup_bal: Optional[Dict], counter: int, explore_every: int = EXPLORE_EVERY) -> Tuple[bool, str]:
    """(prüfen?, Grund) – rein. counter = laufende Nummer des Treffers je Setup."""
    if not setup_bal:
        return True, "noch keine Veto-Bilanz – Prüfung misst den Wert"
    take = setup_bal.get("taken") or {}
    rej = setup_bal.get("rejected") or {}
    take_n, rej_n = int(take.get("n") or 0), int(rej.get("n") or 0)
    every = max(1, int(explore_every or EXPLORE_EVERY))
    # 18.11.2026: Nimmt die KI ein Setup (fast) nie, misst jede weitere Prüfung nur
    # dasselbe „nein“ – vorher wurde trotzdem JEDES Signal geprüft (taken < MIN_EACH).
    # Jetzt Stichprobe; nimmt die KI wieder Signale, gilt automatisch die Regel unten.
    if take_n < MIN_EACH and rej_n >= MIN_EACH and take_n * 20 <= rej_n:      # <= ~5 % genommen
        if counter % every == 0:
            return True, (f"Stichprobe (jede {every}. Prüfung) – KI nahm {take_n} von "
                          f"{take_n + rej_n} Signalen")
        return False, (f"KI nimmt dieses Setup fast nie ({take_n} von {take_n + rej_n}) – "
                       "nur Regel-Paper, KI-Aufruf gespart")
    if take_n < MIN_EACH or rej_n < MIN_EACH \
            or take.get("avg_r") is None or rej.get("avg_r") is None:
        return True, "Veto-Wert wird noch gemessen"
    sel = float(take["avg_r"]) - float(rej["avg_r"])
    if sel > EDGE_MIN_R:
        return True, f"KI-Auswahl besser als ihre Absagen ({sel:+.2f} R)"
    if counter % every == 0:
        return True, f"Stichprobe (jede {every}. Prüfung) – Auswahl-Wert {sel:+.2f} R wird weiter gemessen"
    return False, (f"KI-Auswahl ohne Mehrwert ({sel:+.2f} R: genommen {take['avg_r']:+.2f} R, "
                   f"verworfen {rej['avg_r']:+.2f} R) – nur Regel-Paper, KI-Aufruf gespart")


def _bump(key: str, setup: str):
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if _stats["day"] != day:
        _stats.update(day=day, reviewed=0, saved=0, by_setup={})
    _stats[key] += 1
    s = _stats["by_setup"].setdefault(setup, {"reviewed": 0, "saved": 0})
    s[key] += 1


def stats() -> Dict:
    return {"day": _stats["day"], "reviewed": _stats["reviewed"], "saved": _stats["saved"],
            "by_setup": dict(_stats["by_setup"]), "cache_age_s": int(time.time() - _cache["ts"])
            if _cache["ts"] else None}


async def refresh(db, force: bool = False) -> None:
    if not force and time.time() - _cache["ts"] < REFRESH_S:
        return
    from services import veto_balance
    try:
        bal = await veto_balance.load(db, days=30)
        _cache.update(ts=time.time(), setups=dict(bal.get("setups") or {}))
    except Exception as e:  # noqa: BLE001 – ohne Bilanz wird einfach geprüft
        logger.debug(f"Veto-Bilanz für Prüf-Zuteilung nicht ladbar: {e}")
        _cache["ts"] = time.time()


async def should_review(db, setup: str, cfg: Optional[Dict]) -> Tuple[bool, str]:
    """Für setup_trigger: soll dieser Treffer per LLM geprüft werden?"""
    cfg = cfg or {}
    if not cfg.get("signal_review_by_value", True):
        return True, "Zuteilung nach Veto-Wert aus"
    await refresh(db)
    n = _counter.get(setup, 0) + 1
    _counter[setup] = n
    ok, why = decide(_cache["setups"].get(setup), n,
                     int(cfg.get("signal_review_explore_every", EXPLORE_EVERY) or EXPLORE_EVERY))
    _bump("reviewed" if ok else "saved", setup)
    return ok, why
