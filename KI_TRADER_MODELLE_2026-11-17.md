# KI-Modelle, KI-Trader und Suche nach einer neuen Kante – 17.11.2026 (Abend)

Datenbasis: Produktion, nur lesend abgefragt (17.11., ca. 18 Uhr): 1.454 geschlossene Trades,
KI-Team-Status, Token-Abrechnung, Signal-Broker, Key-Guthaben. Die Forschung lief auf
Binance-Tagesdaten der 64 Portfolio-Coins (2020 bis heute).

## 1. Was an den KI-Modellen „komisch“ war

| Befund | Ursache | Behoben |
|---|---|---|
| Die KI-Aufsicht riet, Trade-Manager, Markt-Beobachter, Chat und Tagesbericht abzuschalten. | Sie sah nur Text-Stichproben, keine Aufrufzahlen. Viele Rollen schreiben nichts in den Feed. Der Trade-Manager hatte an dem Tag 17 Aufrufe, der Markt-Beobachter 52. | Aufrufe laut Token-Abrechnung stehen jetzt als Fakt im Prompt. Danach prüfen Regeln jedes Urteil: Eine aktive Rolle ist nie „inaktiv“. Ereignisrollen dürfen ruhen. Kritische Rollen werden nie zum Abschalten empfohlen. |
| „Analyst auf gpt-6-luna-pro umstellen“, „Forschung auf deepseek-v4.1-flash upgraden“ | Genau diese Modelle liefen bereits. | Empfehlungen, die auf das schon aktive Modell wechseln wollen, werden gestrichen. |
| „news_watcher auf openrouter/glm-5.3“ | Der Slug war verkürzt, richtig ist z-ai/glm-5.3. | Verkürzte Slugs werden auf den Katalog-Eintrag ergänzt. |
| Die Aufsicht lief auf einem kleinen Gratis-Modell (gpt-oss-120b auf Groq). | Sie erbte das Haupt-Modell der Engine, und dessen Kette fiel durch. | Feste Kette: DeepSeek V4.1 Flash → GPT-6 Luna Pro → Gemini Flash. Ein Prüflauf kostet etwa 0,1 Cent. |
| Warnung „Leere Antwort … Free-Modell überlastet“ bei DeepSeek | DeepSeek ist ein Bezahl-Modell, die Meldung war also falsch. Dazu kommt: DeepSeek liefert im JSON-Modus laut eigener Doku gelegentlich leeres content. | Der zweite Versuch läuft ohne response_format und ohne Reasoning. Die Antwort wird ohnehin tolerant gelesen. Die Meldung nennt Bezahl- oder Gratis-Modell und den Abbruchgrund. |
| „Hoher Token-Verbrauch: Forschungs-Analyst“ kam am 16.11. viermal. | Die Sperre gegen doppelte Meldungen lag nur im Speicher. Jeder Neustart durch Deploy oder Render-Schlaf hob sie auf. | Bei Sperrzeiten ab 1 h merkt sich das System die Sperre in der Datenbank (`notify_dedupe`), für Website und Telegram. |

Die Modellwahl je Rolle bleibt wie am Morgen festgelegt. Sie ist nicht das Problem.

## 2. KI-Trader: hat er Potential?

| Zeitraum | Trades | Ø R netto | t | Ø R vor Kosten |
|---|---|---|---|---|
| gesamt (seit 21.07.) | 868 | −0,33 | −8,6 | −0,16 |
| seit den Fixes (16.11.) | 63 | −0,20 | −1,5 | −0,11 |

- Seit dem 16.11. sind **alle 63 Trades Regel-Trades** des Detektors (Paper-Datensammlung). Es gab
  **0 KI-geprüfte Trades**. Die Regel-Trades sind schon vor Kosten negativ.
- Das einzige früher auffällige Setup (crypto_security_breach) liegt seit dem 16.11. bei −0,73 R
  (n = 7).
- **Der Prüfer hat sich selbst blockiert (Bug).** Im Prüfer-Modus öffnet jedes Detektor-Signal
  sofort einen Regel-Trade als Kontrollgruppe. Die KI sah diese Position und antwortete „bereits
  offen – keine Doppelposition“. Das war bei **9 der 16** aktuellen Entscheidungen so. Folgen:
  - Kein KI-geprüfter Trade konnte entstehen.
  - Diese HOLDs zählten als „Veto“ und verfälschten die Veto-Bilanz.
  - Die Reife-Schwelle (30 KI-geprüfte Trades) war unerreichbar.
- **Kosten ohne Nutzen.** Der Analyst (Prüfer) verbraucht ~4,2 Mio. Tokens am Tag (190 Aufrufe à
  ~22.000 Tokens), das sind etwa 0,5 $ am Tag. Viele Aufrufe kamen von TF2-, Sweep- und
  News-Auslösern ohne offenes Detektor-Signal. Dort kann im Prüfer-Modus gar kein Trade
  entstehen, nur HOLD. Das OpenRouter-Hauptguthaben stand bei 7,49 $ und reicht damit etwa
  zwei Wochen.

**Umgesetzt:**
1. Der Prompt erklärt jetzt an drei Stellen (Signal-Liste, Positionsliste, Setup-Auslöser), dass
   der Regel-Trade die Kontrollgruppe ist und kein Grund für HOLD. Ein KI-Einstieg läuft
   getrennt; der Duplikat-Wächter trennt beide Welten schon heute.
