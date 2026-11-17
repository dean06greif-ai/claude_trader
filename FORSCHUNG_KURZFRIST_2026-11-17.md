# Forschung: schnelleres Geld neben dem Portfolio – 17.11.2026

Fragen: Ist das Portfolio ein Langzeitinvestment? Können die 64 Coins in Backtests genutzt werden?
Lohnen Backtests und Endlossuche überhaupt? Gibt es eine zweite, schnellere Methode, die kritisch
geprüft funktioniert?

## Kurzantwort

| Frage | Antwort |
|---|---|
| Ist das Portfolio Langzeit? | Nein, **mittelfristig**. Jede Trend-Position läuft im Schnitt etwa 3 Wochen, dann greift der Nachlauf-Stopp. Das Konto wird täglich neu geplant. Langfristig ist nur der Zeitraum, über den sich das Ergebnis zeigt (Monate, nicht Tage). |
| 64 Coins im Backtest? | **Ja, ab diesem Paket.** Backtester und Optimizer/Endlossuche zeigen die Gruppe „WEITERE COINS (nur Backtest)“ mit 53 Zusatz-Coins (78 insgesamt). Die Kurse kommen von Binance. Live-Scanner und Autotrader bleiben bei den 25 Website-Instrumenten. |
| Lohnen Backtests/Endlossuche? | **Ja, aber als Filter, nicht als Goldgrube.** Auf 15m/5m mit Indikator-Kombinationen findet sie fast nie etwas Echtes, und dass dort fast nichts durchkommt, ist richtig so. Auf 1h/4h/1d mit vielen Coins und strengem Rückwärtstest ist sie sinnvoll. |
| Schnellere Methode gefunden? | **Keine Richtungsstrategie hat die Prüfung überstanden.** Eine Methode funktioniert nachweislich, aber nur in Hype-Phasen: die **Funding-Ernte** (Kassa kaufen + Perp leerverkaufen). Dafür gibt es jetzt einen Wächter im Cockpit. |

## Prüfverfahren (für alle Ideen gleich)

- Daten: Binance-Kerzen und -Funding, Coins aus dem 64er-Universum.
- Drei getrennte Zeiträume: **Entdeckung** vor 2023, **Bestätigung** 2023–2024, **Holdout** ab 2025.
  Den Holdout darf nur eine Idee sehen, die vorher in Entdeckung **und** Bestätigung bestanden hat,
  und das genau einmal.
- Kosten: 0,16 % je Runde (Taker hin und zurück), bei Funding-Ideen zusätzlich der Spot-Kauf.
- t-Werte auf Korb-Ebene (alle Coins pro Tag gemittelt). Gepoolte t-Werte über Coins sind wegen der
  Gleichläufigkeit der Coins zu optimistisch.

## Ergebnisse im Einzelnen

| Idee | Ergebnis | Urteil |
|---|---|---|
| Abend-Block (bestimmte Stunden long) | Entdeckung und Bestätigung positiv, **Holdout −0,027 % je Trade** | verworfen, das war Zufall |
| Stunden-/Wochentags-Muster | wechselt das Vorzeichen zwischen den Zeiträumen | verworfen |
| Intraday-Momentum (erste Stunden → Rest des Tages) | nach Kosten negativ | verworfen |
| Crash-Kauf (nach starkem Tagesverlust kaufen) | schwach, t < 2 | nicht nutzbar, siehe Hinweis unten |
| Volumen-Ausbruch | bis 2021 gut, **seit 2022 tot** | verworfen |
| 1h-Trendfolge (Ausbruch + ATR) | etwa 0 R je Trade | verworfen, die Trendprämie liegt im Tageschart |
| Tägliches Querschnitts-Momentum (stärkste long, schwächste short) | brutto positiv, **die Kosten fressen es** | verworfen |
| BTC führt Altcoins (Lead-Lag) | negativ | verworfen |
| **Funding-Ernte** (Kassa long + Perp short, Einstieg bei Ø > 0,05 % je 8 h, Ausstieg < 0,01 %) | **+4,7 % je Episode nach Kosten, 89 % der Episoden im Plus**, aber stark phasenabhängig: 2021 +33 % im Jahr, seit 2025 nur noch ~0,5 % im Jahr | **funktioniert, nur in Hype-Phasen** → Wächter gebaut |

**Offenlegung:** Beim Crash-Kauf habe ich in einer Jahrestabelle 2025/2026 mit angesehen, bevor die
Idee Entdeckung und Bestätigung bestanden hatte. Der Holdout ist für diese Idee damit verbraucht. Eine
saubere Prüfung geht erst mit Daten ab 2027. Bis dahin gilt sie als nicht bewiesen.

