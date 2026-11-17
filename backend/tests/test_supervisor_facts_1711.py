"""17.11.2026: KI-Aufsicht prüft ihre Urteile gegen Fakten (Prod-Bericht vom 16.11. als Fall)."""
from services import ai_supervisor as sup

ALLOWED = {"openrouter": ["openai/gpt-6-luna-pro", "deepseek/deepseek-v4.1-flash", "z-ai/glm-5.2",
                          "z-ai/glm-5.3", "anthropic/claude-haiku-5.5"],
           "groq": ["openai/gpt-oss-120b"], "mistral": ["ministral-8b-latest"]}
CURRENT = {"analyst": "openrouter/openai/gpt-6-luna-pro",
           "research_analyst": "openrouter/deepseek/deepseek-v4.1-flash",
           "news_watcher": "mistral/ministral-8b-latest",
           "market_observer": "groq/openai/gpt-oss-120b",
           "trade_manager": "openrouter/deepseek/deepseek-v4-flash"}
FACTS = {"analyst": {"calls_today": 190, "calls_7d": 1200},
         "market_observer": {"calls_today": 52, "calls_7d": 400},
         "trade_manager": {"calls_today": 17, "calls_7d": 250},
         "chat": {"calls_today": 0, "calls_7d": 0},
         "summarizer": {"calls_today": 0, "calls_7d": 6}}


def test_activity_facts_from_token_usage():
    rows = [{"date": "2026-11-17", "role": "analyst", "calls": 190, "tokens": 4_000_000},
            {"date": "2026-11-16", "role": "analyst", "calls": 218, "tokens": 4_600_000},
            {"date": "2026-11-01", "role": "analyst", "calls": 99, "tokens": 1},
            {"date": "2026-11-16", "role": "summarizer", "calls": 1, "tokens": 900}]
    f = sup.activity_facts(rows, "2026-11-17")
    assert f["analyst"] == {"calls_today": 190, "tokens_today": 4_000_000, "calls_7d": 218}
    assert f["summarizer"]["calls_today"] == 0 and f["summarizer"]["calls_7d"] == 1


def test_apply_facts_corrects_inactive_and_deactivate():
    rep = {"roles": [
        {"role": "market_observer", "verdict": "inaktiv", "score": 40, "action": "deaktivieren", "reason": "x"},
        {"role": "trade_manager", "verdict": "inaktiv", "score": 40, "action": "deaktivieren", "reason": "x"},
        {"role": "chat", "verdict": "inaktiv", "score": 30, "action": "deaktivieren", "reason": "x"},
        {"role": "deep_analyst", "verdict": "schwach", "score": 20, "action": "deaktivieren", "reason": "x"}]}
    sup.apply_facts(rep, FACTS)
    by = {r["role"]: r for r in rep["roles"]}
    assert by["market_observer"]["verdict"] == "gut" and by["market_observer"]["action"] == "keine"
    assert "52 Aufrufe" in by["market_observer"]["reason"]
    assert by["trade_manager"]["verdict"] == "gut" and by["trade_manager"]["action"] == "keine"
    assert by["chat"]["verdict"] == "gut" and "Anlass" in by["chat"]["reason"]
    assert by["deep_analyst"]["action"] == "einstellungen_pruefen"      # nie abschalten


def test_clean_recommendations_prod_case():
    recs = ["analyst: Hauptmodell zu openrouter/gpt-6-luna-pro wechseln und Fallback1 auf ein anderes "
            "Provider-Modell (z.B. openrouter/deepseek-v4.1-flash) setzen – erhöht Analyse-Tiefe.",
            "market_observer: Keine Ausgaben prüfen und Rolle deaktivieren.",
            "trade_manager: Rolle deaktivieren, da keine Trades verwaltet werden.",
            "news_watcher: Modell auf openrouter/glm-5.3 umstellen – bessere News-Verarbeitung.",
            "research_analyst: Modell auf openrouter/deepseek-v4.1-flash upgraden."]
    out = sup.clean_recommendations(recs, FACTS, CURRENT, ALLOWED)
    assert out == ["news_watcher: Modell auf openrouter/z-ai/glm-5.3 umstellen – bessere News-Verarbeitung."]


def test_normalize_slug_and_report():
    assert sup.normalize_slug("openrouter", "glm-5.3", ALLOWED) == "z-ai/glm-5.3"
    assert sup.normalize_slug("openrouter", "openrouter/z-ai/glm-5.3", ALLOWED) == "z-ai/glm-5.3"
    assert sup.normalize_slug("openrouter", "unbekannt-1", ALLOWED) == "unbekannt-1"
    rep = sup.normalize_report({"roles": [{"role": "news_watcher", "verdict": "auffällig",
                                           "action": "modell_wechseln", "suggested_provider": "openrouter",
                                           "suggested_model": "glm-5.3"}]}, ALLOWED)
    assert rep["roles"][0]["suggested_model"] == "z-ai/glm-5.3"
    assert rep["roles"][0]["action"] == "modell_wechseln"


def test_evidence_text_shows_facts():
    txt = sup.evidence_text({"chat": {"model": "gemini/x", "activity": {"calls_today": 0, "calls_7d": 0}}})
    assert "Aufrufe laut Abrechnung (FAKT): heute 0" in txt and "Arbeitsweise" in txt


def test_run_review_end_to_end(monkeypatch):
    """Ganzer Prüflauf mit Fake-DB/-Engine: feste Kette + Fakten wirken."""
    import asyncio
    import json
    from services import ai_providers
    from tests.phase_fakedb import FakeDB
    db = FakeDB()
    asyncio.run(db.ai_token_usage.insert_one({"date": "2026-11-17", "role": "trade_manager",
                                              "calls": 17, "tokens": 80000}))
    monkeypatch.setattr("core.timeutil.berlin_date", lambda *a: "2026-11-17")

    class Eng:
        config = {"provider": "gemini", "model": "gemini-3.5-flash"}
        key = "k"

        def __init__(self):
            self.db = db

        def status(self):
            return {"config": self.config}

        @staticmethod
        def _parse_json(t):
            return json.loads(t)

        async def _track_tokens(self, *a):
            return None
    seen = {}

    async def fake_chain(chain, prompt, system, **kw):
        seen["chain"] = chain[:2]
        seen["prompt"] = prompt
        return json.dumps({"summary": "s", "roles": [
            {"role": "trade_manager", "verdict": "inaktiv", "score": 40, "action": "deaktivieren"}],
            "recommendations": ["trade_manager: Rolle deaktivieren."]}), "openrouter", "deepseek/deepseek-v4.1-flash"
    monkeypatch.setattr(ai_providers, "generate_chain", fake_chain)
    monkeypatch.setattr(ai_providers, "provider_keys", lambda p: ["k"])
    s = sup.TeamSupervisor()
    s.setup(Eng())
    res = asyncio.run(s.run_review())
    assert res["status"] == "ok", res
    rep = res["report"]
    tm = next(r for r in rep["roles"] if r["role"] == "trade_manager")
    assert tm["verdict"] == "gut" and tm["action"] == "keine" and "17 Aufrufe" in tm["reason"]
    assert rep["recommendations"] == []
    assert seen["chain"][0] == ("openrouter", "deepseek/deepseek-v4.1-flash")
    assert "Aufrufe laut Abrechnung (FAKT): heute 17" in seen["prompt"]
