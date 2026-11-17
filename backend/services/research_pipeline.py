"""Kandidaten-Pipeline (Phase C, 15.11.2026): Fund -> Vorwärtstest -> Urteil.

Ein Champion der Endlossuche hat die ehrliche Prüfung bestanden (Signifikanz,
Tresor-Daten) – trotzdem ist er erst ein KANDIDAT. Der Vorwärtstest prüft ihn
automatisch auf Kursdaten, die es beim Fund noch gar nicht gab (echter
Blick in die Zukunft, ohne Kapital und ohne neue Strategie in der Liste):
gleiche Regeln, gleiche Trade-Einstellungen, Einstiege erst ab dem Fundzeitpunkt.

Urteil (gleicher Maßstab wie die Live-Tore, setup_lifecycle):
  * bestanden: ≥ FORWARD_MIN_TRADES Vorwärts-Trades und vorsichtige Untergrenze
    (Ø R − 1,64·SE) > 0  -> Empfehlung im Leitstand „als Strategie übernehmen
    und im Paper-Betrieb laufen lassen“ (ein Klick, Entscheidung des Traders)
  * durchgefallen: genug Trades und Ø R < 0, oder Obergrenze < 0
  * abgelaufen: nach FORWARD_MAX_DAYS ohne klares Urteil
Live geht ein Kandidat NIE automatisch – Übernehmen legt nur die Strategie an.

KI-Setups und Lab-Setups laufen ohnehin im Paper-Betrieb (Datensammlung);
ihr Fortschritt bis zum Live-Tor wird in `setup_progress` mitgeliefert.
"""
import asyncio
import logging
import math
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

COLLECTION = "research_candidates"
FORWARD_MIN_TRADES = 30
FORWARD_MAX_DAYS = 120
FORWARD_EVERY_H = 24 * 3          # Vorwärtstest höchstens alle 3 Tage je Kandidat
MAX_ACTIVE = 8
PRESET_MAX_DAYS = 365             # Vorgaben handeln selten – sie bekommen mehr Zeit

# ---------------------------------------------------------------------------
# Vorgaben (F3, 17.11.2026): fest vorab festgelegte Strategien aus der Fachliteratur.
# Sie stammen NICHT aus einer Suche – deshalb gibt es kein Vielfach-Test-Problem.
# Beleg (eigene Rechnung auf echten Binance-Tagesdaten/4h-Daten, 26 Coins, mit
# Gebühren 0,08 % je Seite und Funding, docs/UMSETZUNG_ZIEL_2026-11-17.md):
#   Ausbruch über das 20-Tage-Hoch, Stop 2 ATR, Trail 3 ATR (Tageskerzen):
#     1.669 Trades seit 2018, Ø +0,34 R, t 4,6; 2025–26 aber nur ±0 R.
#   10-Tage-Ausbruch auf 4h: 3.677 Trades seit 2021, Ø +0,20 R, t 3,6.
#   Kürzere Horizonte (3–5 Tage): nur noch +0,06 R – je kürzer, desto schwächer.
# Der Vorteil kam fast ganz von der Long-Seite (Short ≈ 0 R). Beide Seiten bleiben
# trotzdem drin: „nur Long“ wäre eine Auswahl im Rückblick.
# ---------------------------------------------------------------------------
_TREND_EXIT = {"sl_mode": "atr", "tp1_crv": 30.0, "tp_full_crv": 40.0, "tp1_close_percent": 50,
               "breakeven_enabled": False, "be_mode": "off", "trail_after_tp1": True,
               "trail_mode": "crv", "trail_trigger_crv": 0.5, "trail_start_be": False}


def _trend_definition(name: str, period: int) -> Dict:
    return {"name": name, "indicators": {"donchian_period": int(period)},
            "long_rules": [{"indicator": "price", "op": "cross_above", "value": "donchian_high"}],
            "short_rules": [{"indicator": "price", "op": "cross_below", "value": "donchian_low"}]}