## Was das bedeutet

1. **Schnelles Geld mit einer Richtungsstrategie gibt es auf Kurzfrist-Zeitebenen in diesen Daten
   nicht.** Alles, was im Backtest nach „schnell“ aussah, ist entweder im Holdout gescheitert oder an den
   Kosten. Hätte ich eines davon trotzdem eingebaut, wäre das eine Kurvenanpassung mit echtem Geld.
2. **Die Trendprämie liegt im Tageschart.** Genau die nutzt das Portfolio, verteilt auf viele Coins und
   mit festem Risiko je Trade. Daran ändert dieser Tag nichts, er bestätigt es.
3. **Die Funding-Ernte ist die einzige zweite Ertragsquelle, die geprüft hält.** Sie ist marktneutral,
   also unabhängig von der Kursrichtung, aber selten ergiebig. In ruhigen Phasen wie seit 2025 bringt sie
   fast nichts. Wenn der Markt wieder heiß läuft (Funding über 0,05 % je 8 h), kann sie in wenigen Wochen
   mehrere Prozent auf das eingesetzte Kapital bringen, mit geringem Kursrisiko.

## Was gebaut wurde

- **Zusatz-Coins für Backtests** (`backend/core/instruments.py`: `RESEARCH_CRYPTO`, `RESEARCH_SYMBOLS`,
  `BACKTEST_SYMBOLS`, `research_groups()`; `/api/coins` liefert `backtest_coins` und `research_groups`).
  Im Backtester und Optimizer erscheint die Gruppe mit dem Knopf „alle wählen“. Ein Tooltip weist darauf
  hin, dass die Coins nicht im Live-Scanner laufen. Die Übernahme-Auswahl „Live/Paper anwenden“ zeigt
  weiterhin nur Website-Instrumente.
- **Übernahme-Schutz:** Ein Kandidat, der nur auf Zusatz-Coins geprüft wurde, lässt sich nicht
  übernehmen (klare Fehlermeldung). Wurde er auch auf Website-Coins geprüft, wird er nur für diese
  übernommen.
- **Funding-Ernte-Wächter im Cockpit** (`services/cockpit.py`: `funding_harvest`, `rec_harvest`): nutzt
  die täglichen Funding-Summen, die das Portfolio ohnehin lädt (`portfolio_funding`). Liegt ein Coin
  3 Tage im Schnitt über 0,15 % je Tag, erscheint die Empfehlung „Funding-Ernte möglich“ mit Coin,
  Jahreswert und Anleitung. **Es wird nichts automatisch gehandelt**, weil der Kassa-Handel nicht
  angebunden ist.
- Tests: `tests/test_research_1711.py` (4, darunter ein kompletter Backtest-Lauf auf einem Zusatz-Coin),
  `tests/test_instruments_universe.py` angepasst.

## Endlossuche: so ist sie sinnvoll

- **Zeitebene 1h, 4h oder 1d**, nicht 5m/15m. Auf kurzen Zeitebenen fressen die Kosten fast jede Kante.
- **Viele Coins gleichzeitig** (jetzt bis 78). Eine Regel, die auf 40 Coins hält, ist viel glaubwürdiger
  als eine, die auf 3 Coins glänzt.
- **Ziel „t_r“** (Stabilität je Trade) statt Gewinn in USDT, mindestens 60 Trades, Rückwärtstest an.
- Ergebnis „0 Champions“ ist ein **gutes** Zeichen dafür, dass der Filter funktioniert, und kein Fehler.
- Die Nachtforschung bleibt bei den Website-Coins, damit ihre Funde direkt übernommen werden können.

## Realistische Wege zu mehr Geld (ehrlich)

| Hebel | Wirkung | Risiko |
|---|---|---|
| Kapital im Portfolio erhöhen, sobald der Paper-/Probe-Verlauf hält | Rendite skaliert linear, bei 130 USDT sind es kleine Beträge | gleich |
| Gewinne stehen lassen (Zinseszins) | bei 15–30 % im Jahr (vorsichtig) verdoppelt sich das Konto in etwa 2,5 bis 5 Jahren | gleich |
| Risikostufe „normal“ | Erwartung 25–50 % im Jahr | Rückgänge 25–40 % |
| Funding-Ernte in Hype-Phasen | einige Prozent je Episode auf das eingesetzte Kapital | gering (marktneutral), Börsenrisiko bleibt |
| Kurzfrist-Strategien | nicht empfohlen, keine hat die Prüfung überstanden | hoch |

Schnell und sicher zugleich gibt es nicht. Wer das verspricht, verkauft eine Rückrechnung.
