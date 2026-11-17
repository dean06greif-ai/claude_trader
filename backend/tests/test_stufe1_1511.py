"""Stufe 1 (Trade-Analyse 15.11.2026): Hebel-Deckel, Kosten-Wächter,
Gegentrend-Schutz für Sammel-Trades, Ausmustern hoffnungsloser KI-Setups,
Lektions-Qualität + Bereinigung, Event-Kalender 2027 und ehrliche
Event-Validierung."""
import asyncio
import json
import os
from datetime import date, datetime, timezone

from services import ai_playbook, boot_migrations as bm, edge_filter as ef
from services import econ_event, fomc_backtest as fb, guard_shadow
from services import lesson_cleanup, lesson_quality as lq
from services.backtester import liq_safe_max_leverage
from services.structure_indicators import FOMC_MEETINGS

HERE = os.path.dirname(__file__)


# ---------------- Hebel-Deckel ----------------
def test_leverage_cap_keeps_liquidation_twice_the_stop_distance():
    cfg = {"maintenance_margin_rate": 0.5}
    for sl_pct in (0.3, 0.6, 1.0, 2.0):
        lev = liq_safe_max_leverage(cfg, 100.0, 100.0 * (1 - sl_pct / 100))
        liq_dist = 1.0 / lev - 0.005
        assert liq_dist + 1e-6 >= 2 * sl_pct / 100
    # Beispiel aus den Trades: HYPE, SL 1,49 % lief mit 40,7x (Liq nur 1,3× SL entfernt)
    assert liq_safe_max_leverage(cfg, 62.215, 61.2909) < 30
    assert liq_safe_max_leverage({**cfg, "liq_sl_min_ratio": 0}, 100, 99) is None
    assert liq_safe_max_leverage(cfg, 100, 100) is None


def test_paper_stop_is_settled_before_liquidation_on_price_gaps():
    from services.bitunix_trade import paper_stop_precedes_liq
    assert paper_stop_precedes_liq("LONG", 61.29, 60.99) is True     # Stop zwischen Entry und Liq
    assert paper_stop_precedes_liq("SHORT", 87.98, 88.35) is True
    assert paper_stop_precedes_liq("LONG", 60.5, 60.99) is False     # Stop hinter Liq -> Liq zählt
    assert paper_stop_precedes_liq("LONG", None, 60.99) is False


# ---------------- Kosten-Wächter ----------------
class _Coll:
    def __init__(self):
        self.docs = {}

    async def find_one(self, q):
        d = self.docs.get(q["_id"])
        return dict(d) if d else None

    async def update_one(self, q, upd, upsert=False):
        self.docs.setdefault(q["_id"], {"_id": q["_id"]}).update(upd.get("$set", {}))


class _DB:
    def __init__(self):
        self.settings = _Coll()


class _Eng:
    def __init__(self):
        self.config = {}


def test_cost_guard_migration_raises_low_values_and_resets_autotune_base():
    db, eng = _DB(), _Eng()
    db.settings.docs["ai_trader_config"] = {"_id": "ai_trader_config", "fee_guard_mult": 3.5,
                                            "fee_guard_atr_mult": 3}
    asyncio.run(bm.migrate_cost_guard(db, eng))
    assert db.settings.docs["ai_trader_config"]["fee_guard_mult"] == bm.FEE_GUARD_MULT_V2 == 10.0
    assert eng.config["fee_guard_mult"] == 10.0
    base = db.settings.docs[guard_shadow.STATE_ID]["baseline"]
    assert base["fee_guard_mult"] == 10.0
    # Autotune darf den neuen Wert nicht wieder wegklemmen
    assert guard_shadow._clamp("fee_guard_mult", 10.0, base["fee_guard_mult"]) == 10.0
    # strengerer Wert bleibt, Marker verhindert zweiten Lauf
    db2 = _DB()
    db2.settings.docs["ai_trader_config"] = {"_id": "ai_trader_config", "fee_guard_mult": 12.0}
    asyncio.run(bm.migrate_cost_guard(db2, _Eng()))
    assert db2.settings.docs["ai_trader_config"]["fee_guard_mult"] == 12.0


def test_fee_guard_10x_means_fees_at_most_ten_percent_of_risk():
    from services.bitunix_trade import fee_guard_check
    ai = {"fee_guard_mult": 10.0, "fee_guard_atr_mult": 0, "fee_guard_crv_relax": False}
    cfg = {"fee_percent": 0.06, "max_capital": 100, "leverage": 10}
    assert fee_guard_check(ai, cfg, 100.0, 99.0)[0] is False        # SL 1 %: Gebühr 12 % des Risikos
    assert fee_guard_check(ai, cfg, 100.0, 98.79)[0] is True        # SL 1,21 %: <= 10 %


