# Was soll traden? Zusammenspiel der Bausteine – Stand 17.11.2026 (Abend)

Datenbasis: Produktion (nur lesend), 1.454 geschlossene Trades; Portfolio-Rückrechnung auf
Binance-Tagesdaten der 64 Coins bis 17.11.

## Bilanz je Baustein (echte Trades)

| Baustein | Trades | Ergebnis | Urteil |
|---|---|---|---|
| Portfolio (Trend + Funding-Korb, Rückrechnung) | 1.825 Trend-Trades seit 2020 | vorsichtig: +52 % p. a., Rückgang 19 %; seit 2025 +32 % p. a. | **einziger Baustein mit belegtem Vorteil** |
| KI-Trader (Detektoren + KI-Prüfer) | 868, alle Paper | −0,33 R je Trade; seit 16.11. −0,20 R | Messlabor, kein Geldverdiener |
| TrendFolge2 (statisch, live) | 352 live | −0,13 R, −89 USDT; seit November −0,45 R | vom Live-Wächter gestoppt (letzter Live-Trade 06.11.) |
| Weitere statische Live-Strategien | 43 | zusammen −46 USDT | zu wenig Trades für ein Urteil |
| **Trades außerhalb der Website auf Bitunix („external“)** | 30 | **−1.088 USDT** (davon 188 USDT Gebühren), Hebel 34–109× | **größter Verlustposten von allen** |
| Regime-Lab / Regime-Brücke | 0 Trades | kein Nutzen nachgewiesen (Analysen 15./16./17.11.) | eingefroren, nur Anzeige |

## Empfohlene Rollen

1. **Portfolio = Kern.** Kapital gehört hierhin, zuerst im Probelauf, dann live mit kleinem
   Betrag.
2. **KI-Trader = Messlabor (Paper).** Seit dem Fix vom 17.11. wird messbar, ob die KI-Prüfung
   bessere Trades auswählt. Live erst, wenn die Reife-Regel greift: 30 KI-geprüfte Trades und
   statistische Untergrenze über 0.
3. **Statische Strategien** nur, wenn sie den Live-Wächter bestehen. Viele Strategien ohne
   Vorteil ergeben zusammen keinen Vorteil, nur mehr Gebühren.
4. **Regime** bleibt Anzeige und Kontext. Ein Filter kommt erst, wenn ein Messtest auf
   ungesehenen Trades Nutzen zeigt.
5. **Endlossuche/Nachtsuche** läuft automatisch. Manuelle Backtests lohnen nur für eine
   konkrete Idee.

## Was das Portfolio gerade hält (Rückrechnung, vorsichtig)

- **19 Trend-Positionen, alle Short**, eröffnet zwischen 07.10. und 03.11. nach 20-Tage-Tiefs.
  Alle im Plus (+0,65 bis +2,4 R), Kurs −15 bis −35 % seit Einstieg. Die Stopps laufen nach und
  liegen 13–32 % über dem Kurs.
- **Funding-Korb:** long XTZ, COMP, WLD, SAND, RUNE, VET, BCH, JUP (niedrigstes Funding), short
  XRP, SNX, TAO, DYDX, PENDLE, NEAR, EGLD, KAVA (höchstes Funding). Marktneutral, kassiert
  Funding, wird wöchentlich neu gebildet.
- **Typisches Muster:** viele kleine Verluste von −1 R und wenige große Gewinne (letzte 30 Tage:
  NEAR long +8,2 R, STX long +7,7 R). Haltedauer im Median 17 Tage.
- Im Probelauf/Live werden weit gelaufene Positionen nicht nachgekauft (Regel „später Einstieg
  nur bis +0,5 R“). Es kommen nur neue Ausbrüche und der Korb dazu.

## Einstellungen (geprüft, 17.11.)

| Bereich | Stand | Änderung |
|---|---|---|
| Haupt-Modell (Setup „KI-Modell“) | Gemini 3.5 Flash (kostenlos) | richtig: nur Ersatz, jede Rolle hat ihr eigenes Modell |
| KI-Team-Anzeige | zeigte „Haupt-Modell (erben)“/„keine“ bei Luna Pro, Haiku, DeepSeek V4.1 | Anzeige-Fehler behoben (Modelle fehlten in der Frontend-Liste); das Backend nutzte immer die richtigen Modelle |
| Analyse-Intervall | 10 min | im Prüfer-Modus ohne Wirkung; jetzt so beschriftet |
| Nachtsuche | 6 Slots rundum, davon Forex 1h, Rohstoffe/Indizes 1h, Krypto 5m | nur noch Krypto 1h Trend → Krypto 1h → Krypto 15m. „Live nur Krypto“ ist an, Funde außerhalb von Krypto könnten nie live gehen; auf 5m fressen die Gebühren den Vorteil |
| Optimizer „Empfohlene Einstellungen“ | 15m, 180 Tage | 1h, 365 Tage, Ziel t-Wert, 100 Trades, 15–30 Krypto-Coins |
| Übrige KI-Trader-Einstellungen (Fee-Wächter, Mindest-SL, Edge-Filter, Live nur Krypto, Prüfer) | passen zu den Befunden | unverändert |

## Risiko-Stufe statt Hebel (Rückrechnung, 64 Coins, Stand 17.11.)

Die Positionsgröße richtet sich nach dem Stop: Ein Stop-Treffer kostet genau das eingestellte
Risiko je Trade. Der Hebel bestimmt nur die gebundene Marge. Mehr Ertrag gibt es nur über mehr
Risiko je Trade, und der Sharpe (Ertrag je Schwankung) bleibt dabei gleich.

| Risiko je Trade | ab 2025: Ertrag p. a. | ab 2025: größter Rückgang | 2020–2026: größter Rückgang |
|---|---|---|---|
| 0,25 % (vorsichtig) | +32 % | 15 % | 19 % |
| 0,5 % (normal) | +46 % | 26 % | 33 % |
| 0,75 % | +59 % | 36 % | 46 % |
| 1,0 % (offensiv) | +71 % | 44 % | 56 % |
| 1,5 % | +88 % | 57 % | 72 % |
| 2,0 % | +84 % | 67 % | 85 % |

- Ab etwa 1,5 % steigt der Ertrag nicht mehr, nur noch der Rückgang (Volatilitäts-Bremse).
- Das Live-Modul rechnet mit 1 % des Live-Kapitals, weil kleinere Beträge unter die
  Mindest-Ordergrößen fallen. Die Not-Aus-Grenze von 30 % kann bei dieser Stufe schon in einer
  normalen Durststrecke auslösen.
