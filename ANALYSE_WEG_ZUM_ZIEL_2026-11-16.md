# Analyse 16.11.2026: Was die Nacht gezeigt hat und der Weg zum profitablen System

Status: **Analyse und Plan zur Freigabe.**
- Sofort behoben, weil kritisch: ein Fehler der Endlossuche (Abschnitt 2a).
- Alles andere ist ein Vorschlag.

Datengrundlage: Live-System (nur gelesen), Code, eigene Härtetests auf Zufallsdaten, Fachliteratur (Quellen am Ende).

## Kurzfassung

1. **Die Verbesserungen wirken, aber der Kern fehlt noch.**
   - Die Gebühren je Trade sind halbiert (0,18 R → 0,09 R), Live-Bypass ist aus, der Stichtag wirkt.
   - Die Einstiege selbst haben aber keinen Vorteil: 23 neue Trades, Ø −0,61 R, brutto −0,53 R.
   - Das bestätigt den Befund vom 15.11.: Die 1m-Detektoren und die KI-Prüfung finden keinen Vorteil.
2. **Der Anti-Overfitting-Test hat auf deinem Worker nicht gewirkt.**
   - Mit mehreren Kernen rechnete die Endlossuche Test und Tresor auf den **Trainingsdaten**.
   - Alle 5 heutigen Champions haben deshalb exakt gleiche Trainings-, Test- und Tresor-Werte. Sie sind **nicht geprüft**.
   - Derselbe Fehler erklärt die „Test = Training“-Liste aus August.
   - **Behoben** (Worker 1.30.0, Tests, Self-Test).
   - Danach fand der Härtetest mit deinen Einstellungen auf reinen Zufallsdaten **0 Fehl-Champions** (5 Läufe, 435 geprüfte Kandidaten).
3. **Danach bleiben drei kleinere Lücken:**
   - Test- und Tresor-Daten werden über viele Läufe immer wieder benutzt.
   - Der Tresor prüft nur „Gewinn > 0“ mit 4 Trades, das ist ein Münzwurf.
   - Die bloße Marktrichtung könnte bei längeren Haltedauern als Vorteil durchgehen. Bei 15m-Trades blieb das im Test aus: 0 Fehl-Champions trotz −45 % Marktbewegung.
4. **Champions zusätzlich auf anderen Zeiträumen prüfen ist sinnvoll und günstig.**
   - Vorschlag: sofortiger **Rückwärtstest** auf den 180 Tagen vor dem Suchzeitraum (Ergebnis in Minuten).
   - Dazu ein Test auf Coins außerhalb der Suche und ein Test gegen die Marktrichtung.
   - Erst danach folgt der Vorwärtstest auf neuen Daten.
5. **Die Regime-Brücke ist derzeit wirkungslos.**
   - Es gibt keine Freigabe und 0 Trades mit Struktur-Regime.
   - Geprüft an TrendFolge2: Ein Regime-Filter, gelernt auf der ersten Hälfte der Trades, hat die zweite Hälfte **nicht** verbessert (−0,21 R statt −0,19 R).
   - Regime lohnt sich nur als nachweislich wirkender Filter oder für die Positionsgröße. Dafür braucht es einen Messtest, keine weiteren Erkennungs-Varianten.
6. **Weg zum Ziel.**
   - Die Forschung auf belegte Vorteils-Quellen ausrichten: Trendfolge auf 4h/1d über viele Coins mit Volatilitäts-Steuerung und Positionierungs-Daten (Funding, Long/Short-Verhältnis).
   - Weniger, größere Trades mit Maker-Einstiegen.
   - Die KI als Prüfer, Erklärer und Risiko-Wächter einsetzen, nicht als Quelle der Einstiege.

---

## 1. Prüfung der Nacht