PRESETS = (
    {"key": "trend_basis_4h", "title": "Trend-Basis 4h (10-Tage-Ausbruch, ATR-Stop, Trail)",
     # adoptable=False (17.11.2026): Der Live-Scanner müsste für 4h-Kerzen 21 Tage
     # Minutenkerzen JE Asset im Speicher halten (statt ~2,5 Tage) – auf Render ein
     # echtes Absturz-Risiko. Der Vorwärtstest läuft ohne das (Simulation).
     "timeframe": "4h", "adoptable": False, "warmup_days": 20,
     "definition": _trend_definition("Trend-Basis 4h", 60),
     "trade_params": {**_TREND_EXIT, "atr_period": 30, "atr_sl_multiplier": 3.0, "trail_atr_mult": 5.0},
     "evidence": {"trades": 3677, "avg_r": 0.20, "t": 3.6, "since": "2021",
                  "recent": "2025–26: −0,06 R; letzte 12 Monate +0,09 R"}},
    {"key": "trend_basis_1d", "title": "Trend-Basis 1d (20-Tage-Ausbruch, ATR-Stop, Trail)",
     "timeframe": "1d", "adoptable": False, "warmup_days": 60,
     "definition": _trend_definition("Trend-Basis 1d", 20),
     "trade_params": {**_TREND_EXIT, "atr_period": 20, "atr_sl_multiplier": 2.0, "trail_atr_mult": 3.0},
     "evidence": {"trades": 1669, "avg_r": 0.34, "t": 4.6, "since": "2018",
                  "recent": "2025–26: −0,03 R; letzte 12 Monate +0,21 R"}},
)
LB_Z = 1.64
STAGES = ("vorwaertstest", "bestanden", "durchgefallen", "abgelaufen", "uebernommen", "verworfen")
STAGE_LABELS = {"vorwaertstest": "im Vorwärtstest", "bestanden": "bestanden – übernehmen?",
                "durchgefallen": "durchgefallen", "abgelaufen": "ohne Urteil abgelaufen",
                "uebernommen": "als Strategie übernommen", "verworfen": "verworfen"}


def _parse(iso) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def r_stats(r_n: int, r_sum: float, r_sq: float, z: float = LB_Z) -> Dict:
    """Ø R, t-Wert, Unter-/Obergrenze aus R-Summen (rein)."""
    n = int(r_n or 0)
    if n <= 0:
        return {"trades": 0, "avg_r": None, "t": None, "lb": None, "ub": None}
    mean = float(r_sum) / n
    var = max(float(r_sq) / n - mean * mean, 0.0) * (n / (n - 1) if n > 1 else 1.0)
    se = math.sqrt(var / n) if n > 1 else None
    t = (mean / se) if se else None
    return {"trades": n, "avg_r": round(mean, 3), "t": round(t, 2) if t is not None else None,
            "lb": round(mean - z * se, 3) if se else None, "ub": round(mean + z * se, 3) if se else None}


def verdict(progress: Dict, found_at: Optional[str], now: Optional[datetime] = None,
            max_days: Optional[int] = None) -> str:
    """Stufe aus dem Vorwärts-Ergebnis (rein)."""
    n = int(progress.get("trades") or 0)
    lb, ub, avg = progress.get("lb"), progress.get("ub"), progress.get("avg_r")
    if n >= FORWARD_MIN_TRADES and lb is not None and lb > 0:
        return "bestanden"
    if n >= FORWARD_MIN_TRADES and ((avg is not None and avg < 0) or (ub is not None and ub < 0)):
        return "durchgefallen"
    found = _parse(found_at)
    if found and ((now or datetime.now(timezone.utc)) - found).days >= int(max_days or FORWARD_MAX_DAYS):
        return "abgelaufen"
    return "vorwaertstest"


def candidate_from_champion(item: Dict, source: str = "endlossuche") -> Dict:
    from services import robustness
    rules = item.get("rules") or {}
    title = " + ".join(item.get("labels") or []) or "Champion"
    return {"id": uuid.uuid4().hex[:12], "kind": "champion", "source": source,
            "ref": robustness.rule_key(item.get("definition") or {}),
            "title": title[:160], "rules": rules, "definition": item.get("definition"),
            "trade_params": item.get("trade_params") or {},
            "symbols": list(item.get("symbols") or []), "timeframe": item.get("timeframe"),
            "found_at": item.get("found_at") or datetime.now(timezone.utc).isoformat(),
            "search_evidence": {k: (item.get("evidence") or {}).get(k)
                                for k in ("t", "t_required", "passed", "engine")},
            "vault_passed": (item.get("vault") or {}).get("passed"),
            # F1: Ergebnis des Rückwärtstests und der Long/Short-Aufteilung mitführen
            "backward": {k: (item.get("backward") or {}).get(k)
                         for k in ("state", "trades", "avg_r", "t", "days", "reason")}
            if item.get("backward") else None,
            "one_sided": (item.get("sides") or {}).get("note") or None,
            "stage": "vorwaertstest", "progress": r_stats(0, 0, 0), "last_eval_at": None,
            "history": [], "created_at": datetime.now(timezone.utc).isoformat()}


