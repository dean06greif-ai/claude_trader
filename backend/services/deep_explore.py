"""Endlos-Suche (Deep Explore): sucht so lange neue Indikator-Kombinationen,
bis genügend Kombinationen sowohl die normale Suche (Training) ALS AUCH den
Walk-Forward-Test (unbekannte Testdaten) bestehen – mit ähnlich gutem Ergebnis
auf beiden Datensätzen.

Ablauf pro Runde:
1. Batch zufälliger, noch nie getesteter Kombinationen ziehen
   (gewichtete Auswahl nach bisheriger Trefferquote + 35% reine Exploration,
   damit auch "vermeintlich sinnlose" Indikatoren immer wieder drankommen)
2. Positive Kombinationen werden je `iterations` Mal feinjustiert (Schwellen)
3. Bestandene Kandidaten laufen durch den Walk-Forward auf den Holdout-Daten
4. Champions (Training positiv + Test positiv + Konsistenz >= X%) kommen in
   die Top-5 – die Suche läuft weiter, bis das Ziel erreicht ist, das
   Zeitlimit greift oder der Nutzer stoppt (Stop-Button, Bestes bleibt)

Jeder Lauf nutzt einen frischen Zufalls-Seed -> zwei Läufe liefern nie
dieselbe Suche. Die globale Top-5 wird serverseitig über alle Läufe gemerkt.
"""
import copy
import logging
import math
import random
import time
from datetime import datetime, timezone
from typing import Dict, List, Tuple

from services import robustness
from services.backtester import JobCancelled

logger = logging.getLogger(__name__)

MAX_SEEN = 250000          # Sicherheitsdeckel für das Duplikat-Gedächtnis
REFINE_PER_BATCH = 3       # wie viele Positive je Batch verfeinert werden
EPSILON = 0.35             # Anteil rein zufälliger Kombis (Exploration)
REVISIT_KEEP = 40          # vielversprechende Kombis für erneute Verfeinerung
REVISIT_PASSES = 3         # so oft wird der Pool nach Ausschöpfung neu verfeinert
LOW_VALID_PCT = 5.0        # darunter: Hinweis "zu wenige Trades je Kombi"
MIN_TRIALS_BUDGET = 100    # Signifikanz-Hürde gilt ab der 1. Prüfung für >= 100 Versuche
# Prüf-Stand der Champions. 2 = ab 16.11.2026: Test/Tresor rechnen nachweislich auf
# eigenen Daten (vorher nutzte der Multi-Core-Pool des lokalen Workers dafür die
# Trainings-Kerzen – Champions älterer Läufe sind deshalb NICHT geprüft).
# 3 = ab 17.11.2026 (F1): Training in R positiv, Tresor mit Ø R und mind. 10
# Trades, Versuchs-Konto über Läufe, Rückwärtstest auf älteren Daten.
EXPLORE_ENGINE = 3


def size_weights(sizes: List[int], valid: Dict[int, List[int]]) -> List[float]:
    """Kombi-Größen nach Anteil Kombis mit genug Trades gewichten (rein): viele
    UND-Regeln feuern selten – dann öfter kleinere Kombis ziehen."""
    out = []
    for k in sizes:
        n, ok = valid.get(k, [0, 0])
        out.append(0.15 + (ok / n if n >= 20 else 0.5))
    return out


def consistent_wf(wf: Dict, min_consistency: float) -> bool:
    """Übereinstimmung Training↔Test – ein im Test BESSERES Ergebnis ist kein
    Overfitting und darf nicht durchfallen (Konsistenz = min/max misst beide
    Richtungen gleich, das sortierte gute Kandidaten aus)."""
    if float(wf.get("test_quality") or 0) >= float(wf.get("train_quality") or 0) > 0:
        return True
    return float(wf.get("consistency_pct") or 0) >= min_consistency


def one_per_indicator(combo: List[str], ind_of: Dict[str, str]) -> bool:
    """Nicht zweimal dieselbe Indikator-Familie (z.B. RSI<25 UND RSI<35) – rein."""
    inds = [ind_of.get(l, l) for l in combo]
    return len(set(inds)) == len(inds)


