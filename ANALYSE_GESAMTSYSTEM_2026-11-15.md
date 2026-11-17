# Gesamtanalyse Daytrading-Website – Stand 15.11.2026

Geprüft: Branch `3` von `dean06greif-ai/EIgen-zip` (vollständiger Klon). **Es wurde kein Code geändert**, nichts deployt, keine Produktiv-Datenbank und keiner der im Chat genannten Schlüssel benutzt.

Aufbau: 1. Kurzfazit · 2. Sofortmaßnahmen Sicherheit · 3. Zahlen zur Größe · 4.–7. die vier Kernbereiche · 8. Forex-Frage · 9. Toter Code / Aufräumliste · 10. Sichtbarkeit · 11. Maßnahmenliste mit Prioritäten · 12. Schritt-für-Schritt-Plan zur Freigabe · 13. Was ich nicht prüfen konnte.

---

## 1. Kurzfazit

1. **Keiner der vier Bereiche hat bisher einen nachgewiesenen Vorteil nach Kosten.** Eure eigene Prod-Auswertung vom 03.11. (`KI_TRADER_RETTUNGSPLAN_0311.md`, `STRATEGIE_REGIME_ANALYSE_0311.md`) sagt: KI-Trader 1.676 Trades, −0,23 R je Trade; beste statische Strategie (TrendFolge2, 5m) 322 Trades, −0,01 R netto bei +0,08 R brutto; dynamische Strategien 0 Trades, alle im Entwurf; Forex −0,48 R. Das Problem ist also nicht „zu wenige Funktionen", sondern fehlender Vorteil plus Kosten.
2. **Der Overfitting-Schutz lässt Zufall durch – das habe ich mit eurem unveränderten Code gemessen.** Auf künstlichen Kursen ohne jeden Vorteil (Random Walk) liefert die Endlos-Suche in 8 von 8 Läufen „Champions", meist alle 5 in unter einer Minute (Details Abschnitt 4).
3. **Die Freigabe-Tore für Live sind statistisch zu schwach.** Das Signal-Broker-Tor (5 Trades) lässt eine Strategie ohne Vorteil in rund 20–40 % der Fälle live gehen.
4. **Kritische Sicherheitslücke:** Das aktuelle Admin-Passwort steht im Klartext in 105 Dateien des (laut euch öffentlichen) Repos. Dazu sind fast alle Lese-Endpunkte ohne Login offen.
5. **Die Größe ist selbst das Risiko:** ~197.000 Zeilen Python, 503 API-Endpunkte, 29 Hintergrund-Schleifen in einem Prozess, über 300 Einstellungen. 42 % des Service-Codes gehören zum KI-Trader, rund 20.000 Zeilen zu Regime-Lab + Dynamik, die nie gehandelt haben.
6. **Empfehlung:** Nichts Neues bauen. Sicherheit schließen, Validierung reparieren, auf Krypto + eine Strategie-Familie + einen einfachen Regime-Filter verkleinern, den KI-Trader vom Auslöser zum Prüfer umbauen, alles andere abschalten (erst per Schalter, später löschen).

---

## 2. Sofortmaßnahmen Sicherheit (vor allem anderen)

| # | Befund | Beleg | Was tun |
|---|---|---|---|
| S1 | **Admin-Passwort im Repo.** Der exakte Wert aus `ADMIN_PASSWORD` steht in 105 Dateien, fast alle unter `backend/tests/` und `tests/` als Fallback-Wert. Damit kann jeder, der Repo und Frontend-URL kennt, sich als Admin anmelden: Modus auf Live stellen, Trades öffnen/schließen, Konfiguration und Master-Prompt ändern, Worker-Token auslesen. | `git grep` auf den Passwort-Anfang | Passwort sofort ändern; alle Fundstellen durch Umgebungsvariable ohne Fallback ersetzen; Repo privat stellen oder Historie bereinigen (auch ältere Repos/Branches prüfen) |
| S2 | **Alle Schlüssel aus dem Chat gelten als offengelegt.** Sie stehen in eurem „Standard-Prompt", wurden also in jede KI-Sitzung kopiert. | Chat | Alle rotieren: Bitunix (dabei: keine Auszahlungsrechte, IP-Bindung), MongoDB, JWT-Secret, Telegram, Supabase, Gateway-Token, alle LLM-Schlüssel. Künftig nur Variablennamen weitergeben, nie Werte |
| S3 | **233 von 244 GET-Endpunkten ohne Login**, darunter komplette Trade-Historie, Einstellungen, Master-Prompt, Lektionen, Debug-Status. | `core/auth.py` (Auth nur je Route), `routers/autotrade.py`, `routers/general.py` | Login global erzwingen, nur `/api/health` und Login offen lassen |
| S4 | **Kette bis auf euren PC:** Admin darf den Daten-Ordner des Local Workers frei setzen (`set_worker_data_dir`, keine Pfadprüfung), der Worker lädt dort alte `.pkl.gz`-Dateien per `pickle.load` (`candle_cache.py`). Mit dem geleakten Passwort ist das potenziell Codeausführung auf dem Rechner. Außerdem wird `symbol` beim Lösch-Job ungeprüft in einen Dateipfad eingesetzt. | `services/local_exec.py`, `services/candle_cache.py`, `routers/local_worker.py` | Pickle-Altpfad entfernen, Symbol gegen Instrumentenliste prüfen, Daten-Ordner nur lokal am Worker einstellbar machen |
| S5 | **IBKR-Gateway öffentlich erreichbar**, geschützt nur durch ein kurzes festes Token, das auch als URL-Parameter akzeptiert wird; Image `voyz/ibeam:latest` ungepinnt; `IBKR_VERIFY_SSL=false`. | `ibeam_gateway/proxy.py`, `Dockerfile` | Dienst abschalten (siehe Abschnitt 8). Falls nicht: langes Zufallstoken, nur Header, Image-Version festlegen |
| S6 | Kleinere Punkte: `ADMIN_PASSWORD` fällt ohne Env auf `admin` zurück; Login-Sperre nutzt `X-Forwarded-For` (fälschbar); Worker-Token-Vergleich nicht zeitkonstant; CORS offen. | `core/auth.py`, `routers/auth.py` | Beim Aufräumen mit erledigen |
| S7 | 12 OpenRouter-, 3 Groq-, 5 Mistral-Schlüssel im Wechsel. Mehrere Konten zum Umgehen von Gratis-Limits verstoßen in der Regel gegen die Anbieter-Bedingungen; Sperren kämen zu zufälligen Zeitpunkten. | Env-Liste, `ai_providers.py` | Ein bezahlter Schlüssel je Anbieter, ein festes Modell je Rolle |

