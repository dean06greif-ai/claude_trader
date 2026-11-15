# Analyse: Trades, Lektionen, KI-Trader-Workflow, Labore, Endlossuche (15.11.2026)

Datenbasis: Produktion (Render), nur lesend über die API abgefragt.
- 1.369 geschlossene Trades (21.07. bis 15.11.2026), davon 783 vom KI-Trader
- 32 Lektionen (die UI zeigt 33, die API liefert 32)
- Lektions-Bilanz (90 Tage), Setup-Lab-Stand, Liquiditäts-Kontext, Orderflow
- Self-Test in Produktion: **15/15 grün**

Kennzahl „R“ = PnL ÷ Anfangsrisiko. t = t-Wert, also wie sicher sich das Ergebnis vom Zufall unterscheidet.
Ab etwa |t| ≥ 3 gilt das hier als belegt, weil viele Gruppen verglichen werden.

---

## 1. Die wichtigsten Befunde (Trades)

| Gruppe | Trades | Winrate | Ø R | t |
|---|---|---|---|---|
| KI-Trader gesamt (alles Paper) | 783 | 43 % | **−0,33** | −8,2 |
| davon Sammel-Trades (Detektor/„regel“) | 714 | 43 % | −0,33 | −7,8 |
| davon reguläre KI-Trades | 69 | 41 % | −0,29 | −2,8 |
| TrendFolge2 (live) | 352 | 48 % | −0,13 | −2,4 |

Der KI-Trader verliert, und zwar deutlich und nicht zufällig. Die Ursachen lassen sich klar benennen:

**1. Gebühren fressen den Trade (größter Hebel).**
- Ø Gebühren betragen 0,18 R pro Trade; ohne Gebühren läge der Schnitt bei −0,15 R statt −0,33 R.
- Der Edge-Filter meldet bei 651 von 783 Trades „Gebühren > X % des Risikos (SL zu eng)“.
- Gebühren unter 0,1 R: −0,05 R (fast Null). Gebühren 0,2–0,3 R: **−0,48 R** (n = 354).
- Ursache: Die Stops sind am 1m-ATR ausgerichtet und für die Kosten zu eng.

**2. Liquidationen vor dem Stop.**
- 19 Trades wurden liquidiert, jeweils mit etwa **−2,2 R**. Ein Stop würde den Verlust bei −1 R halten.
- Grund: Der Auto-Hebel geht bis 75x, der Liq-Preis liegt nur 0,5 % hinter dem SL.
- Ein Preissprung zwischen zwei Ticks trifft dann zuerst die Liquidation (Beispiel: ETH zweimal in einer Minute).
- Im Risiko-Modus ändert der Hebel das Risiko nicht, nur die gebundene Marge. Weniger Hebel kostet also nichts.

**3. Stops: Ø −1,30 R statt −1,0 R.**
- 0,18 R davon sind Gebühren, der Rest Slippage.
- Der Median der besten Zwischenbewegung (MFE) vor dem Stop liegt bei 0,17 R, bei einem Viertel bei 0.
- Die Trades laufen also sofort dagegen. Das Entry-Timing ist praktisch zufällig.

**4. Der Edge-Filter funktioniert, wird aber nur bei Live-Trades angewendet.**

| Edge-Filter-Ergebnis | Trades | Ø R |
|---|---|---|
| würde durchlassen | 72 | **+0,11** |
| würde blocken | 711 | −0,38 |

Bei Paper- und Sammel-Trades wird er nur markiert.

**5. LONG gegen den Tagestrend ist das größte Verlustmuster.**
- LONG bei Tages-Bias „down“: −0,49 R (n = 220).
- SHORT bei „flat/up“: positiv (+0,26 / +0,38 R), aber mit n = 56/31 noch nicht belegt.

**6. Konfidenz sagt nichts aus.**
- Konfidenz 60–69: −0,34 R; 70–79: −0,34 R; unter 60: −0,33 R.
- 683 der 783 Trades haben kein LLM-Modell. Es sind Detektor-Sammel-Trades. Echte LLM-Entscheidungen gab es nur etwa 100 in vier Monaten.

**7. Nach Anlageklasse:**
- Gold: 8 % Winrate, −0,77 R
- Silber: 19 % Winrate, −0,60 R
- Öl: −0,45 R
- Forex: −0,57 R
- Krypto: −0,25 R

