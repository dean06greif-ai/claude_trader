"""Einmalige, idempotente Boot-Migrationen (Marker in settings._id='boot_migrations').

Laufen bei jedem Start; Marker verhindern Wiederholung, spätere UI-Änderungen des
Traders werden dadurch NIE überschrieben. Hintergrund: 10. Handover 26.08. –
Klick-Liste nach User-Freigabe automatisiert (siehe memory/ML_REBUILD_STATUS.md).
"""
import logging
from typing import Dict
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

MARKER_ID = "boot_migrations"

# Cerebras hat das Free-Tier zum 17.08.2026 eingestellt – alle Keys liefern
# dauerhaft 402 payment_required. Analyst-Kette laut User-Wahl 26.08.:
ANALYST_CHAIN = {
    "provider": "openrouter", "model": "nvidia/nemotron-3-super-120b-a12b:free",
    "fallback_provider": "groq", "fallback_model": "openai/gpt-oss-20b",
    "fallback2_provider": "openrouter", "fallback2_model": "deepseek/deepseek-v4-flash",
}
# Übrige tote Cerebras-Slots (z.B. Chat-/Observer-Fallback gemma-4-31b).
# 09/2026: openai/gpt-oss-20b:free gibt es bei OpenRouter nicht mehr -> Groq.
CEREBRAS_REPLACEMENT = {"provider": "groq", "model": "openai/gpt-oss-20b"}

SLIPPAGE_ARTIFACT_PCT = 2.0


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


async def _done(db, key: str) -> bool:
    doc = await db.settings.find_one({"_id": MARKER_ID}) or {}
    return bool(doc.get(key))


async def _mark(db, key: str):
    await db.settings.update_one(
        {"_id": MARKER_ID}, {"$set": {key: True, f"{key}_at": _now_iso()}}, upsert=True)


async def migrate_cerebras_shutdown(db):
    """Tote Cerebras-Slots in allen KI-Rollen ersetzen (Free-Tier eingestellt)."""
    if await _done(db, "cerebras_shutdown_v1"):
        return
    doc = await db.settings.find_one({"_id": "ai_roles_config"})
    if doc:
        updates = {}
        for role, cfg in doc.items():
            if role == "_id" or not isinstance(cfg, dict):
                continue
            if role == "analyst" and cfg.get("provider") == "cerebras":
                for k, v in ANALYST_CHAIN.items():
                    updates[f"{role}.{k}"] = v
                continue
            for slot in ("", "fallback_", "fallback2_"):
                if cfg.get(f"{slot}provider") == "cerebras":
                    updates[f"{role}.{slot}provider"] = CEREBRAS_REPLACEMENT["provider"]
                    updates[f"{role}.{slot}model"] = CEREBRAS_REPLACEMENT["model"]
        if updates:
            await db.settings.update_one({"_id": "ai_roles_config"}, {"$set": updates})
            logger.info("Boot-Migration: tote Cerebras-Slots ersetzt "
                        f"({sorted({k.split('.')[0] for k in updates})}); Analyst-Kette: "
                        "nemotron:free -> gpt-oss-20b:free -> deepseek-v4-flash")
    await _mark(db, "cerebras_shutdown_v1")


async def migrate_heatmap_off(db, engine=None):
    """use_heatmap_data AUS (RCA: erfundene Formel-Level verzerren Entries)."""
    if await _done(db, "heatmap_off_v1"):
        return
    doc = await db.settings.find_one({"_id": "ai_trader_config"}) or {}
    if doc.get("use_heatmap_data"):
        await db.settings.update_one({"_id": "ai_trader_config"},
                                     {"$set": {"use_heatmap_data": False}})
        if engine is not None:
            engine.config["use_heatmap_data"] = False
        logger.info("Boot-Migration: use_heatmap_data AUS (RCA erfundene Formel-Level; "
                    "im UI jederzeit wieder aktivierbar)")
    await _mark(db, "heatmap_off_v1")


async def migrate_slippage_artifacts(db):
    """Phantom-Slippage (Bitunix-Schutzpreis statt Fill) aus Alt-Trades entfernen."""
    if await _done(db, "slippage_artifacts_v1"):
        return
    query = {"slippage_pct": {"$ne": None},
             "order_kind": {"$in": ["market", "taker_fallback", None]},
             "$or": [{"slippage_pct": {"$gt": SLIPPAGE_ARTIFACT_PCT}},
                     {"slippage_pct": {"$lt": -SLIPPAGE_ARTIFACT_PCT}}]}
    res = await db.auto_trades.update_many(query, {
        "$unset": {"slippage_pct": "", "slippage_usdt": ""},
        "$set": {"slippage_artifact_cleared": True}})
    if res.modified_count:
        logger.info(f"Boot-Migration: {res.modified_count} Phantom-Slippage-Messwerte "
                    "entfernt (RCA custom_23a30b65: 'price'-Feld = Schutzpreis)")
    await _mark(db, "slippage_artifacts_v1")


