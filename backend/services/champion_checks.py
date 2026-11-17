"""Ehrlichere Champion-Prüfung der Endlossuche (F1, 16.11.2026).

Nach dem Pool-Fix prüft die Suche Test und Tresor auf eigenen Daten. Offen
blieben vier Lücken (docs/ANALYSE_WEG_ZUM_ZIEL_2026-11-16.md, Abschnitt 2):

  1. Training durfte in R negativ sein (Gewinn nur über Positionsgrößen).
  2. Der Tresor verlangte nur „Gewinn > 0“ mit ~4 Trades – ein Münzwurf.
  3. Jeder neue Lauf auf denselben Daten bekam eine frische Hürde, obwohl die
     Testdaten schon hunderte Male benutzt wurden (Versuchs-Konto).
  4. Kein Blick auf einen ANDEREN Zeitraum (Rückwärtstest auf den Tagen vor
     dem Suchfenster – Daten, die Suche, Test und Tresor nie gesehen haben).

Dieses Modul enthält die reinen Urteile dazu; `deep_explore.run` ruft sie auf.
Unten: das Versuchs-Konto (klein, in `settings._id="explore_trials"`).
"""
import math
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

VAULT_MIN_TRADES = 10       # darunter ist ein Tresor-Ergebnis Zufall
BACK_MIN_TRADES = 20        # darunter gilt der Rückwärtstest als „nicht prüfbar“
TRIAL_WINDOW_DAYS = 30      # so lange zählen frühere Prüfungen auf denselben Daten
TRIAL_CAP = 100000          # Deckel fürs Konto (Hürde wächst nur noch logarithmisch)
SETTINGS_ID = "explore_trials"
LB_Z = 1.64


def r_summary(m: Optional[Dict]) -> Dict:
    """Trades, Ø R, t-Wert und Grenzen aus den additiven R-Summen (rein)."""
    m = m or {}
    n = int(m.get("r_n") or 0)
    if n <= 0 or m.get("r_sum") is None:
        return {"trades": int(m.get("trades") or 0), "known": False,
                "avg_r": None, "t": None, "lb": None, "ub": None}
    mean = float(m.get("r_sum") or 0.0) / n
    if n > 1 and m.get("r_sq") is not None:
        var = max((float(m.get("r_sq") or 0.0) - n * mean * mean) / (n - 1), 0.0)
        se = math.sqrt(var / n)
    else:
        se = 0.0
    t = mean / se if se > 1e-12 else 0.0
    return {"trades": n, "known": True, "avg_r": round(mean, 4), "t": round(t, 2),
            "lb": round(mean - LB_Z * se, 4) if se else None,
            "ub": round(mean + LB_Z * se, 4) if se else None}


def train_ok(m: Optional[Dict]) -> Tuple[bool, str]:
    """Training muss auch in R im Plus sein. Ohne R-Kennzahlen (Alt-Ergebnis)
    entscheidet wie bisher der Gewinn."""
    s = r_summary(m)
    if not s["known"]:
        return float((m or {}).get("pnl") or 0) > 0, "Training ohne R-Kennzahlen"
    if s["avg_r"] > 0:
        return True, ""
    return False, (f"Training in R negativ (Ø {s['avg_r']:+.2f} R) – der Gewinn kam nur "
                   "aus den Positionsgrößen")


def vault_ok(m: Optional[Dict], min_trades: int) -> Tuple[bool, str]:
    """Tresor: genug Trades UND Ø R > 0 (vorher: Gewinn > 0 mit ~4 Trades)."""
    need = max(int(min_trades or 0), VAULT_MIN_TRADES)
    s = r_summary(m)
    n = s["trades"] if s["known"] else int((m or {}).get("trades") or 0)
    if n < need:
        return False, f"Tresor: nur {n} Trades (mind. {need})"
    if s["known"]:
        if s["avg_r"] > 0:
            return True, ""
        return False, f"Tresor: Ø {s['avg_r']:+.2f} R (kein Vorteil auf den jüngsten Daten)"
    if float((m or {}).get("pnl") or 0) > 0:
        return True, ""
    return False, "Tresor: Verlust auf den jüngsten Daten"


def back_verdict(m: Optional[Dict], days: float = 0.0,
                 min_trades: int = BACK_MIN_TRADES) -> Dict:
    """Urteil des Rückwärtstests (Daten VOR dem Suchfenster, rein).

    bestanden      genug Trades und Ø R > 0
    durchgefallen  genug Trades und Ø R ≤ 0
    nicht_pruefbar zu wenige Trades oder keine älteren Daten (kein Ausschluss,
                   aber sichtbar – der Vorwärtstest muss es dann zeigen)"""
    s = r_summary(m)
    out = {**s, "days": round(float(days or 0.0), 1), "min_trades": int(min_trades)}
    if m is None:
        return {**out, "state": "nicht_pruefbar", "passed": True,
                "reason": "keine älteren Daten geladen"}
    if not s["known"] or s["trades"] < int(min_trades):
        return {**out, "state": "nicht_pruefbar", "passed": True,
                "reason": f"nur {s['trades']} Trades im älteren Zeitraum (mind. {int(min_trades)})"}
    if s["avg_r"] > 0:
        return {**out, "state": "bestanden", "passed": True,
                "reason": f"Ø {s['avg_r']:+.2f} R auf {out['days']:.0f} älteren Tagen"}
    return {**out, "state": "durchgefallen", "passed": False,
            "reason": (f"Rückwärtstest: Ø {s['avg_r']:+.2f} R auf {out['days']:.0f} älteren Tagen – "
                       "der Vorteil gilt nur im Suchzeitraum")}