**8. Setups vor Gebühren (Brutto-R, ohne Liquidationen):**

| Setup | n | Brutto Ø R | t | Einordnung |
|---|---|---|---|---|
| crypto_security_breach | 90 | +0,42 | 3,45 | **Täuschung:** alles SHORTs an 11 Tagen im fallenden November-Markt. Das ist Markt-Beta, kein Setup-Vorteil. |
| divergence | 237 | −0,06 | −0,8 | Vor Gebühren neutral; mit richtigen Stops eventuell rettbar |
| momentum_news | 86 | −0,12 | −1,2 | offen |
| pullback | 86 | −0,35 | −3,2 | schon vor Gebühren negativ |
| range_fade / trend_follow | 40 / 26 | −0,36 / −0,43 | −2,5 / −2,4 | schwach, eher negativ |
| **ny_close_reversal** | 19 | **−0,99** | **−7,6** | Winrate 5 % → hoffnungslos, stilllegen |

**9. Lab gegen Realität.** 20 Setups stehen im KI-Trader-Lab auf „tuned“, also bestanden. In echten Paper-Trades verlieren fast alle:
- squeeze_breakout Krypto: −0,65 R
- trend_follow Krypto: −0,60 R
- pullback (Nicht-Krypto): −0,72 R

Das ist der Beleg für Overfitting im Lab (siehe Abschnitt 4).

---

## 2. Die 32 Lektionen – machen sie Sinn?

Kurz: **Überwiegend nein.** Sie sind schwach belegt, teils kaputt, teils widersprüchlich, und ihre Wirkung ist kaum messbar.

**Die Wirkung lässt sich nicht messen.**
- Nur 3 von 783 Trades (0,4 %) sind einer Lektion zugeordnet. Das LLM nennt die Lektions-IDs nicht.
- Nur 1 Lektion hat ein Urteil, und zwar mit n = 18. Alle anderen stehen auf „zu wenig Daten“.

**Gespeicherter Text ist kaputt (Bug).** Bei mehreren Lektionen steht im Detailfeld eine Änderungsanweisung statt der Lektion selbst:
- Nr. 4: „Streichung der 120-Minuten-Frist …“
- Nr. 19: „Ändere das Mindest-CRV auf 1,5 …“
- Nr. 21: „Ersetze die 120-Minuten-Frist …“
- Nr. 32: „Ersetze '1m/5m/15m' durch …“

Vermutlich speichert die Merge-Logik die Revision statt des überarbeiteten Textes. Das prüfe ich beim Fix im Code.

**Bezug auf Daten, die es nicht gibt.** Nr. 1, 2 und 32 verlangen 10m- und 30m-Kerzen. Die KI bekommt aber nur 1m, 5m, 15m und 1h.

**Widerspruch zum System.** Nr. 25, 26 und 30 fordern, regelbasierte Trades ohne LLM-Analyse technisch zu sperren oder sofort zu schließen. Genau diese Trades sind die Datensammlung und die Vergleichsbasis des Signal-Brokers. Würde man die Lektionen befolgen, wäre das Lernen tot.

**Aus winzigen Stichproben.** Nr. 13 („letzte 2 OIL-Longs“), 24 (6 Trades), 28 (5 Trades) und 9 sind aus wenigen Trades abgeleitet. Das ist Rauschen, das als Regel festgeschrieben wird.

**Sie stapeln sich zu „nie handeln“.** Die Regime-Lektionen (Nr. 5, 6, 9, 16, 22, 23, 24) verlangen jeweils 10–50 % Marge und 2–3 Bestätigungen.
- Im Risiko-Modus ist „Marge“ gegenstandslos. Das sagt der eigene Prompt.
- Zusammen erzwingen sie praktisch HOLD.

**Doppelt.** Nr. 2 und 32, Nr. 4 und 21, Nr. 8 und 18 sagen jeweils dasselbe. Die Einstellung max_lessons = 50 begünstigt das Anhäufen.

**Brauchbar im Kern** (als harte Regel statt Prosa besser):
- Nr. 8: 3 Verluste → Coin pausieren
- Nr. 17: nicht gegen den 1h-Trend; die Daten stützen das (LONG gegen „down“: −0,49 R)
- Nr. 29: News-Defensive
- Nr. 12: kein Hedge; der Setup ist bereits stillgelegt

---

## 3. KI-Trader-Workflow – was steckt wirklich dahinter?