async def migrate_leverage_proposals(db, engine):
    """Offene Proposals einmalig abarbeiten (User-Entscheidung 26.08.):
    - reine Hebel-SENKUNGEN anwenden (neuester Vorschlag je Symbol gewinnt,
      Auto-Hebel wird über _apply_changes automatisch mit deaktiviert),
    - ältere Duplikate als 'superseded' schließen,
    - Hebel-ERHÖHUNGEN bleiben zur manuellen Entscheidung liegen,
    - zu restriktive Engine-Vorschläge (max_same_direction/cooldown_min) ablehnen."""
    if await _done(db, "leverage_proposals_v1"):
        return
    now = _now_iso()
    n_rej = 0
    for p in await db.ai_proposals.find(
            {"status": "needs_confirmation", "scope": "engine"}).to_list(1000):
        keys = set((p.get("changes") or {}).keys())
        if keys and keys <= {"max_same_direction", "cooldown_min"}:
            await db.ai_proposals.update_one({"id": p["id"]}, {"$set": {
                "status": "rejected", "decided_at": now,
                "decision_note": "Auto (Migration 26.08.): zu restriktiv für die Messphase"}})
            n_rej += 1

    props = await db.ai_proposals.find(
        {"status": "needs_confirmation", "scope": "coin",
         "changes.leverage": {"$exists": True}}).to_list(2000)
    pure = [p for p in props
            if set((p.get("changes") or {}).keys()) == {"leverage"} and p.get("symbol")]
    newest = {}
    for p in sorted(pure, key=lambda x: str(x.get("ts") or "")):
        newest[p["symbol"]] = p
    n_sup = 0
    for p in pure:
        if p["id"] != newest[p["symbol"]]["id"]:
            await db.ai_proposals.update_one({"id": p["id"]}, {"$set": {
                "status": "superseded", "decided_at": now,
                "decision_note": "Auto (Migration): neuerer Hebel-Vorschlag vorhanden"}})
            n_sup += 1

    at = await db.settings.find_one({"_id": "autotrade_config"}) or {}
    coins = at.get("coins") or {}
    n_applied = n_kept = 0
    for sym, p in newest.items():
        scc = await db.strategy_coin_configs.find_one({"_id": f"ai_trader_{sym}"}) or {}
        merged = {**(coins.get(sym) or {}), **(scc.get("config") or {})}
        try:
            # Effektiv gefahrener Hebel: bei Auto-Hebel deckelt auto_lev_max.
            eff = (float(merged.get("auto_lev_max", 50) or 50)
                   if merged.get("auto_leverage_enabled")
                   else float(merged.get("leverage", 10) or 10))
            proposed = float((p.get("changes") or {}).get("leverage"))
        except (TypeError, ValueError):
            n_kept += 1
            continue
        if proposed < eff:
            await engine._apply_changes("coin", sym, {"leverage": proposed})
            await db.ai_proposals.update_one({"id": p["id"]}, {"$set": {
                "status": "applied", "decided_at": now,
                "decision_note": (f"Auto (Migration): Senkung {eff:g}x -> {proposed:g}x, "
                                  "Auto-Hebel deaktiviert")}})
            n_applied += 1
        else:
            n_kept += 1
    logger.info(f"Boot-Migration Hebel-Proposals: {n_applied} Senkungen angewendet "
                f"(Auto-Hebel je Coin aus), {n_sup} überholt, {n_kept} Erhöhungen "
                f"bleiben offen, {n_rej} zu restriktive abgelehnt")
    await _mark(db, "leverage_proposals_v1")


async def migrate_manual_lev_display(db):
    """Unmögliche Anzeige-Hebel reparieren: der Sync speicherte früher den aus
    der Marge abgeleiteten EFFEKTIVEN Hebel als 'leverage' (z.B. 333x nach
    Margen-Entnahme; Bitunix-Maximum ist 200x). Werte > 200 wandern nach
    effective_leverage, der Anzeige-Hebel wird auf 200 gedeckelt."""
    if await _done(db, "manual_lev_display_v1"):
        return
    rows = await db.auto_trades.find({"mode": "live", "leverage": {"$gt": 200}},
                                     {"id": 1, "leverage": 1}).to_list(1000)
    for t in rows:
        await db.auto_trades.update_one({"id": t["id"]}, {"$set": {
            "effective_leverage": t["leverage"], "leverage": 200}})
    if rows:
        logger.info(f"Boot-Migration: {len(rows)} Trades mit unmöglichem "
                    "Anzeige-Hebel (>200x) korrigiert")
    await _mark(db, "manual_lev_display_v1")


async def migrate_risk_sizing(db, engine):
    """Positionsgröße auf Risiko-Modus umstellen (User-Auftrag 02.09.2026).
    Befund: Live-Marge Median 8 USDT bei ~700 USDT Equity (Kette max_capital 30 ×
    capital_pct 20-30 % × ML 0,5) – Risiko ~0,1-0,5 USDT pro Trade, Fees/KI-
    Kosten unerreichbar. Neuer Standard: 2 % Equity-Risiko pro Trade, Marge-
    Deckel 15 %, Hebel bis 50x mit Liquidation hinter dem SL. Läuft nur, wenn
    der Trader sizing_mode noch nie selbst gesetzt hat."""
    if await _done(db, "risk_sizing_v1"):
        return
    doc = await db.settings.find_one({"_id": "ai_trader_config"}) or {}
    if "sizing_mode" not in doc:
        from services import position_sizing
        vals = {k: v for k, v in position_sizing.DEFAULTS.items() if k not in doc}
        vals["sizing_mode"] = "risk"
        await db.settings.update_one({"_id": "ai_trader_config"}, {"$set": vals}, upsert=True)
        if engine is not None:
            engine.config.update(vals)
        logger.info("Boot-Migration: KI-Positionsgröße -> Risiko-Modus "
                    f"({position_sizing.DEFAULTS['risk_per_trade_pct']:g}% Equity/Trade, Marge max "
                    f"{position_sizing.DEFAULTS['risk_max_margin_pct']:g}%, Hebel max "
                    f"{position_sizing.DEFAULTS['risk_max_leverage']}x)")
    await _mark(db, "risk_sizing_v1")


async def migrate_leverage_cap(db, engine):
    """Hebel-Deckel im Risiko-Modus 50x -> 15x (User-Auftrag 02.09.2026).
    Befund: seit risk_sizing_v1 liefen Live-Trades mit 50x; kleine Slippage ×
    50x = großer Verlust (SILVER -8,50 USDT in einem Trade). Läuft nur, wenn
    der Wert noch auf dem alten Migrations-Standard 50 steht."""
    if await _done(db, "leverage_cap_v1"):
        return
    doc = await db.settings.find_one({"_id": "ai_trader_config"}) or {}
    if int(doc.get("risk_max_leverage") or 0) == 50:
        from services import position_sizing
        new = int(position_sizing.DEFAULTS["risk_max_leverage"])
        await db.settings.update_one({"_id": "ai_trader_config"},
                                     {"$set": {"risk_max_leverage": new}}, upsert=True)
        if engine is not None:
            engine.config["risk_max_leverage"] = new
        logger.info(f"Boot-Migration: KI-Hebel-Deckel (Risiko-Modus) 50x -> {new}x")
    await _mark(db, "leverage_cap_v1")


