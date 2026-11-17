"""Einmalige Bereinigung des Lektions-Bestands (Trade-Analyse 15.11.2026,
Freigabe des Traders: "zusammenfassen, verbessern oder entfernen – keine
Dopplungen, keine Widersprüche, nur was wirklich etwas bringt").

Bestand vorher: 32 KI-Lektionen. Probleme (Belege aus 783 KI-Trades):
- 8 Regime-Lektionen mit Margen-Kürzungen + 2-3 Bestätigungen aus 5-24 Trades
  (im Risiko-Modus ist die Marge wirkungslos; zusammen erzwingen sie HOLD)
- 3 Lektionen sperren/schließen regelbasierte Trades ohne LLM-Analyse
  = die Datensammlung (Lernbasis)
- Detail-Texte waren Änderungs-Anweisungen ("Ersetze …", "Streichung …")
- 10m-/30m-Kerzen, die die KI nie bekommt
- Duplikate (Bestätigungskerze ×3, Re-Entry ×3, OIL ×3)
- Range-Fade-Short-Lektion widerspricht den Daten (range_fade Ø −0,56 R, n=42)

Ergebnis: 6 zusammengeführte Lektionen mit Belegen + 2 unverändert
(Break-Even, News-Defensive). Unbekannte (neuere) Lektionen und vom Trader
gesperrte bleiben unangetastet. Der alte Stand liegt in ai_lessons_history
(Wiederherstellung über die Lektionen-Historie im UI).
"""
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Tuple

VALID_DAYS = 45   # danach Re-Validierung durch den Lernlauf (sonst zurückgestellt)

# Titel-Präfixe (klein, die ersten Zeichen reichen) -> Ziel
REMOVE = (
    "in trend_up_volatil konsequent halbe marge",
    "in breakout_volatil nur mit 25% marge",
    "in drift_volatil nur mit 10% marge",
    "hedge-trades nicht als ersatz",
    "session-timezone-resistenz prüfen",
    "range-fade-shorts an tages-highs",
    "range_volatil und drift_volatil regime",
    "chance/risiko mindestverhältnis",
    "in range_ruhig nur an range-grenzen",
    "in trend_down_ruhig nur mit halber marge",
    "in trend_up_ruhig nur mit halber marge",
    "regelbasierte trades ohne llm-analyse",
    "divergence-setups ohne llm",
    "in breakout_ruhig keine trades",
    "mean_reversion-longs ohne llm-analyse",
    "trades ohne bestätigung nicht stundenlang halten",
)

MERGE: List[Tuple[Tuple[str, ...], Dict]] = [
    (("kein handel gegen den höheren trend", "or-low-retest-shorts ohne bestätigten"),
     {"title": "Mit dem Tagestrend handeln, nicht dagegen",
      "context": "Alle Regime, wenn Tages-Bias oder 1h-Trend klar steigt bzw. fällt",
      "detail": ("LONG nicht, wenn der Tages-Bias 'down' ist oder der 1h-Trend klar fällt; "
                 "SHORT nicht gegen 'up'. Gegen den Trend nur mit benennbarem Anlass "
                 "(bestätigte Abweisung an einem Key-Level, harte News). Beleg: LONG gegen "
                 "Tages-Bias 'down' Ø −0,49 R (220 Trades); Trades, die den Edge-Filter "
                 "bestehen, Ø +0,11 R (72) gegenüber −0,38 R (711).")}),
    (("bestätigungskerze vor einstieg abwarten", "trendfollow-einstiege ohne retest"),
     {"title": "Einstieg erst nach bestätigender Kerze",
      "context": "Alle Regime, Einstieg auf Ablehnung, Trend- oder CVD-Signal",
      "detail": ("Vor dem Einstieg eine abgeschlossene 5m-Kerze in Handelsrichtung abwarten "
                 "(bei 15m-Setups eine 15m-Kerze); bei Trend-Einstiegen zusätzlich Retest "
                 "oder Folgekerze. Beleg: ausgestoppte Trades erreichten im Median nur "
                 "+0,17 R, ein Viertel lief sofort dagegen (378 Stop-Outs).")}),
    (("identische re-entries ohne neue bestätigung", "nach 3 aufeinanderfolgenden verlusten",
      "sofort-stop-outs als trade-invalidierung", "cooldown pro coin auf 120 minuten"),
     {"title": "Nach Stop-Out und Verlustserie pausieren",
      "context": "Alle Regime, nach einem Stop-Out bzw. mehreren Verlusten auf einem Coin",
      "detail": ("Nach einem Stop-Out keinen identischen Re-Entry: erst eine neue "
                 "15m-Struktur (neues Hoch/Tief oder Retest) abwarten. Nach 3 Verlusten in "
                 "Folge auf einem Coin diesen 24 Stunden nicht handeln.")}),
    (("sl-distanz in niedrigvolatilitäts-phasen", "sl-abstand in volatilen trend-regimen"),
     {"title": "Stop an die Struktur und weit genug für die Kosten",
      "context": "Alle Regime, beim Setzen des Stop-Loss",
      "detail": ("SL hinter die nächste Struktur (Swing, Range-Grenze) legen und so weit, "
                 "dass die Roundtrip-Gebühr höchstens 10 % des Risikos ist (Krypto-Taker: "
                 "SL ab etwa 1,2 %); in volatilen Phasen mindestens 3× ATR(14) des "
                 "Einstiegs-Timeframes. Geht das nicht, lieber nicht handeln. Beleg: "
                 "Gebühren 0,2–0,3 R Ø −0,48 R (354 Trades), unter 0,1 R Ø −0,05 R (125).")}),
    (("oil-longs in niedrigvolatilität meiden", "oil nur in aktiven rohstoff-sessions",
      "oil-shorts in niedrigvolatilität"),
     {"title": "Rohstoffe nur mit Trend und weitem Stop",
      "context": "Gold, Silber, Öl",
      "detail": ("Rohstoff-Trades nur in Richtung des Tages-Bias, während London- oder "
                 "US-Session und mit Stop ab 3× ATR(14); Gegentrend-Fades meiden. Beleg: "
                 "Gold Ø −0,77 R (37 Trades), Silber −0,60 R (48), Öl −0,45 R (72).")}),
]