def needs_eval(c: Dict, now: Optional[datetime] = None) -> bool:
    if c.get("stage") != "vorwaertstest":
        return False
    last = _parse(c.get("last_eval_at"))
    return last is None or ((now or datetime.now(timezone.utc)) - last) >= timedelta(hours=FORWARD_EVERY_H)


# ---------------------------------------------------------------------------
# Quellen einsammeln
# ---------------------------------------------------------------------------
async def sync_champions(db) -> int:
    """Neue, ehrlich geprüfte Champions der Bestenliste als Kandidaten anlegen."""
    from services import deep_explore, robustness
    doc = await db.settings.find_one({"_id": "deep_explore_best"}) or {}
    items, _legacy = deep_explore.split_best(doc)
    added = 0
    meta = doc.get("meta") or {}
    for it in items:
        if not (it.get("evidence") or {}).get("passed"):
            continue
        ref = robustness.rule_key(it.get("definition") or {})
        if await db[COLLECTION].count_documents({"ref": ref}):
            continue
        active = await db[COLLECTION].count_documents({"stage": "vorwaertstest"})
        if active >= MAX_ACTIVE:
            break
        it = {**it, "symbols": it.get("symbols") or meta.get("symbols") or [],
              "timeframe": it.get("timeframe") or meta.get("timeframe")}
        if not it["symbols"] or not it.get("timeframe"):
            continue          # ohne Assets/Zeitebene kein Vorwärtstest möglich
        await db[COLLECTION].insert_one(candidate_from_champion(it))
        added += 1
    return added


def preset_candidate(preset: Dict, symbols: List[str], now: Optional[datetime] = None) -> Dict:
    """Vorgabe als Kandidat (rein). `ref` = fester Schlüssel -> nie doppelt."""
    now_iso = (now or datetime.now(timezone.utc)).isoformat()
    return {"id": uuid.uuid4().hex[:12], "kind": "vorgabe", "source": "fachliteratur",
            "ref": f"preset:{preset['key']}", "title": preset["title"], "rules": {},
            "definition": preset["definition"], "trade_params": dict(preset["trade_params"]),
            "symbols": list(symbols), "timeframe": preset["timeframe"], "found_at": now_iso,
            "search_evidence": {}, "history_evidence": dict(preset.get("evidence") or {}),
            "adoptable": bool(preset.get("adoptable")), "max_days": PRESET_MAX_DAYS,
            # Ausbruch + ATR brauchen nur wenige Wochen Vorlauf (kein EMA-200-Warmup)
            "warmup_days": int(preset.get("warmup_days") or 0) or None,
            "stage": "vorwaertstest", "progress": r_stats(0, 0, 0), "last_eval_at": None,
            "history": [], "created_at": now_iso}


async def ensure_presets(db, symbols: Optional[List[str]] = None) -> int:
    """Vorgaben einmalig als Kandidaten anlegen (Vorwärtstest ohne Kapital)."""
    if symbols is None:
        from core.config import BACKTEST_SYMBOLS
        from services import setup_asset_class as ac
        symbols = [x for x in ac.symbols_of("crypto") if x in BACKTEST_SYMBOLS]
    if len(symbols) < 2:
        return 0
    added = 0
    for p in PRESETS:
        if await db[COLLECTION].count_documents({"ref": f"preset:{p['key']}"}):
            continue
        await db[COLLECTION].insert_one(preset_candidate(p, symbols))
        added += 1
    return added


def can_adopt(c: Dict) -> bool:
    """Übernehmen (Paper) erlaubt? Bestandene Kandidaten immer; Vorgaben schon
    im Vorwärtstest, wenn der Live-Scanner ihre Zeitebene tragen kann (rein)."""
    if c.get("stage") == "bestanden":
        return True
    return c.get("kind") == "vorgabe" and c.get("stage") == "vorwaertstest" and bool(c.get("adoptable"))


# ---------------------------------------------------------------------------
# Vorwärtstest
# ---------------------------------------------------------------------------
def _warmup_days(timeframe: str) -> int:
    from services.timeframes import TIMEFRAMES
    try:
        minutes = float(TIMEFRAMES.get(timeframe) or 15)
    except (TypeError, ValueError):
        minutes = 15.0
    return max(3, int(math.ceil(minutes * 260 / 1440.0)))