async def migrate_data_recovery(db):
    """Vorfall 05./06.09.2026: Test-Lauf gegen die Produktiv-DB (MasterPrompt
    überschrieben, Test-Lektionen, Paper-Trades gelöscht). Einmalige, konservative
    Wiederherstellung (services/data_recovery.py) – idempotent, Report in
    settings.data_recovery.last_report bzw. GET /api/admin/recovery/report."""
    if await _done(db, "data_recovery_0906_v1"):
        return
    from services import data_recovery
    report = await data_recovery.run(db, dry_run=False)
    logger.info("Boot-Migration Data-Recovery: "
                f"MasterPrompt {'wiederhergestellt' if (report.get('master_prompt') or {}).get('restored') else 'unverändert'}, "
                f"{len((report.get('lessons') or {}).get('removed') or [])} Test-Lektionen entfernt, "
                f"{(report.get('paper_trades') or {}).get('recovered', 0)} Paper-Trades rekonstruiert")
    await _mark(db, "data_recovery_0906_v1")


async def migrate_strategy_lab_to_playbook(db):
    """Aufräumen 06.09.2026: Strategie-Labor hatte 33 Kandidaten und 0 Ghost-Trades
    (toter Pfad). Aktive Kandidaten werden Playbook-Setups (voller Lebenszyklus
    Paper -> Reife-Gate -> Live), Test-Kandidaten gelöscht, KI-Erzeugung + Autopilot
    aus (UI: KI-Labor -> Einstellungen, jederzeit wieder aktivierbar)."""
    if await _done(db, "strategy_lab_to_playbook_v1"):
        return
    from services.ai_strategy_lab import strategy_lab
    res = await strategy_lab.migrate_to_playbook()
    logger.info(f"Boot-Migration Strategie-Labor -> Playbook: {len(res['migrated'])} übernommen, "
                f"{len(res['skipped'])} nicht übernommen, {res['deleted_test']} Test-Kandidaten gelöscht")
    await _mark(db, "strategy_lab_to_playbook_v1")


async def migrate_observer_llm_off(db):
    """Markt-Beobachter ohne LLM (06.09.2026): seine Kurz-Einschätzung fließt in keine
    Handelsentscheidung ein (nur Status-Anzeige) – Feature-Berechnung bleibt komplett.
    Tages-Reporter bleibt beim LLM (1 Aufruf/Tag, Fallback wäre Qualitätsverlust)."""
    if await _done(db, "observer_llm_off_v1"):
        return
    doc = await db.settings.find_one({"_id": "ai_roles_config"}) or {}
    if (doc.get("market_observer") or {}).get("llm_summary"):
        await db.settings.update_one({"_id": "ai_roles_config"},
                                     {"$set": {"market_observer.llm_summary": False}})
        try:
            from services.ai_roles import role_manager
            await role_manager.load(db)
        except Exception as e:  # noqa: BLE001
            logger.debug(f"Rollen-Reload nach Migration: {e}")
        logger.info("Boot-Migration: Markt-Beobachter LLM-Kurz-Einschätzung AUS (rein datengetrieben)")
    await _mark(db, "observer_llm_off_v1")


async def migrate_ml_findings_decouple(db):
    """06.09.2026: ML-Befunde raus aus dem KI-Gedächtnis (2 465 `ml_finding` in ai_knowledge,
    Prompt-Rauschen ohne Entscheidungsnutzen) -> eigene Collection `ml_findings`,
    sichtbar nur im ML-Labor-Report (GET /api/ai/ml/findings)."""
    if await _done(db, "ml_findings_decouple_v1"):
        return
    from services import ml_findings
    n = await ml_findings.migrate_from_memory(db)
    logger.info(f"Boot-Migration ML-Befunde: {n} Einträge aus ai_knowledge nach ml_findings verschoben")
    await _mark(db, "ml_findings_decouple_v1")


TEST_STRATEGY_RE = r"test"


async def cleanup_test_artifacts(db) -> Dict:
    """Signale verwaister Test-Strategien (id enthält 'test', Strategie existiert nicht mehr)
    und die versehentlich als 'db.ai_lesson_candidates' benannte Collection entfernen."""
    out = {"signals": 0, "strategies": [], "dropped": []}
    known = {s.get("id") for s in await db.strategies.find({}, {"id": 1}).to_list(5000)}
    cur = db.signals.find({"strategy_id": {"$regex": TEST_STRATEGY_RE, "$options": "i"}}, {"strategy_id": 1})
    orphan = {s.get("strategy_id") for s in await cur.to_list(100000)} - known
    for sid in sorted(x for x in orphan if x):
        r = await db.signals.delete_many({"strategy_id": sid})
        out["signals"] += r.deleted_count
        out["strategies"].append(sid)
    names = await db.list_collection_names()
    for bad in [n for n in names if n.startswith("db.")]:
        await db.drop_collection(bad)
        out["dropped"].append(bad)
    return out


async def migrate_test_artifacts(db):
    if await _done(db, "test_artifacts_cleanup_v1"):
        return
    out = await cleanup_test_artifacts(db)
    logger.info(f"Boot-Migration Alt-Artefakte: {out['signals']} Signale von {out['strategies']} "
                f"gelöscht, Collections entfernt: {out['dropped']}")
    await _mark(db, "test_artifacts_cleanup_v1")


async def migrate_fee_guard_relax(db, engine):
    """Fee-Wächter lockern: alte Defaults 4× (Fees/ATR) -> 2.5×. Nutzer-Feedback:
    zu streng – reale Bitunix-Gebühren liegen durch VIP-Level/Voucher niedriger.
    Nur Werte migrieren, die noch exakt auf dem alten Default 4.0 stehen –
    explizit abweichende Nutzer-Werte bleiben unangetastet."""
    if await _done(db, "fee_guard_relax_v1"):
        return
    doc = await db.settings.find_one({"_id": "ai_trader_config"}) or {}
    updates = {}
    for key in ("fee_guard_mult", "fee_guard_atr_mult"):
        v = doc.get(key)
        try:
            if v is not None and float(v) == 4.0:
                updates[key] = 2.5
        except (TypeError, ValueError):
            pass
    if updates:
        await db.settings.update_one({"_id": "ai_trader_config"},
                                     {"$set": updates}, upsert=True)
        if engine is not None:
            engine.config.update(updates)
        logger.info(f"Boot-Migration: Fee-Wächter gelockert {updates} "
                    "(im KI-Setup jederzeit änderbar)")
    await _mark(db, "fee_guard_relax_v1")


