# Änderungen vom 15.11.2026

Grundlage: `ANALYSE_GESAMTSYSTEM_2026-11-15.md` und die Freigabe der einzelnen Punkte.
Die Ordnerstruktur für Render (`backend/`, `frontend/`, `local_worker/`, `ibeam_gateway/`)
ist unverändert. `requirements.txt`, `package.json` und `yarn.lock` wurden nicht angefasst.

## 1. Aufgeräumt

| Was | Umfang |
|---|---|
| Dateien im Repo | 1.348 → 924 |
| Python-Zeilen | ~197.000 → ~153.000 |
| Alte Dokus | 27 Markdown-Dateien im Wurzelverzeichnis, `analysis_paket/`, `test_reports/`, `test_result.md` gelöscht; 5 Handbücher nach `docs/` verschoben |
| Reste | `d.png`, `.screenshots/`, `backend_test.py`, Einmal-Skripte in `scripts/` und `backend/scripts/` (inkl. zwei `.pkl`-Dateien) |
| Totes Frontend | `components/ui/` (46 Dateien), `hooks/use-toast.js`, `lib/utils.js`, `constants/testIds/`, `components.json` |
| Tote Backend-Module | `models/signal.py`, `services/regime_core.py`, `services/gpu_accel.py` |
| Tests | Alle Tests, die einen laufenden Server brauchen (216 Dateien), und 7 Hilfsskripte entfernt. Diese Tests schrieben in die Datenbank, gegen die sie liefen. Feste Pfade `/app/…` in den verbleibenden Tests durch relative ersetzt |

Bewusst behalten: `scripts/copy_prod_readonly_to_local.py`, `scripts/make_icons.py`,
`backend/scripts/backup_restore.py`, `copy_prod_subset_to_dev.py`, `supabase_schema.sql`,
`regime_jump_final_validation.py` (wird von einem Test gebraucht).

## 2. Fund beim Aufräumen: Preis-Wächter war nicht angeschlossen

`services/price_watch.py` (Trade-Verwaltung im 3-Sekunden-Takt) wurde nirgends gestartet;
TP1/Break-even/Trailing liefen nur im Scanner-Takt. Das Modul ist jetzt in `server.py`
verdrahtet, startet aber nur mit `FAST_PRICE_WATCH=1`, damit ein Deploy das Verhalten
nicht ungeprüft ändert.

## 3. Strategie-Suche und Backtest (Analyse Punkt 4)

| Befund | Änderung | Abschalten/zurück |
|---|---|---|
| A1 Testdaten als Auswahlkriterium | **Tresor-Daten:** die jüngsten 15 % der Historie sehen Suche und Walk-Forward nie; nur fertige Kandidaten werden einmal darauf geprüft | `walk_forward.vault_pct: 0` |
| A2 Walk-Forward ließ nie durchfallen | Bestanden nur mit Gewinn, genug Trades **und** belegtem Vorteil auf den Testdaten | `walk_forward.strict: false` |
| A3/A5 keine Korrektur für die Zahl der Versuche | t-Wert des Erwartungswerts in R; die Hürde steigt mit der Zahl der geprüften Kandidaten (Bonferroni). In der Endlos-Suche Pflicht für jeden Champion | `walk_forward.require_significance: false` bzw. `explore.require_significance: false` |
| A7 Hebel/Richtung mitoptimiert | Klartext-Warnung im Ergebnis | – |
| A8 Ziel war absoluter Gewinn | Neues Ziel „Erwartungswert in R" (hebelneutral), in der Oberfläche wählbar | bisherige Ziele unverändert |
| A9 kein Slippage | 0,02 % je Markt-Ausführung (Einstieg, Stop, Trigger-TP); Limit-Fills zahlen nichts. Ergebnis zeigt `slippage` getrennt von `fees` | `slippage_percent: 0` |
| A10 zu kleine Stichproben | Standard Mindest-Trades 30 statt 10; Warnung unter 90 Tagen | gesendeter Wert gilt weiter |
| A11 Monte-Carlo mischte nur | zusätzlich Bootstrap: Verlust-Wahrscheinlichkeit und 5-%-Quantil des Gewinns (Information) | – |
| A12 Regime nach Schließzeit | Auswertung nach Einstiegszeit | – |
| Jeder Trade | trägt jetzt `r` (Ergebnis in R) und `slippage`; Ergebnisse tragen `r_n`, `r_sum`, `r_sq`, `avg_r` | – |

Nicht geändert: A4 (echte Neu-Optimierung je Fenster), A6 (Suchraum), A13 (Fenster 260
entspricht dem Live-Puffer von 220, also kein Fehler), A14, Funding-Kosten im Backtest.

### Nachweis (Original-Pipeline auf Kursen ohne jeden Vorteil)

| Test | Vorher | Nachher |
|---|---|---|
| Endlos-Suche, 8 Läufe | 37 Champions aus 135 geprüften Kandidaten | 0 Champions aus 240 |
| Kombi-Suche, Rang 1 „bestanden" | 13 von 13 Läufen | 0 von 10 Läufen |
| Gegenprobe: Kurse mit eingebautem starkem Trend-Vorteil, 3 Läufe | – | jeweils 5 Champions in 14–19 s |

Die Gegenprobe zeigt, dass ein deutlicher Vorteil weiter gefunden wird. Kleine Vorteile
(unter etwa +0,2 R je Trade) werden bei wenigen Test-Trades nicht mehr als belegt
gewertet; das Ergebnis nennt dann, wie viele Trades nötig wären.

Offene Lücke: Der Versuchszähler gilt je Lauf. Wer dieselbe Suche oft neu startet,
umgeht die Korrektur teilweise; die Tresor-Daten begrenzen das, verhindern es aber nicht.

## 4. KI-Trader (Analyse 6.1 und 6.3)