async def forward_eval(c: Dict, settings: Dict, now: Optional[datetime] = None) -> Dict:
    """Regeln des Kandidaten auf den Daten NACH dem Fund simulieren (Cloud,
    nur lesend). Rückgabe progress-Dict (trades, avg_r, t, lb, ub, per_symbol)."""
    import aiohttp
    from services import optimizer as opt
    from services.backtester import fetch_history, simulate_pair
    from services.bitunix_trade import DEFAULT_COIN_CFG
    from services.timeframes import aggregate_candles
    now = now or datetime.now(timezone.utc)
    found = _parse(c.get("found_at")) or now
    tf = c.get("timeframe") or "15m"
    days = max(1, int(math.ceil((now - found).total_seconds() / 86400.0))) \
        + int(c.get("warmup_days") or _warmup_days(tf))
    strat = opt._mk_strategy(dict(c.get("definition") or {}))
    cfg = {**DEFAULT_COIN_CFG, **(c.get("trade_params") or {})}
    from_ms = int(found.timestamp() * 1000)
    r_n, r_sum, r_sq, per = 0, 0.0, 0.0, {}
    async with aiohttp.ClientSession() as session:
        for sym in c.get("symbols") or []:
            raw = await fetch_history(session, sym, days)
            candles = aggregate_candles(raw, tf)
            del raw
            if len(candles) < 50:
                continue
            res = await asyncio.to_thread(simulate_pair, strat, candles, sym, settings, cfg,
                                          None, False, None, None, from_ms)
            r_n += int(res.get("r_n") or 0)
            r_sum += float(res.get("r_sum") or 0)
            r_sq += float(res.get("r_sq") or 0)
            per[sym] = {"trades": int(res.get("trades") or 0), "pnl": res.get("pnl")}
    out = r_stats(r_n, r_sum, r_sq)
    out["per_symbol"] = per
    out["days_forward"] = round((now - found).total_seconds() / 86400.0, 1)
    return out


async def evaluate_due(db, settings: Dict, limit: int = 2) -> List[Dict]:
    """Fällige Vorwärtstests rechnen (max. `limit` je Aufruf, RAM-schonend)."""
    from services import ram_queue
    done = []
    rows = await db[COLLECTION].find({"stage": "vorwaertstest"}, {"_id": 0}).to_list(50)
    for c in [r for r in rows if needs_eval(r)][:limit]:
        if ram_queue.free_mb() < ram_queue.MIN_FREE_MB:
            break
        try:
            prog = await forward_eval(c, settings)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Vorwärtstest {c.get('title')}: {e}")
            await db[COLLECTION].update_one({"id": c["id"]}, {"$set": {
                "last_eval_at": datetime.now(timezone.utc).isoformat(), "last_error": str(e)[:200]}})
            continue
        stage = verdict(prog, c.get("found_at"), max_days=c.get("max_days"))
        now_iso = datetime.now(timezone.utc).isoformat()
        hist = (list(c.get("history") or []) + [{"at": now_iso, "trades": prog["trades"],
                                                 "avg_r": prog["avg_r"], "lb": prog["lb"]}])[-20:]
        await db[COLLECTION].update_one({"id": c["id"]}, {"$set": {
            "progress": prog, "stage": stage, "last_eval_at": now_iso, "history": hist,
            "last_error": None, **({"decided_at": now_iso} if stage != "vorwaertstest" else {})}})
        done.append({"id": c["id"], "title": c.get("title"), "stage": stage, "progress": prog})
        if stage != "vorwaertstest":
            try:
                await db.ai_chat.insert_one({
                    "id": f"rc_{uuid.uuid4().hex[:8]}", "role": "research", "ts": now_iso,
                    "text": (f"Kandidat „{c.get('title')}“: Vorwärtstest {STAGE_LABELS[stage]} "
                             f"({prog['trades']} Trades, Ø {prog['avg_r']} R, Untergrenze {prog['lb']} R).")})
            except Exception:  # noqa: BLE001
                pass
    return done


async def list_candidates(db, limit: int = 30) -> List[Dict]:
    rows = await db[COLLECTION].find({}, {"_id": 0, "definition": 0}).sort("created_at", -1) \
        .limit(limit).to_list(limit)
    for r in rows:
        r["stage_label"] = STAGE_LABELS.get(r.get("stage"), r.get("stage"))
        r["can_adopt"] = can_adopt(r)
        p = r.get("progress") or {}
        r["progress_pct"] = min(100, round(100 * int(p.get("trades") or 0) / FORWARD_MIN_TRADES))
    return rows


