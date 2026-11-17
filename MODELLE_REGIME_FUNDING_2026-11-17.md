# KI-Modelle, Regime, Funding und andere Vorteils-Quellen (17.11.2026)

Gehört zum Paket `eigen-zip-portfolio-2026-11-17.zip`. Das Portfolio selbst steht in `PORTFOLIO_2026-11-17.md`.

## 1. KI-Modelle je Aufgabe (Aufgaben-Team v2)

Grundlage der Entscheidung:
- **Verbrauch in Produktion (16.11.):** 5,4 Mio. Tokens am Tag, davon 4,6 Mio. beim Prüfer (Rolle „Analyst“).
- **Fehlerbild in Produktion:** `gpt-oss-20b` scheiterte am 16.11. beim Markt-Beobachter an der JSON-Prüfung; die Rolle lief an dem Tag über die Ausweich-Stufe `gpt-oss-120b`. An vier von fünf Tagen entschied ein Gratis-Modell die Prüfungen.
- **Preise:** aktuelle OpenRouter-Liste vom 17.11.
- **Vergleiche:** unabhängige Tests sehen Claude Haiku 5.5 bei gleichem Preis vor GPT-6 Luna und DeepSeek V4.1 Flash knapp vor GPT-6 Luna.

| Rolle | Modell | Ausweich-Stufe 1 | Ausweich-Stufe 2 | Begründung |
|---|---|---|---|---|
| Prüfer (Analyst) | GPT-6 Luna Pro (0,10 / 0,50 $) | Claude Haiku 5.5 (gleicher Preis) | Gemini 3.5 Flash | 85 % aller Tokens, läuft seit 16.11. fehlerfrei. Stufe 1 ist jetzt kein Gratis-Modell mehr. |
| Tiefen-Analyst | Nemotron 3 Ultra (gratis) | DeepSeek V4 Pro | Gemini 3.6 Flash | unverändert, wenige Läufe, stabil |
| Forschungs-Analyst | DeepSeek V4.1 Flash (0,14 / 0,42 $) | Nemotron 3.5 (gratis) | Gemini 3.5 Flash | wenig Volumen, Urteil zählt |
| Markt-Beobachter | gpt-oss-120b (Groq, gratis) | Gemini 3.1 Flash-Lite | Gemma 4 (gratis) | 20b scheiterte an JSON |
| Trade-Manager | DeepSeek V4 Flash (0,09 / 0,18 $) | gpt-oss-120b | Gemini 3.5 Flash | unverändert, bewährt |
| News-Wächter | Ministral 8B (gratis) | gpt-oss-120b | Gemini 3.1 Flash-Lite | Ausweich-Stufe ohne 20b |
| Lerner | DeepSeek V4.1 Flash | Nemotron 3 Ultra (gratis) | Gemini 3.1 Pro | Lektionen wirken dauerhaft |
| Chat, Zusammenfasser | unverändert | | | gratis |

**Hauptmodell:** bleibt Gemini 3.5 Flash (gratis). Es wirkt nur als Rückfall, wenn eine Rolle kein eigenes Modell hat. Die Entscheidungen trifft der Prüfer.

**Kosten:** etwa 0,65 $ am Tag, rund 20 $ im Monat. Ein Flaggschiff-Modell beim Prüfer würde etwa 140 $ im Monat kosten. Das lohnt nicht, solange die KI-Auswahl keinen messbaren Mehrwert zeigt.

**Hinweis:** Das OpenRouter-Guthaben stand am 16.11. bei 9,19 $ (Hauptschlüssel) plus 10 $ (Ersatz). Das reicht für etwa vier Wochen.

## 2. Regime-Erkennung

Die bestehende Erkennung arbeitet je Coin auf Stundenkerzen der letzten 30 Tage. Geprüft habe ich, ob ein langsames, marktweites Regime hilft („Markt-Klima“: BTC über oder unter dem 200-Tage-Schnitt, Schwankung hoch oder normal).

