# Beobachtungen und offene Punkte (laufendes Protokoll)

Geführt von den automatischen Pflege-Läufen (geplante Aufgabe „Krypto-Website Pflege“) und von
Hand. Neueste Einträge oben. Einträge älter als 6 Wochen werden zu einer kurzen
Zusammenfassung verdichtet.

## 2026-11-18 (Abend, von Hand)

**Kennzahlen (Produktion, nur lesend):**
- Mangel „KI-Trader-Schleife läuft nicht“ (2× heute) war ein **Fehlalarm**: Im Prüfer-Modus
  entfällt der Analyse-Zyklus, `last_run` ändert sich nur bei einem Detektor-Signal. Die
  Schleife lief (nächster Zyklus wurde laufend neu geplant).
- Ereignisschleife: 567 Blockaden > 1 s seit dem Start, max. 33 s. In 20 Minuten 65 s blockiert,
  davon 54 s im Setup-Trigger (Merkmale für alle Symbole alle 30 s neu gebaut).
- Cloud-Backtests: 70 min bzw. 3 h **Daten laden** (9–32 Mio. 1m-Kerzen), Simulation 1–15 s.
  Grund: Nach jedem Deploy ist der Platten-Cache leer, ins Archiv sicherte nur der Setup-Backtest.
- KI-Kosten: Analyst (GPT-6 Luna Pro) ~22.000 Tokens je Aufruf, 110–240 Aufrufe/Tag. Der Prüfer
  hat seit dem Stichtag **kein einziges** Signal genommen (taken 0, Signal-Fenster 177 geöffnet).
  Guthaben 5,97 $, Verbrauch ~1,43 $/Tag.
- IBKR-Gateway (Render-Dienst): erreichbar, aber nicht eingeloggt (401) – wird nicht genutzt.
- Live: keine statische Strategie mehr live offen; Portfolio unverändert 14 Positionen.

**Geändert (deployt):**
- Herzschlag der KI-Hauptschleife; der Arzt meldet nur noch echtes Hängen (> 20 min ohne Runde).
  Im Prüfer-Modus kein „Nächste Marktanalyse“ mehr in der Anzeige.
- Setup-Trigger: Merkmale nur bei neuer geschlossener 5m-Kerze (vorher 10× zu oft), Rechnung im
  Thread statt in der Ereignisschleife.
- Daten: Stundenkerzen-Stufe (`candle_hourly`) für Backtests/Optimizer/Forschung ab 1h
  (60× weniger Daten, gleiche Kerzen); kompaktes Format CKC1 (~3× kleiner, verlustfrei);
  Archiv sichert jetzt automatisch alles von der Börse Geladene; alte Archivdateien werden
  gelesen und beim nächsten Sichern ins neue Format übernommen.
- KI-Prüfung: Stichprobe (jede 3.), wenn die KI ein Setup fast nie nimmt (≤ 5 %, ≥ 10 Absagen).

**Beim nächsten Lauf prüfen:**
1. `/api/system/ram` → `hourly_cache` (requests, archive_uploads) und `candle_archive`
   (uploaded, migrated, failed); Backtest-Benchmark `base` = "1h" und `data_seconds`.
2. Loop-Health: Blockaden durch `setup_trigger` deutlich seltener?
3. Analyst-Aufrufe/Tag nach der Stichproben-Regel; nimmt der Prüfer überhaupt Signale?
4. Leitstand: kein Fehlalarm „Schleife läuft nicht“ mehr.

## 2026-11-17 (spät, von Hand)

**Kennzahlen:**
- KI-Trader, Tagesbilanz (geschlossen): 12.11. −0,58 R · 13.11. −0,46 R · 14.11. −0,16 R ·
  15.11. −0,23 R · 16.11. −0,42 R · 17.11. −0,19 R.
- Seit den Fixes (eröffnet ab 16.11. 16 Uhr): 45 Trades, −0,06 R netto, +0,03 R vor Gebühren,
  53 % Gewinner. Das ist kein Beleg für einen Vorteil (t −0,4), aber deutlich weniger Verlust als
  vorher (~−0,5 R).
- 15 offene KI-Trades mit +274 USDT unrealisiert (Paper).
- Live-Portfolio: Der Positions-Wächter sieht 14 Börsen-Positionen, alle dem Portfolio
  zugeordnet. Kein SL fehlt, keine Fehler.

**Fehler behoben (vom Trader gemeldet):**
- TP1 und TP-Full lagen bei 11 von 15 offenen KI-Trades auf demselben Kurs. Ursache:
  Detektoren liefern TP1 1 R / TP-Full 1,5 R, das CRV-Minimum 1,5 hob nur TP1 an. Jetzt folgt
  TP-Full im selben Verhältnis. Die Karte zeigt das echte R statt der Coin-Einstellung.
