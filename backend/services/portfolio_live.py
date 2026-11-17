"""Portfolio live: der Paper-Plan des Portfolios als echte Orders auf Bitunix (17.11.2026).

Warum live schon jetzt, mit kleinem Geld? Die Rückrechnung (7 Jahre, 26 Coins)
belegt die Regel; was sie NICHT belegt, ist die Ausführung: Füllpreise,
Mindestmengen, Funding auf Bitunix statt Binance, Stops am Mark-Preis. Das
lernt man nur live. Deshalb spiegelt dieses Modul den Paper-Plan in klein:

  * dieselben Positionen wie im Paper-Konto, nur skaliert auf das Live-Kapital
  * jede Trend-Position bekommt SOFORT ihren Stop an der Börse (der Stop ist
    die einzige Ausstiegsregel des Modells); jeder Funding-Korb-Leg einen
    Katastrophen-Stop bei 25 %
  * Hebel so klein, dass die Liquidation immer jenseits des Stops liegt
  * Not-Aus: ab einem Verlust von max_loss_pct des Live-Kapitals keine neuen
    Einstiege mehr; Stops und Ausstiege laufen weiter
  * Probelauf-Modus: alles wird geplant und angezeigt, aber nichts gesendet

Der Planer (plan_actions) ist rein und vollständig getestet; der Ausführer
benutzt nur die seit Monaten live erprobten Aufrufe des Bitunix-Clients
(place_order, place_position_tp_sl, modify_tpsl_order, flash_close).
Mengen rechnet dieses Modul selbst und prüft die Mindestmenge vorab – der
Client würde zu kleine Mengen sonst stillschweigend auf das Minimum anheben
und damit das Risiko vervielfachen.
"""
import asyncio
import logging
import math
import time
from datetime import datetime, timezone
from decimal import ROUND_DOWN, ROUND_UP, Decimal
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

CONFIG_ID = "portfolio_live_config"
PREVIEW_ID = "portfolio_live_preview"
BOOK = "portfolio_live_positions"
LOG = "portfolio_live_log"
EQUITY = "portfolio_live_equity"
MODES = ("aus", "probe", "live")
CARRY_DISASTER_PCT = 25.0       # Katastrophen-Stop der Funding-Korb-Legs
CARRY_LEVERAGE = 3
MAX_LEVERAGE = 5
HEALTH_EVERY_S = 3600
CONFIRM_LIVE = "LIVE"
CONFIRM_FLATTEN = "ALLES SCHLIESSEN"

_lock = asyncio.Lock()
_inflight: Set[Tuple[str, str]] = set()          # (Bitunix-Symbol, Seite) während einer Order
_owned_pids: Set[str] = set()                     # offene Portfolio-Positionen an der Börse
_owned_sides: Set[Tuple[str, str]] = set()        # (internes Symbol, Seite)


# ---------------------------------------------------------------------------
# Eigentum (für Positions-Wächter und Autotrader – billig, ohne DB)
# ---------------------------------------------------------------------------
def owns(position_id, bitunix_symbol: str = "", side: str = "") -> bool:
    """Gehört diese Börsen-Position dem Portfolio (oder wird sie gerade eröffnet)?"""
    if position_id and str(position_id) in _owned_pids:
        return True
    return (str(bitunix_symbol).upper(), str(side).upper()) in _inflight


def holds(symbol: str, side: str) -> bool:
    """Hält das Portfolio live eine Position auf Symbol+Seite? (Autotrader-Schutz)"""
    return (str(symbol).upper(), str(side).upper()) in _owned_sides


def _remember(rows: List[Dict]) -> None:
    _owned_pids.clear()
    _owned_sides.clear()
    for r in rows:
        if r.get("position_id"):
            _owned_pids.add(str(r["position_id"]))
        _owned_sides.add((str(r["symbol"]).upper(), str(r["side"]).upper()))


async def load_owned(db) -> int:
    rows = await db[BOOK].find({"status": "open"}, {"_id": 0, "position_id": 1, "symbol": 1,
                                                    "side": 1}).to_list(500)
    _remember(rows)
    return len(rows)


# ---------------------------------------------------------------------------
# Einstellungen
# ---------------------------------------------------------------------------
def default_config() -> Dict:
    return {"mode": "probe", "capital": 100.0, "risk_pct": 1.0, "max_loss_pct": 30.0,
            "carry": True, "late_entry": True, "late_max_r": 0.5, "max_upsize": 2.0,
            "max_gross": 3.0, "halted": False, "halt_reason": None, "started_at": None,
            "last_synced_ts": None, "last_check_at": 0.0}


def normalize_config(raw: Optional[Dict]) -> Dict:
    cfg = default_config()
    raw = raw or {}
    for k in ("carry", "late_entry", "halted"):
        if k in raw:
            cfg[k] = bool(raw[k])
    if raw.get("mode") in MODES:
        cfg["mode"] = raw["mode"]
    for k, lo, hi in (("capital", 20.0, 1_000_000.0), ("risk_pct", 0.1, 2.0),
                      ("max_loss_pct", 5.0, 60.0), ("late_max_r", 0.0, 2.0),
                      ("max_upsize", 1.0, 3.0), ("max_gross", 0.5, 5.0)):
        try:
            if raw.get(k) is not None:
                cfg[k] = min(max(float(raw[k]), lo), hi)
        except (TypeError, ValueError):
            pass
    for k in ("halt_reason", "started_at", "last_synced_ts"):
        if k in raw:
            cfg[k] = raw[k]
    try:
        cfg["last_check_at"] = float(raw.get("last_check_at") or 0.0)
    except (TypeError, ValueError):
        pass
    return cfg


