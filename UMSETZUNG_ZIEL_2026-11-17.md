# Umsetzung 17.11.2026: strengere Champion-Prüfung, Trendfolge-Vorgaben, mehr Lerndaten

Stand: 16.11.2026 abends, Paket `eigen-zip-ziel-2026-11-17.zip`. Baut auf `ANALYSE_WEG_ZUM_ZIEL_2026-11-16.md` auf.

## Kurzfassung

1. **Auf echten Marktdaten geprüft, wo ein Vorteil liegt.** 26 Coins, Binance-Daten seit 2018, mit Gebühren und Funding gerechnet. Ergebnis: Trendfolge mit langem Horizont verdient, kurzer Horizont nicht. Die Tabelle steht in Abschnitt 1.
2. **Die Endlossuche prüft Champions strenger** (Abschnitt 2): Rückwärtstest auf älteren Daten, Versuchs-Konto über Läufe, Tresor mit Ø R, Training auch in R im Plus, neues Ziel „t-Wert (R)“.
3. **Zwei Trendfolge-Vorgaben laufen im Vorwärtstest** (Abschnitt 3), ohne Kapital. Die 4h-Variante lässt sich im Leitstand mit einem Klick als Paper-Strategie starten.
4. **Die Nacht-Forschung sucht zuerst nach Trend-Strategien** und nutzt das Ziel „t-Wert (R)“.
5. **Mehr Lerndaten:** Lern-Trades dürfen 10 statt 5 je Klasse und Richtung offen haben.
6. **Fehler behoben:** „Übernehmen (Paper)“ setzte den Paper-Modus nie, weil die neue Strategie-ID falsch gelesen wurde.

Pflicht nach dem Deploy: **Worker-Paket 1.31.0** herunterladen und den Worker neu starten.

## 1. Was echte Daten zeigen

Rechnung im Browser auf öffentlichen Binance-Kerzen, 26 Coins (BTC, ETH, SOL, BNB, XRP, DOGE, ADA, AVAX, DOT, LINK, LTC, TRX, ATOM, NEAR, UNI, ETC, XLM, BCH, FIL, APT, SUI, ARB, OP, INJ, AAVE, HBAR).

Regel, fest vorab gewählt und nicht optimiert:
- Einstieg beim Schlusskurs über dem N-Tage-Hoch (Long) oder unter dem N-Tage-Tief (Short).
- Stop 2 ATR, danach nachgezogener Stop 3 ATR.
- Kosten: 0,08 % je Seite (Taker-Gebühr plus Slippage) und 0,03 % Funding je Tag für Longs.

| Horizont des Ausbruchs | Trades | Ø R je Trade | t-Wert | 2025–26 | letzte 12 Monate |
|---|---|---|---|---|---|
| 20 Tage, Tageskerzen (seit 2018) | 1.669 | **+0,34** | 4,6 | −0,03 | +0,21 |
| 20 Tage, 4h-Kerzen (seit 2021) | 2.135 | +0,25 | 3,8 | +0,01 | +0,20 |
| 10 Tage, 4h-Kerzen | 3.677 | +0,20 | 3,6 | −0,06 | +0,09 |
| 5 Tage, 4h-Kerzen | 7.402 | +0,06 | 2,5 | −0,03 | −0,04 |
| 3 Tage, 4h-Kerzen | 8.821 | +0,06 | 2,4 | −0,04 | −0,09 |

Was daraus folgt:
- **Je länger der Horizont, desto größer der Vorteil.** Das erklärt, warum 1m- und 15m-Ansätze im System verlieren.
- **Der Vorteil ist nicht an eine Einstellung gebunden.** 10, 20 und 55 Tage sowie Trail 3 und 4 ATR liefern ähnliche Werte (+0,28 bis +0,57 R).
- **Fast der ganze Vorteil kommt von der Long-Seite** (+0,61 R). Shorts lagen bei ±0 R.
- **Der Vorteil schwankt stark.** 2025 verlor die Regel leicht, die letzten 12 Monate waren wieder positiv.