---

## 3. Größe in Zahlen

| Kennzahl | Wert |
|---|---|
| Dateien im Repo | 1.348, davon 952 Python |
| Python-Zeilen | ~197.000 (Services ~86.000 in 259 Dateien, Tests ~76.000 in 477 Dateien) |
| Frontend | ~39.000 Zeilen JS |
| API-Endpunkte | 503 in 49 Routern; rund 95 ohne erkennbaren Aufrufer im Frontend |
| Hintergrund-Schleifen beim Start | 29, alle in einem Render-Prozess (zusammen mit Backtests und LLM-Aufrufen) |
| MongoDB | 60 Collections, 42+ Einstellungs-Dokumente, auf Atlas-Free-Tier (512 MB) |
| Einstellungen KI-Trader | 90 Schlüssel, davon 39 Ein/Aus-Schalter (31 standardmäßig an) |
| Einstellungen Regime-Engine | 75 |
| Handels-Einstellungen | ~35 je Strategie, vierfach geschichtet (global → Coin → Strategie → Strategie×Coin) |
| Bedienelemente im Frontend | ~215 Eingabefelder, 206 Auswahllisten, 113 Checkboxen; `AITradingPanel` allein 81 |
| Größte Funktion | `_on_signal_impl` in `bitunix_trade.py`: 1.245 Zeilen, 382 Verzweigungen – der Order-Einstieg |
| Fehlerbehandlung | 1.543 `except`-Blöcke, 1.009 fangen pauschal alles, 161 davon schlucken den Fehler stumm |

Codeanteil nach Bereich (nur `backend/services`, nach Dateinamen zugeordnet):

| Bereich | Zeilen | Dateien | Ergebnis laut eurer Auswertung 03.11. |
|---|---|---|---|
| KI-Trader | ~36.400 | 106 | −0,23 R je Trade |
| Regime-Lab / Regime-Engine | ~15.100 | 48 | Champions 46–53 % Treffer (Zufall ~33 %) |
| Dynamische Strategien | ~4.800 | 15 | 0 Trades |
| Statische Strategien (Backtest/Optimizer) | ~11.000 | 36 | beste Strategie ±0 |
| Ausführung / Risiko | ~12.100 | 30 | – |
| Local Worker / Jobs / Daten | ~6.800 | 23 | – |

**Muster hinter dem Wachstum:** Fast jedes Modul trägt einen Kommentar „Befund vom …" – jede Auffälligkeit bekam einen neuen Wächter mit eigenem Schalter. Auch die bisherigen Audits (`analysis_paket/` vom 15.09., Rettungsplan 03.11.) endeten jeweils mit neuen Modulen. Seit September ist die Zahl der Python-Dateien von 532 auf 952 gestiegen. Dieser Bericht empfiehlt deshalb ausschließlich Entfernen, Sperren und Reparieren.

---

## 4. Kernbereich 1 – Statische Strategien und Optimierung

### 4.1 Experiment: findet die Suche „Gewinner" im reinen Zufall?

Aufbau: Original-`run_optimizer`, nur der Daten-Download durch künstliche 1-Minuten-Kerzen ersetzt (driftloser Random Walk mit Volatilitäts-Clustern, 365 Tage, 15m, Gebühr 0,06 %). Auf solchen Daten kann es per Konstruktion keinen Vorteil geben.

| Test | Ergebnis |
|---|---|
| **Endlos-Suche** (`deep_explore`), 8 Datensätze | 8 von 8 Läufen liefern Champions; 6 erreichen das Ziel von 5 Champions in 13–41 Sekunden. Von 135 Kandidaten, die den Walk-Forward-Test erreichten, bestanden 37 (27 %). Beispiel: Training +1.077 USDT bei 350 Trades, „unbekannter" Test +559 USDT bei 117 Trades, auf 100 USDT Kapital |
| **Kombi-Suche** mit Preset „Trendfolge", 400 Durchläufe, rollierender Walk-Forward, 13 Datensätze | Rang 1 hat im Training immer +666 bis +1.505 USDT; in 6 von 13 Läufen (46 %) ist auch der Test positiv. In allen 13 Läufen sind alle Top-5 als `passed: true` markiert |
| **Kontrolle:** dieselben Champions auf 30 frischen Zufallspfaden | Netto im Mittel −155 bis −532 USDT je Pfad, nur etwa ein Drittel der Pfade positiv; brutto ungefähr null. Der Simulator selbst erfindet also keinen Gewinn – der Fehler liegt in der Auswahl |