async def get_config(db) -> Dict:
    return normalize_config(await db.settings.find_one({"_id": CONFIG_ID}) or {})


async def _save(db, cfg: Dict) -> Dict:
    cfg = normalize_config(cfg)
    await db.settings.update_one({"_id": CONFIG_ID}, {"$set": cfg}, upsert=True)
    return cfg


USER_KEYS = ("mode", "capital", "risk_pct", "max_loss_pct", "carry", "late_entry", "late_max_r",
             "max_upsize", "max_gross", "halted")


async def set_config(db, updates: Dict) -> Dict:
    """Einstellungen ändern. Wechsel auf „live“ nur mit Bestätigung; interne
    Felder (Start, letzter Lauf, Grund des Not-Aus) setzt nur das Modul selbst."""
    cur = await get_config(db)
    raw = dict(updates or {})
    upd = {k: v for k, v in raw.items() if k in USER_KEYS}
    if upd.get("mode") == "live" and cur["mode"] != "live":
        if str(raw.get("confirm") or "") != CONFIRM_LIVE:
            raise ValueError("Für den Live-Betrieb bitte mit „LIVE“ bestätigen")
        upd.update({"started_at": datetime.now(timezone.utc).isoformat(), "last_synced_ts": None,
                    "halted": False, "halt_reason": None})
    if upd.get("halted") is False:
        upd["halt_reason"] = None
    return await _save(db, {**cur, **upd})


# ---------------------------------------------------------------------------
# Rein: Mengen, Hebel, Plan
# ---------------------------------------------------------------------------
def step_round(value: float, step: float, up: bool = False) -> float:
    if step <= 0:
        return float(value)
    q = (Decimal(str(value)) / Decimal(str(step))).to_integral_value(rounding=ROUND_UP if up else ROUND_DOWN)
    return float(q * Decimal(str(step)))


def size_qty(notional: float, price: float, meta: Dict, max_upsize: float) -> Dict:
    """Menge zur Ziel-Positionsgröße – ohne stilles Anheben (rein).

    Liegt die Mindestmenge höchstens max_upsize-mal über dem Ziel, wird auf die
    Mindestmenge aufgerundet (Risiko steigt höchstens um diesen Faktor);
    sonst wird der Trade übersprungen."""
    step = float((meta or {}).get("qty_step") or 0.0)
    min_qty = float((meta or {}).get("min_qty") or 0.0)
    if price <= 0 or notional <= 0:
        return {"ok": False, "qty": 0.0, "reason": "kein Preis"}
    raw = notional / price
    qty = step_round(raw, step) if step else raw
    if step and qty < raw:
        # Nächstgelegener Schritt statt immer abrunden: bei BTC ist ein Schritt
        # ~7 USDT groß – Abrunden kostete dort bis zu 45 % des geplanten Risikos.
        up = step_round(raw, step, up=True)
        if (up - raw) < (raw - qty) and up / raw <= max_upsize:
            qty = up
    if min_qty and qty < min_qty:
        need = step_round(min_qty, step, up=True) if step else min_qty
        factor = need / raw if raw > 0 else float("inf")
        if factor > max_upsize:
            return {"ok": False, "qty": 0.0, "factor": round(factor, 2),
                    "reason": f"unter Mindestmenge ({need * price:.1f} USDT nötig, Ziel {notional:.1f})"}
        return {"ok": True, "qty": need, "factor": round(factor, 2),
                "note": f"auf Mindestmenge aufgerundet (Risiko ×{factor:.1f})".replace(".", ",")}
    if qty <= 0:
        return {"ok": False, "qty": 0.0, "reason": "Menge 0"}
    return {"ok": True, "qty": qty, "factor": round(qty / raw, 2) if raw > 0 else 1.0}


def leverage_for(stop_pct: float, max_lev: float = 0.0, carry: bool = False) -> int:
    """Hebel so, dass die Liquidation (~1/Hebel) mind. doppelt so weit weg ist wie der Stop."""
    cap = MAX_LEVERAGE if not max_lev else min(MAX_LEVERAGE, int(max_lev))
    if carry:
        return max(1, min(CARRY_LEVERAGE, cap))
    if stop_pct <= 0:
        return 1
    return int(max(1, min(cap, math.floor(0.5 / stop_pct))))


def trend_key(p: Dict) -> str:
    return f"trend:{p['symbol']}:{p['side']}:{int(p.get('entry_ts') or 0)}"


def carry_key(p: Dict) -> str:
    return f"carry:{p['symbol']}:{p['side']}"