# ---------------- Gegentrend-Schutz Sammel-Trades ----------------
def test_collection_counter_trend_block():
    assert ef.collection_blocks({}, "LONG", "down") is True
    assert ef.collection_blocks({}, "SHORT", "up") is True
    assert ef.collection_blocks({}, "LONG", "flat") is False        # flat sammelt weiter
    assert ef.collection_blocks({}, "SHORT", None) is False         # ohne Bias sammelt weiter
    assert ef.collection_blocks({}, "LONG", "up") is False
    assert ef.collection_blocks({"edge_filter_collection_counter_trend": False}, "LONG", "down") is False
    assert ef.collection_blocks({"edge_filter_enabled": False}, "LONG", "down") is False


# ---------------- Hoffnungslose KI-Setups ----------------
def test_hopeless_verdict_needs_clear_evidence():
    ny = [-1.2] * 18 + [0.3, -1.0]                                  # wie ny_close_reversal
    assert "statistisch klar negativ" in ai_playbook.hopeless_verdict(ny)
    assert ai_playbook.hopeless_verdict([-1.2] * 10) is None        # zu wenig Trades
    mixed = [1.5, -1.0] * 10                                         # positiv -> nie
    assert ai_playbook.hopeless_verdict(mixed) is None
    mild = [0.8, -1.0, -1.0, 0.9] * 5                               # leicht negativ, nicht belegt
    assert ai_playbook.hopeless_verdict(mild) is None


# ---------------- Lektions-Qualität ----------------
def test_lesson_quality_rejects_edit_instructions_missing_timeframes_and_collection_blocks():
    assert lq.problems("Bestätigung", "Ersetze '1m/5m/15m' durch '10m/30m/1h'.")
    assert lq.unknown_timeframes("RSI>70 auf 10m/30m prüfen") == ["10m", "30m"]
    assert lq.unknown_timeframes("1h/4h Trend") == ["4h"]
    assert lq.unknown_timeframes("nach 3 Verlusten 24h Pause, 45-60 Minuten halten, "
                                 "120 min warten") == []
    assert lq.unknown_timeframes("5m-Kerze über 15m-Hoch, 1h-Trend") == []
    assert lq.blocks_data_collection("Regelbasierte Trades ohne LLM-Analyse technisch sperren", "")
    assert lq.blocks_data_collection("Divergence", "divergence ohne LLM sofort schließen")
    assert not lq.blocks_data_collection("Mit Trend", "LONG nicht gegen Tages-Bias down")
    good = ("Einstieg erst nach bestätigender Kerze",
            "Vor dem Einstieg eine abgeschlossene 5m-Kerze in Handelsrichtung abwarten.")
    assert lq.problems(*good) == []


def test_find_duplicate_merges_same_statement_under_new_title():
    old = [{"title": "Nach 3 aufeinanderfolgenden Verlusten pro Coin 24h Pause",
            "detail": "Wenn ein Coin 3 aufeinanderfolgende Trades mit Verlust beendet, "
                      "den Coin für 24 Stunden pausieren."},
           {"title": "News-Defensive", "detail": "Vor FOMC/CPI keine neuen Einstiege."}]
    new = {"title": "Serienverlust-Bremse je Coin",
           "detail": "Nach 3 aufeinanderfolgenden Verlusten auf einem Coin diesen Coin "
                     "24 Stunden pausieren."}
    assert lq.find_duplicate(new, old)["title"].startswith("Nach 3 aufeinanderfolgenden")
    other = {"title": "Stop an Struktur", "detail": "SL hinter Swing-Tief, Gebühr <= 10 %."}
    assert lq.find_duplicate(other, old) is None


def test_learning_prompt_carries_hygiene_rules():
    from services import ai_learning
    assert lq.HYGIENE_PROMPT in ai_learning.LEARNING_SYSTEM
    assert "4h-Abwärtstrend" not in ai_learning.LEARNING_SYSTEM


# ---------------- Lektions-Bereinigung (Bestand Produktion) ----------------
def test_lesson_cleanup_on_production_titles():
    titles = json.load(open(os.path.join(HERE, "fixtures", "lessons_prod_titles_1511.json")))
    lessons = [{"title": t, "detail": "x"} for t in titles]
    lessons.append({"title": "Neue Lektion von morgen", "detail": "y"})          # unbekannt
    lessons.append({"title": "Regelbasierte Trades ohne LLM-Analyse sperren",
                    "detail": "Trader", "locked": True})                         # gesperrt
    new, log = lesson_cleanup.plan(lessons, now=datetime(2026, 11, 15, tzinfo=timezone.utc))
    out = {l["title"] for l in new}
    assert len(log["removed"]) + sum(len(v) for v in log["merged"].values()) == len(titles) - 2
    assert {"Break-Even-Nachzug erst nach bestätigter Struktur, nicht bei kleinem Zwischengewinn",
            "News-Defensive", "Neue Lektion von morgen",
            "Regelbasierte Trades ohne LLM-Analyse sperren"} <= out
    assert len(log["added"]) == 5 and len(new) == 2 + 2 + 5
    for l in new:
        if l.get("model") == "bereinigung_1511":
            assert lq.problems(l["title"], l["detail"], l.get("context", "")) == []
            assert l["valid_until"] and l["locked"] is False and l["context"]
    again, log2 = lesson_cleanup.plan(new)                           # idempotent
    assert {l["title"] for l in again} == out and not log2["removed"]


