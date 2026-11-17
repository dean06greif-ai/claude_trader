"""Gesamt-Statistik der Trades für die Analyse-Ansicht (17.11.2026).

Bisher rechnete das Frontend PnL, Anzahl und „Performance je Strategie“ aus den
gerade GELADENEN Trades (die letzten 200 + „Mehr laden“). Beim Nachladen
änderte sich deshalb die Statistik (Trader-Meldung). Jetzt kommt sie über ALLE
Trades vom Server – mit exakt denselben Filtern wie in der Ansicht.
"""
import time
from typing import Callable, Dict, Iterable, List, Optional

FILTERS = ("all", "live", "paper", "collection")
FIELDS = {"_id": 0, "id": 1, "status": 1, "mode": 1, "data_collection": 1, "strategy_id": 1,
          "strategy_name": 1, "symbol": 1, "result": 1, "realized_pnl": 1, "manual_trade": 1,
          "external_adopted": 1}


class RowCache:
    """Kurzzeit-Cache der Trade-Zeilen (Standard 10 s): Ein Filter- oder Coin-Wechsel
    direkt nach einer Abfrage braucht dann keine zweite Voll-Abfrage (~3 s in Produktion)."""

    def __init__(self, ttl: float = 10.0, clock: Callable[[], float] = time.monotonic):
        self.ttl = ttl
        self.clock = clock
        self._rows: Optional[List[Dict]] = None
        self._ts = 0.0

    def get(self) -> Optional[List[Dict]]:
        if self._rows is not None and self.clock() - self._ts < self.ttl:
            return self._rows
        return None

    def put(self, rows: List[Dict]) -> List[Dict]:
        self._rows, self._ts = rows, self.clock()
        return rows

    def clear(self) -> None:
        self._rows = None


CACHE = RowCache()


def passes(t: Dict, flt: str, stale: Callable[[str], bool]) -> bool:
    """Gleiche Logik wie filterFn in PerformanceAnalytics.js (rein)."""
    if stale(t.get("strategy_id") or "external"):
        return False
    if flt == "collection":
        return bool(t.get("data_collection"))
    if t.get("data_collection"):
        return False
    if flt == "live":
        return t.get("mode") == "live"
    if flt == "paper":
        return t.get("mode") != "live"
    return True


def _external(t: Dict) -> bool:
    return t.get("strategy_id") == "external" or bool(t.get("manual_trade")) \
        or bool(t.get("external_adopted"))


def summarize(rows: Iterable[Dict], flt: str = "all", symbol: Optional[str] = None,
              stale: Callable[[str], bool] = lambda _sid: False) -> Dict:
    flt = flt if flt in FILTERS else "all"
    tot = {"open": 0, "closed": 0, "wins": 0, "losses": 0, "pnl": 0.0}
    coin = {"symbol": symbol, "open": 0, "closed": 0, "pnl": 0.0}
    strat: Dict[str, Dict] = {}
    for t in rows:
        if not passes(t, flt, stale):
            continue
        is_open = t.get("status") == "open"
        pnl = float(t.get("realized_pnl") or 0) if not is_open else 0.0
        if is_open:
            tot["open"] += 1
        elif t.get("status") == "closed":
            tot["closed"] += 1
            tot["pnl"] += pnl
            tot["wins"] += t.get("result") == "win"
            tot["losses"] += t.get("result") == "loss"
        if not symbol or t.get("symbol") != symbol:
            continue
        if is_open:
            coin["open"] += 1
        elif t.get("status") == "closed":
            coin["closed"] += 1
            coin["pnl"] += pnl
        if _external(t):
            continue
        sid = t.get("strategy_id") or "unknown"
        e = strat.setdefault(sid, {"id": sid, "name": t.get("strategy_name") or sid, "wins": 0,
                                   "losses": 0, "total": 0, "openCount": 0, "pnl": 0.0})
        if is_open:
            e["openCount"] += 1
        elif t.get("status") == "closed":
            e["total"] += 1
            e["wins"] += t.get("result") == "win"
            e["losses"] += t.get("result") == "loss"
            e["pnl"] += pnl
    tot["pnl"] = round(tot["pnl"], 4)
    coin["pnl"] = round(coin["pnl"], 4)
    for e in strat.values():
        e["pnl"] = round(e["pnl"], 4)
    return {"filter": flt, "totals": tot, "coin": coin, "by_strategy": strat}