Einschränkung: synthetische Daten, ein Symbol, Standardwerte. Auf echten Daten heißt das: ein Champion aus dieser Pipeline ist von Zufall nicht unterscheidbar.

### 4.2 Warum das passiert (Codebefunde)

| # | Befund | Stelle |
|---|---|---|
| A1 | **Testdaten sind Auswahlkriterium.** Die Endlos-Suche läuft, bis genug Kandidaten Training *und* Test bestehen, und merkt sich die Besten über alle Läufe. Der Test ist damit verbraucht; ein unberührter dritter Datenteil existiert nicht. | `deep_explore.py` |
| A2 | **Walk-Forward lässt nie durchfallen.** Er ist als `is_filter=False` nur Sortierkriterium. Ein Kandidat mit Verlust im Test bleibt „bestanden", solange die übrigen Prüfungen nicht einzeln eingeschaltet sind. Alle Prüfungen sind standardmäßig aus. | `robustness.py` (`build_checks_summary`), `optimizer.py` (`_finalize_top5`) |
| A3 | **Rang 1 wird nach Test-Ergebnis gewählt** (Sortierung nach `wf_score` über 5–10 Kandidaten). Das erklärt die 46 % statt etwa 30 %. | `optimizer.py` |
| A4 | **„Rollierender Walk-Forward" optimiert nicht neu.** Parameter werden einmal gefunden und auf späteren Fenstern nur ausgewertet. Das ist ein in Stücke geteilter Einzeltest, kein Test des Verfahrens. | `robustness.py` (`rolling_windows`) |
| A5 | **Keine Korrektur für die Zahl der Versuche.** `wf_checked` wird gezählt, aber nicht verwendet. Mindest-Test-Trades können bei 3 liegen. | `deep_explore.py` |
| A6 | **Suchraum riesig.** Alle Handelsgruppen zusammen ergeben über 10^18 Kombinationen, dazu Strategie-Parameter und Timeframe. | `optimizer.py` (`TRADE_SPACE`) |
| A7 | **Hebel, Handelszeiten und Richtung werden mitoptimiert.** Der Gewinn steigt fast linear mit dem Hebel, die Suche wählt also den höchsten, der zufällig nicht liquidiert wurde. Sessions und Richtung sind reine Rückschau-Auswahl. | `TRADE_SPACE`: `leverage`, `sessions`, `allowed_sides` |
| A8 | **Ziel ist absoluter Gewinn**, nicht Gewinn je Risiko. Standard `combo` = PnL × (0,5 + Trefferquote). | `optimizer.py` |
| A9 | **Kosten zu optimistisch.** Einstieg zum Schlusskurs der Signalkerze, kein Slippage, kein Spread, Stop exakt am Level, keine Funding-Kosten im Backtest. Slippage gibt es nur als abschaltbaren Stresstest (Gebühr × 1,5). | `backtester.py`, `fee_model.py` |
| A10 | **Zu kleine Stichproben erlaubt.** Standard im Backend: 3 Tage, mindestens 10 Trades. Die Oberfläche bietet 1–14 Tage zum Optimieren an. | `optimizer.py`, `constants/optimizerOptions.js` |
| A11 | **Monte-Carlo mischt nur die Reihenfolge**, der Gesamtgewinn bleibt gleich; die Stabilitätsprüfung testet nur 4 Varianten und verlangt 50 % positive. Beides prüft nicht, ob der Vorteil echt ist. | `robustness.py` |
| A12 | **Regime-Auswertung nach Schließzeit des Trades** statt Einstiegszeit: Long-Gewinner landen dadurch überproportional in „Bulle". | `robustness.py`, `backtester.py` (`_market_phase_lookup`) |
| A13 | **Indikator-Fenster 260 Kerzen** – eine EMA200 ist damit nicht eingeschwungen; Abweichung zum Live-Scanner möglich (nicht abschließend geprüft). | `backtester.py` |
| A14 | **Zwei Simulationswege** (klassisch und `fast_sim`) müssen dauerhaft gleich gehalten werden. | `backtester.py`, `fast_sim.py` |
| A15 | **Backtest-Daten Krypto = Binance Spot, gehandelt wird Bitunix-Perp.** Andere Dochte und anderes Volumen; Volumen-Indikatoren lernen auf fremden Daten. | `history_sources.py` |

### 4.3 Was daraus folgt

