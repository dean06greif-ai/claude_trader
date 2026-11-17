"""Wächter für Live-Strategien (Phase D, 15.11.2026).

Prüft jede Strategie, die mit Echtgeld handelt: Liegt nach mindestens
MIN_LIVE_TRADES Live-Trades die vorsichtige Untergrenze des Ergebnisses je
Trade (Ø R − 1,64·SE) unter 0, ist ein Vorteil nicht mehr belegt. Dann kommt
eine Empfehlung in den Leitstand („pausieren oder neu prüfen“).

Automatisches Umschalten auf Paper geschieht NUR, wenn der Trader es im
Leitstand freigibt (`live_watchdog_auto_pause`, Standard aus) – und auch dann
nur auf Paper (Daten laufen weiter), nie auf „aus“. Eine bewusste Entscheidung
„läuft weiter“ wird über das Ausblenden der Empfehlung respektiert.
"""
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

SETTINGS_ID = "live_watchdog"
MIN_LIVE_TRADES = 50
DEFAULTS = {"auto_pause": False}


def _r(t: Dict) -> Optional[float]:
    try:
        risk = float(t.get("risk_usdt") or 0)
        return float(t.get("realized_pnl") or 0) / risk if risk > 0 else None
    except (TypeError, ValueError):
        return None


PROVEN_LOSS = "verliert nachweislich"


def judge(trades: List[Dict], min_trades: int = MIN_LIVE_TRADES) -> Dict[str, Dict]:
    """Live-Bilanz je Strategie (rein). trades: geschlossene Live-Trades."""
    from services.research_pipeline import r_stats
    per: Dict[str, Dict] = {}
    for t in trades or []:
        sid = t.get("strategy_id")
        if not sid or sid == "ai_trader" or t.get("data_collection"):
            continue
        g = per.setdefault(sid, {"name": t.get("strategy_name") or sid, "r_n": 0, "r_sum": 0.0,
                                 "r_sq": 0.0, "trades": 0, "pnl": 0.0})
        g["trades"] += 1
        g["pnl"] += float(t.get("realized_pnl") or 0)
        r = _r(t)
        if r is not None:
            g["r_n"] += 1
            g["r_sum"] += r
            g["r_sq"] += r * r
    out = {}
    for sid, g in per.items():
        st = r_stats(g["r_n"], g["r_sum"], g["r_sq"])
        if st["trades"] < min_trades:
            state = "zu wenig Live-Trades"
        elif st["lb"] is not None and st["lb"] > 0:
            state = "Vorteil belegt"
        elif st["ub"] is not None and st["ub"] < 0:
            state = "verliert nachweislich"
        elif st["lb"] is not None and st["lb"] < 0:
            state = "Vorteil nicht belegt"
        else:
            state = "unklar"
        out[sid] = {"strategy_id": sid, "name": g["name"], "trades": g["trades"],
                    "pnl": round(g["pnl"], 2), **st, "state": state,
                    "alarm": state in ("verliert nachweislich", "Vorteil nicht belegt")}
    return out


async def load(db) -> Dict[str, Dict]:
    rows = await db.auto_trades.find(
        {"mode": "live", "status": "closed", "strategy_id": {"$nin": [None, "", "ai_trader"]}},
        {"_id": 0, "strategy_id": 1, "strategy_name": 1, "realized_pnl": 1, "risk_usdt": 1,
         "data_collection": 1}).to_list(20000)
    return judge(rows)


async def get_config(db) -> Dict:
    doc = await db.settings.find_one({"_id": SETTINGS_ID}) or {}
    return {k: doc.get(k, v) for k, v in DEFAULTS.items()}


async def set_config(db, updates: Dict) -> Dict:
    upd = {"auto_pause": bool((updates or {}).get("auto_pause"))}
    await db.settings.update_one({"_id": SETTINGS_ID}, {"$set": upd}, upsert=True)
    return await get_config(db)


async def enforce(db, autotrader=None) -> List[Dict]:
    """Nur mit Freigabe: Strategien mit Alarm von Live auf Paper umstellen."""
    cfg = await get_config(db)
    if not cfg.get("auto_pause") or autotrader is None:
        return []
    verdicts = await load(db)
    changed = []
    overrides = dict(autotrader.config.get("strategy_overrides", {}))
    coin_cfgs = dict(autotrader.config.get("strategy_coin_configs", {}))
    coin_changed: Dict[str, Dict] = {}
    for sid, v in verdicts.items():
        # 17.11.2026: automatisch nur bei NACHGEWIESENEM Verlust (Obergrenze < 0).
        # „Vorteil nicht belegt“ (Ø evtl. im Plus, nur noch unsicher) bleibt eine
        # Empfehlung – das entscheidet der Trader.
        if v.get("state") != PROVEN_LOSS:
            continue
        hit = False
        cur = dict(overrides.get(sid) or {})
        if cur.get("mode") == "live":
            cur["mode"] = "paper"
            overrides[sid] = cur
            hit = True
        # Coin-Einstellung hat Vorrang vor der Strategie-Einstellung (effective_mode)
        for key, scc in coin_cfgs.items():
            if key.startswith(f"{sid}_") and (scc or {}).get("mode") == "live":
                coin_changed[key] = {**scc, "mode": "paper"}
                hit = True
        if hit:
            changed.append(v)
    if not changed:
        return []
    autotrader.config["strategy_overrides"] = overrides
    await db.settings.update_one({"_id": "autotrade_config"},
                                 {"$set": {"strategy_overrides": overrides}}, upsert=True)
    for key, scc in coin_changed.items():
        coin_cfgs[key] = scc
        await db.strategy_coin_configs.replace_one({"_id": key}, {"_id": key, "config": scc}, upsert=True)
    autotrader.config["strategy_coin_configs"] = coin_cfgs
    now = datetime.now(timezone.utc).isoformat()
    for v in changed:
        try:
            await db.ai_chat.insert_one({
                "id": f"lw_{v['strategy_id']}_{now[:10]}", "role": "governance", "ts": now,
                "text": (f"Live-Wächter: {v['name']} auf Paper umgestellt – {v['trades']} Live-Trades, "
                         f"Ø {v['avg_r']} R, Untergrenze {v['lb']} R (Freigabe: automatisches Pausieren).")})
        except Exception:  # noqa: BLE001
            pass
    logger.info(f"Live-Wächter: {len(changed)} Strategie(n) auf Paper umgestellt")
    return changed
