"""Portfolio-Dienst: Tagesdaten laden, Replay rechnen, Stand speichern (17.11.2026).

Der Minuten-Scanner hält höchstens 21 Tage Kerzen – zu wenig für die einzige
Vorteils-Quelle mit Beleg (Trend und Funding auf Tagesebene). Dieser Dienst hat
deshalb einen EIGENEN, sehr leichten Datenweg: Tageskerzen und Funding-Sätze
kommen direkt von den öffentlichen Binance-Archiven und liegen in MongoDB.

Ablauf (einmal je abgeschlossenem Tag, angestoßen vom Autonomie-Takt):
  1. Tageskerzen ergänzen (nur neue Tage), Funding ergänzen
  2. services/portfolio_core.run -> kompletter Verlauf seit Startdatum
  3. Stand speichern (Kennzahlen, Kurve, Positionen, letzte Trades, Tagesplan)
  4. Tagesplan als Benachrichtigung (wenn sich etwas geändert hat)

Es wird KEIN Auftrag an die Börse geschickt. Das Portfolio läuft als Paper-Konto
mit echter Buchführung; der Tagesplan nennt jede Order mit Größe und Stop, so
dass der Trader sie nachhandeln kann. Die automatische Live-Ausführung ist ein
eigener, späterer Schritt (erst wenn Paper-Verlauf und Replay übereinstimmen).
"""
import asyncio
import hashlib
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from services import portfolio_core as core

logger = logging.getLogger(__name__)

DAY_MS = core.DAY_MS
KLINES_URL = "https://data-api.binance.vision/api/v3/klines"
OKX_URL = "https://www.okx.com/api/v5/public/funding-rate-history"
CANDLES = "portfolio_daily"
FUNDING = "portfolio_funding"
STATE_ID = "portfolio_state"
CONFIG_ID = "portfolio_config"
START_DEFAULT = "2020-01-01"
MAX_STALE_DAYS = 3
# Universum (17.11.2026, zweite Stufe): 64 liquide Coins, die auf Bitunix handelbar
# sind und lückenlose Binance-Tagesdaten haben. Die 38 neuen Coins wurden NICHT nach
# Ergebnis ausgewählt; allein gerechnet (mit den Pleite-Coins LUNA/FTT und den
# delisteten WAVES/XMR) bestätigten sie die Regel unabhängig: Sharpe 1,40.
UNIVERSE_26 = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT", "AVAXUSDT",
               "DOTUSDT", "LINKUSDT", "LTCUSDT", "TRXUSDT", "ATOMUSDT", "NEARUSDT", "UNIUSDT", "ETCUSDT",
               "XLMUSDT", "BCHUSDT", "FILUSDT", "APTUSDT", "SUIUSDT", "ARBUSDT", "OPUSDT", "INJUSDT",
               "AAVEUSDT", "HBARUSDT"]
UNIVERSE_EXTRA = ["ICPUSDT", "ZECUSDT", "DYDXUSDT", "APEUSDT", "LDOUSDT", "CRVUSDT", "VETUSDT", "GRTUSDT",
                  "EGLDUSDT", "STXUSDT", "SANDUSDT", "ALGOUSDT", "IMXUSDT", "SNXUSDT", "GALAUSDT", "THETAUSDT",
                  "MANAUSDT", "XTZUSDT", "AXSUSDT", "COMPUSDT", "WLDUSDT", "RUNEUSDT", "CAKEUSDT", "TIAUSDT",
                  "SEIUSDT", "FETUSDT", "KAVAUSDT", "CHZUSDT", "ARUSDT", "NEOUSDT", "KSMUSDT", "IOTAUSDT",
                  "1INCHUSDT", "ENJUSDT", "PENDLEUSDT", "JUPUSDT", "ENAUSDT", "TAOUSDT"]