| Befund | Änderung |
|---|---|
| C2 Live nach 5 Trades | Signal-Broker: 30 Trades **und** vorsichtige Untergrenze (Ø − 1,64 · Standardfehler) > 0. Neuer Schlüssel `signal_live_z` (0 = altes Tor) |
| C3 Live-Freigabe-Check | zusätzlich t-Wert ≥ 2; die Anzeige nennt die nötige Trade-Zahl |
| C6 Hebel-Regel im Lern-Prompt | Regel bleibt (sie ist eure einstellbare MasterPrompt-Regel). Ergänzt: hoher Hebel ist die Folge eines engen Stops; die Beobachtung soll als Lektion zu Stop-Abstand bzw. Gebühr-zu-Risiko formuliert werden |
| C10 Schutzfilter fail-open | Edge-Filter: bei eigenem Fehler wird ein **Live**-Einstieg blockiert und im Entry-Protokoll vermerkt; Paper läuft weiter |
| C11 Risiko 2 % | Standard 1 % |
| Migration | `evidence_gates_v1` stellt gespeicherte Werte nur um, wenn dort noch exakt der alte Standard steht (5 → 30 Trades, 2,0 → 1,0 % Risiko). Selbst gesetzte Werte bleiben; läuft einmal |
| 6.3 Setups | Nur `hedge` stillgelegt: kein eigenes Signal, rechnerisch eine Verkleinerung der Position mit doppelten Gebühren. Alt-Trades bleiben lesbar. Alle anderen Setups unverändert |

Nicht umgesetzt (hängt an den nicht freigegebenen Punkten 9.3 und 10–12): C4 (92 Zellen),
C5 (Lektionen als Prosa-Schleife), C7 (wechselnde Modelle), C8 (LLM setzt Zahlen),
C9 (Wächterkette in einer Funktion).

## 5. Local Worker und Daten (Analyse 7 und 8)

| Punkt | Änderung |
|---|---|
| D3 Herkunft | Jedes Suchergebnis trägt `data_sources` und Warnungen: Kerzen von Binance Spot statt Bitunix-Perp, Ersatz-Volumen, skalierte Fremd-Historie. Die Suche baut für Symbole ohne echtes Volumen keine Volumen-Regeln mehr |
| D3 Forex-Volumen | Die Dukascopy-Historie brachte eigenes Volumen mit, Live und die letzten 30 Tage nur den Ersatzwert. Jetzt eine Definition in der ganzen Reihe (greift nach erneutem Laden des Symbols) |
| D4 Tage | Gibt es weniger Historie als angefordert, wird mit der vorhandenen Spanne gerechnet; das Ergebnis nennt `days_requested` und `days_loaded` je Symbol |
| D5 GPU | entfernt (Backend, Worker, Oberfläche) |
| D6 Version | Kopfzeile bereinigt, Worker ist jetzt 1.28.0 |

Nicht geändert: Die Krypto-Backtests laufen weiter auf Binance-Spot-Kerzen. Ein Wechsel
auf Perp-Kerzen braucht einen Test gegen die echten Datenquellen.

Korrektur zur Analyse: Für Forex gibt es über Dukascopy bereits bis zu 3 Jahre
1-Minuten-Historie; die 30 Tage gelten nur für Yahoo. Die Aussage „keine belastbare
Optimierung möglich" war damit zu hart. Das Gebührenmodell ist über
`forex_commission_pct` und `forex_min_commission_usd` schon einstellbar; für einen
Broker mit reinem Spread beide auf 0 setzen und den halben Spread als
`slippage_percent` mitgeben (Parameter im Backtest-/Optimizer-Aufruf; ein Feld in der
Oberfläche gibt es dafür noch nicht).

## 6. Prüfwerkzeug (Analyse Punkt 13)

`backend/scripts/systemcheck.py`, siehe README. `stats` liefert die Zahlen, die in der
Analyse nur aus euren Dokumenten stammen (Ø R, Streuung, t-Wert je Herkunft und Setup).

## 6a. Selbsttest

`services/selftest.py`: 11 feste Rechenprüfungen (bekannter Trade, Kosten, Stop-Loss,
Zufall gilt nicht als Vorteil, Verlust fällt durch, Live-Tore, Setups, Strategien,
Instrumente, Risiko) und 4 Laufzeitprüfungen (Datenbank, KI-Konfiguration, Handelsmodus,
Hauptschleife). Nur lesend, löst keinen Handel aus.

- läuft einmal 20 Sekunden nach jedem Start; Ergebnis im Log, bei Fehlern per Telegram
- `GET /api/selftest` (Admin-Login) liefert das Ergebnis als JSON
- offline: `python -m scripts.systemcheck selftest`

## 7. Geprüft und nicht geprüft

- Offline-Tests: 2.641 bestanden. Kein Test, der vorher lief, schlägt jetzt fehl. Acht
  bestehende Testdateien wurden an die neuen Regeln angepasst (Slippage, Live-Tor,
  Risiko-Standard, stillgelegtes Setup, GPU); 4 neue Testdateien decken die Änderungen ab.
- 87 Tests liefen hier weder vorher noch nachher: `fastapi`, `motor` und `openai` fehlen
  in der Prüfumgebung, einige erwarten einen laufenden Server. Für `aiohttp` wurde ein
  Platzhalter benutzt.
- Frontend: Syntax aller 196 Dateien und alle Importe geprüft. Ein echter Build
  (`yarn build`) war mangels installierter Pakete nicht möglich.
- Server-Start, Datenbank-Migration, Worker-Verbindung und Datenquellen wurden nicht
  gegen echte Systeme getestet.

---

# Stufe 1 (Freigabe nach der Trade-Analyse, 15.11.2026 abends)

Grundlage: `docs/ANALYSE_TRADES_KI_2026-11-15.md` (1.369 Trades, nur lesend ausgewertet).

## 1. Hebel und Liquidation

- **Hebel-Deckel für alle Hebel-Pfade:** Auto, KI-Wahl und fester Hebel. Die Liquidation muss mindestens doppelt so weit entfernt liegen wie der Stop.
  - Einstellung: `liq_sl_min_ratio` (Standard 2, 0 = aus).
  - Im Risiko-Modus bleibt das Risiko gleich, nur die gebundene Marge steigt.
  - Code: `backtester.liq_safe_max_leverage`, angewendet in `bitunix_trade`.
- **Paper-Abrechnung bei Preissprüngen:** Springt der Preis zwischen zwei Ticks über den Stop *und* die Liquidation, rechnet Paper jetzt den Stop ab (mit Spread und Slippage), nicht die Liquidation.
  - Grund: Ein Stop liegt als Order an der Börse und wird auf dem Weg zuerst gekreuzt. Die 19 Paper-Liquidationen (−2,2 R) entstanden so. Bei mehreren lag die Liquidation schon doppelt so weit wie der Stop, der Deckel allein hätte sie nicht verhindert.
  - Live bleibt unverändert, dort gilt die Börse.

## 2. Gebühren