def _match(title: str, prefixes) -> bool:
    t = str(title or "").strip().lower()
    return any(t.startswith(p) for p in prefixes)


def plan(lessons: List[Dict], now: datetime = None) -> Tuple[List[Dict], Dict]:
    """Neuer Bestand + Protokoll (rein). Gesperrte Lektionen und nicht
    erkannte Titel bleiben unverändert."""
    now = now or datetime.now(timezone.utc)
    valid_until = (now + timedelta(days=VALID_DAYS)).isoformat()
    keep, removed, merged_from = [], [], {}
    hit_groups = set()
    for l in lessons or []:
        title = l.get("title", "")
        if l.get("locked"):
            keep.append(l)
            continue
        if _match(title, REMOVE):
            removed.append(title)
            continue
        gi = next((i for i, (pref, _) in enumerate(MERGE) if _match(title, pref)), None)
        if gi is not None:
            hit_groups.add(gi)
            merged_from.setdefault(MERGE[gi][1]["title"], []).append(title)
            continue
        keep.append(l)
    existing = {str(l.get("title", "")).strip().lower() for l in keep}
    added = []
    for gi in sorted(hit_groups):
        new = dict(MERGE[gi][1])
        if new["title"].strip().lower() in existing:
            continue
        new.update({"origin": "ai", "locked": False, "weight": 3, "weight_label": "hoch",
                    "confirmations": 3, "valid_until": valid_until,
                    "updated_at": now.isoformat(), "model": "bereinigung_1511"})
        added.append(new)
    log = {"removed": removed, "merged": merged_from,
           "added": [a["title"] for a in added], "kept": [l.get("title") for l in keep]}
    return keep + added, log


# ---------------------------------------------------------------------------
# Phase A (15.11.2026): Lektions-KANDIDATEN nachprüfen statt löschen.
# Kandidaten aus der Zeit vor dem Bewertungs-Stichtag wurden an Trades unter
# alten Regeln wiedererkannt. Sie bleiben erhalten, brauchen aber eine frische
# Bestätigung (Bestätigungen auf 1 gedeckelt). Kandidaten mit harten
# Qualitätsproblemen oder Doppelungen aktiver Lektionen wandern ins Archiv
# (wiederherstellbar), statt den Lernlauf erneut zu belasten.
CANDIDATE_MAX_OLD_CONFIRMATIONS = 1


def recheck_candidates(cands: List[Dict], active: List[Dict],
                       since: str = None) -> Tuple[List[Dict], List[Dict]]:
    """Rein: (updates, archive). updates = [{key, set:{...}}], archive = [{**cand,
    archive_reason}]. `since` = Bewertungs-Stichtag (ISO) oder None."""
    from services import lesson_quality
    updates: List[Dict] = []
    archive: List[Dict] = []
    active = [a for a in (active or []) if a.get("title")]
    for c in cands or []:
        title, detail = str(c.get("title") or ""), str(c.get("detail") or "")
        probs = lesson_quality.problems(title, detail)
        if probs:
            archive.append({**c, "archive_reason": "Qualität: " + "; ".join(probs)})
            continue
        dup = lesson_quality.find_duplicate({"title": title, "detail": detail}, active)
        if dup is not None or title.strip().lower() in {
                str(a.get("title")).strip().lower() for a in active}:
            ref = (dup or {}).get("title") or title
            archive.append({**c, "archive_reason": f"Doppelung der aktiven Lektion „{ref}“"})
            continue
        old = bool(since) and str(c.get("updated_at") or c.get("first_seen") or "") < str(since)
        conf = int(c.get("confirmations") or 0)
        if old and conf > CANDIDATE_MAX_OLD_CONFIRMATIONS:
            updates.append({"key": c.get("key"),
                            "set": {"confirmations": CANDIDATE_MAX_OLD_CONFIRMATIONS,
                                    "evidence_ts": since,
                                    "recheck_note": (f"vor dem Stichtag {conf}× bestätigt – "
                                                     "braucht eine Bestätigung mit neuen Trades")}})
    return updates, archive