async def set_stage(db, cid: str, stage: str, note: str = "") -> Optional[Dict]:
    if stage not in ("verworfen", "vorwaertstest"):
        raise ValueError("nur verwerfen oder erneut testen erlaubt")
    upd = {"stage": stage, "note": str(note)[:200], "updated_at": datetime.now(timezone.utc).isoformat()}
    if stage == "vorwaertstest":
        upd["last_eval_at"] = None
    await db[COLLECTION].update_one({"id": cid}, {"$set": upd})
    return await db[COLLECTION].find_one({"id": cid}, {"_id": 0, "definition": 0})


async def adopt(db, cid: str) -> Dict:
    """Bestandenen Kandidaten als Custom-Strategie anlegen (gleicher Pfad wie
    „Als Strategie speichern“ im Optimizer) und ausdrücklich auf PAPER stellen.
    Ohne eigene Einstellung erbte eine neue Strategie den globalen Modus (ggf.
    live) – deshalb wird der Strategie-Modus hier fest auf Paper gesetzt.
    Live schaltet nur der Trader selbst in den Strategie-Einstellungen."""
    c = await db[COLLECTION].find_one({"id": cid})
    if not c:
        raise ValueError("Kandidat nicht gefunden")
    if not can_adopt(c):
        raise ValueError("Nur bestandene Kandidaten (oder Vorgaben im Vorwärtstest) können übernommen werden")
    from routers.optimizer import optimizer_apply
    # Die Strategie wurde nur auf ihren Assets geprüft – alle anderen bleiben aus.
    try:
        from core.config import ALL_SYMBOLS
        own = set(c.get("symbols") or [])
        excl = [x for x in ALL_SYMBOLS if x not in own] if own else []
    except Exception:  # noqa: BLE001
        own, excl, ALL_SYMBOLS = set(), [], []
    if own and ALL_SYMBOLS and not (own & set(ALL_SYMBOLS)):
        # 17.11.2026: Zusatz-Coins laufen nur im Backtest, nicht im Live-Scanner
        raise ValueError("Nur auf Backtest-Zusatzcoins geprüft – die laufen nicht im Live-Scanner. "
                         "Bitte erneut mit Coins der Website prüfen.")
    name = (c.get("definition") or {}).get("name") if c.get("kind") == "vorgabe" else None
    res = await optimizer_apply({"type": "strategy", "definition": dict(c.get("definition") or {}),
                                 "name": (name or f"Kandidat {c.get('title')}")[:60],
                                 "timeframe": c.get("timeframe"),
                                 "trade_params": c.get("trade_params") or {},
                                 "exclude_symbols": excl,
                                 "exclude_reasons": {x: "nicht Teil der Prüfung" for x in excl}}, True)
    # 17.11.2026: optimizer_apply liefert die neue Strategie unter "id" – vorher
    # wurde nur "strategy_id" gelesen, der Paper-Modus also NIE gesetzt.
    sid = res.get("strategy_id") or res.get("id")
    if sid:
        from routers.autotrade import set_strategy_autotrade
        await set_strategy_autotrade(sid, {"mode": "paper", "enabled": True}, True)
    await db[COLLECTION].update_one({"id": cid}, {"$set": {
        "stage": "uebernommen", "strategy_id": sid, "updated_at": datetime.now(timezone.utc).isoformat()}})
    return {"strategy_id": sid, "result": res}


# ---------------------------------------------------------------------------
# Fortschritt der Setups (KI-/Lab-Setups) bis zum Live-Tor
# ---------------------------------------------------------------------------
def setup_progress_rows(stats: Dict[str, Dict], live: Dict[str, bool], min_trades: int) -> List[Dict]:
    """stats: {setup: {r_n, r_sum, r_sq, trades}} (Paper seit Stichtag) – rein."""
    rows = []
    for sid, st in (stats or {}).items():
        if live.get(sid):
            continue
        prog = r_stats(int(st.get("r_n") or 0), float(st.get("r_sum") or 0), float(st.get("r_sq") or 0))
        n = prog["trades"]
        if n == 0:
            continue
        need = max(0, min_trades - n)
        if prog["lb"] is not None and n >= min_trades and prog["lb"] > 0:
            state = "live-reif"
        elif n >= min_trades and prog["avg_r"] is not None and prog["avg_r"] < 0:
            state = "kein Vorteil"
        else:
            state = f"noch {need} Trades bis zum Urteil" if need else "Untergrenze noch ≤ 0"
        rows.append({"setup": sid, **prog, "need": need, "state": state,
                     "progress_pct": min(100, round(100 * n / max(1, min_trades)))})
    rows.sort(key=lambda r: (-(r["progress_pct"]), -(r["avg_r"] or -9)))
    return rows