- **Fee-Wächter:** Standard 10× statt 2,5×, das heißt Gebühr ≤ 10 % des Risikos.
  - Bei Krypto-Taker braucht der Stop damit etwa 1,2 % Abstand.
  - Ein Boot-Migration hebt gespeicherte Werte unter 10 einmalig an (Produktion stand auf 3,5). Strengere Werte bleiben.
  - Die Autotune-Basis wird mitgesetzt, sonst hätte Autotune den Wert zurückgeholt; ihre Obergrenze ist jetzt 12.
- **Sammel-Trades** werden weiterhin auf das Minimum *erweitert* statt verworfen. Die Datensammlung läuft also weiter, nur mit Stops, die nicht von den Gebühren aufgefressen werden.
- Empfohlene Einstellung „Fee-Faktor“ auf 10 angepasst.

## 3. Gegentrend-Schutz für Sammel-Trades

- Sammel-Trades gegen einen klaren Tages-Bias (LONG bei „down“, SHORT bei „up“) werden nicht mehr eröffnet. Bei „flat“ oder ohne Bias läuft die Sammlung weiter.
- Abschaltbar im Edge-Filter-Bereich: „Sammel-Trades nicht gegen Tagestrend“, Schlüssel `edge_filter_collection_counter_trend`.

## 4. Hoffnungslose KI-Setups

- Neu: KI-eigene Setups werden automatisch ausgemustert, wenn sie statistisch klar verlieren:
  - mindestens 15 Trades, t ≤ −3 und Ø ≤ −0,3 R
  - Prüfung stündlich im Playbook-Refresh
- Die Bibliothek der festen Setups ist davon ausgenommen.
- Das trifft beim nächsten Refresh `ny_close_reversal` (20 Trades, Winrate 5 %, −1,2 R). Die KI bekommt im Feed den Hinweis, die Idee nicht unter neuem Namen zu wiederholen.

## 5. Lektionen

- **Qualitätsprüfung im Lernlauf (`services/lesson_quality.py`).** Abgelehnt werden:
  - Änderungs-Anweisungen statt vollständiger Lektion („Ersetze …“): Das war der Grund für die kaputten Texte.
  - Zeitebenen, die die KI nicht bekommt (10m, 30m, 4h; verfügbar sind 1m, 5m, 15m, 1h und der Tagestrend).
  - Lektionen, die regelbasierte Sammel-Trades sperren oder schließen würden.
- **Duplikate:** Eine nahezu gleiche Lektion unter neuem Titel wird automatisch als Schärfung der bestehenden übernommen.
- **Selbst-Management:** Der Lern-Prompt hat einen Hygiene-Block bekommen.
  - Keine feste Zielzahl, nur Lektionen mit Nutzen.
  - Beim Schärfen immer den kompletten Text liefern.
  - Widersprüche und überholte Lektionen selbst melden.
  - Belege angeben; unter 30 Trades nur ein Kandidat.
  - `max_lessons` bleibt als reine Sicherheitsgrenze.
- **Lern-Prompt angepasst:** Der Hebel wird technisch gedeckelt. Das 4h-Beispiel ist entfernt.
- **Einmalige Bereinigung des Bestands (`services/lesson_cleanup.py`): 33 → 7 Lektionen.**
  - Entfernt (17):
    - Margen-Regime-Regeln
    - Sperren der Datensammlung
    - die Range-Fade-Lektion, die den Daten widerspricht
    - die CRV- und Cooldown-Änderungsanweisungen
    - die Hedge-Lektion (Setup ist stillgelegt)
    - nicht messbare Regeln
  - Zusammengeführt (14 → 5, jeweils mit Belegen aus den Trades):
    - Mit dem Tagestrend handeln
    - Einstieg erst nach bestätigender Kerze
    - Nach Stop-Out und Verlustserie pausieren
    - Stop an die Struktur und weit genug für die Kosten
    - Rohstoffe nur mit Trend und weitem Stop
  - Unverändert: Break-Even-Nachzug, News-Defensive.
  - Unbekannte (neuere) und vom Trader gesperrte Lektionen bleiben unangetastet.
  - Der alte Stand liegt in der Lektionen-Historie und ist wiederherstellbar.
  - Die neuen Lektionen gelten 45 Tage. Danach muss der Lernlauf sie bestätigen, sonst werden sie zurückgestellt.

## 6. Event-Setups (FOMC, CPI, NFP, PPI, PCE)

- **Kalender 2027 ergänzt.** Quellen:
  - CPI, NFP, PPI, PCE: OMB-Terminplan „Principal Federal Economic Indicators 2027“
  - FOMC: Fed-Kalender
- **Neuer Self-Test-Check:** „Kalender reicht noch mindestens 60 Tage“.
- **Ehrlichere Event-Backtests:**
  - Slippage 0,05 % je Seite (Market-Order in den News-Spike).
  - Validierung zusätzlich **auf Event-Ebene:** mindestens 12 Events, t ≥ 2 je Event, Out-of-Sample-Events im Schnitt positiv. Grund: BTC, ETH und SOL zum selben Termin sind keine unabhängigen Trades.
  - KI-angepasste Parameter zählen nicht mehr als Validierung, weil sie auf denselben Events gewählt wurden. Die KI-Schleife bleibt als Erkundung; gültig ist immer der Lauf mit den festen Regeln.
- **Einmalige Neubewertung der gespeicherten Ergebnisse,** ohne neue Daten herunterzuladen. Ergebnis mit den Produktionszahlen:

  | Event | Events | Ø je Event (nach Slippage) | t |
  |---|---|---|---|
  | CPI | 23 | +1,44 USDT | 1,27 |
  | PPI | 18 | +1,41 | 0,97 |
  | PCE | 23 | +0,95 | 0,61 |
  | FOMC | 9 | +1,34 | 0,59 |
  | NFP | 22 | −0,90 | −0,59 |

  Gepoolt CPI, PPI und PCE (gleiche feste Regeln): 64 Events, t = 1,58. Vor Slippage wären es t = 2,57 gewesen, bei CPI allein 2,04.

  → Keines ist nach Kosten belegt, die Live-Bonus-Freischaltung entfällt. Die Setups bleiben als Paper-Sammlung aktiv. CPI ist der aussichtsreichste Kandidat. Der Vorteil hängt an der Ausführung (siehe Bericht).

## 7. Self-Test

- Neu: `event_calendar` und `leverage_cap`. Jetzt 13 Logik-Checks.