| Punkt | Ergebnis |
|---|---|
| Neuer Code live | ja: Leitstand-Endpunkte antworten, Worker 1.29.0 online |
| Bewertungs-Stichtag | 15.11. 21:06 UTC (Start der Kostenregeln) ✔ |
| Live-Bypass | aus ✔ |
| Gebühren je Trade | 0,09 R (vorher 0,18 R) ✔ |
| Stops auf Fee-Minimum erweitert | 19 von 31 Trades ✔ |
| KI-Trades seit Stichtag | 31 in 19,5 h, alle Regel-Lern-Trades, 0 KI-geprüfte |
| Ergebnis | Ø −0,61 R (23 geschlossen), brutto −0,53 R |
| Ø Haltedauer | 3,5 h (weitere Stops → längere Trades) |
| Größte Bremse | Richtungs-Wächter für Lern-Trades: 122 Blocks (Limit 5 je Klasse und Richtung) |
| Nacht-Forschung | nicht gelaufen: In der Nacht war kein aktueller Worker verbunden. Nach dem Deploy dieses Pakets braucht sie Worker **1.30.0**. Dann läuft sie jede Nacht, außer es läuft gerade eine manuelle Suche |
| Endlossuche heute 16:11 | 1.776 Kombis, 141 geprüft, 5 Champions. **Ungeprüft**, weil Test = Training (Abschnitt 2a, behoben) |

**Schluss:** Die Kosten-Seite ist repariert. Die Einstiege haben brutto keinen Vorteil.

Bei den Setups sieht man das so (Stichprobe noch klein):
- `safe_haven_flow` (10 Trades) −0,34 R
- `crypto_security_breach` (5 Trades) −1,13 R
- `momentum_news` (4 Trades) −0,47 R

Nachrichten-Reaktionen auf 1m-Basis verlieren. Mehr Trades dieser Art machen das Ergebnis nicht besser.

## 2. Funktioniert der Anti-Overfitting-Test?

### 2a. Kritischer Fehler: Test = Training auf dem lokalen Worker (behoben)

**Befund im Live-System:** Der Lauf von heute 16:11 brachte 5 Champions. Bei **jedem** sind Training, Test und Tresor identisch, zum Beispiel 93 Trades, Ø +0,501 R und 61,3 % Trefferquote in allen drei Teilen. Bei einer Aufteilung 70/30/15 ist das unmöglich.

**Ursache:**
1. Der lokale Worker rechnet mit mehreren Prozessen (`SIM_WORKERS`).
2. Diese Prozesse bekommen die Kerzen **einmal beim Start**, und zwar die Trainingsdaten.
3. Jeder spätere Auftrag nennt nur die Symbol-Namen.
4. Für Test und Tresor rechnete der Pool deshalb wieder auf den Trainings-Kerzen.

Folgen:
- Die Signifikanz-Prüfung (t ≥ 3,3) lief faktisch auf **genau den Daten, auf denen die Kombination optimiert wurde**. Damit ist sie leicht zu bestehen.
- Auch der Tresor war Training.
- Die Cloud rechnete sequenziell richtig. Mein Härtetest vom 15.11. lief ebenfalls sequenziell und hat den Fehler deshalb nicht gesehen.

**Nachgestellt mit Multi-Core:**
- **Vor dem Fix:** auf reinen Zufallsdaten 3 „Champions“, jeweils Training = Test = Tresor (127 Trades / 320 USDT in allen drei Teilen).
- **Nach dem Fix:** Die Werte unterscheiden sich, Zufalls-Kandidaten fallen im Test durch (Training +696 / Test −5).

**Fix:**
- Der Pool darf nur noch die Daten rechnen, mit denen er gestartet wurde (`parallel_sim.pool_has_data`). Test und Tresor laufen sequenziell auf ihren eigenen Daten.
- Champions tragen jetzt `evidence.engine = 2`. Ältere Funde wandern automatisch in den Altbestand.
- Kandidaten aus solchen Läufen werden verworfen (erneut testbar).
- Worker **1.30.0** ist Pflicht für Optimierungen.
- Eine Self-Test-Prüfung wacht darüber.

**Was das heißt:** Die heutigen 5 Champions (Williams %R / Stochastik / Momentum-Kombinationen) sind **ungeprüft**. Erst ein neuer Lauf mit Worker 1.30.0 zeigt, ob davon etwas trägt.

### 2b. Die Prüfung nach dem Fix

**So prüft die Endlossuche jetzt:**

