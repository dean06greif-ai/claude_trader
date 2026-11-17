# Portfolio: die Handels-Schiene auf Tagesebene (17.11.2026)

Paket `eigen-zip-portfolio-2026-11-17.zip`. Enthält alles aus den Paketen davor.

## Worum es geht

Alles, was die Website bisher handelt, arbeitet auf Minuten- bis Stundenebene und verliert nach Kosten. Die Messungen auf echten Daten zeigen den Vorteil an anderer Stelle: auf Tageskerzen. Dort konnte die Website bisher nicht handeln, weil der Scanner höchstens 21 Tage Minutenkerzen hält.

Neu ist deshalb ein eigenes **Portfolio** mit eigenem Datenweg und eigener Buchführung. Es steht im Leitstand im Reiter „Portfolio“.

| Baustein | Regel |
|---|---|
| Trend | Schließt ein Coin über seinem 20-Tage-Hoch, wird gekauft; unter dem 20-Tage-Tief wird leerverkauft. Stop 2 ATR, im Gewinn nachgezogen mit 3 ATR. Jeder Trade riskiert denselben Anteil des Kontos. Höchstens 12 Positionen. |
| Funding-Korb | Einmal pro Woche die 5 Coins mit dem niedrigsten Funding kaufen und die 5 mit dem höchsten leerverkaufen, mit gleichem Betrag je Seite (zusammen 50 % des Kontos). Unabhängig von der Marktrichtung. |

Universum: 26 liquide Coins (BTC, ETH, SOL, BNB, XRP, DOGE, ADA, AVAX, DOT, LINK, LTC, TRX, ATOM, NEAR, UNI, ETC, XLM, BCH, FIL, APT, SUI, ARB, OP, INJ, AAVE, HBAR).

## Was die Rückrechnung zeigt

Zeitraum 01/2020 bis 16.11.2026, echte Binance-Tageskerzen und echte Funding-Sätze, Gebühren 0,06 % plus 0,02 % Slippage je Seite, Startkonto 10.000 USDT.

| Risiko-Stufe | Risiko je Trade | Pro Jahr | Größter Rückgang | Seit 2025 pro Jahr | Rückgang seit 2025 |
|---|---|---|---|---|---|
| Vorsichtig (Standard) | 0,25 % | +31 % | 19 % | +17 % | 17 % |
| Normal | 0,5 % | +53 % | 29 % | +22 % | 29 % |
| Offensiv | 1 % | +97 % | 49 % | +26 % | 49 % |

Jahre bei „Normal“: 2020 +44 %, 2021 +252 %, 2022 +6 %, 2023 +54 %, 2024 +59 %, 2025 +7 %, 2026 +33 % (bis 16.11.). Kein Jahr im Minus.

Zerlegung bei „Normal“:
- Nur Trend: +43 % pro Jahr, Sharpe 1,35. Seit 2025 nur +10 % pro Jahr.
- Nur Funding-Korb: +8,5 % pro Jahr, Sharpe 0,75. Seit 2025 +11,5 % pro Jahr bei 7 % Rückgang.
- Zusammen: Sharpe 1,51. Der Funding-Korb trägt genau dann, wenn der Trend schwach ist (2025).

### Wie belastbar ist das?

Jede dieser Abwandlungen blieb im Plus (Sharpe über den ganzen Zeitraum / seit 2025):

| Abwandlung | Sharpe gesamt | Sharpe seit 2025 |
|---|---|---|
| Standard | 1,51 | 0,95 |
| Ausbruch 10 / 30 / 55 Tage | 1,41 / 1,30 / 1,06 | 1,19 / 0,89 / 1,06 |
| Nachgezogener Stop 4 ATR | 1,30 | 0,65 |
| Höchstens 8 / 20 Positionen | 1,44 / 1,26 | 1,13 / 0,75 |
| Doppelte Kosten | 1,42 | 0,81 |
| Start erst 2022 / 2023 | 1,09 / 1,27 | 0,95 |
| Nur die 11 Coins der Website | 1,41 | 0,65 |

Der Vorteil hängt also nicht an einer Einstellung und nicht am Ausnahmejahr 2021.

### Was die Rückrechnung schönt

- **Auswahl der Coins:** Es zählen nur Coins, die es heute noch gibt. Gescheiterte Coins fehlen.
- **2021** war ein Ausnahmejahr und trägt den Durchschnitt stark.
- **Ausführung:** Gerechnet wird zum Tagesschluss. Echte Aufträge treffen diesen Kurs nicht genau.
- **Funding** stammt von Binance; auf Bitunix weicht es ab.

