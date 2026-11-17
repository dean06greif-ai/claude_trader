"""Qualitäts-Prüfung für KI-Lektionen (rein, ohne DB).

Befund Trade-Analyse 15.11.2026 (32 Lektionen):
- Detail-Felder enthielten Änderungs-Anweisungen statt der Lektion
  („Ersetze '1m/5m/15m' durch …“, „Streichung der 120-Minuten-Frist …“):
  das LLM lieferte beim „Schärfen“ nur das Delta, der Lernlauf übernahm es.
- Lektionen verlangten 10m-/30m-Kerzen, die die KI nie bekommt (1m/5m/15m/1h).
- Lektionen forderten, regelbasierte Trades ohne LLM-Analyse zu sperren –
  das sind die Datensammel-Trades, also die Lernbasis.
- Nahezu gleiche Aussagen unter verschiedenen Titeln (Duplikate).

Die Funktionen hier erkennen diese Fälle; der Lernlauf (ai_learning) lehnt
solche Lektionen ab bzw. führt Duplikate mit der bestehenden Lektion zusammen.
"""
import re
from typing import Dict, List, Optional

# Zeitebenen, die der KI-Trader tatsächlich bekommt (ai_engine Snapshot) plus
# Tages-Ebene (daily_bias / trend_1d). Alles andere kann die KI nicht prüfen.
AVAILABLE_TFS = {"1m", "5m", "15m", "1h", "1d"}

_TF_RE = re.compile(r"(?<![\w.,])(\d{1,3})\s?(m|min|h|d)(?=[-\s/,.;:)]|$)", re.I)
_TF_UNIT = {"m": "m", "min": "m", "h": "h", "d": "d"}

_EDIT_RE = re.compile(
    r"^\s*(ersetze|ersetzen|ändere|aendere|streiche|streichung|entferne den|"
    r"anpassen auf|anpassung:|setze .{0,40}\bstatt\b|statt .{0,60}\bjetzt\b|"
    r"ergänze|ergaenze|neu formuliert:|korrektur:)", re.I)

_COLLECTION_BLOCK_RE = re.compile(
    r"(regelbasiert\w*|ohne (?:vorherige |schriftliche )*llm(?:[- ]?analyse)?|detektor\w*|"
    r"sammel[- ]?trades?|datensammlung)(?:[^.]|\.\d){0,160}?"
    r"(sperr\w*|blockier\w*|sofort schlie\w*|nicht (mehr )?eröffnen|verbiet\w*|schlie(ß|ss)e)",
    re.I)

_STOP = {"der", "die", "das", "und", "oder", "bei", "mit", "ohne", "nicht", "nur", "auf",
         "für", "fuer", "von", "vor", "nach", "im", "in", "am", "an", "zu", "ist", "sind",
         "eine", "ein", "einen", "kein", "keine", "den", "dem", "des", "als", "wenn", "dann",
         "alle", "auch", "noch", "wird", "werden", "trade", "trades", "lektion", "einem",
         "einer", "diesen", "diese", "dieser", "pro", "je", "beim", "zum", "zur", "sich"}


def _stem(w: str) -> str:
    """Grobe deutsche Stammform (Verlusten/Verlust, aufeinanderfolgende/n)."""
    for suf in ("ungen", "ende", "enden", "en", "er", "es", "e", "n", "s"):
        if w.endswith(suf) and len(w) - len(suf) >= 4:
            return w[: -len(suf)]
    return w


def is_edit_instruction(detail: str) -> bool:
    """Detail beschreibt eine ÄNDERUNG statt der Lektion selbst."""
    return bool(_EDIT_RE.search(str(detail or "")))


def unknown_timeframes(text: str) -> List[str]:
    """Zeitebenen-Angaben wie '10m-Kerze', '30m', '4h', die der KI nicht
    vorliegen. Dauern ('45-60 Minuten', 'nach 120 min') sind keine
    Kerzen-Zeitebenen und werden ignoriert, solange kein 'Kerze/TF/Chart'
    oder Zeitebenen-Format (z.B. '10m/30m') daneben steht."""
    out = []
    s = str(text or "")
    for m in _TF_RE.finditer(s):
        unit = _TF_UNIT[m.group(2).lower()]
        tf = f"{int(m.group(1))}{unit}"
        if tf in AVAILABLE_TFS:
            continue
        tail = s[m.end():m.end() + 14].lower()
        head = s[max(0, m.start() - 3):m.start()]
        # 'min' ohne Kerzen-Bezug ist eine Dauer, keine Zeitebene
        if m.group(2).lower() == "min" and "kerze" not in tail:
            continue
        tf_context = any(k in tail for k in ("kerze", "chart", "trend", "ema", "rsi",
                                             "zeitfenster", "-tf", " tf", "struktur"))
        slashed = "/" in head or tail.startswith("/")
        # '10m' ist praktisch immer eine Zeitebene; '24h'/'2d' meist eine Dauer
        if (unit == "m" and m.group(2).lower() == "m") or tf_context or slashed:
            out.append(tf)
    return sorted(set(out))