1. **Training (70 %):** Suche, Feinjustierung der Schwellen sowie TP/SL/BE/Trail nur auf Trainingsdaten.
2. **Test (30 %):** ehrlicher t-Test auf R je Trade. Die Hürde wächst mit der Zahl geprüfter Kandidaten (mindestens 100, Bonferroni, t ≈ 3,3–3,5) und verlangt mindestens 30 Test-Trades.
3. **Tresor (15 % ganz am Ende):** Gewinn > 0 mit mindestens ~4 Trades.
4. **Top-5-Checks:** Konstanz, Kosten-Stress, Parameter-Stabilität, Monte-Carlo, Multi-Coin.
5. **Danach:** Vorwärtstest auf neuen Daten (Kandidaten-Pipeline).

Wichtig: Schritt 4 rechnet überwiegend auf den **Trainingsdaten**. Er zeigt, ob das Ergebnis stabil gefittet ist, nicht, ob es auf unbekannten Daten trägt.

### Härtetest mit deinen Einstellungen (Multi-Core wie auf dem Worker, nach dem Fix)

**Aufbau:**
- Reine Zufallsdaten: driftloser Random Walk mit Volatilitäts-Clustern, 4 Assets, 180 Tage, 15m.
- Deine Einstellungen: Kombi-Ziel, 30 Min-Trades, 3 Regeln, alle Indikatoren, TP/SL + BE + Trail mitoptimiert, DD-Filter 30 %, Konstanz.
- Es lief der Original-Code, ersetzt wurde nur die Datenquelle.

Jeder Champion wäre hier ein Fehlalarm.

| Lauf | Ausführung | Kombis getestet | im Test geprüft | Champions (= Fehlalarme) |
|---|---|---|---|---|
| 1 | sequenziell | 440 | 71 | 0 |
| 2 | sequenziell | 528 | 83 | 0 |
| 3 | Multi-Core (nach Fix) | 512 | 84 | 0 |
| 4 | Multi-Core (nach Fix) | 776 | 101 | 0 |
| 5 | Multi-Core (nach Fix) | 616 | 96 | 0 |
| **Summe** | | **2.872** | **435** | **0** |

Die knappsten Fehlschläge lagen bei t = −2,2 bis +0,7. Die Hürde lag bei 3,29: Zufall kommt nicht in die Nähe.

**Gegenprobe Marktrichtung:**
- Gleiche Zufallsdaten, aber im letzten Drittel (Test + Tresor) fällt der Markt stetig um ~45 %.
- Ein Indikator-Vorteil existiert nicht, nur die Richtung.

| Lauf | Kombis | im Test geprüft | Champions |
|---|---|---|---|
| 1 (−45 % im Test/Tresor) | 440 | 72 | 0 |
| 2 (−45 % im Test/Tresor) | 640 | 72 | 0 |

Bei 15m-Trades mit wenigen Stunden Haltedauer ist die Marktrichtung je Trade zu klein, um die Hürde zu reißen. Bei 4h/1d-Strategien (Trend-Portfolio, F3) dauern Trades Tage. Dort wird der Richtungs-Check Pflicht.

**Gegenprobe echter Vorteil:**
- Gleiche Zufallsdaten plus eingebauter Trend-Vorteil.
- Die Suche fand **5 Champions in 40 Sekunden**, t 5,9–20,2.
- Training und Test lagen nah beieinander (z. B. +1,30 R / +1,31 R), aber nicht identisch.
- Die Prüfung erkennt echte Vorteile also schnell.

**Aber:** Alle 5 echten Champions fielen danach im Top-5-Check durch, und zwar am **Konstanz-Test mit deiner Einstellung 25 %**. Ihre Streuung lag bei 41–43 %, obwohl **alle** 30-Tage-Abschnitte im Plus waren. Diese Einstellung sortiert also auch perfekte Vorteile aus (siehe Abschnitt 3).

### Die Lücken