Zum Vergleich als Portfolio (Zeitreihen-Momentum über 10/20/40/80 Tage, Einsatz nach Volatilität, täglich angepasst):

| Variante | Ertrag p. a. | Schwankung | Sharpe | größter Rückgang |
|---|---|---|---|---|
| Long/Short | +17,7 % | 22,7 % | 0,78 | 31 % |
| nur Long | +20,3 % | 15,7 % | 1,29 | 24 % |
| Kaufen und Halten (gleiche Steuerung) | +27,0 % | 37,0 % | 0,73 | 54 % |

Grenzen dieser Rechnung:
- **Auswahl-Verzerrung:** Die 26 Coins gibt es heute noch. Gescheiterte Coins fehlen. Das schönt die Long-Seite.
- **Die t-Werte sind zu hoch.** Coins bewegen sich gemeinsam, die Trades sind nicht unabhängig.
- **Seit 2025 ist der Vorteil klein** (Long/Short +6 % p. a., Sharpe 0,27).
- Es ist ein eigener Nachbau der Regel, nicht der Backtester der Website. Die Vorgaben laufen deshalb zusätzlich durch den Vorwärtstest der Website.

Realistische Erwartung: Sharpe 0,5 bis 0,8 mit Rückgängen von 25 bis 30 %. Das ist die einzige Quelle im ganzen System mit positivem Beleg nach Kosten.

## 2. Strengere Champion-Prüfung (F1)

Neu in `services/champion_checks.py`, aufgerufen von `deep_explore.run`. Prüf-Stand 3; ältere Champions wandern in den Altbestand.

| Prüfung | Vorher | Jetzt |
|---|---|---|
| Training | Gewinn in USDT > 0 | zusätzlich Ø R > 0 |
| Tresor | Gewinn > 0 mit ~4 Trades | Ø R > 0 mit mindestens 10 Trades |
| Hürde (t-Wert) | zählt nur die Prüfungen dieses Laufs | zählt alle Prüfungen der letzten 30 Tage auf derselben Klasse und Zeitebene mit (Versuchs-Konto) |
| Anderer Zeitraum | keiner | **Rückwärtstest**: bis zu 365 Tage vor dem Suchfenster, die Suche, Test und Tresor nie gesehen haben. Ø R ≤ 0 bei mindestens 20 Trades = durchgefallen |
| Long/Short | nicht sichtbar | getrennt ausgewiesen, Warnung bei einseitigem Vorteil |
| Ziel der Suche | Kombi (USDT) | neu „t-Wert (R)“; Warnhinweis bei USDT-Zielen in der Endlossuche |

Auch die Top-5-Prüfung der anderen Such-Modi verlangt im Tresor jetzt zusätzlich Ø R > 0.

Der Rückwärtstest läuft nur auf dem lokalen Worker. In der Cloud reicht der Speicher für die doppelte Historie nicht; dort steht „nicht prüfbar“.

### Härtetest (Multi-Core wie auf dem Worker)

Zufallsdaten und eingebaute Vorteile, 4 Assets, 15m, 180 Tage Suchfenster plus 180 ältere Tage, Ziel „t-Wert (R)“. Es lief der Original-Code, ersetzt wurde nur die Datenquelle.

| Daten | Kombis | im Test geprüft | Champions | Bemerkung |
|---|---|---|---|---|
| reiner Zufall, Lauf 1 | 488 | 52 | 0 | richtig |
| reiner Zufall, Lauf 2 | 424 | 58 | 0 | richtig, knappster Fehlschlag t 1,3 bei Hürde 3,29 |
| echter Vorteil im ganzen Zeitraum | 16 | 5 | 5 in 38 s | alle 5 bestehen auch den Rückwärtstest (Ø +0,63 bis +1,27 R auf 351 bis 2.210 älteren Trades) |
| Vorteil nur im Suchfenster, davor keiner | 48 | 16 | 0 | 16 Kandidaten bestanden Test und Tresor (t bis 15), alle fielen im Rückwärtstest durch (Ø −0,09 bis −0,12 R) |