def _def_with(base: Dict, cands: List[Dict]) -> Dict:
    d = copy.deepcopy(base)
    d["long_rules"] = list(base.get("long_rules") or []) + [dict(c["long"]) for c in cands]
    d["short_rules"] = list(base.get("short_rules") or []) + [dict(c["short"]) for c in cands]
    return d


async def run(opt, job, histories, test_hist, settings, cfg, objective,
              min_trades, max_rules, allowed, progress, iterations,
              fs_map, fs_test, should_stop, pool, workers, dd_max_pct,
              train_days, test_days, explore_cfg, base_definition=None,
              tf_options=None, trade_space=None):
    """Rückgabe: (champions_top5, report). `opt` = optimizer-Modul."""
    cands = opt.build_candidates(allowed, tf_options)
    if len(cands) < 2:
        raise RuntimeError("Endlos-Suche braucht mindestens 2 Indikator-Kandidaten")
    if not test_hist:
        raise RuntimeError("Endlos-Suche braucht einen Walk-Forward-Split (Testdaten)")
    ecfg = explore_cfg or {}
    target = min(max(int(ecfg.get("target_champions") or 5), 1), 10)
    try:
        max_minutes = float(ecfg.get("max_minutes") or 0)
    except (TypeError, ValueError):
        max_minutes = 0.0
    max_minutes = min(max(max_minutes, 0.0), 1440.0)
    try:
        min_consistency = float(ecfg.get("min_consistency_pct") or 40)
    except (TypeError, ValueError):
        min_consistency = 40.0
    min_consistency = min(max(min_consistency, 0.0), 95.0)
    # Frischer Seed je Lauf: zwei Läufe erkunden NIE denselben Pfad
    rng = random.Random(ecfg.get("seed") or time.time_ns())

    base = copy.deepcopy(base_definition) if base_definition else {
        "name": "Endlos-Suche", "indicators": {}, "long_rules": [], "short_rules": []}
    base.setdefault("indicators", {})
    base.setdefault("long_rules", [])
    base.setdefault("short_rules", [])
    max_rules = min(max(int(max_rules), 2), 6)
    labels = [c["label"] for c in cands]
    by_label = {c["label"]: c for c in cands}
    sizes = [x for x in (2, 2, 2, 3, 3, 3, 4, 4, 5, 6) if x <= max_rules]

    # 11/2026 (Prod-Läufe: 250.000 Kombis, 0 verfeinert): Der Drawdown-Filter
    # (DD <= X % des PnL) wirkte schon beim ERSTEN Test jeder Kombi. Jede Kombi
    # mit PnL <= 0 oder etwas Drawdown bekam den Ausschluss-Wert – damit wurde
    # NICHTS verfeinert (auch nicht die Rettung der besten Beinahe-Kombi), und
    # bei vielen Assets summieren sich die Drawdowns je Symbol zusätzlich.
    # Der Filter gilt jetzt dort, wo er hingehört: auf den Testdaten (test_dd_ok).
    search_dd = None

    def score(m):
        return opt._score(m, objective, min_trades, search_dd)

    def profitable(m, sc):
        # "positiv" = Filter bestanden UND echter Gewinn. sc > 0 allein reichte
        # nicht: beim Ziel "win_rate" (wr*1000 + pnl) war auch ein Verlust-Kandidat > 0.
        return sc > -4e8 and float(m.get("pnl") or 0) > 0

    # Mindest-Trades im Test-Split (anteilig zu min_trades), sonst ist ein
    # positiver Test-PnL mit 1-2 Trades Glück statt Nachhaltigkeit.
    test_share = (test_days / train_days) if train_days else 0.0
    min_test_trades = max(3, int(round(min_trades * test_share * 0.5)))
    # Analyse 15.11.2026 (A1/A5): Die Suche prüft beliebig viele Kandidaten
    # gegen DIESELBEN Testdaten – auf einem Random Walk bestanden so ~27 % der
    # geprüften Kandidaten ("Champions" aus reinem Zufall). Deshalb:
    #  1. Signifikanz: Erwartungswert in R auf den Testdaten muss die Hürde
    #     nehmen, die mit der Zahl der geprüften Kandidaten steigt (Bonferroni).
    #  2. Tresor-Daten: jüngster, von Suche und Test nie gesehener Abschnitt;
    #     nur wer 1. besteht, wird dort EINMAL geprüft.
    # require_significance=false stellt das alte Verhalten wieder her.
    from services import champion_checks, evidence_stats
    require_sig = ecfg.get("require_significance") is not False
    vault_hist = ecfg.get("_vault_hist") or None
    vault_days = float(ecfg.get("_vault_days") or 0.0)
    fs_vault = ({s: opt.fast_sim.FastSeries(c) for s, c in vault_hist.items()}
                if vault_hist else None)
    # F1 (16.11.2026): Tresor verlangt genug Trades UND Ø R > 0 (vorher reichte
    # „Gewinn > 0“ mit ~4 Trades – unter Zufall besteht das jede zweite Kombi).
    min_vault_trades = max(champion_checks.VAULT_MIN_TRADES,
                           int(round(min_test_trades * (vault_days / test_days)))
                           if test_days else champion_checks.VAULT_MIN_TRADES)
    vault_checked = 0
    # Versuchs-Konto: Prüfungen früherer Läufe auf denselben Daten (30 Tage)
    # zählen für die Hürde mit – sonst bekäme jeder neue Lauf eine frische Chance.
    try:
        prior_trials = max(0, int(ecfg.get("_prior_trials") or 0))
    except (TypeError, ValueError):
        prior_trials = 0
    # Rückwärtstest: Tage VOR dem Suchfenster, nie für Suche/Test/Tresor benutzt
    back_hist = ecfg.get("_back_hist") or None
    back_days = float(ecfg.get("_back_days") or 0.0)
    fs_back = ({s: opt.fast_sim.FastSeries(c) for s, c in back_hist.items()}
               if back_hist else None)
    back_checked = 0

    def trials_now():
        return max(wf_checked + prior_trials, MIN_TRIALS_BUDGET)

    async def ev(defs, hists, fsm, tp=None):
        out = []
        chunk = max(int(workers), 1)
        run_cfg = {**cfg, **(tp or {})}
        for i in range(0, len(defs), chunk):
            if should_stop and should_stop():
                raise JobCancelled()
            part = defs[i:i + chunk]
            items = [(opt._mk_strategy(d), settings, run_cfg) for d in part]
            out.extend(await opt._evaluate_batch(job, pool, items, hists, fsm,
                                                 should_stop))
        return out

    stats = {lab: {"n": 0, "pos": 0, "best": -1e18} for lab in labels}
    seen = set()
    champions: List[Dict] = []
    near_misses: List[Dict] = []
    tested = refined = wf_checked = 0
    valid_n = rescued = tuned = revisits = 0
    valid_by_k: Dict[int, List[int]] = {}
    ind_of = {c["label"]: c["ind"] for c in cands}
    revisit_pool: List[Dict] = []     # beste gültige Kombis (für Ausschöpfung)
    revisit_idx = 0
    t0 = time.time()
    stop_reason = None
    total_space = sum(math.comb(len(cands), k)
                      for k in range(2, max_rules + 1))

    def sample_combo():
        weights = size_weights(sizes, valid_by_k)
        for _ in range(60):
            k = min(rng.choices(sizes, weights=weights)[0], len(cands))
            if rng.random() < EPSILON:
                combo = rng.sample(labels, k)
            else:
                pool_l = list(labels)
                pool_w = []
                for lab in pool_l:
                    s = stats[lab]
                    rate = s["pos"] / s["n"] if s["n"] else 0.25
                    pool_w.append(0.5 + 3.0 * rate)
                combo = []
                for _i in range(k):
                    pick = rng.choices(range(len(pool_l)), weights=pool_w)[0]
                    combo.append(pool_l.pop(pick))
                    pool_w.pop(pick)
            if len(set(ind_of.values())) >= k and not one_per_indicator(combo, ind_of):
                continue
            key = tuple(sorted(combo))
            if key not in seen:
                seen.add(key)
                return combo
        return None

    def phase_txt():
        el = max(time.time() - t0, 1e-6)
        rate = tested / (el / 60.0)
        best_txt = (f" · Best-WF {champions[0]['wf']['wf_score']:.1f}"
                    if champions else "")
        # Der Balken misst Champions/Ziel (bzw. Zeitlimit) – ohne Champion bleibt
        # er bewusst bei 10 %: der Zähler hier zeigt, dass die Suche arbeitet.
        prog_txt = (" · Balken = Zeitlimit" if max_minutes
                    else " · Balken = Champions/Ziel")
        vp = valid_n / tested * 100 if tested else 100.0
        hint = (f" · nur {vp:.1f} % mit ≥{min_trades} Trades (weniger Regeln/Indikatoren oder Min-Trades senken)"
                if tested >= 200 and vp < LOW_VALID_PCT else f" · {vp:.0f} % mit genug Trades")
        rev = f" · Wiederholung {revisits}" if revisits else ""
        return (f"Endlos-Suche · {tested} Kombis · {refined} verfeinert · "
                f"{len(champions)}/{target} Champions{best_txt} · "
                f"{rate:.0f} Kombis/min{hint}{rev}{prog_txt}")

    def pct():
        if max_minutes:
            return min((time.time() - t0) / (max_minutes * 60) * 100, 99)
        return min(len(champions) / target * 100, 99)

    def stopping():
        if job.get("stop_explore"):
            return "stopped_by_user"
        if max_minutes and time.time() - t0 > max_minutes * 60:
            return "time_limit"
        if len(champions) >= target:
            return "target_reached"
        return None

    def add_champion(entry):
        key = tuple(sorted(entry["labels"]))
        champions[:] = [c for c in champions
                        if tuple(sorted(c["labels"])) != key]
        champions.append(entry)
        champions.sort(key=lambda x: -x["wf"]["wf_score"])
        del champions[10:]
        job["best"] = {"rules": entry["rules"], "metrics": entry["metrics"],
                       "definition": entry.get("definition"),
                       "trade_params": entry.get("trade_params") or {},
                       "explore": {"champions": len(champions),
                                   "wf_score": entry["wf"]["wf_score"],
                                   "test_pnl": (entry["test_metrics"] or {}).get("pnl")}}

    def remember(cand):
        """Vielversprechende gültige Kombi für spätere Wiederholungs-Verfeinerung."""
        revisit_pool.append(cand)
        revisit_pool.sort(key=lambda x: -x["score"])
        del revisit_pool[REVISIT_KEEP:]

    def consistent(wf):
        return consistent_wf(wf, min_consistency)

    async def refine_and_test(cand):
        """Schwellen verfeinern, ggf. Trade-Einstellungen (TP/SL …) suchen, dann
        Walk-Forward auf dem Holdout – Champion oder Beinahe-Treffer."""
        nonlocal refined, wf_checked, tuned, vault_checked, back_checked

        def sub_prog(done, total, phase):
            progress(pct(), f"{phase_txt()} · {phase}")

        d2, m2, _log = await opt._refine(
            job, cand["definition"], cand["score"], cand["metrics"],
            histories, settings, cfg, objective, min_trades, iterations,
            sub_prog, fs_map, should_stop, search_dd, None)
        refined += 1
        m_fin = m2 or cand["metrics"]
        sc2 = score(m_fin)
        tp = {}
        if trade_space and sc2 > -9e8:
            # Feste Standard-TP/SL machen viele Kombis künstlich unprofitabel
            tp, m3, sc3 = await opt._optimize_trade_settings(
                job, d2, sc2, m_fin, histories, settings, cfg, objective, min_trades,
                max(iterations // 2, 10), trade_space, sub_prog, fs_map, should_stop,
                pool, workers, search_dd, None)
            tuned += 1
            if tp:
                m_fin, sc2 = m3, sc3
        if not profitable(m_fin, sc2):
            return
        test_m = (await ev([d2], test_hist, fs_test, tp))[0]
        wf_checked += 1
        wf = robustness.walk_forward_eval(m_fin, test_m, train_days, test_days)
        # Ohne bessere Variante: die tatsächlich genutzten Standard-Werte zeigen
        used_tp = dict(tp) if tp else {k: cfg[k] for k in (trade_space or {}) if k in cfg}
        entry = {"labels": list(cand["labels"]), "definition": d2, "trade_params": used_tp,
                 "metrics": m_fin, "test_metrics": test_m, "wf": wf,
                 "score": round(sc2, 3), "rules": opt._labels(d2),
                 "found_at": datetime.now(timezone.utc).isoformat()}
        test_trades = int(test_m.get("trades") or 0)
        test_dd_ok = (dd_max_pct is None
                      or robustness.dd_check(test_m, dd_max_pct)[0])
        # 11/2026: Mit dem LAUFENDEN Zähler hatten frühe Kandidaten eine niedrige
        # Hürde (1., 2., 3. Prüfung …) – über den Lauf summiert sich das zu einer
        # Fehlalarm-Rate von ~α·ln(N). Die Hürde gilt deshalb von Anfang an für
        # mindestens MIN_TRIALS_BUDGET Prüfungen (Zufalls-Benchmark: 1 Fehlalarm
        # in 3 Läufen vorher, siehe tests).
        evidence = evidence_stats.significance(test_m, n_trials=trials_now())
        evidence["engine"] = EXPLORE_ENGINE
        evidence["prior_trials"] = prior_trials
        entry["evidence"] = evidence
        entry["wf_trials"] = wf_checked
        # F1: Training muss auch in R im Plus sein (nicht nur in USDT)
        tr_ok, tr_why = champion_checks.train_ok(m_fin)
        entry["train"] = champion_checks.r_summary(m_fin)
        basic_ok = (float(test_m.get("pnl") or 0) > 0 and test_trades >= min_test_trades
                    and test_dd_ok and consistent(wf) and tr_ok)
        sig_ok = evidence["passed"] or not require_sig
        vault_ok, vault_why = True, ""
        vault_m = None
        if basic_ok and sig_ok and fs_vault is not None:
            vault_m = (await ev([d2], vault_hist, fs_vault, tp))[0]
            vault_checked += 1
            vault_ok, vault_why = champion_checks.vault_ok(vault_m, min_vault_trades)
            entry["vault"] = {"metrics": vault_m, "passed": vault_ok,
                              "days": round(vault_days, 1),
                              "min_trades": min_vault_trades, "reason": vault_why,
                              **{k: v for k, v in champion_checks.r_summary(vault_m).items()
                                 if k in ("avg_r", "t")}}
        back_ok, back_why = True, ""
        if basic_ok and sig_ok and vault_ok:
            back_m = None
            if fs_back is not None:
                back_m = (await ev([d2], back_hist, fs_back, tp))[0]
                back_checked += 1
            bv = champion_checks.back_verdict(back_m, back_days)
            entry["backward"] = bv
            # Standard: hartes Tor. `explore.backward_gate=false` lässt einen im
            # Rückwärtstest durchgefallenen Champion zu (nur markiert) – für Vorteile,
            # die es erst seit kurzem gibt; dann entscheidet allein der Vorwärtstest.
            if ecfg.get("backward_gate") is not False:
                back_ok, back_why = bv["passed"], bv["reason"]
            entry["unseen"] = champion_checks.combined_unseen([vault_m, back_m])
        if basic_ok and sig_ok and vault_ok and back_ok:
            # Long- und Short-Seite getrennt auf den Testdaten (reine Information:
            # hängt der Vorteil nur an einer Seite, kann es Marktrichtung sein)
            try:
                side_defs = [{**d2, "short_rules": []}, {**d2, "long_rules": []}]
                lm, sm = await ev(side_defs, test_hist, fs_test, tp)
                entry["sides"] = champion_checks.side_split(lm, sm)
            except JobCancelled:
                raise
            except Exception:  # noqa: BLE001 – Zusatz-Info darf keinen Champion kosten
                entry["sides"] = None
            add_champion(entry)
        else:
            near_misses.append({
                "labels": entry["labels"], "score": entry["score"],
                "train_pnl": m_fin.get("pnl"), "test_pnl": test_m.get("pnl"),
                "consistency_pct": wf["consistency_pct"],
                "t": evidence.get("t"), "t_required": evidence.get("t_required"),
                "reason": ("Test-PnL negativ"
                           if float(test_m.get("pnl") or 0) <= 0
                           else f"nur {test_trades} Test-Trade{'' if test_trades == 1 else 's'} (< {min_test_trades})"
                           if test_trades < min_test_trades
                           else "Drawdown im Test über Limit" if not test_dd_ok
                           else f"Konsistenz {wf['consistency_pct']}% < {min_consistency}%"
                           if not consistent(wf)
                           else tr_why if not tr_ok
                           else f"nicht signifikant: {evidence.get('reason')}"
                           if not sig_ok
                           else (vault_why or "Tresor-Daten nicht bestanden") if not vault_ok
                           else back_why)})
            near_misses.sort(key=lambda x: -x["score"])
            del near_misses[5:]
        progress(pct(), phase_txt())

    batch_n = max(int(workers) * 2, 8)
    while True:
        stop_reason = stopping()
        if stop_reason:
            break
        combos, defs = [], []
        for _ in range(batch_n):
            c = sample_combo()
            if c is None:
                break
            combos.append(c)
            defs.append(_def_with(base, [by_label[l] for l in c]))
        if not combos or len(seen) >= MAX_SEEN:
            # Kombi-Raum ausgeschöpft: statt aufzuhören die vielversprechendsten
            # Kombis erneut verfeinern (neue Zufalls-Schwellen + TP/SL)
            if not revisit_pool or revisits >= REVISIT_PASSES * len(revisit_pool):
                stop_reason = "space_exhausted"
                break
            cand = revisit_pool[revisit_idx % len(revisit_pool)]
            revisit_idx += 1
            revisits += 1
            await refine_and_test(cand)
            continue
        ms = await ev(defs, histories, fs_map)
        positives, valid = [], []
        for combo, d, m in zip(combos, defs, ms):
            tested += 1
            sc = score(m)
            ok_trades = int(m.get("trades") or 0) >= min_trades
            vk = valid_by_k.setdefault(len(combo), [0, 0])
            vk[0] += 1
            if ok_trades:
                vk[1] += 1
                valid_n += 1
            for lab in combo:
                s = stats[lab]
                s["n"] += 1
                if profitable(m, sc):
                    s["pos"] += 1
                if sc > s["best"]:
                    s["best"] = sc
            item = {"labels": combo, "definition": d, "metrics": m, "score": sc}
            if profitable(m, sc):
                positives.append(item)
            elif sc > -4e8:
                valid.append(item)
        progress(pct(), phase_txt())

        positives.sort(key=lambda x: -x["score"])
        valid.sort(key=lambda x: -x["score"])
        for cand in positives[:REFINE_PER_BATCH] + valid[:1]:
            remember(cand)
        todo = positives[:REFINE_PER_BATCH]
        if not todo and valid:
            # Kein Positiver im Batch: die beste gültige Kombi (genug Trades,
            # knapp im Minus) trotzdem verfeinern – Schwellen/TP-SL drehen oft ins Plus
            todo = valid[:1]
            rescued += 1
        for cand in todo:
            if stopping():
                break
            await refine_and_test(cand)

    elapsed = max(time.time() - t0, 1e-6)
    ind_stats = sorted(
        [{"indicator": by_label[lab]["ind"], "label": lab, "tried": s["n"],
          "positive_pct": round(s["pos"] / s["n"] * 100, 1) if s["n"] else 0.0}
         for lab, s in stats.items() if s["n"]],
        key=lambda x: -x["positive_pct"])[:12]
    top = champions[:5]
    report = {
        "mode": "explore", "tested": tested, "refined": refined,
        "wf_checked": wf_checked, "champions_found": len(champions),
        "champions": top, "near_misses": near_misses,
        "elapsed_seconds": round(elapsed, 1),
        "combos_per_min": round(tested / (elapsed / 60), 1),
        "stop_reason": stop_reason, "target_champions": target,
        "max_minutes": max_minutes, "min_consistency_pct": min_consistency,
        "min_test_trades": min_test_trades,
        "require_significance": require_sig,
        "t_required": round(evidence_stats.required_t(trials_now()), 3),
        "prior_trials": prior_trials,
        "vault_days": round(vault_days, 1) if fs_vault is not None else 0,
        "vault_checked": vault_checked,
        "backward_days": round(back_days, 1) if fs_back is not None else 0,
        "backward_checked": back_checked,
        "indicator_stats": ind_stats,
        "valid_pct": round(valid_n / tested * 100, 2) if tested else 0.0,
        "rescue_refined": rescued, "trade_tuned": tuned, "revisits": revisits,
        "candidates": len(cands), "total_space": total_space,
        "space_seen_pct": round(len(seen) / total_space * 100, 4) if total_space else 0.0,
        "evaluations": (job.get("_bench") or {}).get("evaluations"),
    }
    return top, report


LEGACY_REASON = ("alte Prüfung (vor dem 17.11.2026): ohne Rückwärtstest, Versuchs-Konto und "
                 "strengen Tresor; bis 16.11. liefen Test und Tresor auf dem lokalen Worker sogar "
                 "auf den Trainingsdaten – nicht belastbar, nur zur Ansicht")
BEST_MAX = 5


def is_validated(item: Dict) -> bool:
    """Champion mit der ehrlichen Prüfung gefunden? Ab Prüf-Stand EXPLORE_ENGINE
    (16.11.2026: Test/Tresor auf eigenen Daten) – ältere sind Altbestand (rein)."""
    ev = (item or {}).get("evidence")
    if not isinstance(ev, dict):
        return False
    try:
        return int(ev.get("engine") or 0) >= EXPLORE_ENGINE
    except (TypeError, ValueError):
        return False


def split_best(doc: Dict) -> Tuple[List[Dict], List[Dict]]:
    """Bestenliste in (geprüft, Altbestand) trennen (rein). Alte Einträge werden
    nicht gelöscht, sondern verdrängen nur keine neuen Champions mehr – ihr
    aufgeblähter WF-Score (Test = Training) hätte jeden ehrlichen Fund blockiert."""
    doc = doc or {}
    items = list(doc.get("items") or [])
    legacy = list(doc.get("legacy_items") or [])
    current = [i for i in items if is_validated(i)]
    for i in items:
        if not is_validated(i):
            legacy.append({**i, "legacy_reason": i.get("legacy_reason") or LEGACY_REASON})
    seen, uniq = set(), []
    for i in legacy:
        key = robustness.rule_key(i.get("definition") or {})
        if key in seen:
            continue
        seen.add(key)
        uniq.append(i)
    return current, uniq[:BEST_MAX]


async def persist_best(db, result):
    """Globale Top-5 über ALLE Endlos-Läufe (dedupe per Regel-Schlüssel).
    Nur ehrlich geprüfte Champions konkurrieren; der Altbestand bleibt getrennt."""
    if db is None:
        return
    try:
        from services import champion_checks
        await champion_checks.record_trials(db, result)
    except Exception:  # noqa: BLE001 – das Konto darf die Bestenliste nie blockieren
        pass
    champs = ((result or {}).get("explore_report") or {}).get("champions") or []
    champs = [c for c in champs if is_validated(c)]
    if not champs:
        return
    # Vorwärtstest (services/research_pipeline) braucht Assets, Zeitebene und
    # Lauf-Herkunft je Champion – im Lauf-Ergebnis stehen sie nur einmal oben.
    ctx = {k: (result or {}).get(k) for k in ("symbols", "timeframe", "days")}
    champs = [{**c, **{k: v for k, v in ctx.items() if v and not c.get(k)}} for c in champs]
    doc = await db.settings.find_one({"_id": "deep_explore_best"}) or {}
    items, legacy = split_best(doc)

    def wf_score(x):
        return (x.get("wf") or {}).get("wf_score", -1e18)

    by_key = {robustness.rule_key(i.get("definition") or {}): i for i in items}
    for c in champs:
        key = robustness.rule_key(c.get("definition") or {})
        cur = by_key.get(key)
        if cur is None or wf_score(c) > wf_score(cur):
            by_key[key] = c
    merged = sorted(by_key.values(), key=lambda x: -wf_score(x))[:BEST_MAX]
    await db.settings.update_one(
        {"_id": "deep_explore_best"},
        {"$set": {"items": merged, "legacy_items": legacy,
                  "updated_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True)