def plan_actions(cfg: Dict, pf: Dict, book_open: List[Dict], done: Set[str],
                 exch: List[Dict], prices: Dict[str, float], meta: Dict[str, Dict],
                 available: Optional[float]) -> List[Dict]:
    """Was ist heute an der Börse zu tun? (rein)

    pf         Portfolio-Stand (positions, equity, risk_pct, last_ts)
    book_open  offene Live-Positionen des Portfolios {key, symbol, side, sleeve, qty,
               position_id, sl_price}
    done       Schlüssel, die live schon einmal geschlossen wurden (nicht neu öffnen)
    exch       Börsen-Positionen (position_watchdog.parse_positions)
    """
    acts: List[Dict] = []
    capital = float(cfg["capital"])
    paper_eq = float(pf.get("equity") or 0) or 1.0
    paper_risk = float(pf.get("risk_pct") or 0.25) or 0.25
    last_ts = pf.get("last_ts")
    by_key = {b["key"]: b for b in book_open}
    own_pids = {str(b.get("position_id")) for b in book_open if b.get("position_id")}
    foreign = {(e["bitunix_symbol"], e["side"]) for e in exch if str(e["position_id"]) not in own_pids}

    targets: Dict[str, Dict] = {}
    for p in pf.get("positions") or []:
        if p.get("sleeve") == "trend":
            targets[trend_key(p)] = p
        elif p.get("sleeve") == "carry" and cfg.get("carry"):
            if p.get("entry_ts") and f"{carry_key(p)}:{int(p['entry_ts'])}" in done:
                continue                          # in diesem Korb schon ausgestoppt
            targets[carry_key(p)] = p
    # Seiten, die live schon belegt sind (eine zweite Position derselben Seite
    # würde an der Börse mit ihr verschmelzen) – wird beim Planen ergänzt
    taken = {(b["symbol"], b["side"]): b["sleeve"] for b in book_open}

    # 1) Schließen: live offen, aber nicht mehr im Plan
    for b in book_open:
        if b["key"] not in targets:
            acts.append({"kind": "close", "key": b["key"], "symbol": b["symbol"], "side": b["side"],
                         "sleeve": b["sleeve"], "qty": b["qty"], "position_id": b.get("position_id"),
                         "reason": ("Paper-Position am Stop geschlossen" if b["sleeve"] == "trend"
                                    else "nicht mehr im Funding-Korb")})

    # 2) Stops nachziehen (oder schließen, wenn der Kurs schon jenseits liegt)
    for key, b in by_key.items():
        p = targets.get(key)
        if not p or b["sleeve"] != "trend":
            continue
        new, old = float(p["stop"]), float(b.get("sl_price") or 0)
        px = prices.get(b["symbol"])
        better = (new > old) if b["side"] == "LONG" else (old <= 0 or new < old)
        if not better or abs(new - old) <= max(abs(old) * 1e-5, 1e-12):
            continue
        beyond = px is not None and ((b["side"] == "LONG" and px <= new) or (b["side"] == "SHORT" and px >= new))
        if beyond:
            acts.append({"kind": "close", "key": key, "symbol": b["symbol"], "side": b["side"],
                         "sleeve": "trend", "qty": b["qty"], "position_id": b.get("position_id"),
                         "reason": "Kurs schon jenseits des neuen Stops"})
        else:
            acts.append({"kind": "move_sl", "key": key, "symbol": b["symbol"], "side": b["side"],
                         "qty": b["qty"], "position_id": b.get("position_id"), "old": old, "new": new})

    # 3) Eröffnen
    if cfg.get("halted"):
        for key, p in targets.items():
            if key not in by_key:
                acts.append({"kind": "skip", "key": key, "symbol": p["symbol"], "side": p["side"],
                             "sleeve": p["sleeve"], "reason": "Not-Aus aktiv – keine neuen Einstiege"})
        return acts
    gross = sum(float(b.get("qty") or 0) * float(prices.get(b["symbol"]) or 0) for b in book_open)
    margin_left = None if available is None else float(available) * 0.9
    opens: List[Dict] = []
    # Trend zuerst (größerer Vorteil), dann Funding-Korb
    for key, p in sorted(targets.items(), key=lambda kv: (kv[1]["sleeve"] != "trend", kv[0])):
        if key in by_key:
            continue
        sym, side, sleeve = p["symbol"], p["side"], p["sleeve"]
        base = {"key": key, "symbol": sym, "side": side, "sleeve": sleeve}
        if key in done:
            acts.append({**base, "kind": "skip", "reason": "live schon ausgestoppt – wartet auf neues Signal"})
            continue
        if (sym, side) in foreign:
            acts.append({**base, "kind": "skip", "reason": "fremde Position auf derselben Seite an der Börse"})
            continue
        if (sym, side) in taken:
            other = "Trend-Position" if taken[(sym, side)] == "trend" else "Funding-Leg"
            acts.append({**base, "kind": "skip", "reason": f"{other} hält diese Seite schon live"})
            continue
        px = prices.get(sym)
        m = meta.get(sym) or {}
        if not px or not m:
            acts.append({**base, "kind": "skip", "reason": "kein Kurs oder Kontrakt an der Börse"})
            continue
        sgn = 1 if side == "LONG" else -1
        if sleeve == "trend":
            stop = float(p["stop"])
            dist = sgn * (px - stop)
            if dist <= 0:
                acts.append({**base, "kind": "skip", "reason": "Kurs schon jenseits des Stops"})
                continue
            late = p.get("entry_ts") != last_ts
            if late:
                init = abs(float(p["entry"]) - float(p.get("init_stop") or p["stop"]))
                run_r = sgn * (px - float(p["entry"])) / init if init > 0 else 99.0
                if not cfg.get("late_entry"):
                    acts.append({**base, "kind": "skip", "reason": "nur neue Einstiege eingestellt"})
                    continue
                if run_r > float(cfg["late_max_r"]):
                    acts.append({**base, "kind": "skip",
                                 "reason": f"schon {run_r:.1f} R gelaufen – zu spät für einen Einstieg".replace(".", ",")})
                    continue
            risk = capital * float(cfg["risk_pct"]) / 100.0
            notional = risk / (dist / px)
            cap = float(p.get("notional") or 0) / paper_eq * capital * (float(cfg["risk_pct"]) / paper_risk) * 1.5
            if cap > 0:
                notional = min(notional, cap)
            sl = stop
            lev = leverage_for(dist / px, m.get("max_lev") or 0)
        else:
            notional = float(p.get("notional") or 0) / paper_eq * capital
            sl = px * (1 - sgn * CARRY_DISASTER_PCT / 100.0)
            lev = leverage_for(0, m.get("max_lev") or 0, carry=True)
            risk = None
        sz = size_qty(notional, px, m, float(cfg["max_upsize"]))
        if not sz["ok"]:
            acts.append({**base, "kind": "skip", "reason": sz["reason"]})
            continue
        qty = sz["qty"]
        real_notional = qty * px
        if gross + real_notional > float(cfg["max_gross"]) * capital:
            acts.append({**base, "kind": "skip", "reason": "Gesamtgröße erreicht (max. "
                         f"{cfg['max_gross']:.0f}× Kapital)".replace(".", ",")})
            continue
        margin = real_notional / lev
        if margin_left is not None and margin > margin_left:
            acts.append({**base, "kind": "skip", "reason": "freie Margin an der Börse reicht nicht"})
            continue
        gross += real_notional
        taken[(sym, side)] = sleeve
        if margin_left is not None:
            margin_left -= margin
        opens.append({**base, "kind": "open", "qty": qty, "price": px, "notional": round(real_notional, 2),
                      "sl": sl, "leverage": lev, "margin": round(margin, 2),
                      "risk": round(qty * abs(px - sl), 2) if sleeve == "trend" else None,
                      "note": sz.get("note"), "paper_entry": p.get("entry"),
                      "late": sleeve == "trend" and p.get("entry_ts") != last_ts,
                      "entry_ts": p.get("entry_ts")})

    # Funding-Korb marktneutral halten: gleich viele Long- wie Short-Legs
    def legs(side):
        return ([b for b in book_open if b["sleeve"] == "carry" and b["side"] == side
                 and b["key"] in targets] + [o for o in opens if o["sleeve"] == "carry" and o["side"] == side])
    n_long, n_short = len(legs("LONG")), len(legs("SHORT"))
    drop = n_long - n_short
    if drop:
        heavy = "LONG" if drop > 0 else "SHORT"
        cand = [o for o in opens if o["sleeve"] == "carry" and o["side"] == heavy]
        for o in sorted(cand, key=lambda x: x["symbol"], reverse=True)[:abs(drop)]:
            opens.remove(o)
            acts.append({**{k: o[k] for k in ("key", "symbol", "side", "sleeve")},
                         "kind": "skip", "reason": "Gegenseite im Korb fehlt (marktneutral halten)"})
    return acts + opens