| Lücke | Warum es zählt | Lösung |
|---|---|---|
| Test- und Tresor-Daten werden über viele Läufe wiederverwendet | Jeder Lauf auf denselben 180 Tagen bekommt eine frische Hürde. Nach 10 Läufen liegt die Chance auf mindestens einen Zufalls-Champion bei ~20–40 % | **Versuchs-Konto** je Klasse/Zeitebene über 30 Tage: Die Hürde zählt alle Prüfungen auf denselben Daten |
| Tresor = „Gewinn > 0“ mit ~4 Trades | Unter Zufall besteht das jede zweite Strategie | Tresor: Ø R > 0 **und** mindestens 10 Trades |
| Training darf in R negativ sein | Ein Champion kann im Training verlieren und nur im Test gewinnen. Das spricht eher für Glück oder Marktphase | Vorzeichen in R muss in Training **und** Test positiv sein |
| Ziel „Kombi (PnL × Winrate)“ | Die Suche optimiert Gewinn in USDT, die Prüfung misst R. Beobachtet: Bestwert mit +230 USDT, aber −0,05 R je Trade | Endlossuche standardmäßig auf „Erwartungswert (R)“. Neu: „t-Wert (R)“, das ist genau das, was die Prüfung verlangt |
| Marktrichtung als „Vorteil“ | Bei 15m im Test kein Problem (0 von 144). Bei 4h/1d-Strategien mit Haltedauer von Tagen kann eine Trendphase aber einen Vorteil vortäuschen | **Richtungs-Check:** R des Champions gegen zufällige Einstiege mit gleicher Long/Short-Mischung und gleichen Ausstiegen |
| Robustheits-Checks auf Trainingsdaten | Wenig Aussage über unbekannte Daten | **Rückwärtstest** auf älteren Daten und **Fremd-Coin-Test** (Abschnitt 4) |

Die Suche selbst ist ehrlicher geworden. Solange diese Lücken offen sind, gilt: **Ein Champion ist ein Kandidat, kein belegter Vorteil.** Den Beleg liefern erst Rückwärts- und Vorwärtstest.

## 3. Deine Einstellungen

| Einstellung | Jetzt | Empfehlung | Warum |
|---|---|---|---|
| Modus, Zeitebene, Zeitraum | Endlos, 15m, 180 Tage | **so lassen** | gute Balance aus Trade-Zahl und Kosten |
| Ziel | Kombi (PnL × Winrate) | **Erwartungswert (R)** | misst dasselbe wie die Prüfung; Gewinn in USDT verzerrt durch Positionsgrößen |
| Min. Trades | 30 | **100** | Für t ≥ 3,3 braucht ein Vorteil von 0,3 R ~120 Test-Trades. Kombis mit 30 Trades können nie bestehen und kosten nur Rechenzeit |
| Iterationen | 200 | **80–100** | mehr verschiedene Kombis statt Feinschliff; Feinschliff passt nur das Training genauer an |
| Max. Regeln | 3 | so lassen | |
| Mitoptimieren | TP/SL, Break-Even, Trail | **nur TP/SL** in der Suche; BE/Trail danach im Parameter-Modus | jede Gruppe vergrößert den Suchraum und damit die Fehlalarm-Chance |
| Walk-Forward | Rolling, 4 Fenster | ok | die Suche selbst nutzt einen Split + Tresor; Rolling gilt im Top-5-Check |
| Drawdown-Filter | 30 % vom PnL | ok | gilt nur auf Testdaten |
| Konstanz | 30-Tage-Abschnitte, max. 25 % | **60–80 %** | **Belegt:** Ein eingebauter, echter Vorteil mit 100 % profitablen Abschnitten fiel mit 41–43 % Streuung durch. 25 % sortiert gute Strategien aus |
| Kosten-Stress, Stabilität, Monte-Carlo | an | an lassen | |
| Regime-Analyse | aus | **an** | reine Info, liefert die Daten für den Regime-Messtest (Abschnitt 5) |
| Assets | 13 Krypto | ok; besser 20–30 einer Klasse | mehr Assets = mehr Test-Trades = schärferer Test |
| Ausführung | Lokal | so lassen | |

## 4. Champions auf anderen Zeiträumen prüfen

**Heute:** Training und Test liegen im selben 180-Tage-Fenster, der Tresor ist dessen letzter Teil. Danach folgt der Vorwärtstest auf neuen Daten. Der dauert Wochen, bis 30 Trades zusammen sind.

**Vorschlag, gestaffelt und automatisch in der Kandidaten-Pipeline:**

1. **Rückwärtstest (sofort, Minuten):**
   - Dieselben Regeln und Trade-Einstellungen auf den 180 Tagen **vor** dem Suchzeitraum.
   - Diese Daten hat die Suche nie gesehen, und oft lag dort eine andere Marktphase.
   - Bestanden: Ø R > 0 und mindestens 30 Trades. Durchgefallen: Ø R < 0 und Obergrenze < 0.