## 8. Geprüft

- Neue Tests: `tests/test_stufe1_1511.py` (15 Tests).
  - Echte Produktionstitel der Lektionen als Fixture.
  - Migrationen gegen eine Test-DB.
- Ganze Testsuite: 2.656 bestanden, keine neue Fehlschlag-Stelle gegenüber dem letzten Stand. Zwei Tests wurden auf den neuen Empfehlungswert 10 angepasst.
- Frontend-Syntax und Importe geprüft (196 Dateien).

---

# Stufe 2 und 3 (15.11.2026, spätabends)

## 1. KI-Trader-Lab (Setup-Backtests): ehrliche Validierung

- **Auswahl nach Trainingsdaten:** Feintuning und Optimierer wählen den besten Satz jetzt nach dem In-Sample-Ergebnis. Out-of-Sample bleibt der unabhängige Test; vorher wurde danach ausgewählt.
- **Signifikanz mit Versuchszahl:**
  - Ein bestandener Satz braucht zusätzlich einen statistisch belegten OOS-Vorteil: mindestens 30 OOS-Trades, t-Wert in R über der Hürde.
  - Die Hürde steigt mit der Zahl **aller** je Setup × Klasse geprüften Sätze (`oos_trials`, Bonferroni wie in der Endlossuche). Gezählt werden Varianten, Feintuning, Optimierer und KI-Revisionen.
- **Altbestand ohne diese Prüfung:**
  - zählt nicht mehr fürs Reife-Gate (gespeicherte Lab-Trades nur noch mit `lab_evidence`)
  - gibt keine Live-Freigabe mehr (`setup_lab_live.lab_validated`)
  - Der nächste Lab-Lauf prüft neu.
- **Neue Ansicht im Lab: „Lab gegen echte Paper-Trades“.** Je Setup: Ø R im Lab-Test gegenüber Ø R der echten Paper- und Sammel-Trades (90 Tage), mit Urteil („widerspricht dem Lab“, „stützt das Lab“ …).

## 2. Live-Freigabe von Setups (Playbook)

- **Vorher:** 5 Trades und ein geschrumpfter Ø ≥ +0,05 R reichten. **Jetzt:** 30 Trades, und sobald je Trade R-Daten vorliegen, zusätzlich eine Untergrenze (Ø − 1,64 · Standardfehler) > 0.
- Die Statistik je Setup trägt dafür `r_n`, `r_sum` und `r_sq`.
- Der Backtest-Anteil am Reife-Gate bleibt auf 3 gewichtete Trades gedeckelt.

## 3. Lernen aus nicht gehandelten Chancen: Veto-Bilanz

- Jedes Detektor-Signal hat einen Regel-Paper-Trade. Daraus berechnet `services/veto_balance.py` je Setup:
  - was die von der KI **verworfenen** Signale ohne KI gebracht hätten: Veto-Wert, verpasste Gewinne, vermiedene Verluste
  - das Ergebnis der genommenen Signale
  - den Timing-Wert: KI-Trade minus Regel-Trade desselben Signals
- Sichtbar in der Signal-Broker-Karte; fließt in den Lernlauf ein (Block „VETO-BILANZ“). Der KI-Trader lernt damit auch dann, wenn er nicht handelt.
- Hintergrund: Die Detektoren lieferten in 60 Tagen rund 6.000 Signale, die KI nahm etwa 1 %.

## 4. Markt-Benchmark je Setup

- `services/market_benchmark.py` vergleicht jeden Trade mit allen anderen KI-Trades gleicher Richtung und Klasse am selben Tag (±1). Der Mehrwert zeigt, ob ein Setup mehr kann als „einfach in diese Richtung handeln“. Anzeige in der Signal-Broker-Karte.
- **Korrektur meiner Analyse:** crypto_security_breach liegt +0,47 R über den anderen SHORTs derselben Tage. Es ist also nicht nur Markt-Beta, aber mit 11 Tagen noch nicht belegt.

## 5. ML-Labor

- **Echter Hold-out:** Die jüngsten 20 % der Daten (ab 100 Datensätzen) bleiben beim Training unberührt. Die Hold-out-AUC wird mit dem fertigen Modell gemessen. Die bisherige CV-AUC war die beste aus vielen Optuna-Versuchen und damit zu optimistisch.
- **Prompt-Sperre:** In die Handels- und Lern-Prompts kommt das ML-Labor nur noch mit mindestens 150 Datensätzen **und** Hold-out-AUC ≥ 0,55. Die „ML-Erkenntnis“ für den Forschungs-Analysten wird nur dann gespeichert. Training und Anzeige bleiben unverändert.

## 6. Prüfer-Modus als Standard

- **Standardrolle der KI ist jetzt „Prüfer“.**
  - Detektoren liefern die Trades mit berechnetem SL/TP.
  - Die KI prüft (Veto/Timing) und macht keine freien Trades ohne Detektor-Signal mehr.
  - Der periodische Voll-Analyse-Zyklus entfällt; das spart LLM-Aufrufe.
- **Einmalige Umstellung** gespeicherter „frei“-Einstellungen (`ai_role_pruefer_v1`). „Frei“ bleibt im KI-Setup wählbar; danach gilt eure Wahl.
- Grund: KI-frei-Trades lagen bei −0,35 R (84 Trades). Ob die Prüfung selbst Wert hat, zeigt ab jetzt die Veto-Bilanz.

## 7. Endlossuche

- **Indikatoren:** Die immer-wahren Regeln „BB-Breite > 0,3/0,8 %“ und „ATR > 0,05/0,15 %“ sind ersetzt durch relative Volatilität („ATR 14 > ATR 100“ bzw. „<“). Sie feuern auf 5m/15m/1h in 35–65 % der Kerzen. Kein Indikator schaut in die Zukunft (Prüfung aller 62 Regeln).
- **Hürde ab der ersten Prüfung:**
  - Die Signifikanz-Hürde gilt jetzt von Anfang an für mindestens 100 Versuche. Vorher war sie für die ersten Kandidaten niedrig; im Zufalls-Benchmark gab es dadurch 1 Fehlalarm in 3 Läufen.
  - Jetzt: 0 aus 158 geprüften Kandidaten auf reinem Zufall.
  - Gegenprobe mit eingebautem Trend-Vorteil: weiterhin je Lauf 5 Champions in 5–11 s.