- Drei Datenteile: Suche · Auswahl · **Tresor** (die jüngsten ~20 %, je Kandidat genau einmal auswertbar, mit Zähler, ohne Rückfluss in die Suche).
- Champion nur, wenn der Tresor-Test statistisch trägt: Mittelwert in R mit t-Wert, Schwelle steigt mit der Zahl geprüfter Kandidaten, mindestens 50–100 Test-Trades.
- **Zufalls-Benchmark als Pflichtschritt:** dieselbe Suche auf gemischten/künstlichen Reihen laufen lassen und anzeigen „auf Zufall findet diese Suche X Champions". Das Experiment oben ist genau das; die Skripte liegen vor.
- Hebel, Sessions, Richtung aus dem Suchraum nehmen; Ziel auf R je Trade umstellen; Slippage und Funding fest einrechnen; Einstieg zur nächsten Eröffnung.
- Optimieren erst ab 180 Tagen und 100 Trades zulassen.
- Letzte Instanz bleibt Paper-Vorwärtstest mit fester Parameter-Version.

---

## 5. Kernbereich 2 – Regime-Lab und dynamische Strategien

**Positiv:** Der frühere Blick in die Zukunft ist im Standardpfad behoben. `label_basis_of` und `dynamic_backtest` nutzen standardmäßig die kausalen Live-Labels; die Wisch-Indikatoren in `fast_sim` berücksichtigen die Bestätigungsverzögerung.

| # | Befund | Stelle |
|---|---|---|
| B1 | **Kein Nutzennachweis.** Laut eurer Anleitung vom 10.10. treffen die Champions 46–53 % (Zufall ~33 %, handelbar wäre ≥ 60 %). Dynamische Strategien: 0 Trades, 27 Dokumente im Entwurf, davon ~11 Testreste. | `REGIME_ANLEITUNG_1010.md`, `STRATEGIE_REGIME_ANALYSE_0311.md` |
| B2 | **Gemessen wird gegen Rückschau-Labels.** Ein kausaler Detektor kann eine Referenz mit Zukunftssicht nie gut treffen; bessere Trefferquote heißt nicht bessere Trades. | `regime_engine.py` (`ideal_labels`, `_profile_quality`) |
| B3 | **Alter Pfad lebt weiter.** Analysen ohne Live-Segmente fallen still auf die korrigierten `final`-Labels zurück; `_build_regime_segments` hat `basis="final"` als Vorgabe. | `regime_opt.py` |
| B4 | **Fenster als Anteil des Analysezeitraums.** Dieselbe Marktphase bekommt je nach Länge der Historie andere Labels. | `regime_engine.py` (adaptive Overrides) |
| B5 | **75 Detektor-Parameter plus Autopilot-Suche** – ein zweiter Ort für Overfitting, noch vor der Strategie-Suche. | `CONFIG_META` |
| B6 | **Daten werden zerstückelt.** Bis zu 9 Regime × Strategie je Regime × Parameter je Regime × Coin: pro Zelle bleiben zu wenige Trades. | `dynamic_strategy.py` |
| B7 | **Ein Preis-Trend-Regime ist im Kern ein Trendfolge-Signal.** „Long im Aufwärts-Regime" ist ein gleitender Durchschnitt mit vielen Zusatzparametern. | Konzept |
| B8 | **Neunstufiger Arbeitsablauf** (Daten → Gruppen → Autopilot → Feinsuche → Pooling → Champion → Nutzen → Walk-Forward → Freigabe), 42 Regime- und 23 Dynamik-Komponenten im Frontend. | `REGIME_ANLEITUNG_1010.md` |

**Empfehlung:** Regime-Lab einfrieren. Übrig bleibt *ein* fester, dokumentierter Klassifikator (Trend auf 4h/1D × Volatilität hoch/niedrig, ohne Anpassung je Coin), genutzt als Filter für die statische Strategie und als Kontextzeile für den KI-Prüfer. Einziges Erfolgsmaß: Unterschied in R zwischen den Regimen auf ungesehenen Daten. Eure eigene Auswertung zeigt genau dort den einzigen Lichtblick (TrendFolge2 im passenden Kurzfrist-Regime +0,27 R gegen −0,32 R) – das ist aber noch im Rückblick gemessen und muss vorwärts bestätigt werden. Dynamische Strategien erst wieder anfassen, wenn dieser Filter vorwärts trägt.

---

## 6. Kernbereich 3 – KI-Trader

### 6.1 Befunde

