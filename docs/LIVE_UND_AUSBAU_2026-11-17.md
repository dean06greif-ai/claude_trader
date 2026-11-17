# Live-Ausführung und größeres Portfolio (17.11.2026, Nachmittag)

Paket `eigen-zip-live-2026-11-17.zip`. Enthält alles aus den Paketen davor.

## Kurzfassung

1. **Nicht 8 Wochen warten:** Das Portfolio kann ab sofort mit kleinem Geld live auf Bitunix handeln. Jede Position bekommt sofort ihren Stop an der Börse, und ein Not-Aus stoppt neue Einstiege ab einem festgelegten Verlust.
2. **Mehr Coins, besserer Vorteil:** Das Portfolio handelt jetzt 64 statt 26 Coins, bis zu 20 Positionen, und der Funding-Korb hat 8 statt 5 Coins je Seite. In der Rückrechnung steigt der Sharpe von 1,47 auf 1,81, seit 2025 der Ertrag von +17 auf +32 % pro Jahr.
3. **Unabhängige Bestätigung:** Die 38 neuen Coins plus 6 tote Coins (LUNA, FTT, MATIC, EOS, WAVES, XMR) allein ergeben Sharpe 1,40. Die Regel funktioniert also auch auf Coins, die nicht zur Entwicklung benutzt wurden.
4. **Zukunftsrechner** im Reiter „Portfolio“ mit drei ehrlichen Szenarien.

## 1. Warum jetzt live, und wie sicher

Du hattest recht: Live ist immer anders als Paper. Die Rückrechnung belegt die Regel über 7 Jahre. Was sie nicht belegt, ist die Ausführung:

| Was nur live sichtbar wird | Wie die Website es misst |
|---|---|
| Füllpreis gegenüber dem Kurs bei der Entscheidung | Abweichung je Order, Durchschnitt im Reiter |
| Mindestmengen und Mengenschritte von Bitunix | werden vor jeder Order geprüft, übersprungene Orders mit Grund |
| Funding auf Bitunix statt Binance | im Ergebnis je Position (netto laut Börse) |
| Stop am Mark-Preis | Stop-Auslösung live gegenüber Paper |

Die Schutzregeln:

- **Probelauf ist Standard.** Die Website plant jede Order und zeigt sie an, sendet aber nichts. Live startet erst, wenn du „LIVE“ eintippst.
- **Stop sofort an der Börse.** Wird er nicht bestätigt, schließt die Website die Position sofort wieder; nie liegt etwas ungeschützt. Stündlich prüft sie, ob alle Stops noch stehen, und setzt fehlende neu.
- **Hebel klein:** höchstens 5×, und so gewählt, dass die Liquidation mindestens doppelt so weit entfernt ist wie der Stop. Liegt die Liquidation trotzdem vor dem Stop, wird die Position sofort geschlossen.
- **Funding-Korb:** Hebel 3× und ein Katastrophen-Stop bei 25 %.
- **Keine stille Vergrößerung:** Der Bitunix-Client hebt zu kleine Mengen sonst stillschweigend auf die Mindestmenge an. Die Live-Ausführung rundet höchstens auf das Doppelte des geplanten Risikos auf und überspringt sonst.
- **Not-Aus:** Ab einem Verlust von 30 % des Live-Kapitals (einstellbar) gibt es keine neuen Einstiege mehr. Stops und Ausstiege laufen weiter. Zusätzlich gibt es den Knopf „Not-Aus: alles schließen“, der nur mit Eingabe von „ALLES SCHLIESSEN“ wirkt.
- **Keine Vermischung:** Der Positions-Wächter lässt Portfolio-Positionen in Ruhe. Der Autotrader eröffnet live nichts auf einer Seite, die das Portfolio hält. Das Portfolio eröffnet nichts auf einer Seite, auf der eine fremde Position liegt.
- **Kein Nachkauf von weit gelaufenen Positionen:** Positionen, die im Paper-Konto schon laufen, kauft die Website live nur nach, solange sie höchstens 0,5 R gelaufen sind. Sonst wartet sie auf neue Ausbrüche.

### Was heute mit deinem Konto passieren würde

Gerechnet mit deinem echten Paper-Stand vom 17.11. und den echten Bitunix-Mindestmengen, 130 USDT Live-Kapital:

- **Trend:** keine Order. Alle 12 Short-Positionen sind schon 1,6 bis 7,7 R gelaufen, die Kurse liegen 15 bis 35 % unter dem Einstieg. Neue Trend-Positionen kommen mit den nächsten Ausbrüchen.
- **Funding-Korb:** 6 Legs zu je etwa 6 USDT, 3× Hebel, zusammen rund 14 USDT Margin. TRX und BCH liegen unter der Mindestmenge und werden übersprungen.