- **Standardwerte im Optimizer** (wenn nichts gespeichert ist):

  | Einstellung | vorher | jetzt |
  |---|---|---|
  | Zeitraum | 3 Tage | 180 Tage |
  | Timeframe | 1m | 15m |
  | Mindest-Trades | 10 | 30 |
  | Regeln je Kombi | 4 | 3 |

  Gespeicherte Einstellungen bleiben.
- **Neu in der Endlossuche:**
  - Knopf „Empfohlene Einstellungen“: 15m, 180 Tage, 3 Regeln, 30 Trades, 70 % Training.
  - Hinweis, wie viele Test-Trades ein Nachweis braucht.
  - Warnungen im Ergebnis bei mehr als 3 Regeln, unter 5 Assets oder bei 1m/3m.

## 8. Geprüft

- Neue Tests: `tests/test_stufe2_3_1511.py` (13 Tests, 1 übersprungen, weil xgboost/optuna hier fehlen).
- **An die neuen Regeln angepasst:**
  - Lebenszyklus-Tests: 30 Trades, neuer Test zur Untergrenze.
  - Optimierer-Vergleich: jetzt In-Sample.
  - Lab-Live-Fixture: mit Nachweis.
  - Rollen-Standard.
  - Drei Ablauf-Tests (Rückstufung, Wieder-Freischaltung, Feed) setzen die alte Schwelle 5 per Fixture, weil sie den Ablauf prüfen, nicht die Schwelle.
- **Ganze Suite:** 2.668 bestanden, keine neue Fehlstelle gegenüber dem Stand vor Stufe 1.
- **Weitere Prüfungen:**
  - Self-Test: 13/13 grün.
  - Frontend-Syntax und Importe: 196 Dateien ok.
  - Zufalls- und Gegenprobe der Endlossuche wie oben.

---

# Nach dem Deploy (15.11.2026, 23 Uhr): Prüfung und zwei Fehler

**Geprüft und in Ordnung:**
- Self-Test 17/17 grün.
- KI-Rolle steht auf „Prüfer“.
- Fee-Faktor steht auf 10.
- 8 Lektionen: die 7 bereinigten plus eine am Abend vom Lernlauf reaktivierte.

**Fehler 1: Endlossuche fand nie etwas.**
- Befund: In allen Läufen wurde **keine einzige** Kombination verfeinert oder im Walk-Forward geprüft, auch nicht bei 250.000 getesteten Kombinationen.
- Ursache: Der Drawdown-Filter (DD ≤ 30 % des PnL) griff schon beim ersten Test jeder Kombination. Damit fiel jede Kombi mit PnL ≤ 0 oder etwas Drawdown raus, und die eingebaute „Rettung“ der besten Beinahe-Kombi war ebenfalls blockiert.
- Behoben: Der Filter gilt jetzt nur noch auf den Testdaten.

**Fehler 2: Der lokale Worker rechnete mit altem Code.**
- Der Worker lief noch mit Paket 1.27.0, also mit der alten Validierung. Die Suchen liefen dort.
- Neu: Optimierungen verlangen Worker **1.29.0**. Bitte das Worker-Paket neu herunterladen und den Worker neu starten.

**Außerdem:** Der Knopf „Empfohlene Einstellungen“ wählt jetzt auch alle Indikatoren aus. Einige Läufe hatten nur 4 Indikatoren (Suchraum 84 Kombinationen, nach 17 s erschöpft).

---

# Leitstand und Autonomie (Phasen A–D, 16.11.2026)

Grundlage: `PLAN_AUTONOMIE_LEITSTAND_2026-11-15.md`, Freigabe „alles A–D umsetzen“.
Entscheidungen des Traders: TrendFolge2 bleibt an. Den Rest habe ich so entschieden:
Champions automatisch in den Vorwärtstest, nie automatisch live; Tagesbericht ohne KI-Kosten;
Live-Bypass aus. Grundsatz: **nichts löschen, sondern verbessern oder trennen.**
Die Ordnerstruktur bleibt unverändert.

## A. Saubere Ausgangslage

**Bewertungs-Stichtag** (`services/evaluation_cutoff.py`):
- Vorgabe ist der Zeitpunkt, an dem die Kostenregeln in Kraft traten (Boot-Marker der Migration vom 15.11.).
- Ab dann zählen: Lernlauf, Lektions-Bilanz, Veto-Bilanz, Markt-Benchmark, Konfidenz-Kalibrierung, Quellen-Freigabe, Live-Reife, Playbook-Tore und Setup-Profile.
- Trades bleiben gespeichert. Der Stichtag ist im Leitstand änderbar oder abschaltbar.
- Bereits live geschaltete Setups werden dadurch nicht zurückgestuft: Rückstufen geht erst nach 8 neuen Live-Trades.

**Endlossuche-Bestenliste:**
- Die alte Top-5 aus August (Test gleich Training) wird **nicht gelöscht**, sondern als „Altbestand“ getrennt.
- Vorher hätte ihr aufgeblähter Wert jeden ehrlichen neuen Champion aus der Liste gehalten. Jetzt konkurrieren nur noch Champions mit Signifikanz-Prüfung.
- Champions speichern zusätzlich Assets und Zeitebene; das braucht der Vorwärtstest.

**Lektions-Kandidaten** werden nachgeprüft statt gelöscht:
- Qualitätsprobleme und Doppelungen aktiver Lektionen gehen ins Archiv (`ai_lesson_candidates_archive`, wiederherstellbar).
- Kandidaten aus der Zeit vor dem Stichtag brauchen eine frische Bestätigung mit neuen Trades.

**KI-Gedächtnis bleibt unverändert.** In die Prompts gehen ohnehin nur die 3 neuesten Einträge je Art, ein Archiv hätte nichts verbessert.

**Live-Diagnose:**
- Bewertet jetzt nur Trades seit dem Stichtag.
- Empfiehlt Fee-Faktor 10 statt des veralteten „≥ 6“.
- Rät nicht mehr dazu, den Bypass zu erhöhen.

**Live-Bypass bei hoher Konfidenz:** einmalig aus (Konfidenz nachweislich ohne Aussage). Der Schalter bleibt im KI-Panel.

**Setup-Profile:** Profile aus der Zeit vor der Kostenregel, deren SL unter dem Fee-Minimum liegt, werden im Prompt markiert. So widersprechen sie dem Fee-Wächter nicht mehr.

**Fee-Wächter-Prompt:** Ist der 1m-Struktur-SL zu eng, prüft die KI zuerst die 5m/15m-Struktur, statt sofort HOLD zu geben.