| # | Befund | Beleg |
|---|---|---|
| C1 | **LLM als Auslöser bringt nichts.** Eigene Daten: Konfidenz ohne Zusammenhang mit dem Ergebnis; 81 % der KI-Trades trugen ein Setup-Etikett, ohne dass der Detektor gefeuert hatte. Einziger positiver Wert: „Regel-Signal + KI-Prüfung" +0,32 R, aber nur 25 Trades. | `KI_TRADER_SIGNAL_BROKER_1010.md`, Rettungsplan 03.11. |
| C2 | **Live-Tor mit 5 Trades.** Danach live, wenn der geschrumpfte Mittelwert ≥ +0,05 R ist (roh also ≥ +0,15 R). Simulation: eine Strategie ohne Vorteil besteht das in rund 20–40 % der Fälle. Folge ist ein Kreislauf „Glückssträhne → live → Rückfall → zurückgestuft". | `signal_broker.py`, `source_stats.py`, `setup_lifecycle.py` |
| C3 | **Live-Freigabe-Check (60 Trades, Ø ≥ +0,10 R, jüngere Hälfte > 0)** ist besser, lässt aber eine Null-Strategie noch in ~21 % der Fälle durch. | `edge_filter.py` |
| C4 | **23 Setups × 4 Anlageklassen = 92 Zellen** mit eigenem Lebenszyklus, Kapitalgewicht, Varianten und Revisionen. Bei ~1.700 Trades sind das im Schnitt 18 je Zelle; die Messunsicherheit liegt dann bei etwa ±0,5 R. Alles, was daraus „gelernt" wird, ist Rauschen. | `ai_playbook.py` |
| C5 | **Lernen als Prosa-Schleife.** Lektionen aus einzelnen Trades fließen zurück in den Prompt. Das ist Overfitting in Textform und nicht messbar. | `ai_learning.py`, `ai_lessons.py` |
| C6 | **Fest verdrahtete Regel im Lern-Prompt:** „Hebel ist kein Stellhebel", Hebel-Deckel-Lektionen werden verworfen. Eure Daten zeigen den Bereich 50–100× als schlechtesten (−0,35 R, 1.049 Trades). Die eigentliche Ursache sind enge Stops im Verhältnis zur Gebühr; die Regel verhindert aber, dass das System das selbst erkennt. | `ai_learning.py` (`LEARNING_SYSTEM`) |
| C7 | **Wechselnde Modelle.** Gratis-Modelle mit Rückfallkette: wer gerade antwortet, entscheidet. Die „Strategie" ist dadurch nicht stabil und nicht auswertbar. | `ai_roles.py`, `ai_providers.py` |
| C8 | **LLM setzt Zahlen und greift ein:** Stop, Ziel, Kapitalanteil; `trade_manager` verändert offene Trades; Supervisor/Advisor ändern Einstellungen; Strategy-Lab und Policy-Lab schlagen Strategien vor. | `ai_engine.py`, `ai_trade_manager.py`, `ai_supervisor.py` |
| C9 | **Rund 20 Wächter in einer 400-Zeilen-Funktion**, jeder mit eigenem Schalter und Datum. | `ai_engine.py` (`_emit_signal`) |
| C10 | **Schutzfilter „fail-open".** 69 Stellen; unter anderem lässt der Edge-Filter bei internem Fehler den Live-Trade durch. | `bitunix_trade.py` (`_edge_filter_step`) u. a. |
| C11 | **Risiko 2 % je Trade als Standard** bei einem System ohne nachgewiesenen Vorteil. | `position_sizing.py` |
| C12 | **Wirtschaftlichkeit.** Laut Code-Kommentar vom 02.09. lag das Konto bei ~700 USDT. Selbst mit +0,15 R, 1 % Risiko und 20 Trades pro Woche wären das etwa 20 USDT pro Woche – weniger als Hosting und LLM-Kosten. Ziel bei dieser Größe ist der Nachweis, nicht der Ertrag. | `position_sizing.py` (Kommentar) |

### 6.2 Bessere Anordnung der Agenten

| Schicht | Wer | Aufgabe |
|---|---|---|
| 1 Signal | Code | 3–4 regelbasierte, backtestbare Setups auf 15m/1h |
| 2 Kosten- und Risikotor | Code | Gebühr ≤ 10 % des Risikos, Trend-/Regime-Filter, Risikobudget, Kill-Switch – **fail-closed** |
| 3 Prüfer | ein LLM, festes Modell | Nur Veto oder halbe Größe, mit Begründung. Jede Entscheidung wird gegen dasselbe Regel-Signal ohne KI gemessen (diesen Vergleich „regel" gegen „ki_geprueft" habt ihr schon – behalten) |
| 4 Nachrichten | ein LLM | Nur eine Flagge: „Ereignisrisiko in den nächsten 30 Minuten ja/nein" |
| 5 Bericht | ein LLM | Wochenbericht und Trade-Tagebuch für euch – ohne Rückkanal in den Prompt |

Das LLM setzt keine Stops, Ziele oder Hebel, verwaltet keine offenen Trades, ändert keine Einstellungen und schreibt keine Lektionen in den eigenen Prompt. Gelernt wird über eine kleine Tabelle (Erwartungswert je Setup × Regime mit Mindestmenge), geändert wird nur zu festen Terminen alle 2–4 Wochen mit Versionsnummer (`policy_fingerprint` gibt es dafür schon).

Damit entfallen: Deep-Analyst, Research-Analyst, Market-Observer als LLM-Rolle, Trade-Manager, Learner, Supervisor, Strategy-Lab, Policy-Lab, ML-Lab/ML-Gate, Closed-Loop, Activity-Guard-Automatik, Setup-Varianten und -Revisionen.

### 6.3 Setups und KI-Trader-Lab

- **Setups:** von 23 auf 3–4 reduzieren, nur solche mit Detektor (Vorschlag: `trend_follow2`, `divergence`, `vwap_reclaim`, optional `liquidity_sweep`). Event-Setups (FOMC/CPI/NFP/PPI/PCE) haben wenige Ereignisse pro Jahr und sind nie belegbar – entfernen.
- **KI-Trader-Lab / manuelles Nachbessern: ja, weglassen.** Das Seeding schreibt Backtest-Gewichte in Live-Entscheidungen und ist ein weiterer Overfitting-Kanal, die KI-Revisionen ebenso. Der Mensch bleibt an zwei Stellen: Hypothese vorab festlegen und Freigabe am Prüftermin. Parameter nachstellen gehört nicht dazu.

---

## 7. Kernbereich 4 – Local Worker

**Gut:** ausgehende Verbindung ohne offene Ports, derselbe Rechencode wie der Server (Paket-Download), nur 8 Einstellungen, Versionsprüfung.