| Messung auf echten Daten (1.625 Ausbruchs-Trades) | mit dem Klima | gegen das Klima |
|---|---|---|
| alle Jahre | +0,49 R | +0,13 R |
| bis 2022 | +0,61 R | +0,28 R |
| 2023–24 | +0,66 R | +0,26 R |
| seit 2025 | +0,10 R | −0,25 R |

Auf Einzel-Trade-Ebene hilft das Klima also in allen drei Abschnitten. **Im Portfolio hilft es nicht:** Mit begrenzter Positionszahl nimmt das Portfolio ohnehin die stärksten Ausbrüche, und der Filter kostet dort Ertrag (Sharpe 1,27 mit, 1,51 ohne).

Folge:
- Das Markt-Klima ist als **Anzeige und Messung** gebaut (`services/market_climate.py`), nicht als Filter.
- Der Leitstand zeigt unter „Fortschritt“ das aktuelle Klima und die Bilanz der eigenen Krypto-Trades mit und gegen das Klima.
- Ein Filter folgt nur, wenn die eigenen Trades ihn stützen (mindestens 50 Trades je Gruppe).
- Die Regime-Brücke bleibt unverändert und ohne Freigabe.

## 3. Funding

Das System hatte bereits eine Funding-Historie (Binance-Archiv), sie wurde aber nur in zwei Strategien genutzt.

| Messung (26 Coins seit 2020) | Ergebnis |
|---|---|
| Sehr heißes Funding (≥ 0,05 % je 8 h), Kurs der nächsten 3 Tage | +2,4 % (2.851 Fälle). Ein Short gegen die Menge verlor im Schnitt. |
| Sehr negatives Funding (≤ −0,05 % je 8 h), nächste 3 Tage | +1,9 % (699 Fälle). Der Long gegen die Menge wurde bestätigt. |
| Funding im Vergleich zur eigenen Vergangenheit (oberste 10 %) | kein Unterschied zum Markt |
| Funding im Vergleich der Coins untereinander (Korb, voller Einsatz) | +22 % pro Jahr, Sharpe 0,92, in allen drei Zeitabschnitten im Plus, Rückgang bis 36 % |

Folgen:
- Das Setup `funding_fade` bekommt die Bilanz in den Prompt: Die Short-Seite ist die schwache, die Long-Seite die belegte.
- Der Funding-Korb ist als zweiter Baustein im Portfolio gebaut.

## 4. Weitere Ansätze, auf echten Daten geprüft

| Ansatz | Ergebnis |
|---|---|
| Gegenbewegung kaufen/verkaufen (RSI 2, Tageskerzen) | insgesamt ±0. Überkaufte Coins leerverkaufen verlor deutlich (−1,3 % je Trade). |
| Dieselbe Idee auf 4h | kein Vorteil |
| Stärkste Coins des letzten Monats kaufen, schwächste verkaufen | bis 2024 gut, seit 2025 im Minus |
| Verlierer der letzten Woche kaufen | im Minus |

Gemeinsamer Nenner: Im Kryptomarkt wird belohnt, wer mit der Stärke geht. Leerverkäufe gegen die Stärke verlieren fast überall.

## 5. Umgesetzte Entscheidungen

| Entscheidung | Umsetzung |
|---|---|
| Live-Strategien mit nachgewiesenem Verlust | Der Live-Wächter stellt sie jetzt selbst auf Paper (mindestens 50 Live-Trades, Obergrenze des Ø R unter 0). Abschaltbar im Leitstand. „Vorteil nicht belegt“ bleibt eine Empfehlung. |
| Trend-Basis 4h als Paper-Strategie im Minuten-Scanner | zurückgenommen. Der Scanner müsste 21 Tage Minutenkerzen je Asset halten; das ist auf Render ein Absturz-Risiko. Die Idee lebt im Portfolio weiter. |
| Modelle | siehe Abschnitt 1, einmalig übernommen |
| Lern-Limit, Rückwärtstest, Versuchs-Konto | wie am 16.11. gebaut, unverändert |
