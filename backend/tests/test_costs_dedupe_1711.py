"""17.11.2026: Verbrauch/Reichweite des KI-Guthabens, Meldungs-Dedupe über Neustarts."""
import asyncio

from services import cockpit, key_credits as kc, notifications as nt
from tests.phase_fakedb import FakeDB

H = 3600.0


def test_burn_rate_and_runway():
    now = 1_000_000.0
    pts = [[now - 48 * H, 50.0], [now - 24 * H, 50.6], [now, 51.2]]
    assert abs(kc.burn_rate(pts, now) - 0.6) < 1e-9
    assert kc.burn_rate([[now - 2 * H, 50.0], [now, 50.1]], now) is None          # < 12 h Verlauf
    assert kc.burn_rate([[now - 30 * H, 50.0], [now, 10.0]], now) is None         # Zähler zurückgesetzt
    assert abs(kc.runway_days(7.49, 0.6) - 12.483) < 0.01
    assert kc.runway_days(7.49, 0.0) is None


def test_record_usage_adds_runway_to_rows(monkeypatch):
    db = FakeDB()
    now = 2_000_000.0
    asyncio.run(db.settings.update_one({"_id": kc.USAGE_ID}, {"$set": {"hist": {
        "sk-or-v1-4457…a53b": [[now - 30 * H, 51.0]]}}}, upsert=True))
    monkeypatch.setattr(kc.time, "time", lambda: now)
    rows = [{"label": "OpenRouter Haupt", "key_masked": "sk-or-v1-4457…a53b", "total_credits": 60.0,
             "usage": 51.75, "remaining": 8.25, "level": "ok"},
            {"label": "Free", "key_masked": "x", "total_credits": 0, "usage": 0, "remaining": 0}]
    asyncio.run(kc._record_usage(db, rows))
    assert rows[0]["burn_usd_day"] == 0.6 and rows[0]["runway_days"] == 13.8
    assert "runway_days" not in rows[1]


def test_cockpit_runway_recommendation():
    snap = {"keys": [{"label": "OpenRouter Haupt", "total_credits": 60, "remaining": 7.49,
                      "burn_usd_day": 0.62, "runway_days": 12.1}]}
    top = {"role": "analyst", "tokens": 4_189_281, "model": "openai/gpt-6-luna-pro"}
    r = cockpit.rec_credit_runway(snap, top)
    assert len(r) == 1 and "12 Tage" in r[0]["title"] and r[0]["prio"] == 3
    assert "4,2 Mio. Tokens" in r[0]["detail"] and "7,49 $" in r[0]["detail"]
    snap["keys"][0]["runway_days"] = 30
    assert cockpit.rec_credit_runway(snap, top) == []


def test_daily_notification_survives_restart():
    db = FakeDB()
    nt._last_sent.clear()
    first = asyncio.run(nt.website_notify(db, "token_alert", "T", "m", cooldown_min=1440,
                                          dedupe_key="web:token:analyst:2026-11-17"))
    nt._last_sent.clear()                       # Neustart: Speicher leer
    second = asyncio.run(nt.website_notify(db, "token_alert", "T", "m", cooldown_min=1440,
                                           dedupe_key="web:token:analyst:2026-11-17"))
    assert first is True and second is False
    # kurze Sperrzeiten bleiben rein im Speicher (kein DB-Abgleich)
    nt._last_sent.clear()
    assert asyncio.run(nt.website_notify(db, "x", "kurz", "m", cooldown_min=5)) is True
    nt._last_sent.clear()
    assert asyncio.run(nt.website_notify(db, "x", "kurz", "m", cooldown_min=5)) is True