Mit 130 USDT misst der Live-Betrieb vor allem die Ausführung. Er verdient kaum etwas, kostet bei einem Fehler aber auch kaum etwas. Ab etwa 500 USDT werden fast alle Orders handelbar.

Diese Rechnung entstand mit dem Code vor dem Wechsel auf 64 Coins und 8 Coins je Seite; nach dem Deploy sieht der Plan anders aus. Der Probelauf zeigt ihn dann genau.

## 2. Das größere Portfolio

| Aufstellung (Stufe „Vorsichtig“, 0,25 % Risiko je Trade) | Pro Jahr | Sharpe | Größter Rückgang | Seit 2025 pro Jahr |
|---|---|---|---|---|
| Bisher: 26 Coins, 12 Positionen, Korb 5 je Seite | +31 % | 1,47 | 19 % | +17 % |
| **Neu: 64 Coins, 20 Positionen, Korb 8 je Seite** | **+52 %** | **1,81** | **19 %** | **+32 %** |
| Neu, aber mit den 6 toten Coins | +50 % | 1,72 | 22 % | +31 % |
| Nur die 44 neuen Coins (unabhängiger Test) | +30 % | 1,40 | 33 % | +31 % |

Jahre bei „Vorsichtig“ (neu): 2020 +62 %, 2021 +193 %, 2022 +17 %, 2023 +50 %, 2024 +32 %, 2025 +32 %, 2026 +26 % (bis 16.11.). Die längste Durststrecke dauerte 262 Tage.

### Belastungstests (neue Aufstellung, mit den toten Coins)

| Abwandlung | Pro Jahr | Sharpe | Rückgang |
|---|---|---|---|
| Doppelte Kosten | +45 % | 1,60 | 24 % |
| Dreifache Kosten | +41 % | 1,49 | 25 % |
| Start erst 2022 (Bärenmarkt) | +28 % | 1,19 | 22 % |
| Start erst 2024 | +33 % | 1,34 | 22 % |
| Ausbruch 10 / 30 / 55 Tage | +49 / +45 / +35 % | 1,71 / 1,58 / 1,36 | 23 / 25 / 25 % |
| Höchstens 15 Positionen | +42 % | 1,74 | 20 % |
| Korb 5 / 10 je Seite | +44 / +47 % | 1,49 / 1,68 | 29 / 22 % |
| Nur Trend | +37 % | 1,46 | 19 % |
| Nur Funding-Korb | +10 % | 0,88 | 26 % |

Keine Abwandlung kippt ins Minus.

### Die anderen Stufen

| Stufe | Risiko je Trade | Pro Jahr | Größter Rückgang | Seit 2025 |
|---|---|---|---|---|
| Vorsichtig | 0,25 % | +52 % | 19 % | +32 % |
| Normal | 0,5 % | +97 % | 33 % | +46 % |
| Offensiv | 1 % | +195 % | 56 % | +71 % |

„Normal“ und „Offensiv“ sehen durch 2021 spektakulär aus. Ein Rückgang von 56 % heißt aber: Aus 10.000 werden zwischendurch 4.400. Meine Empfehlung bleibt „Vorsichtig“.

### Ehrliche Erwartung

Die Rückrechnung ist geschönt: Ich habe die Aufstellung (20 Positionen, 8 je Seite) nach dem Blick auf die Ergebnisse gewählt, und 2021 war ein Ausnahmejahr. Realistisch für „Vorsichtig“ sind **15 bis 30 % pro Jahr**, mit Rückgängen von 15 bis 25 % und Durststrecken von bis zu 9 Monaten.

Was das heißt (Zukunftsrechner, 1.000 USDT Start, 100 USDT im Monat, 18 % pro Jahr): nach 5 Jahren etwa 11.600 USDT, davon 7.000 eingezahlt. Reich wird man damit über Zeit und Kapital, nicht über Nacht.

## 3. Weitere Änderungen