def summarize(acts: List[Dict]) -> Dict:
    c = {k: sum(1 for a in acts if a["kind"] == k) for k in ("open", "close", "move_sl", "skip")}
    return {**c, "notional": round(sum(a.get("notional") or 0 for a in acts if a["kind"] == "open"), 2),
            "margin": round(sum(a.get("margin") or 0 for a in acts if a["kind"] == "open"), 2),
            "risk": round(sum(a.get("risk") or 0 for a in acts if a["kind"] == "open"), 2)}


def live_pnl(closed: List[Dict], open_rows: List[Dict], prices: Dict[str, float]) -> Dict:
    """Ergebnis des Live-Portfolios: realisiert (Börse, netto) + offen (rein)."""
    real = sum(float(r.get("net_pnl") or 0) for r in closed)
    unreal = 0.0
    for b in open_rows:
        px = prices.get(b["symbol"])
        if px and b.get("fill_price"):
            sgn = 1 if b["side"] == "LONG" else -1
            unreal += sgn * (px - float(b["fill_price"])) * float(b.get("qty") or 0)
    return {"realized": round(real, 2), "unrealized": round(unreal, 2), "total": round(real + unreal, 2)}


def kill_check(cfg: Dict, pnl_total: float) -> Optional[str]:
    lim = float(cfg["capital"]) * float(cfg["max_loss_pct"]) / 100.0
    if pnl_total <= -lim:
        return (f"Verlust {pnl_total:.2f} USDT erreicht die Grenze von {cfg['max_loss_pct']:.0f} % "
                f"des Live-Kapitals ({lim:.2f} USDT)").replace(".", ",")
    return None


def slippage_pct(side: str, ref: float, fill: float) -> Optional[float]:
    """+ = schlechter gefüllt als der Referenzkurs."""
    if not ref or not fill:
        return None
    d = (fill - ref) / ref * 100.0
    return round(d if side == "LONG" else -d, 4)


# ---------------------------------------------------------------------------
# Börse
# ---------------------------------------------------------------------------
def _client():
    from core import state
    return getattr(state, "trade_client", None)


def _ok(res) -> bool:
    return isinstance(res, dict) and res.get("code") in (0, "0")