async def migrate_risk_usdt_backfill(db):
    """R in Geld (Audit 2.3): `risk_usdt = risk × qty` für alle bestehenden
    auto_trades nachtragen. `risk` ist die Preisdistanz Entry->initialer SL pro
    Einheit – erst ×qty wird daraus riskiertes Kapital in USDT. Einmalig."""
    if await _done(db, "risk_usdt_backfill_v1"):
        return
    res = await db.auto_trades.update_many(
        {"risk_usdt": {"$exists": False}, "risk": {"$gt": 0}, "qty": {"$gt": 0}},
        [{"$set": {"risk_usdt": {"$round": [{"$multiply": ["$risk", "$qty"]}, 6]}}}])
    logger.info(f"Boot-Migration: risk_usdt für {res.modified_count} Trades nachgetragen")
    await _mark(db, "risk_usdt_backfill_v1")


async def migrate_setup_backtest_edges(db):
    """Edge-Register (09/2026): früher bestandene Backtest-Sätze aus dem Verlauf
    von settings.setup_backtest_state rückwirkend ins Register holen; Setups,
    deren Edge durch spätere Fehlläufe überschrieben wurde, bekommen den
    robustesten Satz zurück (nächster Lauf prüft ihn zuerst). Einmalig."""
    if await _done(db, "setup_backtest_edges_v1"):
        return
    from services.setup_backtest import edges
    res = await edges.recover_from_history(db, activate_best=True)
    logger.info(f"Boot-Migration: Edge-Register – {res['imported']} Edges importiert, "
                f"reaktiviert: {', '.join(res['activated']) or 'keine'}")
    await _mark(db, "setup_backtest_edges_v1")


async def migrate_lesson_attribution_backfill(db):
    """PLAN_LEKTIONS_BILANZ A3: `applied_lessons` aus ai_decisions an bestehende
    auto_trades mit decision_id nachziehen (nur wo die Entscheidung das Feld hat)."""
    key = "lesson_attribution_backfill_v1"
    if await _done(db, key):
        return
    n = 0
    cur = db.auto_trades.find({"decision_id": {"$exists": True, "$ne": None},
                               "applied_lessons": {"$exists": False}},
                              {"_id": 0, "id": 1, "decision_id": 1})
    async for t in cur:
        dec = await db.ai_decisions.find_one({"id": t["decision_id"], "applied_lessons": {"$exists": True}},
                                             {"_id": 0, "applied_lessons": 1})
        if dec and dec.get("applied_lessons"):
            await db.auto_trades.update_one({"id": t["id"]},
                                            {"$set": {"applied_lessons": dec["applied_lessons"]}})
            n += 1
    await _mark(db, key)
    logger.info(f"Boot-Migration {key}: {n} Trades mit Lektions-Attribution nachgezogen")


async def migrate_regime_history_import(db):
    """10/2026: alte Regime-Analysen (z.B. „sehr gut, 9 Regime“) einmalig als
    gemerkte Referenzen in den Autopilot-Verlauf übernehmen (idempotent)."""
    key = "regime_history_import_v1"
    if await _done(db, key):
        return
    from services import regime_history_import
    res = await regime_history_import.import_existing(db)
    await _mark(db, key)
    logger.info(f"Boot-Migration {key}: {res['imported']} Analysen in den Autopilot-Verlauf übernommen")


async def migrate_evidence_gates(db, engine):
    """Analyse 15.11.2026 (6.1): strengere Standardwerte in gespeicherte
    KI-Konfigurationen übernehmen – NUR wo noch der unveränderte Alt-Standard
    steht (ein vom Trader gesetzter Wert wird nie überschrieben):
      signal_min_ki_trades 5 -> 30   (Live-Tor des Signal-Brokers)
      risk_per_trade_pct  2.0 -> 1.0 (Risiko je Trade)
    signal_live_z ist ein neuer Schlüssel und greift ohne Migration."""
    if await _done(db, "evidence_gates_v1"):
        return
    from services import position_sizing, signal_broker
    doc = await db.settings.find_one({"_id": "ai_trader_config"}) or {}
    upd = {}
    try:
        if int(doc.get("signal_min_ki_trades") or 0) == 5:
            upd["signal_min_ki_trades"] = int(signal_broker.DEFAULTS["signal_min_ki_trades"])
        if float(doc.get("risk_per_trade_pct") or 0) == 2.0:
            upd["risk_per_trade_pct"] = float(position_sizing.DEFAULTS["risk_per_trade_pct"])
    except (TypeError, ValueError):
        upd = {}
    if upd:
        await db.settings.update_one({"_id": "ai_trader_config"}, {"$set": upd}, upsert=True)
        if engine is not None:
            engine.config.update(upd)
        logger.info(f"Boot-Migration: strengere Evidenz-/Risiko-Standards übernommen: {upd}")
    await _mark(db, "evidence_gates_v1")


FEE_GUARD_MULT_V2 = 10.0