UNIVERSE = UNIVERSE_26 + UNIVERSE_EXTRA
# Je Stufe: Risiko je Trade, höchstens 20 Trend-Positionen, Gesamtgröße
MAX_POSITIONS = 20
MAX_GROSS = {"vorsichtig": 2.0, "normal": 3.0, "offensiv": 4.0}
CARRY_N_SIDE = 8
RISK_LEVELS = {"vorsichtig": 0.25, "normal": 0.5, "offensiv": 1.0}
# Rückrechnung 01/2020–16.11.2026, 64 Coins, Gebühren + Slippage + echtes Funding
BACKTEST = {
    "vorsichtig": {"cagr": 52, "max_dd": 19, "cagr_2025": 32, "dd_2025": 15, "sharpe": 1.81},
    "normal": {"cagr": 97, "max_dd": 33, "cagr_2025": 46, "dd_2025": 26, "sharpe": 1.78},
    "offensiv": {"cagr": 195, "max_dd": 56, "cagr_2025": 71, "dd_2025": 44, "sharpe": 1.78},
}
BACKTEST_YEARS = {"vorsichtig": [62, 193, 17, 50, 32, 32, 26], "normal": [142, 441, 26, 114, 51, 40, 42],
                  "offensiv": [402, 1348, 39, 260, 75, 53, 72]}      # 2020 … 2026 (bis 16.11.)
EXPECTATION = {
    "vorsichtig": ("Realistische Erwartung: 15 bis 30 % pro Jahr, mit Rückgängen von 15 bis 25 % und "
                   "Durststrecken von bis zu 9 Monaten."),
    "normal": ("Realistische Erwartung: 25 bis 50 % pro Jahr, mit Rückgängen von 25 bis 40 % und "
               "Durststrecken von bis zu 9 Monaten."),
    "offensiv": ("Realistische Erwartung: 30 bis 70 % pro Jahr, aber mit Rückgängen über 50 % – "
                 "nur für Geld, auf das du lange verzichten kannst."),
}
CAVEAT = ("Die Rückrechnung ist geschönt: Es zählen nur Coins, die es heute noch gibt, und 2021 war ein "
          "Ausnahmejahr. Maßgeblich ist der Verlauf seit 2025 und – ab jetzt – der Paper-Verlauf.")


def backtest_note(level: str) -> str:
    b = BACKTEST.get(level) or BACKTEST["normal"]
    return (f"Rückrechnung 01/2020–11/2026 auf echten Daten (64 Coins, mit Gebühren und Funding): "
            f"+{b['cagr']} % pro Jahr, größter Rückgang {b['max_dd']} %. "
            f"Seit 2025: +{b['cagr_2025']} % pro Jahr, Rückgang {b['dd_2025']} %.")


_lock = asyncio.Lock()
_progress: Dict = {"phase": "", "done": 0, "total": 0}


def progress() -> Dict:
    return dict(_progress)


# ---------------------------------------------------------------------------
# Einstellungen
# ---------------------------------------------------------------------------
def default_config() -> Dict:
    return {"enabled": True, "start": START_DEFAULT, "start_equity": 10000.0, "risk_level": "vorsichtig",
            "trend": True, "carry": True, "symbols": list(UNIVERSE)}


def normalize_config(raw: Optional[Dict]) -> Dict:
    """Nutzer-Einstellungen prüfen (rein)."""
    cfg = default_config()
    raw = raw or {}
    for k in ("enabled", "trend", "carry"):
        if k in raw:
            cfg[k] = bool(raw[k])
    if raw.get("risk_level") in RISK_LEVELS:
        cfg["risk_level"] = raw["risk_level"]
    try:
        if raw.get("start_equity") is not None:
            cfg["start_equity"] = min(max(float(raw["start_equity"]), 100.0), 10_000_000.0)
    except (TypeError, ValueError):
        pass
    if raw.get("start"):
        try:
            datetime.strptime(str(raw["start"])[:10], "%Y-%m-%d")
            cfg["start"] = str(raw["start"])[:10]
        except ValueError:
            pass
    syms = [str(s).upper() for s in (raw.get("symbols") or []) if str(s).upper().endswith("USDT")]
    if len(syms) >= 8:
        cfg["symbols"] = sorted(set(syms))[:120]
    return cfg