# ---------------- Event-Kalender ----------------
def test_event_calendar_reaches_into_2027():
    for arr in (econ_event.CPI_RELEASES, econ_event.NFP_RELEASES,
                econ_event.PPI_RELEASES, econ_event.PCE_RELEASES):
        assert max(arr) >= "2027-12-01" and arr == sorted(arr)
        assert all(date.fromisoformat(d).weekday() < 5 for d in arr)
    assert max(d2 for _, d2 in FOMC_MEETINGS) == "2027-12-08"


# ---------------- Event-Validierung ----------------
def _per_event(values, trades=3):
    return {f"2025-{i // 28 + 1:02d}-{i % 28 + 1:02d}": {"trades": trades if v is not None else 0,
                                                          "pnl": v or 0}
            for i, v in enumerate(values)}


def test_event_level_validation():
    agg_ok = {"total": {"trades": 60, "pnl": 60, "winrate": 60, "wilson_wr_95": [40, 70]},
              "out_of_sample": {"trades": 20, "pnl": 20}}
    strong = _per_event([3, 2, 4, -1, 3, 2, 5, 1, 3, 2, 4, 2, 3, 1, 2, 3])
    agg = {**agg_ok, "events": fb.event_stats(strong, list(strong)[-5:])}
    assert fb.validated(agg)[0] is True
    weak = _per_event([5, -4, 6, -5, 4, -3, 5, -4, 6, -5, 4, -3, 2, -1])
    agg_w = {**agg_ok, "events": fb.event_stats(weak, list(weak)[-5:])}
    ok, why = fb.validated(agg_w)
    assert ok is False and "je Event nicht belegt" in why
    assert fb.validated(agg, ai_params=True)[0] is False             # KI-Parameter nie validiert
    assert fb.validated(agg_ok)[0] is True                           # Altaufruf ohne Events


def test_revalidation_subtracts_slippage_once():
    pe = _per_event([3.0] * 14)
    trades = [{"event": e, "pnl": 1.0, "entry_ts": 0} for e in pe for _ in range(3)]
    doc = {"per_event": pe, "trades": trades, "ai_params": False}
    new = bm.revalidate_event_result(doc)
    slip = fb.NOTIONAL * fb.SLIPPAGE_RT
    assert abs(new["trades"][0]["pnl"] - (1.0 - slip)) < 1e-9
    assert new["slippage_included"] is True
    again = bm.revalidate_event_result(new)
    assert again["trades"][0]["pnl"] == new["trades"][0]["pnl"]      # kein doppelter Abzug


def test_event_pnl_includes_slippage():
    assert fb._pnl("LONG", 100.0, 100.0) == -round(fb.NOTIONAL * (fb.FEE_RT + fb.SLIPPAGE_RT), 2)


class _Sink:
    def __init__(self):
        self.rows = []

    async def insert_one(self, d):
        self.rows.append(d)


class _DB2(_DB):
    def __init__(self):
        super().__init__()
        self.ai_chat = _Sink()
        self.ai_lessons_history = _Sink()


def test_boot_migrations_lessons_and_events_run_on_fake_db():
    from services import ai_lessons, econ_backtest, fomc_event
    db = _DB2()
    titles = json.load(open(os.path.join(HERE, "fixtures", "lessons_prod_titles_1511.json")))
    db.settings.docs[ai_lessons.DOC_ID] = {"_id": ai_lessons.DOC_ID,
                                          "lessons": [{"title": t, "detail": "x"} for t in titles]}
    asyncio.run(bm.migrate_lesson_cleanup(db))
    assert len(db.settings.docs[ai_lessons.DOC_ID]["lessons"]) == 7
    assert any("Lektionen bereinigt" in r["text"] for r in db.ai_chat.rows)
    # Event-Neubewertung aus gespeichertem Ergebnis (validiert -> nicht mehr validiert)
    pe = _per_event([1.0, -1.0] * 8)
    trades = [{"event": e, "pnl": v["pnl"] / 3, "entry_ts": 0} for e, v in pe.items() for _ in range(3)]
    rid = econ_backtest.result_id("cpi", "crypto")
    db.settings.docs[rid] = {"_id": rid, "per_event": pe, "trades": trades, "validated": True}
    fomc_event._state.setdefault("validation", {})
    asyncio.run(bm.migrate_event_revalidation(db))
    assert db.settings.docs[rid]["validated"] is False
    assert db.settings.docs[rid]["slippage_included"] is True
    cpi_state = db.settings.docs[econ_event.get("cpi").state_id]["validation"]["crypto"]
    assert cpi_state["validated"] is False and "events" in cpi_state