| # | Befund | Empfehlung |
|---|---|---|
| D1 | Sicherheit: siehe S4 (Pickle-Altpfad, freier Daten-Ordner, ungeprüftes Symbol); Paket-Download ohne Login | wie S4 |
| D2 | **Die Langzeit-Suche ist die Endlos-Suche aus Abschnitt 4.** Mehr Rechenzeit erzeugt mehr Scheintreffer. | Bis zur Reparatur der Validierung sperren |
| D3 | **Datenqualität:** Krypto aus Binance Spot statt Bitunix-Perp; Ersatzquellen (PAXG, Dukascopy, FXCM) werden auf den Ankerpreis skaliert und aneinandergesetzt; für Quellen ohne Volumen wird ein Volumen aus der Kerzenspanne errechnet (`activity_volume`). | Je Symbol genau eine Quelle, am besten der gehandelte Kontrakt; kein Kunst-Volumen; Quelle im Ergebnis anzeigen |
| D4 | Bis 5.500 Tage wählbar, obwohl viele Coins nur 1–2 Jahre existieren; Indizes/Rohstoffe auf Bitunix erst wenige Monate | Feste Stufen 180 / 365 / 730 / „alles", tatsächliche Länge anzeigen |
| D5 | GPU-Beschleunigung für Indikatoren; der Engpass ist die Python-Schleife je Kerze | GPU-Pfad entfernen |
| D6 | Kopfkommentar „v1.9.0", Konstante `1.27.0` | angleichen |

---

## 8. Forex – ja oder nein?

**Nein, bei dieser Kontogröße nicht.**

- **Kosten:** IBKR-Mindestgebühr 2 USD je Order (so im `fee_model.py` hinterlegt). Bei 1.000 USD Positionsgröße sind das 0,4 % für Ein- und Ausstieg, mit Teilverkauf bis 0,8 %. Die übliche Tagesspanne von EURUSD liegt bei 0,5–0,7 %. Die Mindestgebühr spielt erst ab etwa 100.000 USD Positionsgröße keine Rolle mehr.
- **Daten:** Yahoo liefert rund 30 Tage 1-Minuten-Daten, verzögert und ohne echtes Volumen. Damit ist keine belastbare Optimierung möglich.
- **Betrieb:** eigener Gateway-Dienst mit Auto-Login, regelmäßige Neuanmeldung, Sicherheitsrisiko S5.
- **Ergebnis:** −0,48 R je Trade laut eurer Auswertung.

**Weniger Assets:** von 25 auf 4–6 liquide Krypto-Perps (BTC, ETH, SOL, dazu höchstens zwei bis drei weitere mit langer Historie und engem Spread). Indizes und Rohstoffe als Bitunix-Perp haben nur wenige Monate Historie und laufen am Wochenende dünn – ebenfalls pausieren. Weniger Märkte bedeutet mehr Trades je Markt und damit schnellere Gewissheit.

---

## 9. Toter Code und Aufräumliste

**Wichtig vorab:** Auf Datei-Ebene ist das Backend erstaunlich dicht – 336 von 339 Modulen sind vom Server aus erreichbar, nur 18 Funktionen (194 Zeilen) werden nirgends aufgerufen. Das Problem sind nicht verwaiste Dateien, sondern **verdrahtete Funktionen ohne Nutzen**. Aufräumen heißt deshalb vor allem: ganze Funktionsbereiche abschalten.

### 9.1 Sicher entfernbar (ohne Einfluss auf Render)

| Was | Umfang |
|---|---|
| `frontend/src/components/ui/` komplett, `hooks/use-toast.js`, `lib/utils.js`, `constants/testIds/` | 51 Dateien, ~3.080 Zeilen, nirgends importiert |
| Ungenutzte npm-Pakete | 52 von 60: 39 nur vom toten `ui/`-Ordner genutzt (alle Radix-Pakete, cmdk, vaul, react-hook-form …), 13 gar nicht importiert (axios, lodash, framer-motion, react-router-dom, swr, zod, date-fns, dayjs …). `react-scripts` und `cra-template` vor dem Entfernen gegen den Build prüfen |
| `backend/requirements.txt` | rund 130 Pakete, gut 20 werden importiert. Unbenutzt u. a. stripe, boto3, SQLAlchemy, alembic, passlib, bcrypt, python-jose, tiktoken, tokenizers, huggingface_hub, black, flake8, mypy, isort. Spart Build-Zeit und Speicher |
| Backend-Module ohne Aufrufer | `models/signal.py`, `services/price_watch.py`, `services/regime_core.py` |
| Wurzelverzeichnis | 31 der 49 Markdown-Dateien, `d.png`, `.screenshots/`, `backend_test.py`, `test_result.md`, `test_reports/`, `analysis_paket/`, `scripts/` (darunter Prod-Sonden), `backend/scripts/*.pkl`, `backend/test_bitunix_precision_fix.py`. Zur Laufzeit wird nichts davon gelesen (nur in Kommentaren erwähnt). Vorschlag: in einen Ordner `docs/archiv/` verschieben statt löschen |
| Alte Router | `routers/fomc.py`, `routers/econ.py` (10 Endpunkte, im Frontend durch `/api/event-setups` ersetzt) |
| Testreste in der Prod-DB | ~11 Dynamik-Dokumente (`TEST_…`, `AP04-Test-…`) – entstanden, weil Live-Tests gegen die echte Datenbank liefen |