## Handelsfluss: kann die KI noch genug handeln?

**Geprüft an den Live-Daten (nur gelesen):**
- Seit dem Deploy blockte der Fee-Wächter genau 1 Sammel-Signal (SUI, SL 0,42 %).
- Größte Bremse der letzten 7 Tage war der Richtungs-Wächter (maximal 5 gleichgerichtete Positionen, 195×).

**Verbesserung:** Sammel-Trades (Paper) dürfen ihren SL jetzt bis zum **3-fachen** auf das Fee-Minimum erweitern, vorher bis zum 2,5-fachen. Damit kommen auch Signale mit dem Mindest-SL von 0,42 % durch, vorher fielen etwa 17 % der Lern-Signale weg. Live bleibt unverändert hart.

**Geschätzter Fluss** nach allen Regeln (Fee-Wächter, Gegentrend-Schutz, Richtungs-Wächter): etwa die Hälfte der bisherigen ~78 KI-Trades pro Tag, dazu Schattentrades.

**Neue Warnung:** Der Systemarzt meldet, wenn 12 Stunden lang kein Trade entsteht, und nennt die häufigsten Gründe.

## B. Leitstand und Systemarzt

**Kopfzeile:** Knopf mit Herzschlag-Symbol. Die Zahl zeigt offene Mängel, rot bei „kritisch“.

**Fenster `CockpitPanel`** mit Überblick und fünf Bereichen:

| Bereich | Inhalt |
|---|---|
| Jetzt | was der KI-Trader tut, offene Trades mit Grund, Signal-Fenster, letzte Entscheidungen in einem Satz, Handel der letzten 24 h, gesparte KI-Prüfungen |
| Mängel | Befunde des Systemarztes mit „Was tun“ |
| Empfehlungen | nächste Schritte mit Knopf, wo gefahrlos; ausblendbar für 14 Tage |
| Fortschritt | belegte Vorteile, Vorher/Nachher seit Stichtag, Kandidaten, Setups bis zum Live-Tor, Live-Strategien, Tagesberichte |
| Neu | Zeitleiste der letzten 7 Tage |

**Systemarzt** (`services/system_doctor.py`, alle 15 min, 0 KI-Kosten). Er prüft:
- Self-Test (stündlich)
- Sicherheits-Ampel
- Worker-Version und Verbindung
- Kurs-Frische nach Handelszeiten
- KI-Schleife
- Handelsfluss
- fehlgeschlagene Jobs
- KI-Anbieter: Drosselung, Guthaben, Anteil kostenloser Modelle
- Website-Fehler
- riskante Einstellungen

Eine kaputte Prüfung wird selbst zum Hinweis, der Arzt läuft weiter.

**Website-Fehler** (`POST /api/client-errors`, `frontend/src/lib/clientErrors.js`):
- **Gemeldet werden:** JS-Abstürze, React-Fehlergrenzen sowie Server-Anfragen mit 5xx oder ohne Verbindung.
- **Schutz:**
  - nur mit Admin-Login
  - ohne URL-Parameter, Tokens werden entfernt
  - gedrosselt, dedupliziert
  - 7 Tage gespeichert

**Gefahrlose Aktionen** (feste Liste, nie Handel):
- Systemarzt prüfen
- Self-Test
- Nacht-Suche einplanen
- Lab wöchentlich einschalten
- Kandidat übernehmen (Paper), verwerfen oder neu testen
- Empfehlung ausblenden
- Tagesbericht erstellen
- Live-Wächter-Freigabe

## C. Forschungs-Motor

**Nacht-Forschung** (`services/night_research.py`):
- Jede Nacht zwischen 23 und 5 Uhr eine Endlossuche mit den empfohlenen Einstellungen.
- Rotation: Krypto 15m → Krypto 1h → Forex 1h → Krypto 5m → Rohstoffe + Indizes 1h.
- Läuft über die Nacht-Serie, nur mit verbundenem Worker ab Version 1.29.
- Im Leitstand abschaltbar.

**Lab-Automatik:** wieder an, wöchentlich mit ehrlicher Prüfung und 2 KI-Revisionsrunden. Erster Lauf um 2 Uhr nachts statt direkt nach dem Deploy.

**Kandidaten-Pipeline** (`services/research_pipeline.py`):
1. **Vorwärtstest:** Jeder Champion mit bestandener Signifikanz läuft automatisch auf Kursdaten, die es beim Fund noch nicht gab (alle 3 Tage nachgerechnet).
2. **Urteil:** Bestanden ab 30 Trades mit Untergrenze > 0.
3. **Übernehmen:** legt die Strategie im **Paper**-Modus an, Live schaltet nur der Trader.

Der Paper-Modus wird dabei ausdrücklich gesetzt, weil eine neue Strategie sonst den globalen Modus erben würde.

## D. Lernen schärfen

**KI-Prüfung nach Veto-Wert** (`services/review_allocation.py`):
- Wo die KI-Auswahl nachweislich nicht besser ist als ihre Absagen, wird nur jedes 3. Signal per KI geprüft.
- Beispiel Produktion: genommen −0,38 R, verworfen −0,30 R.
- Die übrigen Signale laufen weiter als Regel-Paper. Die Datensammlung bleibt also gleich, die KI-Aufrufe sinken.
- Schalter: `signal_review_by_value`.

**Live-Wächter** (`services/live_watchdog.py`):
- Ab 50 Live-Trades mit Untergrenze < 0 erscheint eine Empfehlung, zum Beispiel für TrendFolge2. Sie ist ausblendbar.
- Automatisch auf Paper umgestellt wird nur mit Freigabe im Leitstand (Standard: aus), nie ausgeschaltet.

**Tagesbericht** (`services/daily_report.py`):
- Täglich ab 8 Uhr, ohne KI, mit den Zahlen des Vortags.
- Wird für die Verlaufstabelle gespeichert.
- Telegram-Schalter „Leitstand-Tagesbericht“ ist standardmäßig aus.

## Geprüft