async def migrate_cost_guard(db, engine):
    """Stufe 1 (Trade-Analyse 15.11.2026, Freigabe des Traders): Gebühren
    fraßen im Schnitt 0,18 R je KI-Trade; nur Trades mit Gebühren <= 0,1 R
    lagen nahe Null. Der Fee-Wächter verlangt deshalb SL >= 10 × Roundtrip-Fee
    (= Gebühr <= 10 % des Risikos, passend zu edge_filter_max_fee_r 0,10).
    Werte UNTER 10 werden einmalig angehoben (strengere Werte bleiben), und die
    Autotune-Basis wird auf den neuen Wert gesetzt – sonst zöge Autotune ihn
    wegen seiner ±1,5-Leitplanke zurück zur alten Basis."""
    if await _done(db, "cost_guard_v1"):
        return
    from services import guard_shadow
    doc = await db.settings.find_one({"_id": "ai_trader_config"}) or {}
    upd = {}
    try:
        cur = float(doc.get("fee_guard_mult") if doc.get("fee_guard_mult") is not None else 0)
    except (TypeError, ValueError):
        cur = 0.0
    if cur < FEE_GUARD_MULT_V2:
        upd["fee_guard_mult"] = FEE_GUARD_MULT_V2
    if upd:
        await db.settings.update_one({"_id": "ai_trader_config"}, {"$set": upd}, upsert=True)
        if engine is not None:
            engine.config.update(upd)
        logger.info(f"Boot-Migration: Kosten-Wächter verschärft {cur:g} -> {upd}")
    try:
        cfg = {**doc, **upd}
        base = {k: float(cfg.get(k, 2.5) or 2.5) for k in guard_shadow.BOUNDS}
        await db.settings.update_one({"_id": guard_shadow.STATE_ID},
                                     {"$set": {"baseline": base}}, upsert=True)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Boot-Migration cost_guard: Autotune-Basis nicht gesetzt: {e}")
    await _mark(db, "cost_guard_v1")


async def migrate_lesson_cleanup(db):
    """Stufe 1: Lektions-Bestand einmalig bereinigen (services/lesson_cleanup).
    LessonStore.save_all sichert den alten Stand in ai_lessons_history."""
    if await _done(db, "lesson_cleanup_v1"):
        return
    from services import ai_lessons, lesson_cleanup
    store = ai_lessons.LessonStore()
    store.setup(db)
    doc = await db.settings.find_one({"_id": ai_lessons.DOC_ID}) or {}
    old = ai_lessons.normalize_all(doc.get("lessons"))
    if old:
        new, log = lesson_cleanup.plan(old)
        if log["removed"] or log["merged"]:
            await store.save_all(new)
            logger.info(f"Boot-Migration: Lektionen bereinigt {len(old)} -> {len(new)} "
                        f"(entfernt {len(log['removed'])}, zusammengeführt "
                        f"{sum(len(v) for v in log['merged'].values())} -> "
                        f"{len(log['added'])})")
            try:
                await db.ai_chat.insert_one({
                    "id": f"lc_{datetime.now(timezone.utc).timestamp():.0f}",
                    "role": "governance", "ts": datetime.now(timezone.utc).isoformat(),
                    "text": (f"Lektionen bereinigt: {len(old)} -> {len(new)}. Entfernt: "
                             f"{len(log['removed'])} (Margen-Regime-Regeln, Sperren der "
                             f"Datensammlung, Widersprüche). Zusammengeführt zu: "
                             f"{', '.join(log['added'])}. Alter Stand in der Lektionen-"
                             f"Historie wiederherstellbar.")})
            except Exception:  # noqa: BLE001
                pass
    await _mark(db, "lesson_cleanup_v1")


def revalidate_event_result(doc: Dict) -> Dict:
    """Gespeichertes Event-Backtest-Ergebnis mit den neuen Regeln neu bewerten
    (rein): Slippage nachträglich abziehen (falls noch nicht enthalten) und
    auf Event-Ebene validieren. Liefert das aktualisierte Dokument."""
    from services import fomc_backtest as fb
    out = dict(doc)
    slip = fb.NOTIONAL * fb.SLIPPAGE_RT
    trades = [dict(t) for t in (doc.get("trades") or [])]
    per_event = {k: dict(v) for k, v in (doc.get("per_event") or {}).items()}
    if not doc.get("slippage_included"):
        for t in trades:
            t["pnl"] = round(float(t.get("pnl") or 0) - slip, 2)
        for v in per_event.values():
            v["pnl"] = round(float(v.get("pnl") or 0) - slip * int(v.get("trades") or 0), 2)
    agg = fb.aggregate(trades, sorted(per_event))
    agg["events"] = fb.event_stats(per_event, agg["oos_events"])
    ok, why = fb.validated(agg, ai_params=bool(doc.get("ai_params")))
    out.update({"trades": trades, "per_event": per_event, "aggregate": agg,
                "validated": ok, "validation_reason": why, "slippage_included": True})
    return out


async def migrate_event_revalidation(db):
    """Stufe 1: Event-Setups (FOMC/CPI/NFP/PPI/PCE) nach den neuen Regeln
    (Slippage + Event-Ebene + keine KI-Parameter) neu bewerten – ohne neuen
    Daten-Download, aus den gespeicherten Backtest-Ergebnissen."""
    if await _done(db, "event_revalidation_v1"):
        return
    from services import econ_backtest, econ_event, event_assets, fomc_backtest, fomc_event
    jobs = [("fomc", None)] + [(k, econ_event.get(k)) for k in fomc_backtest_keys()]
    for key, ev in jobs:
        for cls in event_assets.CLASSES:
            rid = (fomc_backtest.RESULT_ID + event_assets.result_suffix(cls) if key == "fomc"
                   else econ_backtest.result_id(key, cls))
            doc = await db.settings.find_one({"_id": rid})
            if not doc or not doc.get("per_event"):
                continue
            doc.pop("_id", None)
            new = revalidate_event_result(doc)
            await db.settings.update_one({"_id": rid}, {"$set": new})
            agg = new["aggregate"]
            details = {"trades": agg["total"]["trades"], "pnl": agg["total"]["pnl"],
                       "oos_pnl": agg["out_of_sample"]["pnl"], "events": agg["events"]}
            if key == "fomc":
                await fomc_event.set_validation(db, cls, new["validated"],
                                                new["validation_reason"], details)
            elif ev is not None:
                await ev.set_validation(db, cls, new["validated"],
                                        new["validation_reason"], details)
            logger.info(f"Boot-Migration Event-Neubewertung {key}/{cls}: "
                        f"validiert={new['validated']} ({new['validation_reason']})")
    await _mark(db, "event_revalidation_v1")


def fomc_backtest_keys():
    from services import econ_backtest
    return list(econ_backtest.FIXED)