2. Ein HOLD, der nur auf die laufende Position verweist, zählt nicht als Prüfung. Das Signal
   endet dann als „ungeprüft“ statt „verworfen“. Erkannt wird das an Formulierungen wie
   „bereits offen“ oder „keine Doppelposition“; alle 16 Produktions-Begründungen werden richtig
   eingeordnet.
3. TF2-, Sweep- und News-Analysen laufen im Prüfer-Modus nur noch, wenn für das Symbol ein
   Detektor-Signal offen ist. Bei HIGH-News werden nur die offenen Signale geprüft, ohne
   Voll-Analyse. Erwartung: gut die Hälfte weniger Analyst-Aufrufe. Gemessen wird das in der
   Token-Abrechnung.
4. **Reichweite des KI-Guthabens.** Das System misst den Verbrauch je Key aus dem stündlichen
   Guthaben-Abruf, als Dollar pro Tag über die letzten 3 Tage. Bei weniger als 14 Tagen
   Reichweite erscheinen ein Banner im KI-Tab und eine Cockpit-Empfehlung mit dem größten
   Verbraucher.

**Ehrliches Urteil:** Der KI-Trader hat in seiner jetzigen Form, also Kurzfrist-Detektoren auf
1m/5m/15m mit KI-Prüfung, **kein belegtes Potential**. Die Signale sind vor Kosten negativ, und
die Gebühren machen etwa 0,1–0,2 R je Trade aus. Ob die KI-Prüfung Wert hat, war wegen des Bugs
nie messbar. Ab jetzt ist es messbar. Eine Prüfung, die aus einem negativen Topf etwas
Positives filtert, ist möglich, aber unwahrscheinlich. Realistisch ist der KI-Trader ein
Messlabor und kein Geldverdiener. Das Geld verdient das Portfolio.

## 3. Suche nach einer neuen Kante (Portfolio)

Vorgehen wie immer:
- Entdeckung 2020–2022 (D), Bestätigung 2023–2024 (V).
- Holdout ab 2025 (H) nur für den vorab festgelegten Kandidaten, einmal angesehen.
- Kosten 0,08 % je Seite, Funding gerechnet.
- Basis: Portfolio „normal“ (D Sharpe 2,30, V 1,48, H 1,19). Die Rückrechnung stimmt exakt mit
  den angezeigten Werten überein.

| Idee | D | V | Urteil |
|---|---|---|---|
| Volatilitäts-Steuerung des Gesamtportfolios (Ziel 30–50 % p. a.) | schlechter (2,11–2,15) | besser (1,57–1,70) | verworfen, nicht in beiden Zeiträumen besser |
| Funding-Korb größer (Gross 0,75 / 1,0) | besser | schlechter | verworfen |
| Ausbruch 10 / 30 / 55 Tage statt 20 | jeweils schlechter | schlechter | 20 Tage bleibt |
| Nur Long (ohne Shorts) | 2,20 | 1,39, mit höherem Rückgang | verworfen, Shorts helfen |
| Funding-Filter für Trend-Einstiege | 2,21–2,25 | 1,45–1,47 | verworfen |
| Trend-Bestätigung 60/90/180 Tage | 1,69–2,04 | 0,94–1,53 | verworfen |
| **Querschnitts-Momentum** (wöchentlich, 8 stärkste long / 8 schwächste short, Ensemble 7/14/28 Tage) | Sharpe allein 1,25; mit Portfolio 2,36 | Sharpe allein 1,47; mit Portfolio 1,63 | **im Holdout gescheitert** (siehe unten) |

Querschnitts-Momentum im Detail:
- **Stabil in D und V:** alle 6 Varianten positiv, auch bei doppelten Kosten und mit toten Coins
  (LUNA, FTT …).
- **Holdout ab 2025:** allein nur Sharpe 0,37 (+5,5 % p. a.). Fast der ganze Gewinn stammt aus
  einem Monat (Oktober 2025, +28 %). Im Portfolio sinkt der Sharpe von 1,19 auf 1,14.
- **Urteil:** Die Kante ist seit 2025 weitgehend verschwunden. Nicht eingebaut.

Nebenbefund: Der Funding-Korb war in V wertlos (Sharpe 0,08), im Holdout aber stark (Sharpe 1,83,
+17 % p. a.). Die Bausteine wechseln sich ab. Genau deshalb bleibt die Mischung aus Trend und
Funding-Korb.

Weitere Ergebnisse:
- Maker- statt Taker-Gebühren bringen etwa +3–4 Prozentpunkte im Jahr. Das wäre möglich, kostet
  aber Ausführungs-Risiko; vorgemerkt.
- „Offensiv“ (max_gross 4) wird im Rechenkern zwar auf 3 begrenzt. Das ist folgenlos, weil die
  20-Positionen-Grenze vorher greift. Die Ergebnisse sind identisch.

**Fazit der Suche:** Keine der geprüften Ideen schlägt das bestehende Portfolio in allen
Zeiträumen. Das Portfolio steht nahe an dem, was mit öffentlichen Tagesdaten erreichbar ist.

## 4. Was das Geld wirklich bewegt

| Hebel | Wirkung |
|---|---|
| KI-Kosten senken (Prüfer-Aufrufe ohne Signal entfallen) | spart voraussichtlich gut die Hälfte von ~0,5 $ pro Tag. Bei einem kleinen Konto ist das mehr als der erwartete Handelsgewinn. |
| Kapital im Portfolio, sobald der Probelauf hält | Rendite skaliert linear |
| Zeit und Zinseszins | vorsichtig 15–30 % p. a. |
| Neue Strategien | keine gefunden, die den Holdout übersteht |