2. **Fremd-Coin-Test:** gleiche Regeln auf Coins derselben Klasse, die nicht in der Suche waren. Ein echter Vorteil sollte nicht nur an 13 bestimmten Coins hängen.
3. **Richtungs-Check:** R gegen zufällige Einstiege mit gleicher Long/Short-Mischung. Damit fällt auf, wenn es nur Marktrichtung war.
4. **Vorwärtstest** (gibt es schon): neue Daten seit dem Fund.
5. **Übernehmen (Paper)** und danach die Live-Tore.

**Warum das sinnvoll ist:** Die Fachliteratur nennt das Wiederverwenden derselben Daten als Hauptursache für Fehlfunde. Sie empfiehlt mehrere unabhängige Zeitabschnitte (CSCV/PBO, López de Prado). Der Rückwärtstest ist die günstigste Form davon. Er ersetzt den Vorwärtstest nicht, filtert aber die meisten Zufallsfunde, bevor man wochenlang wartet.

## 5. Regime-Brücke: sinnvoll?

**Stand im Live-System:**
- 14 Lab-Analysen, **keine Freigabe**, 0 Trades mit Struktur-Regime.
- 10 dynamische Strategien ruhen (Auto-Check aus).
- Ein Vorschlag vom 02.11. ist offen. Er sagt selbst: Kein Struktur-Regime ist klar positiv, 1.190 von 1.476 Trades fallen in „unbekannt“.
- Die Brücke zum KI-Trader läuft also derzeit ins Leere.
- Dahinter stehen rund 50 Regime-Module.

**Messtest an TrendFolge2:** 468 Trades vom 27.07. bis 06.11., chronologisch halbiert. Gelernt wird auf Hälfte 1, geprüft auf Hälfte 2.

| Filter | Hälfte 2 alle | Hälfte 2 nach Filter | Urteil |
|---|---|---|---|
| Kurzfrist-Regime (gesperrt: trend_up_normal, trend_down_ruhig, unbekannt) | −0,19 R | −0,21 R | hilft **nicht** |
| Nur Long (Short lief in Hälfte 1 schlechter) | −0,19 R | −0,24 R | dreht sich um |
| Mit/gegen Tagestrend | — | — | keine Trennung |

Außerdem verliert TrendFolge2 selbst: Hälfte 1 −0,05 R (t −0,7), **Hälfte 2 −0,19 R (t −2,8)**. Das liegt deutlich unter null.

**Urteil:**
- Regime-Erkennung ist **als Idee** sinnvoll. Die Fachliteratur findet den Nutzen vor allem beim **Risiko**: weniger Einsatz in ungünstigen Phasen und Volatilitäts-Steuerung. Persistente Modelle (Jump-Modelle) schlagen dabei klassische HMMs.
- In diesem System hat sich **kein** Richtungs-Nutzen gezeigt.
- Statt weiterer Erkennungs-Varianten fehlt ein **Messtest**: Hilft der Filter auf ungesehenen Trades?

**Vorschlag (nichts löschen):**
1. **Regime-Nutzen-Test** im Leitstand für jede Strategie und jedes Setup: lernen auf frühen Trades, prüfen auf späten (wie oben). Ein Regime-Filter darf nur aktiv werden, wenn er dort nachweislich hilft.
2. **Volatilitäts-Steuerung** der Positionsgröße für systematische Strategien: Einsatz ∝ Ziel-Vola ÷ aktuelle Vola. Belegt verbessert das das Verhältnis von Ertrag zu Risiko (Harvey u. a. 2018).
3. **Gute Regime finden:** wenige robuste Merkmale (Tages-Trend-Steigung, realisierte Volatilität, Funding-Perzentil), Mindest-Verweildauer gegen Flackern, Bewertung nur über die Wirkung auf Strategien **außerhalb der Stichprobe**, nicht über die Übereinstimmung mit dem Chart.
4. Die Regime-Brücke bleibt als „Experiment“ markiert, bis ein Messtest Nutzen zeigt. Den offenen Vorschlag vom 02.11. ablehnen (Begründung steht schon drin).