async def migrate_ai_role_pruefer(db, engine):
    """Stufe 3: KI-Rolle einmalig von „frei“ auf „Prüfer“ umstellen (Freigabe
    des Traders). Danach gilt die gespeicherte Wahl – „frei“ bleibt wählbar."""
    if await _done(db, "ai_role_pruefer_v1"):
        return
    doc = await db.settings.find_one({"_id": "ai_trader_config"}) or {}
    if doc.get("ai_role") in (None, "frei"):
        await db.settings.update_one({"_id": "ai_trader_config"},
                                     {"$set": {"ai_role": "pruefer"}}, upsert=True)
        if engine is not None:
            engine.config["ai_role"] = "pruefer"
        logger.info("Boot-Migration: KI-Rolle frei -> Prüfer")
    await _mark(db, "ai_role_pruefer_v1")


async def migrate_evaluation_since(db):
    """Phase A (15.11.2026): Bewertungs-Stichtag einmalig auf den Start der
    Kostenregeln setzen (Marker cost_guard_v1_at, sonst jetzt). Lernlauf,
    Live-Tore und Bilanzen zählen ab dann; Trades bleiben gespeichert."""
    if await _done(db, "evaluation_since_v1"):
        return
    from services import evaluation_cutoff
    since = await evaluation_cutoff.ensure_default(db)
    try:
        await db.ai_chat.insert_one({
            "id": f"es_{datetime.now(timezone.utc).timestamp():.0f}",
            "role": "governance", "ts": _now_iso(),
            "text": (f"Bewertungs-Stichtag gesetzt: {str(since)[:16].replace('T', ' ')} UTC. "
                     "Lernlauf, Live-Tore, Lektions- und Veto-Bilanz zählen nur noch Trades "
                     "unter den neuen Kostenregeln. Nichts gelöscht – im Leitstand änderbar.")})
    except Exception:  # noqa: BLE001
        pass
    await _mark(db, "evaluation_since_v1")


async def migrate_lesson_candidates_recheck(db):
    """Phase A: Lektions-Kandidaten nachprüfen (services/lesson_cleanup.
    recheck_candidates). Problemfälle/Doppelungen -> ai_lesson_candidates_archive
    (wiederherstellbar), alte Bestätigungen gedeckelt. Nichts endgültig gelöscht."""
    if await _done(db, "lesson_candidates_recheck_v1"):
        return
    from services import ai_lessons, evaluation_cutoff, lesson_cleanup
    cands = await db.ai_lesson_candidates.find({}, {"_id": 0}).to_list(500)
    doc = await db.settings.find_one({"_id": ai_lessons.DOC_ID}) or {}
    active = ai_lessons.normalize_all(doc.get("lessons"))
    since = evaluation_cutoff.cached_since() or (await evaluation_cutoff.load(db))
    updates, archive = lesson_cleanup.recheck_candidates(cands, active, since)
    now = _now_iso()
    for a in archive:
        a = {**a, "archived_at": now}
        await db.ai_lesson_candidates_archive.update_one({"key": a.get("key")}, {"$set": a},
                                                         upsert=True)
        await db.ai_lesson_candidates.delete_one({"key": a.get("key")})
    for u in updates:
        await db.ai_lesson_candidates.update_one({"key": u["key"]}, {"$set": u["set"]})
    if archive or updates:
        logger.info(f"Boot-Migration: Lektions-Kandidaten geprüft – {len(archive)} archiviert, "
                    f"{len(updates)} brauchen frische Bestätigung")
        try:
            await db.ai_chat.insert_one({
                "id": f"lcr_{datetime.now(timezone.utc).timestamp():.0f}",
                "role": "governance", "ts": now,
                "text": (f"Lektions-Kandidaten geprüft: {len(archive)} ins Archiv (Qualitätsproblem "
                         f"oder Doppelung einer aktiven Lektion), {len(updates)} brauchen eine "
                         "Bestätigung mit Trades nach dem Stichtag. Archiv wiederherstellbar.")})
        except Exception:  # noqa: BLE001
            pass
    await _mark(db, "lesson_candidates_recheck_v1")


async def migrate_live_bypass_off(db, engine):
    """Phase A (Freigabe des Traders 15.11.2026): Live-Bypass bei hoher Konfidenz
    einmalig AUS. Befund: die Konfidenz trennt gute und schlechte Trades nicht
    (services/confidence_calibration) – der Bypass ließ nicht belegte Setups mit
    Echtgeld handeln. Paper-Handel und Datensammlung laufen unverändert weiter;
    der Schalter bleibt im KI-Panel, eine spätere Entscheidung wird respektiert."""
    if await _done(db, "live_bypass_off_v1"):
        return
    doc = await db.settings.find_one({"_id": "ai_trader_config"}) or {}
    if doc.get("live_gate_bypass_enabled"):
        await db.settings.update_one({"_id": "ai_trader_config"},
                                     {"$set": {"live_gate_bypass_enabled": False}}, upsert=True)
        if engine is not None:
            engine.config["live_gate_bypass_enabled"] = False
        logger.info("Boot-Migration: Live-Bypass bei hoher Konfidenz ausgeschaltet")
        try:
            await db.ai_chat.insert_one({
                "id": f"lb_{datetime.now(timezone.utc).timestamp():.0f}",
                "role": "governance", "ts": _now_iso(),
                "text": ("Live-Bypass bei hoher Konfidenz ausgeschaltet: die Konfidenz sagt "
                         "nachweislich nichts über das Ergebnis. Live geht nur, was belegt ist; "
                         "Paper-Handel läuft weiter. Wieder einschaltbar im KI-Panel.")})
        except Exception:  # noqa: BLE001
            pass
    await _mark(db, "live_bypass_off_v1")


LAB_WEEKLY = {"enabled": True, "interval_hours": 168, "mode": "loop", "ai_revise": True, "ai_rounds": 2}