- **Mengenschritt:** Bei BTC ist ein Mengenschritt etwa 7 USDT groß, Abrunden kostete dort bis zu 45 % des geplanten Risikos. Die Live-Ausführung rundet jetzt auf den nächstgelegenen Schritt.
- **Delistete Coins:** Hat ein Coin länger als 3 Tage keine Kurse mehr, schließt das Portfolio seine Position zum letzten Kurs, statt sie ewig offen zu halten.
- **Ursprünglicher Stop:** Das Portfolio speichert jetzt für jede Position den ersten Stop. Die Live-Ausführung braucht ihn für die Regel „höchstens 0,5 R gelaufen“.
- **Migration:** Eine gespeicherte Liste mit genau den alten 26 Coins wird auf 64 erweitert; eine eigene Auswahl bleibt. Durch den Wechsel startet der Paper-Verlauf neu. Der erste Lauf lädt Kurse und Funding für 38 neue Coins und dauert einige Minuten länger.
- **Systemarzt:** meldet Not-Aus, fehlgeschlagene Orders und eine ausbleibende Live-Prüfung.
- **Meldungen:** neuer Schalter „Portfolio live“ für ausgeführte Orders, Stopps und Not-Aus.

## 4. Prüfung

- 19 neue Tests für die Live-Ausführung gegen eine nachgebaute Börse. Sie prüfen unter anderem: Probelauf sendet nichts, Stop wird gesetzt und nachgelesen, ohne Stop wird sofort geschlossen, Liquidation vor dem Stop führt zum Schließen, Stop nachziehen, Stopp an der Börse ohne Wiedereinstieg, Not-Aus, Not-Aus von Hand, fehlender Stop wird stündlich ersetzt.
- 3 neue Tests im Rechenkern (Delisting, Universum, Migration).
- Self-Test: 20 von 20 (neu: Live-Ausführung).
- Frontend: Syntax-Prüfung ohne Fehler, Render-Test der neuen Bereiche.
- **Nicht prüfbar von hier:** echte Orders an Bitunix. Die Live-Ausführung nutzt nur die Börsen-Aufrufe, die der Autotrader seit Monaten live verwendet. Der Probelauf zeigt vor dem Start jede Order.

## 5. Schwierige Entscheidungen

| Nr. | Thema | Entscheidung | Warum / Risiko |
|---|---|---|---|
| 1 | Live vor 8 Wochen Paper | ja, aber Probelauf als Standard; Live nur nach Eingabe von „LIVE“ | Live-Daten sind der schnellste Weg zu belastbaren Ergebnissen. Das Risiko ist durch kleines Kapital, Stop an der Börse und Not-Aus begrenzt. |
| 2 | Risiko je Trade live | Standard 1 % (statt 0,25 % im Paper-Konto) | Mit 130 USDT wären 0,25 % fast immer unter der Mindestmenge. 1 % von 130 USDT sind 1,30 USDT je Trade. |
| 3 | Not-Aus-Grenze | 30 % des Live-Kapitals | Die Rückrechnung hatte bei 1 % Risiko Rückgänge bis 56 %. 30 % stoppt früher, kann also auch in einer normalen Durststrecke auslösen. Dann „Not-Aus lösen“ oder die Grenze anheben. |
| 4 | Laufende Paper-Positionen live nachkaufen | nur bis 0,5 R gelaufen | Späte Einstiege sind eine andere Wette als ein Ausbruch. Heute wird deshalb keine der 12 Shorts gekauft. |
| 5 | Universum 64 statt 26 Coins | übernommen | Unabhängige Bestätigung auf den neuen Coins (Sharpe 1,40) und mehr Streuung. Nachteil: Ich habe 20 Positionen und 8 je Seite nach Blick auf die Ergebnisse gewählt. Die Belastungstests zeigen aber, dass auch 15 Positionen oder 10 je Seite gut abschneiden. |
| 6 | Klima-Filter, Nur-Long | weiter aus | Im Portfolio schlechter (siehe Bericht vom Vormittag). |
| 7 | Fremde Position auf derselben Seite an der Börse | Portfolio überspringt die Order | Sonst würden sich die Positionen an der Börse vermischen. |
| 8 | Maker-Orders (geringere Gebühr) | nicht gebaut | Auf Tagesebene machen Gebühren wenig aus (dreifache Kosten: Sharpe immer noch 1,49). Market-Orders sind dagegen sicher gefüllt. |

## 6. Nach dem Deploy

1. Reiter „Portfolio“ öffnen und warten, bis der Lauf mit 64 Coins fertig ist (einige Minuten).
2. Unter „Live-Ausführung“ das Live-Kapital eintragen (zum Beispiel 100 USDT) und „Plan jetzt berechnen“ drücken.
3. Den Plan prüfen. Passt er, „Live starten“ drücken und „LIVE“ eintippen.
4. Die Meldung „Portfolio live“ in den Benachrichtigungen anlassen.
5. Nach 4 bis 6 Wochen Live-Betrieb: Abweichung beim Einstieg und Ergebnis mit dem Paper-Konto vergleichen. Passt beides, das Live-Kapital schrittweise erhöhen.