Die letzte Zeile zeigt Nutzen und Preis des Rückwärtstests: Er sortiert Vorteile aus, die es nur in der jüngsten Marktphase gab. Wer solche Vorteile zulassen will, schaltet das Tor mit `explore.backward_gate=false` ab. Dann wird der Champion nur markiert, und der Vorwärtstest entscheidet.

## 3. Trendfolge-Vorgaben (F3)

Zwei fest vorab festgelegte Strategien stehen als Kandidaten in der Pipeline (`research_pipeline.PRESETS`). Sie stammen nicht aus einer Suche, deshalb gibt es kein Vielfach-Test-Problem.

| Vorgabe | Regel | Als Paper-Strategie startbar |
|---|---|---|
| Trend-Basis 4h | 10-Tage-Ausbruch (Donchian 60), Stop 3 ATR, Trail 5 ATR | ja, ein Klick im Leitstand |
| Trend-Basis 1d | 20-Tage-Ausbruch (Donchian 20), Stop 2 ATR, Trail 3 ATR | nein, siehe unten |

- Beide laufen automatisch im Vorwärtstest auf neuen Daten, ohne Kapital und ohne neue Strategie in der Liste.
- Sie haben 365 Tage Zeit statt 120, weil sie selten handeln.
- Im Backtester der Website geprüft: Beide Seiten eröffnen Trades, der Trail hält Positionen über Tage, schneller und langsamer Rechenweg liefern dieselbe Trade-Zahl.
- **Tageskerzen kann der Live-Scanner noch nicht handeln.** Er hält höchstens 21 Tage Minutenkerzen im Speicher, das sind 21 Tageskerzen. Ein 20-Tage-Ausbruch braucht mehr.

Nacht-Forschung:
- Neuer erster Slot „Krypto 1h Trend“: 540 Tage, alle Krypto-Assets, nur Trend-Indikatoren, TP/SL und Trail mitoptimiert.
- Alle Slots nutzen das Ziel „t-Wert (R)“ und mindestens 60 Trades.

## 4. Mehr Lerndaten (F2)

- Richtungs-Limit der Lern-Trades (Paper, ohne Kapital) von 5 auf 10 je Klasse. In 24 Stunden standen 133 geblockte Signale 34 eröffneten Lern-Trades gegenüber.
- Ein bewusst anders gesetzter Wert bleibt erhalten.
- Auf eine eigene „virtuelle Bewertung“ jedes Signals habe ich verzichtet: Der Regel-Lern-Trade ist bereits diese Bewertung, es fehlte nur der Platz.

## 5. Behobener Fehler

`research_pipeline.adopt` las die ID der neuen Strategie aus dem Feld `strategy_id`. Die Strategie-Anlage liefert sie aber unter `id`. Folgen bisher: Der Paper-Modus wurde nie ausdrücklich gesetzt, und die Strategie erbte den globalen Modus. Zusätzlich handelte eine übernommene Strategie alle Assets, auch ungeprüfte Klassen. Jetzt:
- Der Paper-Modus wird sicher gesetzt.
- Alle Assets außerhalb der Prüfung sind für die Strategie ausgeschaltet.

Im Live-System gab es noch keinen bestandenen Kandidaten. Der Fehler hat also nie gewirkt.

## 6. Prüfung

- Neue Tests: `tests/test_f1_f3_1711.py` (22 Tests). Angepasst: Rotations- und Worker-Versions-Tests.
- Self-Test: 18 von 18 Logik-Prüfungen grün (neu: „Champions werden streng geprüft“).
- Ganze Test-Suite: 2.747 bestanden, 62 bekannte Fehlstellen (Tests, die Netz oder Datenbank brauchen), keine neue Fehlstelle gegenüber dem Stand vom 16.11.
- Frontend: 199 Dateien, 0 Syntaxfehler.