async def migrate_lab_auto_weekly(db):
    """Phase C (Freigabe 15.11.2026): Lab-Automatik wöchentlich wieder an – seit
    11/2026 mit ehrlicher Validierung (Signifikanz, Wahl nach Trainingsdaten,
    Abgleich mit echten Paper-Trades) und begrenzten KI-Revisionen (2 Runden).
    Nur wenn sie aus ist; eine spätere Entscheidung des Traders bleibt."""
    if await _done(db, "lab_auto_weekly_v1"):
        return
    from services.setup_backtest import auto as seed_auto
    cur = await seed_auto.get(db)
    if not cur.get("enabled"):
        await seed_auto.save(db, LAB_WEEKLY)
        # Erster Lauf nachts um 2 Uhr (Berlin) statt direkt nach dem Deploy –
        # dann wöchentlich zur selben Zeit (is_due rechnet ab last_run_at).
        try:
            from datetime import timedelta
            from zoneinfo import ZoneInfo
            berlin = ZoneInfo("Europe/Berlin")
            now_l = datetime.now(berlin)
            first = now_l.replace(hour=2, minute=0, second=0, microsecond=0)
            if first <= now_l:
                first += timedelta(days=1)
            anchor_ts = (first - timedelta(hours=LAB_WEEKLY["interval_hours"])).astimezone(timezone.utc)
            await db.settings.update_one({"_id": seed_auto.STATE_ID},
                                         {"$set": {"auto.last_run_at": anchor_ts.isoformat()}})
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Lab-Automatik: Startzeit nicht gesetzt: {e}")
        try:
            await db.ai_chat.insert_one({
                "id": f"law_{datetime.now(timezone.utc).timestamp():.0f}",
                "role": "governance", "ts": _now_iso(),
                "text": ("KI-Trader-Lab: Automatik wöchentlich eingeschaltet (ehrliche Prüfung, "
                         "2 KI-Revisionsrunden). Abschaltbar im KI-Trader-Lab.")})
        except Exception:  # noqa: BLE001
            pass
        logger.info("Boot-Migration: Lab-Automatik wöchentlich eingeschaltet")
    await _mark(db, "lab_auto_weekly_v1")


async def migrate_explore_pool_fix(db):
    """16.11.2026: Im Multi-Core-Pool des lokalen Workers liefen Test und Tresor
    der Endlossuche auf den Trainingsdaten (parallel_sim.pool_has_data). Champions
    davor sind ungeprüft: Bestenliste trennt sie über deep_explore.is_validated;
    Kandidaten daraus werden verworfen (erneut testbar, nichts gelöscht)."""
    if await _done(db, "explore_pool_fix_v1"):
        return
    from services import deep_explore, research_pipeline
    now = _now_iso()
    rows = await db[research_pipeline.COLLECTION].find(
        {"kind": "champion", "stage": "vorwaertstest"}, {"_id": 0, "id": 1, "search_evidence": 1}).to_list(200)
    n = 0
    for c in rows:
        eng = (c.get("search_evidence") or {}).get("engine") or 0
        if int(eng) >= deep_explore.EXPLORE_ENGINE:
            continue
        await db[research_pipeline.COLLECTION].update_one({"id": c["id"]}, {"$set": {
            "stage": "verworfen", "updated_at": now,
            "note": "vor dem Testdaten-Fix gefunden (Test lief auf Trainingsdaten) – bei Bedarf erneut testen"}})
        n += 1
    try:
        await db.ai_chat.insert_one({
            "id": f"epf_{datetime.now(timezone.utc).timestamp():.0f}", "role": "governance", "ts": now,
            "text": ("Endlossuche repariert: Auf dem lokalen Worker mit mehreren Kernen liefen Test und "
                     "Tresor versehentlich auf den Trainingsdaten. Champions aus älteren Läufen sind ungeprüft "
                     f"und stehen im Altbestand; {n} Kandidat(en) daraus verworfen. Worker 1.30.0 nötig.")})
    except Exception:  # noqa: BLE001
        pass
    await _mark(db, "explore_pool_fix_v1")


async def migrate_collection_direction_10(db, engine):
    """F2 (17.11.2026): Richtungs-Limit der Lern-Trades (Paper, ohne Kapital)
    einmalig von 5 auf 10 je Anlageklasse. Befund: 133 geblockte Signale in 24 h
    gegenüber 34 eröffneten Lern-Trades – dem Veto-Vergleich und den Setups
    fehlten damit die meisten Daten. Ein bewusst anders gesetzter Wert bleibt."""
    if await _done(db, "collection_direction_10_v1"):
        return
    doc = await db.settings.find_one({"_id": "ai_trader_config"}) or {}
    cur = doc.get("collection_max_same_direction")
    if cur is None or int(cur) == 5:
        await db.settings.update_one({"_id": "ai_trader_config"},
                                     {"$set": {"collection_max_same_direction": 10}}, upsert=True)
        if engine is not None:
            engine.config["collection_max_same_direction"] = 10
        logger.info("Boot-Migration: Richtungs-Limit der Lern-Trades 5 -> 10")
    await _mark(db, "collection_direction_10_v1")


async def migrate_champion_checks_v3(db):
    """F1/F3 (17.11.2026): strengere Champion-Prüfung (Prüf-Stand 3) und
    Trendfolge-Vorgaben. Kandidaten älterer Prüf-Stände im Vorwärtstest werden
    verworfen (erneut testbar, nichts gelöscht); die Vorgaben werden einmalig
    als Kandidaten für den Vorwärtstest angelegt (kein Kapital, keine Strategie)."""
    if await _done(db, "champion_checks_v3"):
        return
    from services import deep_explore, research_pipeline
    now = _now_iso()
    rows = await db[research_pipeline.COLLECTION].find(
        {"kind": "champion", "stage": "vorwaertstest"}, {"_id": 0, "id": 1, "search_evidence": 1}).to_list(200)
    n = 0
    for c in rows:
        eng = (c.get("search_evidence") or {}).get("engine") or 0
        if int(eng) >= deep_explore.EXPLORE_ENGINE:
            continue
        await db[research_pipeline.COLLECTION].update_one({"id": c["id"]}, {"$set": {
            "stage": "verworfen", "updated_at": now,
            "note": "vor der strengeren Prüfung (Rückwärtstest, Versuchs-Konto) gefunden – bei Bedarf erneut testen"}})
        n += 1
    added = 0
    try:
        added = await research_pipeline.ensure_presets(db)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Trend-Vorgaben nicht angelegt: {e}")
    try:
        await db.ai_chat.insert_one({
            "id": f"cc3_{datetime.now(timezone.utc).timestamp():.0f}", "role": "governance", "ts": now,
            "text": ("Endlossuche prüft strenger: Rückwärtstest auf älteren Daten, Versuchs-Konto über Läufe, "
                     "Tresor mit Ø R. Worker 1.31.0 nötig. "
                     f"{added} Trendfolge-Vorgabe(n) laufen jetzt im Vorwärtstest (ohne Kapital)."
                     + (f" {n} ältere Kandidat(en) verworfen." if n else ""))})
    except Exception:  # noqa: BLE001
        pass
    await _mark(db, "champion_checks_v3")