- **Neue Tests:** `tests/test_phase_a_1511.py` (16) und `tests/test_phase_bcd_1511.py` (33), beide grün.
- **Ganze Suite:** 2.718 bestanden. Keine neue Fehlstelle gegenüber dem letzten Stand. Die bekannten Fehlstellen kommen daher, dass hier fastapi, Mongo und Netz fehlen.
- **Self-Test:** 16/16 grün. Neu sind die Prüfungen Stichtag, Vorwärtstest-Urteil und Prüf-Zuteilung.
- **Frontend:**
  - Syntax und Importe: 199 Dateien ok.
  - Alle Leitstand-Bereiche mit echten Backend-Ausgaben gerendert, ohne Fehler.
  - Fehlermelder in Node getestet.

---

# Kritischer Fix 16.11.2026 (abends): Endlossuche testete auf Trainingsdaten

**Befund:** Alle 5 Champions des Laufs vom 16.11. hatten identische Trainings-, Test- und Tresor-Werte.

**Ursache:** Der Multi-Core-Pool des lokalen Workers (`parallel_sim`) bekommt die Kerzen einmal beim Start, also die Trainingsdaten. Spätere Aufträge nennen nur Symbol-Namen. Test und Tresor der Endlossuche liefen deshalb auf dem Training. Die Signifikanz-Prüfung war damit wirkungslos. Derselbe Fehler steckt hinter der „Test = Training“-Liste vom August.

**Fix:**
- `parallel_sim.pool_has_data()`: Der Pool rechnet nur seine Startdaten. `optimizer._evaluate_batch` rechnet andere Daten sequenziell.
- Champions tragen `evidence.engine = 2`. Ältere stehen automatisch im Altbestand.
- Migration `explore_pool_fix_v1` verwirft Kandidaten aus alten Läufen (erneut testbar).
- Worker-Paket **1.30.0**, Optimierungen verlangen 1.30.0.
- Self-Test-Prüfung „Endlossuche testet auf eigenen Testdaten“ (17/17 grün).

**Nachweis:**
- Nachgestellt mit 2 Kernen: vorher 3 Zufalls-„Champions“ mit Training = Test = Tresor, nachher getrennte Werte.
- Härtetest nach dem Fix: 0 Fehl-Champions in 5 Läufen (435 geprüfte Kandidaten).
- Ein eingebauter echter Vorteil wird in 40 s gefunden.
- Neue Tests: `tests/test_explore_pool_fix_1611.py`.
- Ganze Suite: keine neue Fehlstelle.

## Umsetzung 17.11.2026 (F1–F3)

Details, Messwerte und offene Entscheidungen: `docs/UMSETZUNG_ZIEL_2026-11-17.md`.

- **Strengere Champion-Prüfung** (`services/champion_checks.py`, Prüf-Stand 3): Training auch in R im Plus, Tresor mit Ø R und mindestens 10 Trades, Versuchs-Konto über Läufe, Rückwärtstest auf bis zu 365 älteren Tagen, Long/Short getrennt.
- **Neues Ziel „t-Wert (R)“** (`optimizer._score`), Warnhinweis bei USDT-Zielen in der Endlossuche, Knopf „Empfohlene Einstellungen“ angepasst.
- **Nacht-Forschung:** neuer erster Slot „Krypto 1h Trend“, Ziel t-Wert, mindestens 60 Trades.
- **Trendfolge-Vorgaben** als Kandidaten im Vorwärtstest (`research_pipeline.PRESETS`); 4h-Variante per Klick als Paper-Strategie startbar.
- **Fehler behoben:** „Übernehmen (Paper)“ setzte den Paper-Modus nicht und ließ alle Assets zu.
- **Lern-Trades:** Richtungs-Limit 5 → 10 je Klasse (Boot-Migration, eigener Wert bleibt).
- **Worker 1.31.0** ist Pflicht für Optimierungen.
- Self-Test: 18 Logik-Prüfungen.

## Portfolio, Modelle, Klima (17.11.2026, zweites Paket)

Details: `docs/PORTFOLIO_2026-11-17.md` und `docs/MODELLE_REGIME_FUNDING_2026-11-17.md`.

- **Neu: Portfolio auf Tagesebene** (Trendfolge + Funding-Korb) mit eigenem Datenweg, Paper-Buchführung, Tagesplan und Reiter im Leitstand (`portfolio_core.py`, `portfolio_engine.py`, `PortfolioSection.js`).
- **Aufgaben-Team v2:** Modelle je Rolle neu gesetzt; Prüfer fällt nicht mehr auf ein Gratis-Modell zurück; `gpt-oss-20b` (JSON-Fehler) ersetzt.
- **Markt-Klima** als Anzeige und Messung der eigenen Trades (`market_climate.py`), bewusst kein Filter.
- **Funding-Fade:** Bilanz der beiden Seiten steht jetzt im Prompt.
- **Live-Wächter** stellt nachweislich verlierende Live-Strategien selbst auf Paper (Boot-Migration, abschaltbar).
- **Trend-Basis 4h** nicht mehr per Klick im Minuten-Scanner startbar (Speicher-Risiko).
- Systemarzt prüft das Portfolio; Self-Test: 19 Logik-Prüfungen.

## Live-Ausführung und 64 Coins (17.11.2026, drittes Paket)

Details: `docs/LIVE_UND_AUSBAU_2026-11-17.md`.

- **Neu: Portfolio live** (`services/portfolio_live.py`, `PortfolioLive.js`): Paper-Plan als kleine echte Orders auf Bitunix; Probelauf als Standard, Live nur nach Eingabe von „LIVE“; Stop sofort an der Börse mit Nachlesen; Hebel mit Liquidation jenseits des Stops; Not-Aus; stündliche Stop-Prüfung; Not-Aus von Hand.
- Positions-Wächter überspringt Portfolio-Positionen; Autotrader eröffnet live nichts auf einer vom Portfolio gehaltenen Seite.
- **Portfolio: 64 Coins, 20 Positionen, Funding-Korb 8 je Seite** (Rückrechnung Sharpe 1,81 statt 1,47); Migration der alten Standardliste.
- Rechenkern: Positionen delisteter Coins werden geschlossen; erster Stop wird gespeichert.
- Zukunftsrechner im Reiter „Portfolio“; Systemarzt-Prüfung „Portfolio live“; Meldung „Portfolio live“.
- Self-Test: 20 Logik-Prüfungen.

## Kurzfrist-Forschung, Backtest-Coins, Funding-Wächter (17.11.2026, viertes Paket)

Details: `docs/FORSCHUNG_KURZFRIST_2026-11-17.md`.