## 7. Schwierige Entscheidungen

| Nr. | Entscheidung | Was ich getan habe | Empfehlung an dich |
|---|---|---|---|
| 1 | **TrendFolge2 läuft live und verliert** (352 Live-Trades, Ø −0,13 R, t −2,4; der Leitstand meldet „verliert nachweislich“) | nichts geändert, du hattest „bleibt an“ entschieden | auf Paper stellen. Die Daten laufen weiter, es geht kein Geld mehr verloren |
| 2 | **Trend-Vorgaben: Long/Short oder nur Long?** Echte Daten: Long +0,61 R, Short ±0 R | beide Seiten gelassen. „Nur Long“ wäre eine Auswahl im Rückblick und im Bärenmarkt ungeschützt | so lassen, nach 100 Paper-Trades neu bewerten |
| 3 | **Trend-Basis 4h sofort als Paper-Strategie?** Der Vorwärtstest braucht für einen strengen Nachweis etwa 400 Trades, also über ein Jahr | nicht automatisch gestartet, nur als Ein-Klick-Empfehlung | starten. Danach im Leitstand unter „Mängel“ den Speicher beobachten: Eine 4h-Strategie hält 21 Tage Minutenkerzen je Asset |
| 4 | **Rückwärtstest als hartes Tor** | Ø R ≤ 0 bei mindestens 20 älteren Trades wirft den Champion raus | so lassen. Nachteil: Ein Vorteil, der erst seit kurzem besteht, fällt durch |
| 5 | **Versuchs-Konto je Klasse und Zeitebene** | alle Läufe der letzten 30 Tage zählen mit, auch auf anderen Coins derselben Klasse | so lassen. Es ist streng, aber Krypto-Coins bewegen sich gemeinsam |
| 6 | **Lern-Limit 10 statt „aus“** | 10 je Klasse und Richtung | so lassen. Viele gleichgerichtete Trades zur selben Zeit sind keine unabhängigen Daten |
| 7 | **Tageskerzen im Live-Handel** | nicht gebaut. Der Scanner bräuchte einen eigenen Datenweg für 4h- und Tageskerzen | als Nächstes bauen, sobald der Vorwärtstest der 1d-Vorgabe nach 30 Trades im Plus liegt |
| 8 | **Regime-Brücke** | unverändert. Der Messtest vom 16.11. zeigte keinen Nutzen | ruhen lassen, den offenen Vorschlag vom 02.11. ablehnen |
| 9 | **KI-Trader mit 1m-Signalen** (Ø −0,61 R, brutto −0,53 R) | läuft weiter im Paper-Betrieb, wie von dir gewünscht | Paper lassen. Live erst, wenn ein Setup das Live-Tor nimmt |
| 10 | **Funding als Indikator in der Suche** | nicht gebaut. Ich habe nicht geprüft, ob die vorhandenen Positionierungs-Daten für Backtests weit genug zurückreichen | zurückstellen, bis die Trend-Schiene läuft |

## 8. Nach dem Deploy

1. Worker-Paket 1.31.0 herunterladen, Worker neu starten.
2. Im Leitstand unter „Empfehlungen“: „Trend-Basis 4h“ als Paper-Strategie starten (Entscheidung 3).
3. TrendFolge2 auf Paper stellen (Entscheidung 1).
4. Den Worker über Nacht laufen lassen. Die Nacht-Forschung startet um 23 Uhr mit „Krypto 1h Trend“. Der erste Lauf lädt einmalig mehr Historie.
5. Eigene Suche: Knopf „Empfohlene Einstellungen“ (setzt jetzt Ziel t-Wert, 100 Trades, nur TP/SL).