def core_config(cfg: Dict) -> Dict:
    """Nutzer-Einstellungen -> Einstellungen des Rechenkerns (rein)."""
    return {"start_equity": cfg["start_equity"], "btc": "BTCUSDT",
            "trend": {"enabled": bool(cfg["trend"]), "risk_pct": RISK_LEVELS[cfg["risk_level"]],
                      "climate": False, "max_positions": MAX_POSITIONS,
                      "max_gross": MAX_GROSS[cfg["risk_level"]]},
            "carry": {"enabled": bool(cfg["carry"]), "n_side": CARRY_N_SIDE}}


def strategy_hash(cfg: Dict) -> str:
    """Alles, was den Verlauf in % verändert. Kontogröße gehört NICHT dazu."""
    key = {k: cfg[k] for k in ("start", "risk_level", "trend", "carry")}
    key["symbols"] = sorted(cfg["symbols"])
    return hashlib.sha1(json.dumps(key, sort_keys=True).encode()).hexdigest()[:12]


async def get_config(db) -> Dict:
    doc = await db.settings.find_one({"_id": CONFIG_ID}) or {}
    return normalize_config(doc)


async def set_config(db, updates: Dict) -> Dict:
    cur = await get_config(db)
    new = normalize_config({**cur, **(updates or {})})
    await db.settings.update_one({"_id": CONFIG_ID}, {"$set": new}, upsert=True)
    return new


