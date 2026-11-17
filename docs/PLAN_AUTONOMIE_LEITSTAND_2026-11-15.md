# Vorschlag: Autonom lernender KI-Trader + Leitstand (15.11.2026)

Status: **umgesetzt am 16.11.2026** (Phasen A–D), Details in `AENDERUNGEN_2026-11-15.md`, Abschnitt „Leitstand und Autonomie“.
Grundlage sind die Live-Daten der Produktion (nur gelesen), der Code und die heutigen Analysen.

---

## 1. Ehrliche Lage

- Die Verbesserungen von heute stoppen vor allem das **systematische Verlieren**: Gebühren, Liquidationen, Gegentrend-Trades und freie KI-Trades. Außerdem sorgen sie dafür, dass ein **Scheinvorteil nicht mehr live geht**.
- **Einen Vorteil erzeugen sie nicht.** Der kann nur aus Forschung kommen, also aus Setups oder Strategien, die sich im Test **und** danach im Paper-Betrieb bewähren.
- Ein autonomer, lernender KI-Trader braucht deshalb vor allem drei Dinge:
  1. einen Kreislauf, der laufend neue Ideen erzeugt und ehrlich prüft
  2. Kapital nur für Belegtes
  3. eine Ansicht, in der man sieht, ob das funktioniert

### Was die Verbesserungen bringen (rückwirkend auf die 783 KI-Trades gerechnet)

| Stand | Trades | Ø Ergebnis je Trade |
|---|---|---|
| bisher | 783 | **−0,33 R** (t −8,2) |
| + Paper-Liquidationen als Stop abgerechnet | 783 | −0,32 R |
| + ohne freie KI-Trades (Prüfer-Modus) | 699 | −0,32 R |
| + ohne Sammel-Trades gegen den Tagestrend | 452 | −0,29 R |
| + nur Trades, deren Gebühr ≤ 10 % des Risikos war | 91 | **+0,02 R** |
| davon nur Krypto (Gebühr ≤ 13 %) | 114 | +0,09 R (t 0,85, nicht belegt) |

- **Einschränkung:** Die Gebühren-Regel filtert nicht nur, sie erweitert auch zu enge Stops. Die letzten zwei Zeilen sind deshalb eher optimistisch.
- **Realistische Erwartung:** von −0,33 R auf etwa −0,1 bis 0 R je Trade. Aus „verliert sicher“ wird also „ungefähr null“. Profit ist damit nicht belegt.
- **Sichtbar wird das nach etwa 100–200 neuen Trades.** Beim bisherigen Tempo sind das 1–2 Wochen, mit den strengeren Regeln eher etwas länger. Dafür braucht es den Stichtag (Abschnitt 5) und die Vorher/Nachher-Kachel (Abschnitt 3).

---

## 2. Der Lern-Kreislauf: was es gibt und was fehlt

| Baustein | Stand | Was fehlt |
|---|---|---|
| **Messen:** Ergebnis in R, Gebühren, Veto-Bilanz, Markt-Benchmark | ✅ seit heute | Sichtbarkeit (Leitstand) |
| **Sauber trennen:** alte gegen neue Regeln | ❌ | Bewertungs-Stichtag (Phase A) |
| **Ideen erzeugen:** Detektoren, KI-Setups aus 4 Quellen, Endlossuche, Lab | ✅ vorhanden, läuft aber nur von Hand oder ist aus (Lab-Automatik seit September aus) | Nacht-Forschung, die selbstständig plant und rotiert (Phase C) |
| **Ehrlich prüfen:** Signifikanz, Tresor-Daten, Walk-Forward, Event-Ebene | ✅ seit heute | – |
| **Vorwärtstest:** Kandidat läuft als Paper weiter, bevor er live darf | teilweise (Setups ja, Strategien aus der Suche nein) | Kandidaten-Pipeline mit Fortschritt (Phase C) |
| **Aussortieren:** hoffnungslose KI-Setups, Lektionen ohne Beleg | ✅ seit heute | Wächter für verlierende **Live-Strategien** (Phase D) |
| **KI lernt, wo sie hilft:** Veto-Wert je Setup | ✅ gemessen | KI-Prüfungen gezielt dort einsetzen, wo das Veto nachweislich Wert hat; spart Kosten (Phase D) |
| **Kapital nur für Belegtes:** Live-Tore 30 Trades + Untergrenze | ✅ | – |

---

## 3. Der Leitstand: ein Fenster für alles Wichtige

Ein Knopf „Leitstand“ in der Kopfzeile öffnet ein Fenster mit fünf Bereichen. Alles ist **regelbasiert aus vorhandenen Daten** berechnet, ohne zusätzliche KI-Kosten.