| Annahme | Realität im Code |
|---|---|
| Alle 10 min Marktanalyse aller Assets | **Ja**, im 10–15-min-Raster nach Berlin-Zeit. Assets werden in Gruppen analysiert (Krypto, Forex, …). Unveränderte Gruppen überspringt der Smart-Skip. |
| Bei besonderen News sofort analysieren | **Teilweise.** Der News-Wächter, Sweep-, TF2- und Setup-Trigger lösen Sofort-Analysen einzelner Symbole aus. Bei FOMC/CPI/NFP wird der Takt verdichtet. |
| Tiefenanalyse zum Markt-Open London/US | **Nein.** Sie läuft zu festen Berlin-Zeiten (Voreinstellung 06:30/18:30 bzw. 08:00/20:00), nicht zur Eröffnung. Sie erzeugt nur einen Text-Report, der in den nächsten Prompt fließt. Für die Eröffnung gibt es separat das Setup session_open. |
| Orderbuch / Liquidationen / Heatmap | **Daten sind echt** (Binance, Bybit, OKX live, Orderflow-Websocket verbunden). **Aber:** Die „Liquidations-Cluster“ sind modelliert, nämlich feste Abstände 0,5/1,5/3,5/9,5 % = 1/Hebel, immer „high“. Sie enthalten keine Information. Echt gemessene Liquidationen gibt es zusätzlich. Die Heatmap ist standardmäßig aus. |
| Entry-Zonen mit SL/TP berechnen | **Das LLM wählt** Richtung, Konfidenz und sl_pct/tp_pct. Code klemmt die Werte danach nur ein (CRV-Rahmen, Fee-Wächter, Klassen-Grenzen). Entry ist meist Market zum aktuellen Preis. |

**Rechnet das System oder schreibt das LLM nur Text?** Beides.
- Alle Zahlen werden **echt berechnet**: RSI, EMA, ATR je Timeframe, Session-Hochs und -Tiefs, Smart-Money-Zonen, VWAP, Orderflow/CVD, OI, Long/Short-Ratio.
- Sie gehen aber **als Text** an das LLM. Das LLM „interpretiert“ sie und gibt Prozentwerte zurück.
- Die Daten belegen: Die LLM-Konfidenz trägt keine Information, und die LLM-Trades sind nicht besser als die Detektor-Trades. Die Entscheidung selbst ist damit „Gelaber mit echten Zahlen als Kulisse“.

**Die bessere Methode gibt es schon im Code.** Der Signal-Broker mit „Prüfer-Modus“ funktioniert so:
- Ein **regelbasierter Detektor** schlägt einen Trade mit berechnetem SL/TP vor.
- Das **LLM darf nur ablehnen oder das Timing wählen**.
- Gemessen wird, ob die Ablehnungen Wert haben (regel gegen ki_geprueft).

So bekommt man viele, nicht zufällige Trades, und das LLM richtet weniger Schaden an.

**Datensammlung.**
- Sie läuft: 714 Sammel-Trades, die meisten seit November.
- Die Labels sind aber **von Gebühren dominiert**, weil die Stops zu eng sind. Das System lernt daraus vor allem, dass Gebühren verlieren.
- **Lernen ohne Trade** gibt es teilweise:
  - Die HOLD-Gegenprobe ist gelaufen (1.453 Fälle), aber nur für HOLDs, die eine Lektion blockiert hat.
  - Der Bewegungs-Scanner prüft große verpasste Moves.
  - Es fehlt eine Gegenprobe für **alle** HOLDs und nicht genommenen Detektor-Signale.

**Kalender läuft ab.** Die Termine für CPI, NFP, PPI, PCE und FOMC reichen nur bis **Dezember 2026**. Danach feuern die Event-Setups stillschweigend nie wieder.

**Sicherheit.** Alle GET-Endpunkte (Trades, Lektionen, Bot-Einstellungen) sind **ohne Login** öffentlich lesbar. Ich konnte die Daten ohne Anmeldung abrufen. Das gehört zum vertagten Passwort- und Sicherheitsthema.

---

## 4. KI-Trader-Lab und KI-Labor

**KI-Trader-Lab (Setup-Backtests): ja, es wird overfittet.**