### 9.2 Endpunkte ohne Oberfläche (~95)

Ohne Aufrufer im Frontend unter anderem: Policy-Lab (8), Makro-Router (7), Recovery (3), Risikobudget, AI-Protection, Safety-Config, OpenRouter-Schlüssel, Pause/Fortsetzen für Backtest und Optimizer, mehrere Lab-Statusabfragen. **Behalten und sichtbar machen** sollte man die Diagnose-Endpunkte `system/loop-health`, `ai/providers/health`, `debug/status` (siehe Abschnitt 10).

### 9.3 Abschalten per Schalter, später löschen

Forex/IBKR komplett · Indizes/Rohstoffe · dynamische Strategien und Werkbank · Regime-Lab-Stufen (Autopilot, Pooling, Champions, Assistent, Cockpit, Freigabe) · Endlos-Suche · KI-Rollen laut 6.2 · KI-Trader-Lab/Seeding · Event-Setups · Strategy-Copilot · GPU-Pfad · Portfolio-Backtest-Sonderszenarien.

### 9.4 Tests

460 Testdateien in `backend/tests`, 134 davon nach Iterationen benannt (`iterN`), rund 204 brauchen einen laufenden Server und melden sich mit dem fest eingetragenen Admin-Passwort an; teils feste Pfade `/app/...`. In meiner Umgebung: 975 Unit-Tests grün, 941 Live-Tests nicht ausführbar, der Rest scheiterte an fehlenden Paketen (kein Netz für die Installation) – echte Fehlschläge habe ich nicht gefunden. Empfehlung: Live-Tests in einen eigenen Ordner, nur gegen eine Test-Datenbank; für den Geldpfad wenige, bewusst geschriebene Tests statt Iterations-Sammlung.

---

## 10. Besser sehen, was passiert

1. **Eine Statusseite „Was läuft, was nicht":** je Hintergrund-Schleife letzter Lauf, Dauer, letzter Fehler. Die Daten liefert `system/loop-health` bereits – es fehlt nur die Anzeige.
2. **Wächter-Zähler:** je Schutzfilter pro Tag „durchgelassen / blockiert / Fehler / übersprungen". Ein Filter mit Fehlern oder mit null Entscheidungen fällt dann sofort auf.
3. **Schutzfilter für echtes Geld fail-closed**, jeder Ausfall als Telegram-Meldung. Die 161 stummen `except`-Blöcke schrittweise durch Protokoll plus Zähler ersetzen, beginnend im Order-Pfad.
4. **Entscheidungsspur je Trade:** eine Zeile mit Signal, Regime, jedem Tor und Ergebnis, Modellname und Parameter-Version.
5. **Eine Kennzahl oben auf der Seite:** Erwartungswert in R mit Unsicherheitsbereich und Trade-Anzahl, getrennt nach Live und Paper – statt USDT-Summen.
6. **Einstellungen:** drei Profile (Aus / Paper / Live-klein) statt Einzelschalter; alles andere hinter „Experte", schreibgeschützt bis zum Prüftermin. Jede Änderung mit Zeitstempel und Version protokollieren.
7. **`_on_signal_impl` (1.245 Zeilen) in benannte Schritte zerlegen** – erst nach Absicherung durch Tests, ohne Verhaltensänderung.

---

## 11. Maßnahmenliste nach Priorität

### P0 – sofort (Sicherheit, kein Risiko für die Funktion)
1. Admin-Passwort ändern, alle Schlüssel rotieren (S1, S2).
2. Passwort aus allen 105 Dateien entfernen, Repo privat stellen.
3. Login für alle Endpunkte außer Health und Login (S3).
4. IBKR-Gateway-Dienst stoppen (S5).
5. Worker: Pickle-Altpfad, Symbolprüfung, Daten-Ordner (S4).

### P1 – Geldabfluss stoppen (nur Schalter und Standardwerte)
6. Live-Handel auf Paper stellen, bis ein Tor nach 11.2 bestanden ist. Manuelle Live-Trades über die Seite sperren (laut eurer Auswertung −908 USDT).
7. Forex, Indizes, Rohstoffe aus; Krypto auf 4–6 Märkte.
8. Endlos-Suche und Optimierung unter 180 Tagen sperren.
9. Risiko je Trade auf 0,25–0,5 %.
10. KI-Rollen laut 6.2 abschalten, ein festes Modell.

### P2 – Validierung reparieren (Code, modular)
11. Tresor-Daten mit Einmal-Auswertung und Zähler.
12. Walk-Forward als echtes Durchfall-Kriterium; t-Wert mit Korrektur für die Zahl der Versuche; Mindest-Trades.
13. Zufalls-Benchmark als fester Schritt jeder Suche.
14. Kostenmodell: Slippage, Funding, Einstieg zur nächsten Eröffnung.
15. Hebel, Sessions, Richtung aus dem Suchraum; Ziel in R.
16. Live-Tore ersetzen: mindestens ~120 Trades und t ≥ 2 statt 5 bzw. 60 Trades.
17. Schutzfilter fail-closed, Wächter-Zähler, Statusseite.