async def _exchange_view(client) -> Tuple[List[Dict], Dict[str, float], Dict[str, Dict], Optional[float]]:
    from services.position_watchdog import parse_positions
    if not client._pairs_meta:
        await client.load_trading_pairs()
    exch = parse_positions(await client.get_positions())
    prices = await client.get_all_mark_prices()
    meta = dict(client._pairs_meta)
    avail = None
    try:
        bal = await client.get_balance()
        data = bal.get("data") if isinstance(bal, dict) else None
        if isinstance(data, list) and data:
            data = data[0]
        if isinstance(data, dict):
            avail = float(data.get("available") or data.get("availableBalance") or 0)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Portfolio live: Kontostand nicht lesbar: {e}")
    return exch, prices, meta, avail


async def _log(db, entry: Dict) -> None:
    entry = {"ts": datetime.now(timezone.utc).isoformat(), **entry}
    try:
        await db[LOG].insert_one(entry)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Portfolio-live-Log: {e}")


async def _sl_rows(client, symbol: str, pid: str) -> Optional[List[Dict]]:
    try:
        res = await client.get_pending_tpsl(symbol, position_id=pid)
    except Exception:  # noqa: BLE001
        return None
    if not _ok(res):
        return None
    data = res.get("data")
    if isinstance(data, dict):
        data = data.get("orderList") or data.get("list") or data.get("rows") or [data]
    return [r for r in (data or []) if isinstance(r, dict) and r.get("slPrice") not in (None, "", "0")]


def _sl_matches(rows: List[Dict], want: float, tick: float) -> bool:
    tol = max(tick * 1.5, abs(want) * 1e-6)
    for r in rows or []:
        try:
            if abs(float(r.get("slPrice")) - want) <= tol:
                return True
        except (TypeError, ValueError):
            continue
    return False


async def _ensure_sl(client, symbol: str, pid: str, side: str, qty: float, sl: float) -> bool:
    """SL setzen bzw. ändern und an der Börse nachlesen. True = steht."""
    tick = float((client.contract_meta(client.to_bitunix_symbol(symbol)) or {}).get("price_tick") or 0)
    rows = await _sl_rows(client, symbol, pid)
    if rows is not None and _sl_matches(rows, sl, tick):
        return True
    if rows:
        oid = rows[0].get("id") or rows[0].get("orderId")
        if oid:
            await client.modify_tpsl_order(symbol, oid, side=side, sl_price=sl, sl_qty=qty)
            await asyncio.sleep(0.8)
            again = await _sl_rows(client, symbol, pid)
            if again is not None and _sl_matches(again, sl, tick):
                return True
        for r in rows:                              # kein Stapeln alter SL-Orders
            oid = r.get("id") or r.get("orderId")
            if oid:
                await client.cancel_tpsl_order(symbol, oid)
    await client.place_position_tp_sl(symbol, pid, side, sl_price=sl, sl_qty=qty)
    await asyncio.sleep(0.8)
    final = await _sl_rows(client, symbol, pid)
    return bool(final is not None and _sl_matches(final, sl, tick))


async def _execute_open(db, client, a: Dict, own_pids: Set[str]) -> Dict:
    from services.bitunix_trade import pick_new_position
    from services.position_watchdog import parse_positions
    sym, side = a["symbol"], a["side"]
    bsym = client.to_bitunix_symbol(sym)
    _inflight.add((bsym, side))
    try:
        lev_res = await client.set_leverage(sym, a["leverage"])
        if not _ok(lev_res):
            return {"ok": False, "error": f"Hebel nicht gesetzt: {str(lev_res)[:160]}"}
        res = await client.place_order(sym, "BUY" if side == "LONG" else "SELL", a["qty"], "MARKET",
                                       client_id=f"pf{int(time.time())}{sym[:6]}")
        if not _ok(res):
            return {"ok": False, "error": f"Order abgelehnt: {str(res)[:200]}"}
        pid, row = None, None
        for _ in range(4):
            await asyncio.sleep(1.2)
            raw = await client.get_positions(sym)
            data = raw.get("data") if isinstance(raw, dict) else None
            rows = data if isinstance(data, list) else ([data] if isinstance(data, dict) else [])
            pid = pick_new_position(rows, side, a["qty"], exclude=own_pids)
            if pid:
                row = next((r for r in parse_positions(raw) if r["position_id"] == str(pid)), None)
                break
        if not pid or not row:
            return {"ok": False, "error": "Order gesendet, Position nicht gefunden – bitte an der Börse prüfen",
                    "unknown_fill": True}
        fill, qty = float(row.get("entry") or a["price"]), float(row.get("qty") or a["qty"])
        liq = float(row.get("liq_price") or 0)
        bad_liq = liq > 0 and ((side == "LONG" and liq >= a["sl"]) or (side == "SHORT" and liq <= a["sl"]))
        sl_ok = False if bad_liq else await _ensure_sl(client, sym, pid, side, qty, a["sl"])
        if not sl_ok:
            # Nie ungeschützt liegen lassen
            await client.flash_close(sym, pid, side, qty, full=True)
            why = "Liquidation läge vor dem Stop" if bad_liq else "Stop ließ sich nicht setzen"
            return {"ok": False, "error": f"{why} – Position sofort wieder geschlossen", "position_id": pid}
        doc = {"key": a["key"], "symbol": sym, "side": side, "sleeve": a["sleeve"], "qty": qty,
               "position_id": str(pid), "fill_price": fill, "ref_price": a["price"],
               "paper_entry": a.get("paper_entry"), "entry_ts": a.get("entry_ts"),
               "slippage_pct": slippage_pct(side, a["price"], fill), "sl_price": a["sl"],
               "leverage": a["leverage"], "notional": round(qty * fill, 2), "late": a.get("late"),
               "first_sl": a["sl"],
               "status": "open", "opened_at": datetime.now(timezone.utc).isoformat()}
        await db[BOOK].insert_one(doc)
        own_pids.add(str(pid))
        _owned_pids.add(str(pid))
        _owned_sides.add((sym.upper(), side))
        return {"ok": True, "position_id": str(pid), "fill": fill, "slippage_pct": doc["slippage_pct"]}
    finally:
        _inflight.discard((bsym, side))