Warum:
- Varianten, Feintuning, „optimize“ und KI-Revisions-Runden wählen den **besten Kandidaten nach Out-of-Sample-PnL** (runner.tune / optimize_better). Damit ist der OOS-Teil kein unbekannter Test mehr.
- Die Hürde ist niedrig: 10–30 OOS-Trades, PnL > 0, 2 von 3 Fenstern positiv. Es gibt keine Signifikanz und keine Korrektur für die Zahl der Versuche.

Ergebnis: 20 bestandene Setups, die in echten Paper-Trades fast alle verlieren. Das ist eher kontraproduktiv, weil es scheinbar validierte Setups liefert, die automatisch live dürfen.

**Event-Setups (FOMC/CPI/…): nicht löschen, aber nicht automatisch live.**
- Die Regeln sind fest und ohne Optimierung definiert. Das ist gut.
- „Validiert“ gilt aber schon ab 10 Trades und 4 OOS-Trades. Diese stammen aus wenigen Ereignissen und sind stark korreliert, denn ein CPI-Termin erzeugt viele gleichzeitige Trades.
- Gezählt werden müssen **Ereignisse, nicht Trades**. Ehrlich betrachtet gilt: Paper-Sammlung ja, Live erst nach vielen Ereignissen.

**KI-Labor (Forschung, ML, Gedächtnis, Markt-Beobachter):**

| Baustein | Bewertung |
|---|---|
| Markt-Beobachter | **Nützlich**: echte Feature-Snapshots, Basis für alles andere |
| Gedächtnis | Neutral, funktioniert als Speicher |
| ML-Labor | **Zu optimistisch.** Training ab 40 Beispielen, Optuna mit vielen Versuchen meldet den *besten* Kreuzvalidierungs-AUC (also auch Selektions-Bias), das Label ist nur Gewinn/Verlust ohne Größe. Die Feature-Wichtigkeiten aus so kleinen Daten fließen als „Wissen“ in die Prompts, also Rauschen. |
| Forschungs-Analyst | LLM-Zusammenfassungen. Nur sinnvoll, wenn Zahlen dahinterstehen. |

---

## 5. Endlossuche – sinnvoll gebaut? Welche Einstellungen?

**Aufbau:** Nach den strengeren Regeln sinnvoll.
- Signifikanz mit ehrlicher Versuchszahl, Tresor-Daten und Walk-Forward.
- Der Zufalls-Test findet 0 Champions, ein eingebauter echter Vorteil wird gefunden.

**Indikator-Check:** 62 Discovery-Regeln, jeweils long und short, auf 5m, 15m und 1h.

- **Kein Look-ahead.** Werte aus abgeschnittenen Daten sind identisch mit denen aus vollen Daten.
- **Nutzlos (immer an):**
  - „ATR > 0,05 % / 0,15 %“
  - „BB-Breite > 0,3 % / 0,8 %“

  Bei Krypto ist das auf jedem Timeframe zu 100 % wahr. Diese Regeln filtern nichts, erhöhen aber die Versuchszahl und damit die Hürde.
- **Kaum aussagekräftig:**
  - Der FOMC-Filter ist zu 98–100 % an.
  - „Equal Lows/Highs“ hat auf 1h 50–60 % fehlende Werte (NaN) und feuert unter 1 %.
- Alle übrigen Regeln feuern in sinnvollen Raten.

**Wie viele Test-Trades braucht ein Vorteil?** Annahme: Streuung etwa 1,1 R pro Trade.

| geprüfte Kandidaten | t-Hürde | Vorteil 0,10 R | 0,15 R | 0,25 R |
|---|---|---|---|---|
| 1 | 1,64 | 328 | 146 | 53 |
| 10 | 2,58 | 803 | 357 | 129 |
| 50 | 3,09 | 1.156 | 514 | 185 |
| 200 | 3,48 | 1.466 | 652 | 235 |

**Empfehlung daraus:**
- **Regeln:** 2–3 (max_rules = 3). Mehr Regeln bedeuten weniger Trades und mehr Versuche, also Verlust auf beiden Seiten.
- **Assets:** 8–15 derselben Klasse. Die Trades werden gepoolt; mehr Assets bedeuten mehr Test-Trades. Klassen nicht mischen.
- **Zeitraum:**
  - 15m/1h: 180–365 Tage
  - 5m: 90–120 Tage
  - Ziel: mindestens 300–600 Test-Trades für realistische Vorteile von 0,15–0,25 R