## 6. Wie wird die Website profitabel?

### Ehrlicher Stand

| Baustein | Stand |
|---|---|
| KI-Trader (1m-Detektoren + LLM-Prüfung) | kein Vorteil, auch brutto nicht (783 Trades: brutto ~−0,06 R; neu −0,53 R) |
| LLM-Auswahl | genommen −0,38 R gegen verworfen −0,30 R: keine Auswahl-Fähigkeit |
| TrendFolge2 (live) | −0,13 R über 352 Live-Trades, zuletzt −0,19 R (t −2,8) |
| Event-Setups | bester Pool t 1,58, nicht belegt |
| Endlossuche | Champions bisher ungeprüft (Fehler 2a, jetzt behoben). Echte Funde erst mit Worker 1.30.0 |

Die Infrastruktur (Daten, Backtester, Risiko, Leitstand) ist stark. **Es fehlt die Vorteils-Quelle.**

### Was die Forschung sagt

- **Zeitreihen-Momentum/Trendfolge** ist in Krypto der robusteste Befund. Querschnitts-Momentum ist schwach. Viele Varianten scheitern aber an Kosten und Liquidationen, wenn man realistisch rechnet (Han, Kang, Ryu).
- Trendfolge mit **längeren Haltedauern** (Tage bis Wochen) übersteht Kosten, kurzfristiges Umschichten nicht. Ensemble mehrerer Rückblick-Längen und Volatilitäts-Ziel sind Standard (Zarattini, Pagani, Barbon 2025).
- **Funding-Raten** sagen ihre eigenen Folgewerte stark voraus und Kursbewegungen schwächer. Am deutlichsten wirken sie in den Extremen, dort teils als Gegensignal.
- **LLM-Agenten** haben in Live-Wettbewerben überwiegend verloren, vor allem durch zu viel Handeln. Der Betreiber sagt selbst, man könne einem LLM noch nicht einfach Geld zum Handeln geben (Alpha Arena).
- **Kosten bei Bitunix:** Maker 0,02 %, Taker 0,06 %. Maker-Einstiege senken die Einstiegs-Kosten um zwei Drittel.

### Fahrplan (Vorschlag)

**F1: Ehrlichere Champions** (Abschnitte 2 und 4)
- Rückwärtstest, Fremd-Coin-Test, Richtungs-Check
- R-Vorzeichen in Training und Test, Tresor mit Ø R und mindestens 10 Trades
- Versuchs-Konto über Läufe
- neues Ziel „t-Wert (R)“ als Standard der Endlossuche
- Long/Short- und Coin-Aufteilung je Champion im Ergebnis

**F2: Mehr und bessere Lerndaten**
- **Virtuelle Signal-Bewertung:** Jedes Detektor-Signal, auch eines, das nur wegen Lern-Limits geblockt wurde, bekommt ein Ergebnis aus den Folge-Kerzen (TP/SL, brutto und netto). Ohne Positionen und Slots. Das liefert ein Mehrfaches an gelabelten Daten für Setups, Veto-Bilanz und ML.
- Richtungs-Limit nur für Lern-Trades (Paper) von 5 auf 10 je Klasse.
- **Detektoren auf 15m/1h im Lab testen:** Bei 1m liegt der natürliche Stop unter dem Fee-Minimum. Der Lab-Test zeigt, ob die Setups auf höherer Ebene einen Vorteil haben.
- Mehr Coins in der Forschung (20–30 je Klasse) und längere Historie (2–4 Jahre auf 1h/4h).

**F3: Neue Vorteils-Quellen**
- **Trend-Portfolio** als feste Strategie:
  - Zeitreihen-Momentum/Donchian-Ausbruch auf 4h/1d.
  - Ensemble aus 3–4 Rückblick-Längen.
  - Volatilitäts-Ziel je Coin, 13–30 Coins, Long/Short.
  - Wenige Trades, Maker-Einstieg.
  - Ehrlich geprüft mit Walk-Forward, Rückwärtstest und Vorwärtstest.
- **Positionierungs-Indikatoren** in der Endlossuche: Funding-Perzentil und Long/Short-Verhältnis-Perzentil aus `market_positioning` (ohne Blick in die Zukunft). Das erste Nicht-Preis-Signal der Suche.
- Nacht-Forschung um den Slot „Krypto 4h Trend“ erweitern.