async def _book_closed(db, client, b: Dict, reason: str, done_key: Optional[str] = None) -> Dict:
    from services.bitunix_trade import parse_closed_position
    info = None
    for _ in range(3):
        try:
            info = parse_closed_position(await client.get_history_positions(b["symbol"], b["position_id"]),
                                         b["position_id"])
        except Exception:  # noqa: BLE001
            info = None
        if info:
            break
        await asyncio.sleep(1.0)
    upd = {"status": "closed", "closed_at": datetime.now(timezone.utc).isoformat(), "close_reason": reason,
           "net_pnl": (info or {}).get("net_pnl"), "exit_price": (info or {}).get("exit_price"),
           "fee": (info or {}).get("fee"), "funding": (info or {}).get("funding"),
           "liquidated": (info or {}).get("liquidated")}
    if b.get("fill_price") and upd["exit_price"] and b["sleeve"] == "trend":
        risk = abs(float(b["fill_price"]) - float(b.get("first_sl") or b.get("sl_price") or 0)) * float(b["qty"])
        upd["r"] = round(float(upd["net_pnl"] or 0) / risk, 3) if risk > 0 else None
    await db[BOOK].update_one({"key": b["key"], "status": "open"}, {"$set": upd})
    if done_key:
        await db.settings.update_one({"_id": CONFIG_ID}, {"$addToSet": {"done": done_key}}, upsert=True)
    _owned_pids.discard(str(b.get("position_id")))
    _owned_sides.discard((str(b["symbol"]).upper(), b["side"]))
    return upd


def _done_key(b: Dict, pf_positions: List[Dict]) -> Optional[str]:
    """Sperre nach einem Stopp: Trend bis zum nächsten Einstieg (Schlüssel enthält
    das Einstiegsdatum), Funding-Leg bis zum nächsten Korb. Ohne aktuellen Korb
    keine Sperre (sonst bliebe der Coin für immer gesperrt)."""
    if b["sleeve"] == "trend":
        return b["key"]
    ts = next((p.get("entry_ts") for p in pf_positions if p.get("sleeve") == "carry"
               and p["symbol"] == b["symbol"] and p["side"] == b["side"]), None)
    return f"{b['key']}:{int(ts)}" if ts else None


async def reconcile(db, client, exch: List[Dict], pf_positions: List[Dict]) -> List[Dict]:
    """Live-Positionen, die an der Börse nicht mehr existieren (Stop, Liquidation,
    manuell geschlossen), als geschlossen verbuchen."""
    live_pids = {str(e["position_id"]) for e in exch}
    out = []
    for b in await db[BOOK].find({"status": "open"}, {"_id": 0}).to_list(500):
        if b.get("position_id") and str(b["position_id"]) not in live_pids:
            upd = await _book_closed(db, client, b, "an der Börse geschlossen (Stop)", _done_key(b, pf_positions))
            out.append({"symbol": b["symbol"], "side": b["side"], "net_pnl": upd.get("net_pnl")})
            await _log(db, {"kind": "closed_at_exchange", "symbol": b["symbol"], "side": b["side"],
                            "sleeve": b["sleeve"], "net_pnl": upd.get("net_pnl"), "r": upd.get("r")})
    return out


async def _pnl_now(db, prices: Dict[str, float]) -> Dict:
    cfg = await get_config(db)
    since = cfg.get("started_at") or "0"
    closed = await db[BOOK].find({"status": "closed", "opened_at": {"$gte": since}},
                                 {"_id": 0, "net_pnl": 1}).to_list(5000)
    open_rows = await db[BOOK].find({"status": "open"}, {"_id": 0}).to_list(500)
    return live_pnl(closed, open_rows, prices)