- **Timeframe:** 15m als Standard. Auf 5m fressen Gebühren den Vorteil (siehe Trades: Gebühren pro Risiko sind der Hauptverlust).
- **Suchbreite begrenzen:** lieber 100 gut gewählte Kandidaten als 1.000 zufällige. Jeder zusätzliche Versuch hebt die Hürde.

---

## 6. Plan (zur Freigabe)

**Stufe 1 – direkte Wirkung, klein, rückwärtskompatibel**

1. **Hebel-Deckel:** Der Liquidationspreis muss mindestens doppelt so weit entfernt sein wie der SL (statt 0,5 % dahinter). Das Risiko pro Trade bleibt gleich, die −2,2-R-Liquidationen entfallen.
2. **Gebühren-Regel für alle Trades:**
   - Gilt auch für Sammel-Trades.
   - Der SL wird so weit gesetzt, dass die Gebühren höchstens etwa 0,1 R ausmachen. Ist das nicht möglich, gibt es keinen Trade.
   - Gebühren und Slippage werden je Trade in R gespeichert, damit Setups getrennt **vor und nach Kosten** bewertet werden können.
3. **Edge-Filter bei Sammel-Trades:**
   - Das Tages-Bias-Kriterium wird angewendet: kein LONG gegen „down“.
   - Die Filter-Bilanz wird weiter gemessen.
4. **ny_close_reversal stilllegen** (über dieselbe RETIRED-Mechanik wie hedge). Andere Setups erst nach Stufe 1 neu beurteilen, auf Basis der Brutto-Ergebnisse.
5. **Lektionen:**
   - Merge-Bug beheben.
   - Lektionen streichen, die auf nicht vorhandene Timeframes verweisen oder dem System widersprechen (Nr. 1, 2, 25, 26, 30, 32).
   - Duplikate zusammenführen, max_lessons auf 12.
   - Neue Lektionen nur mit belegter Stichprobe (mindestens 30 Fälle).
   - Lektions-IDs im Antwortformat zur Pflicht machen, damit die Wirkung messbar wird.
6. **Modellierte Liquidations-Cluster aus dem Prompt nehmen**; nur gemessene behalten.
7. **Event-Kalender 2027 ergänzen** (offizielle Termine von BLS, BEA und Fed) und einen Self-Test-Check „Kalender reicht noch mindestens 60 Tage“ hinzufügen.

**Stufe 2 – Lernen und Labore ehrlich machen**

8. **KI-Trader-Lab:**
   - Auswahl nur auf Trainingsdaten.
   - OOS als echter Test mit Signifikanz und gezählten Versuchen; dafür die Bausteine der Endlossuche wiederverwenden (evidence_stats, Tresor).
   - Bestehende „tuned“-Setups werden als „unbestätigt“ markiert.
   - Neue Ansicht „Lab gegen echte Paper-Trades“ je Setup.
9. **Event-Setups:**
   - Ereignisse zählen statt Trades.
   - Kein automatisches Live mehr; live erst nach Belegung.
10. **HOLD-Gegenprobe für alle HOLDs und verpassten Detektor-Fenster.** Damit lernt das System aus verpassten Chancen, auch ohne zu handeln. Der Baustein existiert bereits und wird nur erweitert.
11. **Markt-Benchmark:** Jedes Setup wird gegen „gleiche Richtung, zufälliger Zeitpunkt, gleicher Coin“ gemessen, damit Markt-Beta wie bei crypto_security_breach nicht als Vorteil erscheint.
12. **ML-Labor:** Mindestens 300 Beispiele, Label in R, Kennzahl auf einem echten Hold-out. Nur in Prompts einspeisen, wenn das Modell nachweislich besser als Zufall ist.

**Stufe 3 – Rolle des LLM**

13. **Prüfer-Modus als Standard:** Detektoren liefern Trades mit berechnetem SL/TP, das LLM darf nur ablehnen oder das Timing wählen. Gemessen wird, ob die Ablehnungen Geld wert sind. Erst wenn ja, bekommt das LLM mehr Spielraum.
14. **Endlossuche:**
   - Die zwei immer-wahren Indikator-Regeln entfernen bzw. durch Volatilitäts-Perzentile ersetzen.
   - Vor dem Start anzeigen: erwartete Test-Trades und kleinster nachweisbarer Vorteil.

Jede Stufe bekommt Regressionstests und den Self-Test. Die Ordnerstruktur bleibt unverändert.