def blocks_data_collection(title: str, detail: str = "") -> bool:
    """Lektion würde die Datensammel-Trades (regelbasierte Detektor-Trades
    ohne LLM-Analyse) sperren/schließen – das zerstört die Lernbasis."""
    return bool(_COLLECTION_BLOCK_RE.search(f"{title} {detail}"))


def _tokens(text: str) -> set:
    return {_stem(w) for w in re.findall(r"[a-zä-üß0-9_]+", str(text).lower())
            if len(w) > 2 and w not in _STOP}


def similarity(a: Dict, b: Dict) -> float:
    """Jaccard-Ähnlichkeit über Titel + Kontext + Detail (0..1)."""
    ta = _tokens(f"{a.get('title', '')} {a.get('context', '')} {a.get('detail', '')}")
    tb = _tokens(f"{b.get('title', '')} {b.get('context', '')} {b.get('detail', '')}")
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


DUPLICATE_SIM = 0.45


def find_duplicate(lesson: Dict, existing: List[Dict],
                   threshold: float = DUPLICATE_SIM) -> Optional[Dict]:
    """Bestehende Lektion mit (fast) derselben Aussage unter anderem Titel."""
    key = str(lesson.get("title", "")).strip().lower()
    best, best_sim = None, 0.0
    for e in existing or []:
        if str(e.get("title", "")).strip().lower() == key:
            continue
        s = similarity(lesson, e)
        if s > best_sim:
            best, best_sim = e, s
    return best if best is not None and best_sim >= threshold else None


def problems(title: str, detail: str, context: str = "") -> List[str]:
    """Alle harten Qualitätsprobleme einer vorgeschlagenen Lektion."""
    out = []
    if is_edit_instruction(detail):
        out.append("Detail ist eine Änderungs-Anweisung statt der vollständigen Lektion – "
                   "bitte die komplette, für sich verständliche Regel formulieren")
    tfs = unknown_timeframes(f"{title} {detail} {context}")
    if tfs:
        out.append(f"nutzt Zeitebenen, die dir nicht vorliegen ({', '.join(tfs)}) – "
                   "verfügbar sind 1m/5m/15m/1h und der Tagestrend")
    if blocks_data_collection(title, detail):
        out.append("würde die regelbasierten Datensammel-Trades sperren – sie sind die "
                   "Lern- und Vergleichsbasis und bleiben bewusst ohne LLM-Analyse")
    return out


HYGIENE_PROMPT = (
    "LEKTIONS-HYGIENE (du managst deine Lektionen selbst): Es gibt KEINE feste Zielzahl – "
    "behalte nur Lektionen, die nachweislich etwas bringen. Wenige starke Lektionen sind "
    "besser als viele schwache. Regeln: (1) Jede Lektion ist vollständig und für sich "
    "verständlich – beim Schärfen den KOMPLETTEN neuen Text liefern, nie nur die Änderung "
    "('Ersetze …', 'Streiche …' wird verworfen). (2) Nur Zeitebenen, die du bekommst: "
    "1m/5m/15m/1h und Tagestrend – keine 10m/30m/4h. (3) Regelbasierte Datensammel-Trades "
    "nie sperren oder schließen – sie sind deine Lernbasis. (4) Gleiche Aussage = EINE "
    "Lektion: schärfe die bestehende (exakt gleicher Titel) statt eine neue anzulegen; "
    "nahezu gleiche neue Lektionen werden automatisch mit der bestehenden zusammengeführt. "
    "(5) Widersprüche und überholte Lektionen in 'contradictory_lessons' bzw. "
    "'removed_lessons' nennen. (6) Belege nennen (Anzahl Trades, Ø R); unter 30 Trades "
    "ist ein Muster nur ein Kandidat. (7) Größen-/Margen-Anweisungen sind im Risiko-Modus "
    "wirkungslos – stattdessen Entry-Qualität, Stop-Abstand oder Auswahl verbessern."
)