def _day_ms(iso_day: str) -> int:
    return int(datetime.strptime(iso_day, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)


def last_closed_day(now_ms: Optional[int] = None) -> int:
    """Öffnungszeit der letzten ABGESCHLOSSENEN Tageskerze (UTC)."""
    now_ms = now_ms or int(time.time() * 1000)
    return (now_ms // DAY_MS - 1) * DAY_MS


# ---------------------------------------------------------------------------
# Daten: Tageskerzen
# ---------------------------------------------------------------------------
def merge_bars(old: List[List[float]], new: List[List[float]], now_ms: int) -> List[List[float]]:
    """Kerzen zusammenführen; nur abgeschlossene Tage, aufsteigend, ohne Dubletten (rein)."""
    by = {int(b[0]): [int(b[0])] + [float(x) for x in b[1:5]] for b in old or []}
    for b in new or []:
        try:
            ts = int(b[0])
            row = [ts, float(b[1]), float(b[2]), float(b[3]), float(b[4])]
        except (TypeError, ValueError, IndexError):
            continue
        if ts + DAY_MS <= now_ms and min(row[1:]) > 0:
            by[ts] = row
    return [by[k] for k in sorted(by)]


async def _fetch_klines(session, sym: str, limit: int, end_ms: Optional[int] = None) -> List:
    import aiohttp
    params = {"symbol": sym, "interval": "1d", "limit": limit}
    if end_ms:
        params["endTime"] = end_ms
    async with session.get(KLINES_URL, params=params, timeout=aiohttp.ClientTimeout(total=20)) as r:
        if r.status != 200:
            return []
        return await r.json()


async def update_candles(db, session, sym: str, start_ms: int, now_ms: int) -> List[List[float]]:
    doc = await db[CANDLES].find_one({"_id": sym}) or {}
    bars = doc.get("bars") or []
    need_from = start_ms - 260 * DAY_MS          # Vorlauf für 200-Tage-Schnitt und ATR
    target = last_closed_day(now_ms)
    # „full“ = Historie reicht bis zum Bedarf ODER bis zum Listing des Coins zurück
    full = bool(bars) and (bars[0][0] <= need_from + 5 * DAY_MS
                           or (doc.get("full") and int(doc.get("full_from") or 0) <= need_from))
    if full and bars[-1][0] >= target:
        return bars
    fresh: List = []
    reached_listing = False
    if full:
        missing = int((target - bars[-1][0]) // DAY_MS) + 2
        fresh = await _fetch_klines(session, sym, min(max(missing, 3), 1000))
    else:
        end = None
        for _ in range(6):
            part = await _fetch_klines(session, sym, 1000, end)
            if not part:
                reached_listing = end is not None
                break
            fresh = part + fresh
            end = int(part[0][0]) - 1
            if len(part) < 1000:
                reached_listing = True
                break
            if end < need_from:
                break
    merged = merge_bars(bars, fresh, now_ms)
    if merged and (merged != bars or reached_listing):
        upd = {"bars": merged, "updated_at": now_ms}
        if reached_listing:
            upd.update({"full": True, "full_from": need_from})
        await db[CANDLES].update_one({"_id": sym}, {"$set": upd}, upsert=True)
    return merged


# ---------------------------------------------------------------------------
# Daten: Funding (Tages-Summen)
# ---------------------------------------------------------------------------
def daily_sums(rows: Dict[int, float]) -> Dict[int, float]:
    """Einzelne Funding-Zahlungen {ts: Satz} -> {Tages-ts: Summe} (rein)."""
    out: Dict[int, float] = {}
    for ts, rate in (rows or {}).items():
        d = (int(ts) // DAY_MS) * DAY_MS
        out[d] = out.get(d, 0.0) + float(rate)
    return out


def _months(start_ms: int, end_ms: int) -> List[str]:
    out, d = [], datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc).replace(day=1)
    end = datetime.fromtimestamp(end_ms / 1000, tz=timezone.utc)
    while d <= end:
        out.append(d.strftime("%Y-%m"))
        d = (d.replace(day=28) + timedelta(days=4)).replace(day=1)      # 1. des Folgemonats
    return out


def _archive_month(sym: str, ym: str) -> Dict[int, float]:
    """Ein Monat Funding aus dem Binance-Archiv (blockierend, mit Disk-Cache)."""
    from services import market_positioning as mp
    blob = mp._download(f"{mp.ARCHIVE}/monthly/fundingRate/{sym}/{sym}-fundingRate-{ym}.zip")
    rows: Dict[int, float] = {}
    for r in (mp._csv_rows(blob) if blob else []):
        try:
            rows[int(r["calc_time"])] = float(r["last_funding_rate"])
        except (KeyError, ValueError):
            continue
    return rows


async def _recent_funding(session, sym: str) -> Dict[int, float]:
    """Jüngste ~33 Tage: Binance (falls erreichbar), sonst OKX (öffentlich)."""
    import aiohttp
    try:
        async with session.get("https://fapi.binance.com/fapi/v1/fundingRate",
                               params={"symbol": sym, "limit": 200},
                               timeout=aiohttp.ClientTimeout(total=12)) as r:
            if r.status == 200:
                return {int(x["fundingTime"]): float(x["fundingRate"]) for x in await r.json()}
    except Exception:  # noqa: BLE001 – Region gesperrt/Timeout -> OKX
        pass
    try:
        async with session.get(OKX_URL, params={"instId": f"{sym[:-4]}-USDT-SWAP", "limit": 100},
                               timeout=aiohttp.ClientTimeout(total=12)) as r:
            if r.status == 200:
                data = (await r.json()).get("data") or []
                return {int(x["fundingTime"]): float(x.get("realizedRate") or x["fundingRate"]) for x in data}
    except Exception:  # noqa: BLE001
        pass
    return {}


async def update_funding(db, session, sym: str, start_ms: int, now_ms: int) -> Dict[int, float]:
    doc = await db[FUNDING].find_one({"_id": sym}) or {}
    days: Dict[int, float] = {int(k): float(v) for k, v in (doc.get("days") or {}).items()}
    done = set(doc.get("months") or [])
    cur_month = datetime.fromtimestamp(now_ms / 1000, tz=timezone.utc).strftime("%Y-%m")
    todo = [m for m in _months(start_ms - 40 * DAY_MS, now_ms) if m not in done and m != cur_month]
    changed = False
    if todo:
        loop = asyncio.get_running_loop()
        for i in range(0, len(todo), 8):
            chunk = todo[i:i + 8]
            parts = await asyncio.gather(*[loop.run_in_executor(None, _archive_month, sym, m) for m in chunk])
            for m, rows in zip(chunk, parts):
                days.update(daily_sums(rows))
                done.add(m)             # auch leere Monate (Coin noch nicht gelistet) merken
            changed = True
    target = last_closed_day(now_ms)
    if days.get(target) is None:
        recent = daily_sums(await _recent_funding(session, sym))
        today = (now_ms // DAY_MS) * DAY_MS
        for d, v in recent.items():
            if d < today:               # nur abgeschlossene Tage
                days[d] = v
                changed = True
    if changed:
        await db[FUNDING].update_one(
            {"_id": sym}, {"$set": {"days": {str(k): v for k, v in days.items()},
                                    "months": sorted(done), "updated_at": now_ms}}, upsert=True)
    return days


# ---------------------------------------------------------------------------
# Tagesplan (rein)
# ---------------------------------------------------------------------------
def _de(x: float, digits: int = 0) -> str:
    """Zahl in deutscher Schreibweise (1.234,5)."""
    return f"{x:,.{digits}f}".replace(",", "§").replace(".", ",").replace("§", ".")


def _fmt_px(x: float) -> str:
    return _de(x, 2) if x >= 100 else (_de(x, 4) if x >= 0.1 else _de(x, 6))


def day_plan(res: Dict, prev_carry: Optional[List[str]] = None) -> List[Dict]:
    """Was heute zu tun ist – aus dem Ergebnis des Replays (rein)."""
    last = res.get("last_ts")
    plan: List[Dict] = []
    for t in res.get("trades") or []:
        if t.get("exit_ts") == last and t.get("sleeve") == "trend":
            plan.append({"kind": "schliessen", "symbol": t["symbol"], "side": t["side"],
                         "text": f"{t['symbol']} {t['side']} wurde am Stop geschlossen "
                                 f"({_de(t['r'], 2) if t['r'] < 0 else '+' + _de(t['r'], 2)} R, {_de(t['pnl'])} USDT)"})
    for p in res.get("positions") or []:
        if p.get("sleeve") != "trend":
            continue
        if p.get("new"):
            plan.append({"kind": "eroeffnen", "symbol": p["symbol"], "side": p["side"],
                         "notional": p["notional"], "stop": p["stop"],
                         "text": f"{p['symbol']} {p['side']} eröffnen: {_de(p['notional'])} USDT Positionsgröße, "
                                 f"Stop bei {_fmt_px(p['stop'])} (Risiko {_de(p['risk'])} USDT)"})
        else:
            plan.append({"kind": "stop", "symbol": p["symbol"], "side": p["side"], "stop": p["stop"],
                         "text": f"{p['symbol']} {p['side']}: Stop auf {_fmt_px(p['stop'])} setzen"})
    carry = [p for p in res.get("positions") or [] if p.get("sleeve") == "carry"]
    now_names = sorted(f"{p['symbol']}:{p['side']}" for p in carry)
    if carry and carry[0].get("entry_ts") == last and now_names != sorted(prev_carry or []):
        longs = ", ".join(p["symbol"][:-4] for p in carry if p["side"] == "LONG")
        shorts = ", ".join(p["symbol"][:-4] for p in carry if p["side"] == "SHORT")
        per = carry[0]["notional"]
        plan.append({"kind": "carry", "text": f"Funding-Korb neu ({_de(per)} USDT je Coin): "
                                              f"Long {longs} · Short {shorts}"})
    order = {"schliessen": 0, "eroeffnen": 1, "carry": 2, "stop": 3}
    plan.sort(key=lambda x: (order.get(x["kind"], 9), x.get("symbol") or ""))
    return plan


def plan_text(state: Dict) -> str:
    acts = [p for p in state.get("plan") or [] if p["kind"] != "stop"]
    stops = [p for p in state.get("plan") or [] if p["kind"] == "stop"]
    day = datetime.fromtimestamp((state.get("last_ts") or 0) / 1000, tz=timezone.utc).strftime("%d.%m.%Y")
    lines = [f"Portfolio (Paper) – Tagesschluss {day}",
             f"Konto: {_de(state.get('equity') or 0)} USDT · offen: {state.get('open_trend', 0)} Trend-Positionen"]
    lines += [f"• {p['text']}" for p in acts] or ["• Keine neue Order heute."]
    if stops:
        lines.append(f"• {len(stops)} Stops nachziehen (Liste im Leitstand unter „Portfolio“).")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Lauf
# ---------------------------------------------------------------------------
def build_state(res: Dict, cfg: Dict, prev: Optional[Dict], now_ms: int) -> Dict:
    """Ergebnis des Replays -> gespeicherter Stand (rein)."""
    prev = prev or {}
    shash = strategy_hash(cfg)
    paper_since = prev.get("paper_since") if prev.get("strategy_hash") == shash else None
    if paper_since is None:
        paper_since = res.get("last_ts")
    prev_carry = prev.get("carry_names") if prev.get("strategy_hash") == shash else None
    carry = [p for p in res["positions"] if p["sleeve"] == "carry"]
    trend = [p for p in res["positions"] if p["sleeve"] == "trend"]
    since = [c for c in res["curve"] if paper_since is not None and c[0] >= paper_since]
    return {
        "strategy_hash": shash, "updated_at": now_ms, "last_ts": res["last_ts"], "first_ts": res["first_ts"],
        "paper_since": paper_since, "equity": res["equity"], "start_equity": cfg["start_equity"],
        "risk_level": cfg["risk_level"], "risk_pct": RISK_LEVELS[cfg["risk_level"]],
        "stats": res["stats"], "years": res["years"], "parts": res["parts"],
        "trend_trades": res["trend_trades"], "carry_rebalances": res["carry_rebalances"],
        "since_paper": {**core._stats(since), "from_ts": paper_since, "days": max(len(since) - 1, 0),
                        "start": since[0][1] if since else None, "now": since[-1][1] if since else None},
        "positions": trend + carry, "open_trend": len(trend), "open_carry": len(carry),
        "gross_trend": round(sum(p["notional"] for p in trend), 2),
        "carry_names": sorted(f"{p['symbol']}:{p['side']}" for p in carry),
        "plan": day_plan(res, prev_carry),
        "trades": sorted((t for t in res["trades"]), key=lambda t: t["exit_ts"])[-80:][::-1],
        "curve": core.sample_curve(res["curve"]), "symbols": res["symbols"],
        "note": backtest_note(cfg["risk_level"]), "expectation": EXPECTATION[cfg["risk_level"]],
        "caveat": CAVEAT,
    }


async def refresh(db, force: bool = False, notify: bool = True, now_ms: Optional[int] = None) -> Dict:
    """Daten ergänzen und Stand neu rechnen (höchstens einmal je abgeschlossenem Tag)."""
    now_ms = now_ms or int(time.time() * 1000)
    cfg = await get_config(db)
    prev = await db.settings.find_one({"_id": STATE_ID}) or {}
    if not cfg["enabled"]:
        return {"status": "aus"}
    target = last_closed_day(now_ms)
    if (not force and prev.get("last_ts") == target
            and prev.get("strategy_hash") == strategy_hash(cfg)
            and float(prev.get("start_equity") or 0) == cfg["start_equity"]):
        return {"status": "aktuell", "last_ts": target}
    if _lock.locked():
        return {"status": "läuft bereits"}
    async with _lock:
        import aiohttp
        start_ms = _day_ms(cfg["start"])
        candles: Dict[str, List] = {}
        funding: Dict[str, Dict[int, float]] = {}
        syms = cfg["symbols"]
        _progress.update({"phase": "Lade Tagesdaten", "done": 0, "total": len(syms)})
        async with aiohttp.ClientSession() as session:
            for i, sym in enumerate(syms):
                try:
                    bars = await update_candles(db, session, sym, start_ms, now_ms)
                    if len(bars) > 60:
                        candles[sym] = bars
                        if cfg["carry"] or cfg["trend"]:
                            funding[sym] = await update_funding(db, session, sym, start_ms, now_ms)
                except Exception as e:  # noqa: BLE001 – ein Coin darf den Lauf nicht stoppen
                    logger.warning(f"Portfolio: {sym} nicht ladbar: {type(e).__name__}: {e}")
                _progress["done"] = i + 1
        if "BTCUSDT" not in candles or len(candles) < 8:
            _progress["phase"] = "Fehler: zu wenige Daten"
            return {"status": "fehler", "detail": f"nur {len(candles)} Coins ladbar"}
        last = max(b[-1][0] for b in candles.values())
        if target - last > MAX_STALE_DAYS * DAY_MS:
            _progress["phase"] = "Fehler: Daten veraltet"
            return {"status": "fehler", "detail": "Tagesdaten sind älter als 3 Tage"}
        _progress["phase"] = "Rechne Verlauf"
        loop = asyncio.get_running_loop()
        res = await loop.run_in_executor(None, lambda: core.run(candles, funding, core_config(cfg), start_ms))
        state = build_state(res, cfg, prev, now_ms)
        state["funding_coverage"] = sum(1 for s in candles if funding.get(s))
        await db.settings.update_one({"_id": STATE_ID}, {"$set": state}, upsert=True)
        _progress.update({"phase": "fertig", "done": len(syms), "total": len(syms)})
        changed = prev.get("last_ts") != state["last_ts"]
        if notify and changed and prev.get("last_ts"):
            try:
                from core import state as app_state
                from services import notifications
                await notifications.telegram_notify(db, getattr(app_state, "telegram", None),
                                                    "portfolio_daily", plan_text(state))
            except Exception as e:  # noqa: BLE001
                logger.info(f"Portfolio-Tagesplan nicht gesendet: {e}")
        return {"status": "neu gerechnet", "last_ts": state["last_ts"], "equity": state["equity"],
                "open": state["open_trend"], "plan": len(state["plan"])}


_task: Optional[asyncio.Task] = None


def kick(db, force: bool = False) -> str:
    """Lauf im Hintergrund starten (der erste Lauf lädt Minuten lang Historie)."""
    global _task
    if _task is not None and not _task.done():
        return "läuft bereits"

    async def _go():
        try:
            return await refresh(db, force=force)
        except Exception as e:  # noqa: BLE001
            _progress["phase"] = f"Fehler: {type(e).__name__}: {str(e)[:120]}"
            logger.warning(f"Portfolio-Lauf: {e}")
    _task = asyncio.create_task(_go())
    return "gestartet"


async def tick(db, now_ms: Optional[int] = None) -> str:
    """Vom Autonomie-Takt: nur rechnen, wenn ein neuer Tag abgeschlossen ist."""
    now_ms = now_ms or int(time.time() * 1000)
    cfg = await get_config(db)
    if not cfg["enabled"]:
        return "aus"
    prev = await db.settings.find_one({"_id": STATE_ID}, {"last_ts": 1, "strategy_hash": 1,
                                                          "start_equity": 1}) or {}
    if (prev.get("last_ts") == last_closed_day(now_ms) and prev.get("strategy_hash") == strategy_hash(cfg)
            and float(prev.get("start_equity") or 0) == cfg["start_equity"]):
        return "aktuell"
    return kick(db)


async def get_state(db) -> Dict:
    doc = await db.settings.find_one({"_id": STATE_ID}) or {}
    doc.pop("_id", None)
    return {"config": await get_config(db), "state": doc or None, "progress": progress(),
            "running": _task is not None and not _task.done(),
            "risk_levels": [{"key": k, "risk_pct": v, **BACKTEST[k], "years": BACKTEST_YEARS[k],
                             "expectation": EXPECTATION[k]} for k, v in RISK_LEVELS.items()],
            "caveat": CAVEAT}


def summary_line(state: Optional[Dict]) -> Optional[str]:
    """Ein Satz für den Leitstand (rein)."""
    if not state or not state.get("stats"):
        return None
    sp = state.get("since_paper") or {}
    part = ""
    if sp.get("start") and sp.get("now") and sp.get("days"):
        chg = (sp['now'] / sp['start'] - 1) * 100
        part = f" Seit Paper-Start ({sp['days']} Tage): {'+' if chg >= 0 else ''}{_de(chg, 1)} %."
    return (f"Portfolio (Paper): {state.get('open_trend', 0)} Trend-Positionen, "
            f"{state.get('open_carry', 0)} Coins im Funding-Korb.{part}")