1. **Jetzt:**
   - was der KI-Trader gerade tut (prüft Signal X, wartet, nächster Lauf um …)
   - offene Signal-Fenster und offene Trades mit Grund
   - die letzten 5 Entscheidungen in einem Satz
   - LLM-Aufrufe und Kosten heute
2. **Fortschritt zum Ziel:**
   - Zähler „Setups/Strategien mit belegtem Vorteil“ (heute: 0)
   - Kandidaten in Prüfung mit Fortschrittsbalken (z. B. crypto_security_breach: Trades bis Urteil, aktueller t-Wert)
   - **Vorher/Nachher seit Stichtag:** Ø R, Gebühren je Trade, Liquidationen, Anteil Gegentrend
3. **Neu:** Zeitleiste der letzten 7 Tage:
   - neue oder ausgemusterte KI-Setups
   - Lab-Ergebnisse
   - Endlossuche-Champions und Beinahe-Treffer
   - Lektions-Änderungen
   - Live-Freigaben und Rückstufungen
   - Forschungs-Bericht (Kurzfassung)
4. **Mängel – muss repariert werden** (der „Systemarzt“, siehe Abschnitt 4), nach Dringlichkeit sortiert und jeweils mit „was tun“. Beispiele aus heute:
   - Worker veraltet (1.27.0)
   - Live-Bypass bei hoher Konfidenz ist **an**: Die Konfidenz ist nachweislich nicht aussagekräftig, Empfehlung: aus.
   - Ein kostenloses Modell trifft die Prüf-Entscheidungen.
   - Forex-Kurse veraltet
5. **Empfehlungen – was du tun kannst, um einen Vorteil zu finden**, regelbasiert und mit Knopf, wo es gefahrlos geht. Beispiele aus den heutigen Daten:
   - „TrendFolge2 handelt live mit −0,13 R je Trade (352 Trades, t −2,4): pausieren oder neu prüfen“
   - „Seit X Tagen keine Endlossuche für Rohstoffe: mit empfohlenen Einstellungen starten“
   - „N Lab-Setups aus dem Altbestand ungeprüft: Lab-Lauf starten“
   - „crypto_security_breach braucht noch N Trades bis zum Urteil“
   - „CPI am 10.12.: Event-Daten werden gesammelt“

**Kosten:** 0 zusätzliche KI-Aufrufe.
**Optional:** 1 kurzer Tagesbericht pro Tag mit einem günstigen Modell, als Telegram-Nachricht.

---

## 4. Fehlersuche, ohne einen teuren „Website-Agenten“

Ein KI-Agent, der regelmäßig die Seite durchklickt, wäre teuer und fehleranfällig. Er würde meist nur finden, was billige Prüfungen auch finden. Stattdessen schlage ich drei Ebenen vor:

1. **Systemarzt, alle 15 min, ohne KI.** Er bündelt die vorhandenen Prüfungen:
   - Self-Test
   - Sicherheits-Ampel
   - Live-Diagnose
   - Hauptschleifen-Wächter

   Neu dazu kommen:
   - Worker-Version
   - Daten-Frische, abhängig von den Handelszeiten (keine Fehlalarme am Wochenende)
   - fehlgeschlagene Jobs der letzten 24 h
   - Fehler und Guthaben bei den KI-Anbietern
   - Datenbank-Speicher (heute 57 %)
   - Kalender-Reichweite
2. **Fehler direkt aus dem Browser:** Die Website meldet eigene Abstürze und fehlgeschlagene Server-Anfragen an den Server, gedrosselt und 7 Tage gespeichert. Im Leitstand steht dann z. B. „Optimizer-Fenster: 3× Fehler ‚…‘ seit gestern“. Das findet echte Fehlerquellen auf der Website, die kein Server-Check sieht.
3. **Tiefenprüfung bei Bedarf:** so wie heute durch mich, wenn ihr eine Analyse anstoßt.

---

## 5. Alte Daten: löschen, archivieren oder per Stichtag trennen