- Die Analyse-Statistik (PnL, Anzahl, Performance je Strategie) rechnete nur über die geladenen
  Trades. Jetzt kommt sie vom Server über alle Trades (`/api/autotrade/trade-summary`).

**Offen / beim nächsten Lauf prüfen:**
- Neue KI-Trades: Liegen TP1 und TP-Full auseinander? Wirkt sich der weitere TP-Full auf das R aus?
- Bewertungs-Stichtag: auf Wunsch des Traders per einmaliger Boot-Migration auf den
  17.11. 23:15 gesetzt (nach dem TP-Fix, nicht 19:45). Im Leitstand jederzeit änderbar.
- Analyse-Statistik sprang trotz Server-Summe noch: Beim ersten Laden (~3,5 s) und bei jedem
  Fehlversuch zeigte die Ansicht kurz die Teil-Summe der geladenen Trades. Jetzt bleibt der
  letzte Server-Stand je Filter/Coin stehen, beim ersten Laden steht „…“; Teil-Summen nur noch
  mit sichtbarem Hinweis, wenn der Server nicht antwortet. Zeilen-Cache 10 s im Backend.
- Die ~3,3 s je Abfrage kamen vom alten Prozess: Nach dem Deploy antworteten rund zehn Minuten
  lang **zwei Prozesse abwechselnd** (Speicher 622 MB / 759 MB, verschiedene Zähler). Danach mit
  Cache ~50 ms.
- **Risiko Deploy-Überlappung:** Fällt ein neuer Portfolio-Tag in diese Minuten, könnten beide
  Prozesse dieselbe Live-Position eröffnen (die asyncio-Sperre gilt nur je Prozess). Vorschlag
  als Branch `claude/vorschlag-2026-11-17` (Sperre in MongoDB für `portfolio_live.sync`/`health`,
  Tests grün). Der Trader gibt ihn frei. Bis dahin: nicht kurz nach 0 Uhr UTC deployen.
- Live-Portfolio nach dem Deploy: 14 Positionen, alle dem Portfolio zugeordnet, kein SL fehlt.

## 2026-11-17 (Abend, von Hand)

**Kennzahlen (Produktion, nur lesend):**
- Analyst/Prüfer (GPT-6 Luna Pro): 220 Aufrufe, ~4,8 Mio. Tokens am 17.11.
- OpenRouter-Hauptguthaben: 7,44 $. Die Reichweiten-Anzeige liefert erst ab ~12 h Verlauf Werte.
- Prüfer seit dem Fix: 20 Signale geprüft, alle mit echter Begründung (kein „bereits offen“
  mehr). Fast alle waren Long-Signale gegen den Abwärtstrend (safe_haven_flow) und wurden
  abgelehnt.
- Portfolio (Rückrechnung, vorsichtig): 19 Shorts, alle im Plus. Funding-Korb 8 long / 8 short.
- TrendFolge2: vom Live-Wächter gestoppt (seit November −0,45 R).
- Trades außerhalb der Website („external“): 30 Trades, −1.088 USDT.

**Geändert heute:**
- KI-Prüfung entfällt für klare Gegentrend-Signale (LONG bei Tages-Bias down, SHORT bei up).
  Diese Signale können weder live gehen (Edge-Filter) noch einen Kontroll-Trade bekommen.
  Erwartung: deutlich weniger Analyst-Aufrufe in Trendphasen.
- Offline-Prüfkit `backend/tests/offline/` (Tests ohne Netzwerk, Frontend-Syntaxcheck).

**Beim nächsten Lauf prüfen:**
1. Analyst-Aufrufe pro Tag nach der Gegentrend-Sperre (vorher ~200/Tag).
2. KI-geprüfte Trades (`ki_geprueft`) und Veto-Bilanz: Gibt es erste Einstiege mit dem Trend?
3. Guthaben-Reichweite (`key_credits.runway_days`, `burn_usd_day`).
4. Nachtsuche: Ergebnisse auf dem Local Worker (`/api/optimizer/history`,
   `/api/optimizer/explore/best`). Neue Rotation: Krypto 1h Trend → 1h → 15m.
5. Fehler/Leerantworten (`/api/ai/providers/health` → `recent_failures`).

**Offene Ideen (noch nicht gebaut):**
- Limit- statt Marktorders im Live-Portfolio (geschätzt +3–4 Prozentpunkte pro Jahr). Betrifft
  die Live-Ausführung, deshalb nur als Pull Request.
- `review_allocation`: Wenn die KI ein Setup nie nimmt („genommen“ = 0), wird dauerhaft
  geprüft. Eine Stichproben-Regel wäre günstiger. Erst nach 1–2 Wochen sauberer Daten
  entscheiden.
- Not-Aus des Live-Portfolios (30 %) passt nicht ganz zu 1 % Risiko je Trade (Rückgänge bis
  44 % ab 2025). Das entscheidet der Trader.
