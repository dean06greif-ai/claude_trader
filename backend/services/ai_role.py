"""Rolle der KI im KI-Trader: frei (bisher) oder Prüfer (nur Detektor-Signale).

Befund Prod 11/2026 (Signal-Quelle): ki_geprueft +0,32 R (25 Trades),
ki_frei −0,13 R (73), regel −0,29 R (524). Im Prüfer-Modus
  * entfällt der periodische Voll-Analyse-Zyklus (spart LLM-Kosten),
  * prüft die KI nur noch Detektor-Treffer (Setup-/Sweep-/TF2-Trigger),
  * werden KI-Entscheidungen ohne offenes Detektor-Fenster (ki_frei) zu HOLD.
Wirkt nur mit aktivem Signal-Broker (sonst gibt es keine Fenster). Standard
seit 11/2026: „pruefer“ (vorher „frei“). Reine Funktionen.
"""
from typing import Dict, Optional

# 11/2026 (Trade-Analyse, Freigabe Stufe 3): Standard ist jetzt „Prüfer“.
# KI-frei-Trades lagen bei −0,35 R (84 Trades) – die freie Analyse hatte keinen
# messbaren Wert, kostete aber die meisten LLM-Aufrufe. Detektoren liefern die
# Trades mit berechnetem SL/TP, die KI prüft (Veto/Timing); die Veto-Bilanz
# (services/veto_balance) misst, ob das Veto etwas bringt. „frei“ bleibt wählbar.
DEFAULTS = {"ai_role": "pruefer"}
ROLES = ("frei", "pruefer")


def clamp_updates(updates: Dict, cfg: Dict) -> None:
    if updates.get("ai_role") in ROLES:
        cfg["ai_role"] = updates["ai_role"]


def is_pruefer(cfg: Optional[Dict]) -> bool:
    from services import signal_broker
    cfg = cfg or {}
    return cfg.get("ai_role") == "pruefer" and signal_broker.enabled(cfg)


def skip_cycle(cfg: Optional[Dict]) -> bool:
    return is_pruefer(cfg)


def veto_free(dec: Dict, cfg: Optional[Dict]) -> bool:
    return is_pruefer(cfg) and dec.get("signal_source") != "ki_geprueft"


def trigger_skip_reason(cfg: Optional[Dict], symbol: str) -> Optional[str]:
    """17.11.2026: TF2-/Sweep-Analysen im Prüfer-Modus ohne offenes Detektor-Signal
    können keinen Trade auslösen (Einstieg nur mit Signal, sonst KI-frei -> HOLD).
    Sie kosteten trotzdem einen vollen KI-Aufruf (~22.000 Tokens) und zählten als
    „Prüfung“ fremder Signale. Rückgabe: Grund zum Überspringen oder None."""
    if not is_pruefer(cfg):
        return None
    from services.signal_broker import signal_broker
    if signal_broker.has_open([symbol]):
        return None
    return "Prüfer-Modus: kein offenes Detektor-Signal – die Analyse könnte nur HOLD ergeben"


def news_targets(cfg: Optional[Dict], impulse, severity: str):
    """News-Impuls im Prüfer-Modus: nur Symbole mit offenem Detektor-Signal analysieren;
    HIGH ohne betroffene Signale -> die offenen Signale prüfen statt Voll-Analyse.
    Rückgabe: (Symbole, Voll-Analyse erlaubt)."""
    impulse = list(impulse or [])
    if not is_pruefer(cfg):
        return impulse, True
    from services.signal_broker import signal_broker
    impulse = [s for s in impulse if not trigger_skip_reason(cfg, s)]
    if not impulse and severity == "high":
        impulse = sorted({x["symbol"] for x in signal_broker.open_signals()})[:6]
    return impulse, False