### P3 – Entschlacken
18. Totes Frontend, npm-Pakete, `requirements.txt`, Wurzelverzeichnis (9.1).
19. Abgeschaltete Bereiche nach 4 Wochen ohne Vermissen löschen (9.3).
20. Einstellungen auf drei Profile; Setups auf 3–4.
21. Order-Funktion zerlegen, Tests neu ordnen.

### P4 – Weg zur Profitabilität
22. Eine Hypothese festschreiben: TrendFolge2 auf 15m statt 5m (bessere Gebühr-zu-Risiko-Relation), Maker-Einstieg, fester 4h-Trendfilter, Gebühr ≤ 10 % des Risikos.
23. Einmal mit reparierter Validierung testen, dann Parameter einfrieren.
24. Paper-Vorwärtstest bis zum Tor, danach Live mit kleinstem Risiko, erst nach bestandenem zweiten Tor vergrößern.
25. KI-Prüfer parallel im Vergleich messen; nur behalten, wenn er gegenüber dem reinen Regel-Signal messbar besser ist.

### 11.2 Wie viele Trades braucht ein Nachweis?

Bei einer Streuung von etwa 1,1 R je Trade (Annahme, aus euren Daten nachzurechnen) und t ≥ 2:

| Echter Vorteil je Trade | Nötige Trades | Bei 20 Trades/Woche |
|---|---|---|
| +0,05 R | ~1.970 | ~99 Wochen |
| +0,10 R | ~490 | ~25 Wochen |
| +0,15 R | ~220 | ~11 Wochen |
| +0,20 R | ~120 | ~6 Wochen |
| +0,30 R | ~50 | ~3 Wochen |

Folgerung: Kleine Vorteile sind mit eurem Handelsvolumen nicht in vertretbarer Zeit beweisbar. Sinnvoll sind nur Ansätze, die mindestens +0,15 bis +0,20 R versprechen, auf wenigen Märkten gebündelt.

---

## 12. Schritt-für-Schritt-Plan zur Freigabe

Jeder Schritt ist einzeln freigebbar, hält die Ordnerstruktur (`backend/`, `frontend/`, `local_worker/`, `ibeam_gateway/`) unverändert und endet mit Testlauf und Prüfung der Oberfläche.

| Schritt | Inhalt | Risiko für den Betrieb | Braucht von euch |
|---|---|---|---|
| 0 | Schlüssel rotieren, Repo privat (macht ihr selbst in Render/GitHub/Anbietern) | keines | Erledigung |
| 1 | Passwort aus Tests entfernen, Login global, Worker-Härtung | gering; Tests brauchen danach Env-Variable | Freigabe |
| 2 | Schalter und Standardwerte aus P1 (kein Löschen) | gering, rückholbar | Entscheidung Märkte, Entscheidung Live aus |
| 3 | Statusseite und Wächter-Zähler, fail-closed im Order-Pfad | mittel – blockiert bei Filterfehler Trades (gewollt) | Freigabe |
| 4 | Validierung: Tresor, Durchfall-Kriterium, Zufalls-Benchmark, Kostenmodell | gering für Live, ändert Suchergebnisse | Freigabe |
| 5 | Neue Live-Tore | gering | Schwellen bestätigen |
| 6 | Aufräumen 9.1 (Frontend, Pakete, Wurzel) | gering; Build vorher/nachher prüfen | Freigabe |
| 7 | KI-Trader auf die Anordnung aus 6.2 | mittel | Entscheidung, welche Rollen wegfallen |
| 8 | Löschen der abgeschalteten Bereiche | mittel, nach 4 Wochen Wartezeit | Freigabe je Bereich |

**Offene Entscheidungen:**
1. Live-Handel pausieren, bis ein Tor bestanden ist – ja/nein?
2. Forex und IBKR-Dienst ganz stilllegen – ja/nein?
3. Welche 4–6 Krypto-Märkte bleiben?
4. Regime-Lab und dynamische Strategien einfrieren – ja/nein?
5. KI-Trader zum Prüfer umbauen, oder vorerst nur Rollen abschalten?

---

## 13. Was ich nicht prüfen konnte

- **Produktivdaten:** Alle Ergebniszahlen (R-Werte, Trade-Anzahlen, Kontogröße) stammen aus euren Dokumenten und Code-Kommentaren, nicht aus eigener Abfrage.
- **Laufender Server:** `fastapi`, `motor`, `aiohttp` waren hier nicht installierbar. Server-Start, Live-Tests und die Oberfläche im Browser sind ungeprüft.
- **Repo-Sichtbarkeit:** „öffentlich" laut eurer Angabe; technisch konnte ich es nicht abfragen.
- **Nicht zeilenweise gelesen:** große Teile von `bitunix_trade.py`, `ai_engine.py`, `regime_lab.py` und der Frontend-Komponenten. Dort habe ich Struktur, Einstiegspfade und Stichproben geprüft. Weitere Logikfehler im Detail sind wahrscheinlich.
- **Experiment:** künstliche Daten, ein Symbol, 8 bzw. 13 Läufe. Die Richtung ist eindeutig, die genauen Prozentwerte sind Schätzungen.
- **Endpunkte ohne Aufrufer:** statische Suche; dynamisch zusammengesetzte Adressen habe ich von Hand herausgerechnet, einzelne Fehlzuordnungen sind möglich.
- **Streuung 1,1 R** in 11.2 und den Tor-Simulationen ist eine Annahme.