- **Backtester und Optimizer/Endlossuche: 53 Zusatz-Coins** (Gruppe „WEITERE COINS (nur Backtest)“, Historie von Binance, „alle wählen“). Live-Scanner, Autotrader und die Übernahme-Auswahl bleiben bei den 25 Website-Instrumenten.
- Übernahme-Schutz: Kandidaten, die nur auf Zusatz-Coins geprüft wurden, werden nicht übernommen.
- **Cockpit-Empfehlung „Funding-Ernte möglich“** bei Funding im Schnitt über 0,15 % je Tag (3 Tage); nur ein Hinweis, kein automatischer Handel.
- Forschung: 8 Kurzfrist-Ideen geprüft, keine besteht Kosten und Holdout; die Funding-Ernte funktioniert, aber nur in Hype-Phasen.

## KI-Modelle, KI-Trader-Prüfer, Kosten (17.11.2026, fünftes Paket)

Details: `docs/KI_TRADER_MODELLE_2026-11-17.md`.

- **KI-Aufsicht faktenbasiert:** Aufrufe je Rolle laut Token-Abrechnung im Prompt, Plausibilitäts-Regeln (keine „inaktiv“-Urteile für arbeitende Rollen, nie Abschalten kritischer Rollen, kein „Wechsel“ auf das schon aktive Modell, vollständige Slugs), feste Modell-Kette DeepSeek V4.1 Flash → GPT-6 Luna Pro → Gemini.
- **Leere Antworten (DeepSeek):** zweiter Versuch ohne response_format und ohne Reasoning; Meldung unterscheidet Bezahl- und Gratis-Modell und nennt den Abbruchgrund.
- **KI-Trader-Prüfer entblockt:** Regel-Trade = Kontrollgruppe, kein Grund für HOLD (Prompt); HOLD „bereits offen“ zählt nicht als Veto; TF2-/Sweep-/News-Analysen im Prüfer-Modus nur mit offenem Detektor-Signal.
- **KI-Guthaben-Reichweite:** Verbrauch $/Tag je OpenRouter-Key, Banner im KI-Tab und Cockpit-Empfehlung unter 14 Tagen.
- **Meldungen:** Tages-Sperren überstehen Neustarts (DB-Dedupe, Website + Telegram).
- Forschung: Volatilitäts-Steuerung, Korb-Größe, Ausbruchslängen, Filter und Querschnitts-Momentum geprüft – nichts schlägt das Portfolio in allen Zeiträumen (Momentum im Holdout gescheitert).

## KI-Team-Anzeige, Nachtsuche, Optimizer-Vorgabe (17.11.2026, sechstes Paket)

Details: `docs/ZUSAMMENSPIEL_2026-11-17.md`.

- **KI-Team-Anzeige:** GPT-6 Luna Pro, Claude Haiku 5.5 und DeepSeek V4.1 Flash fehlten in der Frontend-Modellliste – die Rollen zeigten deshalb „Haupt-Modell (erben)“/„keine“, obwohl das Backend die richtigen Modelle nutzte. Liste ergänzt, vom Anbieter entfernte Modelle raus, das aktuell gewählte Modell wird immer angezeigt; Test hält Frontend- und Backend-Katalog synchron.
- **Prüfer-Modus sichtbar:** Kopfzeile „Prüfer: prüft Detektor-Signale“ statt „analysiert alle 10 min“; Analyse-Intervall als „(Prüfer: aus)“ beschriftet; Haupt-Modell als „nur Ersatz“ beschriftet.
- **Nachtsuche:** Rotation nur noch Krypto 1h Trend → Krypto 1h → Krypto 15m (Forex/Rohstoffe/Indizes können wegen „Live nur Krypto“ nie live gehen, 5m scheitert an Gebühren).
- **Optimizer „Empfohlene Einstellungen“:** 1h, 365 Tage statt 15m, 180 Tage.

## Gegentrend-Sperre für KI-Prüfungen, Offline-Prüfkit, Pflege-Protokoll (17.11.2026, siebtes Paket)

- **Prüfer:** keine KI-Prüfung mehr für klare Gegentrend-Signale (LONG bei Tages-Bias „down“, SHORT bei „up“), solange Edge-Filter, „Nur mit Tagestrend“ und „Sammel-Trades nicht gegen Tagestrend“ an sind – solche Signale können weder live gehen noch einen Kontroll-Trade bekommen. Seit dem letzten Deploy waren das fast alle geprüften Signale.
- **Offline-Prüfkit** `backend/tests/offline/`: Test-Suite ohne Netzwerk mit Baseline der Umgebungs-Fehler, Frontend-Syntaxcheck (für automatische Pflege-Läufe).
- **Pflege-Protokoll** `docs/BEOBACHTUNGEN.md`: Kennzahlen, Änderungen und offene Punkte je Lauf.

## TP1/TP-Full-Fehler, Gesamt-Statistik der Analyse (17.11.2026, achtes Paket)

- **TP1 = TP-Full behoben:** Das CRV-Minimum (1,5) hob bei Detektor-Levels (TP1 1 R / TP-Full 1,5 R) nur TP1 an; TP-Full blieb liegen, beide fielen zusammen. TP-Full folgt jetzt im selben Verhältnis (`AIEngine._apply_crv_frame`). Die Trade-Karte zeigt das echte R aus Entry und Anfangs-SL.
- **Analyse-Statistik über alle Trades:** neuer Endpunkt `GET /api/autotrade/trade-summary?filter=…&symbol=…` (`services/trade_summary.py`), die Analyse-Ansicht nutzt ihn für PnL, Anzahl offen/geschlossen und „Performance je Strategie“. Vorher änderten sich die Zahlen beim „Mehr laden“.

## Analyse-Statistik stabil, Bewertungs-Stichtag (17.11.2026, neuntes Paket)

- **Statistik springt nicht mehr:** Die Analyse-Ansicht merkt sich je Filter und Coin den letzten Server-Stand. Ein Fehlversuch oder ein Filterwechsel fällt nicht mehr auf die Teil-Summe der geladenen Trades zurück; beim ersten Laden steht „…“. Nur wenn der Server nicht antwortet, wird über die geladenen Trades gezählt, mit sichtbarem Hinweis. Backend: 10-s-Cache der Trade-Zeilen (`trade_summary.RowCache`).
- **Bewertungs-Stichtag 17.11. 23:15** (Auftrag des Traders): einmalige Boot-Migration `migrate_evaluation_cutoff_1711`. Verschiebt nur nach vorn, nie zurück; danach gilt, was im Leitstand eingestellt wird.