Realistische Erwartung für die Zukunft bei „Vorsichtig“: 8 bis 18 % pro Jahr, mit Rückgängen von 15 bis 25 % und Durststrecken bis zu einem Jahr. Die längste Durststrecke in der Rückrechnung dauerte 324 Tage; 42 von 100 Monatsabschnitten waren im Minus.

### Zwei geprüfte und verworfene Ideen

- **Klima-Filter** (Long nur, wenn BTC über dem 200-Tage-Schnitt liegt, Short nur darunter): Bei einzelnen Trades sah er gut aus (+0,49 R mit dem Klima gegen +0,13 R dagegen). Im Portfolio war er ein Verlust: Sharpe 1,27 mit Filter gegen 1,51 ohne, größter Rückgang 36 % statt 29 %. Das Portfolio handelt ohne ihn.
- **Nur Long:** Sharpe 1,47 statt 1,51, seit 2025 aber nur 0,62 statt 0,95. Beide Seiten bleiben.

## Wie es läuft

- Jeden Tag kurz nach dem Tagesschluss (01:00 Uhr deutscher Zeit, im Sommer 02:00) lädt die Website die neue Tageskerze und rechnet den gesamten Verlauf neu.
- Der Stand von heute ist das Ende dieser Rechnung. Es gibt keinen versteckten Zustand: gleiche Daten und gleiche Einstellungen ergeben immer dasselbe Ergebnis.
- Das Portfolio läuft als **Paper-Konto**. Es schickt keinen Auftrag an die Börse.
- Der **Tagesplan** nennt jede Order mit Größe und Stop. Er kommt auch als Benachrichtigung (Schalter „Portfolio-Tagesplan“).
- Der erste Lauf lädt die Daten seit 2020 und dauert einige Minuten.
- Fehlen Funding-Daten, pausiert nur der Funding-Korb; der Trend-Teil läuft weiter.

Einstellbar im Reiter: Risiko-Stufe, Kontogröße, Trend und Funding-Korb einzeln. Die Kontogröße ändert nur die Beträge. Eine andere Risiko-Stufe startet den Paper-Verlauf neu.

## Prüfung

- **Zwei unabhängige Rechnungen:** Der Rechenkern (Python) und ein Nachbau im Browser (JavaScript) kamen auf identischen Kunstdaten auf den Cent auf dasselbe Ergebnis (27.009,08 USDT, 259 Trades). Die Zahlen oben stammen aus dem Nachbau auf echten Daten.
- **Kein Blick in die Zukunft:** Spätere Daten ändern den früheren Verlauf nicht (Test und Self-Test).
- 18 neue Tests in `tests/test_portfolio_1711.py`, Self-Test 19 von 19.
- Nicht prüfbar von hier: die Abrufe im Live-Betrieb (Binance-Archiv, OKX als Ersatz). Der Systemarzt meldet, wenn der Lauf fehlschlägt oder veraltet.

## Weg zum Echtgeld

1. **Jetzt:** Paper-Konto läuft automatisch. Wer will, handelt den Tagesplan von Hand nach.
2. **Nach 8 Wochen:** Paper-Verlauf mit der Rückrechnung vergleichen. Weichen sie nicht auseinander, ist der Datenweg belegt.
3. **Dann:** automatische Ausführung auf Bitunix bauen und mit einer Kleinst-Order unter Aufsicht testen. Das ist bewusst noch nicht gebaut: Auftrags-Code für Echtgeld lässt sich von hier nicht gegen die Börse testen.

## Dateien

| Datei | Inhalt |
|---|---|
| `backend/services/portfolio_core.py` | Rechenkern (rein, nur Standardbibliothek) |
| `backend/services/portfolio_engine.py` | Daten laden, Lauf, Stand, Tagesplan, Benachrichtigung |
| `backend/routers/cockpit.py` | `/api/portfolio`, `/api/portfolio/refresh`, `/api/portfolio/config` |
| `backend/services/autonomy_loop.py` | Takt „portfolio“ (alle 15 Minuten prüfen, einmal je Tag rechnen) |
| `backend/services/system_doctor.py` | Prüfung „Portfolio“ |
| `frontend/src/components/PortfolioSection.js` | Reiter „Portfolio“ |