def side_split(long_m: Optional[Dict], short_m: Optional[Dict]) -> Dict:
    """Long- und Short-Seite getrennt (rein). Hinweis, wenn der Vorteil nur an
    einer Seite hängt – dann kann es die bloße Marktrichtung gewesen sein."""
    lo, sh = r_summary(long_m), r_summary(short_m)
    note = ""
    if lo["known"] and sh["known"] and lo["trades"] >= 10 and sh["trades"] >= 10:
        if lo["avg_r"] > 0 >= sh["avg_r"]:
            note = "Vorteil nur auf der Long-Seite – kann Marktrichtung sein"
        elif sh["avg_r"] > 0 >= lo["avg_r"]:
            note = "Vorteil nur auf der Short-Seite – kann Marktrichtung sein"
    elif (lo["known"] and lo["trades"] >= 10) != (sh["known"] and sh["trades"] >= 10):
        note = "fast nur eine Richtung gehandelt – Marktrichtung nicht auszuschließen"
    return {"long": lo, "short": sh, "one_sided": bool(note), "note": note}


def combined_unseen(parts: List[Optional[Dict]]) -> Dict:
    """Alle nie zur Auswahl benutzten Abschnitte zusammen (Tresor + Rückwärtstest)."""
    agg = {"r_n": 0, "r_sum": 0.0, "r_sq": 0.0}
    for m in parts:
        if not m or not m.get("r_n"):
            continue
        agg["r_n"] += int(m.get("r_n") or 0)
        agg["r_sum"] += float(m.get("r_sum") or 0.0)
        agg["r_sq"] += float(m.get("r_sq") or 0.0)
    return r_summary(agg)


# ---------------------------------------------------------------------------
# Versuchs-Konto: wie oft wurden dieselben Testdaten schon benutzt?
# ---------------------------------------------------------------------------
def trial_key(symbols: Optional[List[str]], timeframe: Optional[str]) -> str:
    """Schlüssel je Anlageklasse(n) + Zeitebene. Läufe derselben Klasse und
    Zeitebene prüfen weitgehend dieselben Marktdaten (Krypto bewegt sich
    gemeinsam) – sie teilen sich deshalb ein Konto."""
    try:
        from services.setup_asset_class import asset_class_of
        classes = sorted({asset_class_of(s) for s in (symbols or []) if s})
    except Exception:  # noqa: BLE001 – z. B. im Worker ohne das Modul
        classes = []
    return f"{'+'.join(classes) or 'alle'}|{timeframe or '?'}".replace(".", "_").replace("$", "_")


def _parse(iso) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def prune(rows: Optional[List[Dict]], now: Optional[datetime] = None,
          window_days: int = TRIAL_WINDOW_DAYS) -> List[Dict]:
    now = now or datetime.now(timezone.utc)
    lim = now - timedelta(days=window_days)
    out = []
    for r in rows or []:
        at = _parse((r or {}).get("at"))
        if at and at >= lim and int((r or {}).get("n") or 0) > 0:
            out.append({"at": at.isoformat(), "n": int(r["n"])})
    return out[-200:]


def prior_from_doc(doc: Optional[Dict], key: str, now: Optional[datetime] = None) -> int:
    rows = prune(((doc or {}).get("keys") or {}).get(key), now)
    return min(sum(r["n"] for r in rows), TRIAL_CAP)


async def prior_trials(db, symbols, timeframe) -> int:
    """Bereits verbrauchte Prüfungen auf diesen Daten (letzte 30 Tage)."""
    if db is None:
        return 0
    try:
        doc = await db.settings.find_one({"_id": SETTINGS_ID}) or {}
    except Exception:  # noqa: BLE001
        return 0
    return prior_from_doc(doc, trial_key(symbols, timeframe))


async def record_trials(db, result: Optional[Dict]) -> int:
    """Prüfungen eines fertigen Laufs aufs Konto buchen. Rückgabe: gebuchte Zahl."""
    if db is None:
        return 0
    rep = (result or {}).get("explore_report") or {}
    n = int(rep.get("wf_checked") or 0)
    if n <= 0:
        return 0
    key = trial_key((result or {}).get("symbols"), (result or {}).get("timeframe"))
    doc = await db.settings.find_one({"_id": SETTINGS_ID}) or {}
    keys = dict(doc.get("keys") or {})
    now = datetime.now(timezone.utc)
    keys[key] = prune(list(keys.get(key) or []) + [{"at": now.isoformat(), "n": n}], now)
    await db.settings.update_one({"_id": SETTINGS_ID},
                                 {"$set": {"keys": keys, "updated_at": now.isoformat()}},
                                 upsert=True)
    return n
