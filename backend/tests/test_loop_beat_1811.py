"""18.11.2026: „KI-Trader-Schleife läuft nicht“ im Prüfer-Modus war ein Fehlalarm.

Im Prüfer-Modus entfällt der Analyse-Zyklus; `last_run` ändert sich nur bei einem
Detektor-Signal. Lebenszeichen ist jetzt der Herzschlag der Hauptschleife."""
from datetime import datetime, timedelta, timezone

from services import cockpit, signal_broker
from services import system_doctor as sd

NOW = datetime(2026, 11, 18, 18, 45, tzinfo=timezone.utc)


def _iso(minutes_ago):
    return (NOW - timedelta(minutes=minutes_ago)).isoformat()


def _pruefer(monkeypatch):
    monkeypatch.setattr(signal_broker, "enabled", lambda cfg: True)
    return {"enabled": True, "interval_min": 15, "ai_role": "pruefer"}


def test_pruefer_without_signals_is_not_an_alarm(monkeypatch):
    cfg = _pruefer(monkeypatch)
    assert sd.judge_loop(cfg, _iso(98), False, NOW, beat=_iso(0.1)) == []
    assert sd.judge_loop(cfg, _iso(98), False, NOW, beat=None) == []


def test_hanging_loop_is_still_critical(monkeypatch):
    cfg = _pruefer(monkeypatch)
    f = sd.judge_loop(cfg, _iso(98), False, NOW, beat=_iso(35))
    assert f and f[0]["level"] == "kritisch" and "hängt" in f[0]["title"]
    assert sd.judge_loop(cfg, _iso(98), True, NOW, beat=_iso(35)) == []      # lange Analyse läuft


def test_normal_mode_keeps_the_analysis_check(monkeypatch):
    monkeypatch.setattr(signal_broker, "enabled", lambda cfg: True)
    cfg = {"enabled": True, "interval_min": 10, "ai_role": "trader"}
    f = sd.judge_loop(cfg, _iso(60), False, NOW, beat=_iso(0.1))
    assert f and f[0]["id"] == "ai_loop_stale" and "läuft nicht" in f[0]["title"]
    assert sd.judge_loop(cfg, _iso(5), False, NOW, beat=_iso(0.1)) == []


def test_activity_text_without_analysis_time_in_pruefer_mode():
    cfg = {"enabled": True}
    t = cockpit.activity_text(cfg, False, _iso(-5), "pruefer")
    assert "Prüfer-Modus" in t and "Nächste Marktanalyse" not in t
    assert "Nächste Marktanalyse" in cockpit.activity_text(cfg, False, _iso(-5), "trader")