async def migrate_decisions_1711(db):
    """Entscheidungen vom 17.11.2026 (Auftrag des Traders: „nach bestem Wissen
    und Gewissen umsetzen“), jeweils einmalig und im Leitstand rückstellbar:

    1. Live-Wächter schaltet automatisch um: Strategien, die mit Echtgeld
       NACHWEISLICH verlieren (≥ 50 Live-Trades, Obergrenze des Ø R < 0), laufen
       auf Paper weiter. Betrifft aktuell TrendFolge2 (352 Live-Trades, Ø −0,13 R).
       Es wird nichts gelöscht, Paper-Daten laufen weiter.
    2. Trend-Basis 4h ist nicht mehr per Klick als Paper-Strategie startbar:
       der Live-Scanner bräuchte dafür 21 Tage Minutenkerzen je Asset im Speicher
       (Absturz-Risiko auf Render). Der Vorwärtstest läuft unverändert weiter."""
    if await _done(db, "decisions_1711_v1"):
        return
    from services import live_watchdog, research_pipeline
    try:
        await live_watchdog.set_config(db, {"auto_pause": True})
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Live-Wächter nicht umstellbar: {e}")
    await db[research_pipeline.COLLECTION].update_many(
        {"ref": "preset:trend_basis_4h", "stage": "vorwaertstest"},
        {"$set": {"adoptable": False, "updated_at": _now_iso()}})
    try:
        await db.ai_chat.insert_one({
            "id": f"d1711_{datetime.now(timezone.utc).timestamp():.0f}", "role": "governance", "ts": _now_iso(),
            "text": ("Live-Wächter schaltet ab jetzt selbst um: Strategien, die mit Echtgeld nachweislich "
                     "verlieren (mind. 50 Live-Trades), laufen auf Paper weiter. Abschaltbar im Leitstand "
                     "unter Fortschritt. KI-Team: Modelle je Aufgabe neu gesetzt (Aufgaben-Team v2).")})
    except Exception:  # noqa: BLE001
        pass
    await _mark(db, "decisions_1711_v1")


async def migrate_portfolio_universe_64(db):
    """Portfolio: gespeicherte Coin-Liste von 26 auf 64 Coins erweitern – nur wenn
    sie noch genau die alte Standardliste ist (eigene Auswahl bleibt)."""
    if await _done(db, "portfolio_universe_64_v1"):
        return
    from services import portfolio_engine as pe
    doc = await db.settings.find_one({"_id": pe.CONFIG_ID}) or {}
    if doc.get("symbols") and sorted(doc["symbols"]) == sorted(pe.UNIVERSE_26):
        await db.settings.update_one({"_id": pe.CONFIG_ID}, {"$set": {"symbols": list(pe.UNIVERSE)}})
        logger.info("Boot-Migration: Portfolio-Universum 26 -> 64 Coins")
    await _mark(db, "portfolio_universe_64_v1")


async def run_boot_migrations(db, engine):
    for fn, args in ((migrate_evidence_gates, (db, engine)),
                     (migrate_cerebras_shutdown, (db,)),
                     (migrate_heatmap_off, (db, engine)),
                     (migrate_slippage_artifacts, (db,)),
                     (migrate_leverage_proposals, (db, engine)),
                     (migrate_manual_lev_display, (db,)),
                     (migrate_risk_sizing, (db, engine)),
                     (migrate_leverage_cap, (db, engine)),
                     (migrate_data_recovery, (db,)),
                     (migrate_strategy_lab_to_playbook, (db,)),
                     (migrate_observer_llm_off, (db,)),
                     (migrate_ml_findings_decouple, (db,)),
                     (migrate_test_artifacts, (db,)),
                     (migrate_fee_guard_relax, (db, engine)),
                     (migrate_cost_guard, (db, engine)),
                     (migrate_lesson_cleanup, (db,)),
                     (migrate_event_revalidation, (db,)),
                     (migrate_ai_role_pruefer, (db, engine)),
                     (migrate_evaluation_since, (db,)),
                     (migrate_lesson_candidates_recheck, (db,)),
                     (migrate_live_bypass_off, (db, engine)),
                     (migrate_lab_auto_weekly, (db,)),
                     (migrate_explore_pool_fix, (db,)),
                     (migrate_champion_checks_v3, (db,)),
                     (migrate_collection_direction_10, (db, engine)),
                     (migrate_decisions_1711, (db,)),
                     (migrate_portfolio_universe_64, (db,)),
                     (migrate_risk_usdt_backfill, (db,)),
                     (migrate_setup_backtest_edges, (db,)),
                     (migrate_lesson_attribution_backfill, (db,)),
                     (migrate_regime_history_import, (db,))):
        try:
            await fn(*args)
        except Exception as e:
            logger.error(f"Boot-Migration {fn.__name__} fehlgeschlagen: {e}")
    # Portfolio live: offene Positionen in den Eigentums-Cache laden, damit der
    # Positions-Wächter sie gleich nach dem Start in Ruhe lässt.
    try:
        from services import portfolio_live
        await portfolio_live.load_owned(db)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Portfolio-live-Cache nicht geladen: {e}")
    # Bewertungs-Stichtag bei JEDEM Start in den Prozess-Cache laden (auch
    # synchrone Stellen wie ai_playbook._stats_match nutzen ihn).
    try:
        from services import evaluation_cutoff
        await evaluation_cutoff.load(db)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Bewertungs-Stichtag nicht geladen: {e}")