async def sync(db, force: bool = False) -> Dict:
    """Ein Lauf: Abgleich, Plan, (im Live-Modus) Ausführung."""
    from services import portfolio_engine
    cfg = await get_config(db)
    if cfg["mode"] == "aus":
        return {"status": "aus"}
    client = _client()
    if client is None or not client.configured():
        return {"status": "fehler", "detail": "Bitunix-Schlüssel fehlen"}
    pf = (await portfolio_engine.get_state(db)).get("state") or {}
    if not pf.get("positions") and not pf.get("last_ts"):
        return {"status": "wartet", "detail": "Portfolio noch nicht gerechnet"}
    if _lock.locked():
        return {"status": "läuft bereits"}
    async with _lock:
        exch, prices, meta, avail = await _exchange_view(client)
        live = cfg["mode"] == "live"
        closed_now = await reconcile(db, client, exch, pf.get("positions") or []) if live else []
        book_open = await db[BOOK].find({"status": "open"}, {"_id": 0}).to_list(500)
        _remember(book_open)
        doc = await db.settings.find_one({"_id": CONFIG_ID}) or {}
        done = set(doc.get("done") or [])
        pnl = await _pnl_now(db, prices)
        if live and not cfg["halted"]:
            why = kill_check(cfg, pnl["total"])
            if why:
                cfg = await _save(db, {**cfg, "halted": True, "halt_reason": why})
                await _notify(db, f"Portfolio live: Not-Aus. {why}. Keine neuen Einstiege mehr; "
                                  "Stops und Ausstiege laufen weiter.")
        acts = plan_actions(cfg, pf, book_open, done, exch, prices, meta, avail)
        preview = {"generated_at": datetime.now(timezone.utc).isoformat(), "mode": cfg["mode"],
                   "pf_last_ts": pf.get("last_ts"), "actions": acts, "summary": summarize(acts),
                   "available": avail, "pnl": pnl}
        results = []
        if live:
            own = {str(b["position_id"]) for b in book_open if b.get("position_id")}
            by_key = {b["key"]: b for b in book_open}
            for a in acts:
                try:
                    if a["kind"] == "close":
                        b = by_key[a["key"]]
                        r = await client.flash_close(a["symbol"], a["position_id"], a["side"], a["qty"], full=True)
                        ok = _ok(r)
                        if ok:
                            await asyncio.sleep(1.0)
                            # planmäßiger Ausstieg: keine Sperre (nur Stopps sperren)
                            upd = await _book_closed(db, client, b, a["reason"],
                                                     b["key"] if b["sleeve"] == "trend" else None)
                            res = {"ok": True, "net_pnl": upd.get("net_pnl")}
                        else:
                            res = {"ok": False, "error": f"Schließen abgelehnt: {str(r)[:160]}"}
                    elif a["kind"] == "move_sl":
                        ok = await _ensure_sl(client, a["symbol"], a["position_id"], a["side"], a["qty"], a["new"])
                        if ok:
                            await db[BOOK].update_one({"key": a["key"], "status": "open"},
                                                      {"$set": {"sl_price": a["new"]}})
                        res = {"ok": ok, "error": None if ok else "Stop ließ sich nicht verschieben"}
                    elif a["kind"] == "open":
                        res = await _execute_open(db, client, a, own)
                        if not res.get("ok") and res.get("unknown_fill"):
                            await _notify(db, f"Portfolio live: {a['symbol']} {a['side']} – Order gesendet, "
                                              "Position nicht gefunden. Bitte an der Börse prüfen!")
                    else:
                        continue
                except Exception as e:  # noqa: BLE001 – ein Fehler darf die anderen Schritte nicht stoppen
                    res = {"ok": False, "error": f"{type(e).__name__}: {str(e)[:160]}"}
                a["result"] = res
                results.append(a)
                await _log(db, {**{k: a.get(k) for k in ("kind", "key", "symbol", "side", "sleeve", "qty", "price",
                                                       "notional", "sl", "new", "reason", "note")}, "result": res})
                await asyncio.sleep(0.3)
            preview["results"] = len(results)
            preview["errors"] = sum(1 for a in results if not (a.get("result") or {}).get("ok"))
        await db.settings.update_one({"_id": PREVIEW_ID}, {"$set": preview}, upsert=True)
        await _save(db, {**cfg, "last_synced_ts": pf.get("last_ts"), "last_check_at": time.time()})
        await _snapshot(db, pnl)
        if live and (results or closed_now):
            await _notify(db, _result_text(results, closed_now, pnl))
        return {"status": "ok", "mode": cfg["mode"], **summarize(acts),
                "errors": preview.get("errors", 0), "closed_at_exchange": len(closed_now)}


async def health(db) -> Dict:
    """Stündlich: geschlossene Positionen verbuchen, fehlende Stops nachsetzen."""
    cfg = await get_config(db)
    if cfg["mode"] != "live":
        return {"status": cfg["mode"]}
    client = _client()
    if client is None or not client.configured() or _lock.locked():
        return {"status": "übersprungen"}
    from services import portfolio_engine
    from services.position_watchdog import parse_positions
    async with _lock:
        pf = (await portfolio_engine.get_state(db)).get("state") or {}
        exch = parse_positions(await client.get_positions())
        closed = await reconcile(db, client, exch, pf.get("positions") or [])
        if not cfg["halted"]:
            why = kill_check(cfg, (await _pnl_now(db, await client.get_all_mark_prices()))["total"])
            if why:
                cfg = await _save(db, {**cfg, "halted": True, "halt_reason": why})
                await _notify(db, f"Portfolio live: Not-Aus. {why}. Keine neuen Einstiege mehr; "
                                  "Stops und Ausstiege laufen weiter.")
        fixed = 0
        for b in await db[BOOK].find({"status": "open"}, {"_id": 0}).to_list(500):
            rows = await _sl_rows(client, b["symbol"], b["position_id"])
            if rows is not None and not rows and b.get("sl_price"):
                if await _ensure_sl(client, b["symbol"], b["position_id"], b["side"], b["qty"], b["sl_price"]):
                    fixed += 1
                    await _log(db, {"kind": "sl_restored", "symbol": b["symbol"], "side": b["side"]})
        await _save(db, {**cfg, "last_check_at": time.time()})
        if closed:
            await _notify(db, _result_text([], closed, None))
        return {"status": "ok", "closed": len(closed), "sl_restored": fixed}