**F4: Regime messen statt glauben** (Abschnitt 5)
- Regime-Nutzen-Test, Volatilitäts-Steuerung, Brücke als Experiment markieren.

**F5: Kapital-Regeln**
- Live nur nach bestandenem Vorwärtstest und Live-Toren.
- Start mit 0,25–0,5 % Risiko je Trade, steigern erst nach 100 Live-Trades mit Untergrenze > 0.
- TrendFolge2: Empfehlung **Paper** (Daten laufen weiter, kein Geldverlust). Die Entscheidung bleibt bei dir.

**Rolle der KI danach:**
- Sie prüft Signale nur dort, wo ihr Veto nachweislich hilft (gebaut).
- Sie erklärt Entscheidungen, fasst Nachrichten und Events zusammen und überwacht Risiken.
- Sie schlägt Forschungsaufträge vor.
- Einstiege kommen aus geprüften Systemen. Die KI darf nur dann selbst einsteigen, wenn sie in Paper einen Vorteil belegt.

## 7. Mehr Lerndaten: was wirklich hilft

| Hebel | Mehr Daten | Qualität | Aufwand |
|---|---|---|---|
| Virtuelle Signal-Bewertung (F2) | hoch (×3–5) | gleich wie Lern-Trades, ohne Slot-Grenzen | mittel |
| Lern-Richtungslimit 5 → 10 | mittel (×1,5–2) | Trades gleicher Richtung hängen zusammen | sehr klein |
| Lab wöchentlich (läuft) auf mehr Coins und 2 Jahren | hoch, historisch | ehrlich geprüft | klein |
| Mehr Coins live scannen | mittel | gut | mittel (Server-Last) |
| Mehr 1m-Lern-Trades | gering | schlecht: Kosten fressen den Vorteil | — |

Mehr Daten helfen nur, wenn die Daten zu einem handelbaren Vorteil führen können. Deshalb gehören F2 und F3 zusammen.

## 8. Zur Freigabe

1. **F1–F5 in dieser Reihenfolge bauen?** Mein Vorschlag: zuerst F1 + F2, da klein mit großer Wirkung, dann F3, dann F4/F5.
2. **TrendFolge2 auf Paper?** Empfehlung ja, wegen t −2,8 in der jüngeren Hälfte.
3. **Lern-Richtungslimit 5 → 10** (nur Paper) und virtuelle Signal-Bewertung?
4. **Trend-Portfolio:** Long/Short oder nur Long?
5. **Deine Such-Einstellungen** (Abschnitt 3) schon jetzt umstellen? Das geht ohne Code.

## Quellen

- Bailey, Borwein, López de Prado, Zhu: The Probability of Backtest Overfitting, J. of Computational Finance (2017) – https://escholarship.org/uc/item/4w1110bb
- Han, Kang, Ryu: Time-Series and Cross-Sectional Momentum in the Cryptocurrency Market – https://acfr.aut.ac.nz/__data/assets/pdf_file/0009/918729/Time_Series_and_Cross_Sectional_Momentum_in_the_Cryptocurrency_Market_with_IA.pdf
- Zarattini, Pagani, Barbon: Catching Crypto Trends (2025) – https://abarbon.com/papers/catching-crypto-trends
- Harvey u. a.: The Impact of Volatility Targeting (JPM 2018), Zusammenfassung – https://hedgefundalpha.com/strategies/volatility-targeting-improves-risk-adjusted-returns/
- Shu, Yu, Mulvey: Regime-Aware Asset Allocation: a Statistical Jump Model Approach (2024) – https://arxiv.org/abs/2402.05272
- Robot Wealth: Funding-Raten und Folge-Renditen – https://edgealchemy.robotwealth.com/p/hyperliquid-carry-looks-trendy
- Alpha Arena (Nof1), Live-Test von LLM-Händlern – https://www.kucoin.com/news/flash/ai-trading-models-struggle-in-live-market-tests-majority-of-systems-report-losses
- Bitunix-Gebühren – https://cryptodaily.co.uk/2026/06/bitunix-fees-spot-futures-vip-withdrawals