| Was | Vorschlag | Grund |
|---|---|---|
| Bestenliste der Endlossuche (Top-5 aus August) | **löschen** | Dort ist das Test-Ergebnis identisch mit dem Trainings-Ergebnis. Die Kombinationen bestehen aus den immer-wahren Regeln („ATR > 0,05 %“, „BB-Breite > 0,3 %“). Eindeutig falsch. |
| Forschungs-Erkenntnisse und Ideen im KI-Gedächtnis vor dem Stichtag (962 + 450) | **archivieren** (ausblenden, wiederherstellbar) | Beruhen auf der alten, zu laxen Validierung |
| Offene Lektions-Kandidaten aus der Zeit vor der Bereinigung | **löschen** | Könnten alte Muster wieder hochspülen |
| Trades (1.369) | **behalten**, aber **Bewertungs-Stichtag** setzen | Lernlauf, Live-Tore, Lektions-Bilanz, Veto-Bilanz und Konfidenz-Kalibrierung zählen ab dem Stichtag. Die alten Trades wurden mit Stops gemacht, die heute nicht mehr erlaubt sind; sie würden die KI „lernen“ lassen, dass alles verliert. Auswertungen können zwischen „seit Stichtag“ und „alles“ umschalten. |
| Kerzendaten, Backtests, Regime-Analysen, Strategien | behalten | Sind Rohdaten bzw. eure Arbeit. Strategien aus alten Suchen bekommen nur den Hinweis „mit alter Validierung gefunden – neu prüfen“. |
| Lektionen, Lab-Altbestand, Event-Ergebnisse | erledigt (heute) | bereinigt bzw. neu bewertet |

Speicherplatz ist kein Grund zum Löschen: Die Datenbank ist zu 57 % voll, und die automatische Aufbewahrungsregel läuft.

---

## 6. Plan in Phasen

**Phase A – Saubere Ausgangslage** (klein)
1. Bewertungs-Stichtag `evaluation_since` (Standard: Zeitpunkt des Deploys). Er gilt für Lernlauf, Live-Tore, Lektions-Bilanz, Veto-Bilanz und Kalibrierung.
2. Einmalige Bereinigung: Bestenliste löschen, Gedächtnis archivieren, alte Kandidaten löschen. Läuft als Boot-Migration, protokolliert.
3. Live-Diagnose an die neuen Regeln anpassen. Ein Beispiel für veralteten Text: „Empfehlung Faktor ≥ 6“, obwohl längst 10 gilt.

**Phase B – Leitstand v1** (mittel)
1. Backend: `GET /api/cockpit` bündelt alle fünf Bereiche (regelbasiert).
2. Systemarzt-Prüfungen plus Browser-Fehlermeldungen (`POST /api/client-errors`).
3. Frontend: Knopf in der Kopfzeile und Fenster mit den fünf Bereichen. Empfehlungen mit Knopf, wo es gefahrlos geht (Suche starten, Lab starten, Worker-Hinweis).

**Phase C – Forschungs-Motor** (mittel)
1. **Nacht-Forschung:** pro Nacht eine Endlossuche mit empfohlenen Einstellungen, rotierend über Klasse und Timeframe. Sie läuft über die vorhandene Nacht-Serie auf dem lokalen Worker, nur wenn er online und aktuell ist.
2. **Lab-Automatik** wöchentlich wieder an, jetzt mit der ehrlichen Validierung und begrenzten KI-Revisionen.
3. **Kandidaten-Pipeline:** Champion, Lab-Setup oder KI-Setup durchlaufen Vorwärtstest (Paper) → Urteil → Live, mit Fortschritt im Leitstand. Live geht nichts ohne die bestehenden Tore.

**Phase D – Lernen schärfen** (klein bis mittel)
1. KI-Prüfungen dort einsetzen, wo ihr Veto nachweislich Wert hat. Bei Setups ohne messbaren Veto-Wert laufen die Signale nur als Regel-Paper und kosten keinen KI-Aufruf.
2. Wächter für Live-Strategien: Liegt die Untergrenze nach mindestens 50 Live-Trades unter 0, kommt eine Empfehlung im Leitstand; automatisches Pausieren nur, wenn ihr es freigebt.
3. Optional: Tagesbericht (1 günstiger KI-Aufruf pro Tag).

Jede Phase bekommt Tests und den Self-Test, die Ordnerstruktur bleibt. Bauen würde ich in der Reihenfolge A → B → C → D. A und B machen die Wirkung sichtbar, C und D erhöhen die Chance auf einen echten Vorteil.

---

## 7. Entscheidungen, die ich von euch brauche

1. **Umfang:** alle Phasen A–D oder zuerst nur A + B?
2. **TrendFolge2 live** (−0,13 R je Trade, 352 Trades, t −2,4, aktuell kleine Beträge): pausieren, neu prüfen oder weiterlaufen lassen?
3. **Champions der Nacht-Forschung:** automatisch als Paper-Kandidat in den Vorwärtstest übernehmen? Empfehlung: ja, live nie automatisch.
4. **Tagesbericht** per KI (≈ 1 Aufruf pro Tag): ja oder nein?
5. **Live-Bypass bei hoher Konfidenz:** ausschalten? Empfehlung: ja.