async def tick(db) -> str:
    """Autonomie-Takt (alle 5 Minuten): nach jedem neuen Portfolio-Tag ein voller
    Lauf, sonst stündlich die Gesundheitsprüfung."""
    from services import portfolio_engine
    cfg = await get_config(db)
    if cfg["mode"] == "aus":
        return "aus"
    st = await db.settings.find_one({"_id": portfolio_engine.STATE_ID}, {"last_ts": 1}) or {}
    if st.get("last_ts") and st["last_ts"] != cfg.get("last_synced_ts"):
        r = await sync(db)
        return f"Lauf: {r.get('status')}"
    if cfg["mode"] == "live" and time.time() - float(cfg.get("last_check_at") or 0) > HEALTH_EVERY_S:
        r = await health(db)
        return f"Prüfung: {r.get('status')}"
    return "aktuell"


async def flatten(db, confirm: str) -> Dict:
    """Not-Aus von Hand: alle Portfolio-Positionen schließen, Modus auf Probelauf."""
    if str(confirm or "") != CONFIRM_FLATTEN:
        raise ValueError("Bitte mit „ALLES SCHLIESSEN“ bestätigen")
    client = _client()
    cfg = await get_config(db)
    await _save(db, {**cfg, "mode": "probe", "halted": True, "halt_reason": "von Hand alles geschlossen"})
    out = []
    async with _lock:
        for b in await db[BOOK].find({"status": "open"}, {"_id": 0}).to_list(500):
            try:
                r = await client.flash_close(b["symbol"], b["position_id"], b["side"], b["qty"], full=True)
                ok = _ok(r)
                if ok:
                    await asyncio.sleep(1.0)
                    await _book_closed(db, client, b, "Not-Aus von Hand", None)
                out.append({"symbol": b["symbol"], "side": b["side"], "ok": ok})
            except Exception as e:  # noqa: BLE001
                out.append({"symbol": b["symbol"], "side": b["side"], "ok": False, "error": str(e)[:120]})
    await _log(db, {"kind": "flatten", "result": out})
    await _notify(db, f"Portfolio live: Not-Aus von Hand – {sum(1 for x in out if x['ok'])} von {len(out)} "
                      "Positionen geschlossen.")
    return {"closed": out}


# ---------------------------------------------------------------------------
# Bericht
# ---------------------------------------------------------------------------
async def _snapshot(db, pnl: Dict) -> None:
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        await db[EQUITY].update_one({"day": day}, {"$set": {"day": day, **pnl}}, upsert=True)
    except Exception:  # noqa: BLE001
        pass


def _result_text(results: List[Dict], closed: List[Dict], pnl: Optional[Dict]) -> str:
    lines = ["Portfolio live (Bitunix):"]
    for a in results:
        r = a.get("result") or {}
        ok = "✓" if r.get("ok") else "✗"
        if a["kind"] == "open":
            lines.append(f"{ok} {a['symbol']} {a['side']} eröffnet: {a['qty']} (≈{a['notional']} USDT), Stop {a['sl']:.6g}"
                         + (f" – {r.get('error')}" if not r.get("ok") else ""))
        elif a["kind"] == "close":
            lines.append(f"{ok} {a['symbol']} {a['side']} geschlossen ({a['reason']})"
                         + (f", {r.get('net_pnl'):+.2f} USDT" if r.get("net_pnl") is not None else ""))
        elif a["kind"] == "move_sl":
            lines.append(f"{ok} {a['symbol']} Stop {a['old']:.6g} → {a['new']:.6g}")
    for c in closed:
        lines.append(f"• {c['symbol']} {c['side']} an der Börse ausgestoppt"
                     + (f" ({c['net_pnl']:+.2f} USDT)" if c.get("net_pnl") is not None else ""))
    if pnl:
        lines.append(f"Ergebnis seit Live-Start: {pnl['total']:+.2f} USDT")
    return "\n".join(lines)


async def _notify(db, text: str) -> None:
    try:
        from core import state as app_state
        from services import notifications
        await notifications.telegram_notify(db, getattr(app_state, "telegram", None), "portfolio_live", text)
    except Exception as e:  # noqa: BLE001
        logger.info(f"Portfolio-live-Meldung nicht gesendet: {e}")


async def get_overview(db) -> Dict:
    cfg = await get_config(db)
    preview = await db.settings.find_one({"_id": PREVIEW_ID}) or {}
    preview.pop("_id", None)
    open_rows = await db[BOOK].find({"status": "open"}, {"_id": 0}).sort("opened_at", -1).to_list(200)
    closed = await db[BOOK].find({"status": "closed"}, {"_id": 0}).sort("closed_at", -1).to_list(60)
    log = await db[LOG].find({}, {"_id": 0}).sort("ts", -1).to_list(40)
    eq = await db[EQUITY].find({}, {"_id": 0}).sort("day", 1).to_list(400)
    slips = [float(r["slippage_pct"]) for r in open_rows + closed if r.get("slippage_pct") is not None]
    cfg.pop("done", None)
    return {"config": cfg, "preview": preview, "open": open_rows, "closed": closed, "log": log, "equity": eq,
            "execution": {"fills": len(slips),
                          "avg_slippage_pct": round(sum(slips) / len(slips), 4) if slips else None},
            "confirm_live": CONFIRM_LIVE, "confirm_flatten": CONFIRM_FLATTEN}
