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
