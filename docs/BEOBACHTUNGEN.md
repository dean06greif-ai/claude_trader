# Beobachtungen und offene Punkte (laufendes Protokoll)

Geführt von den automatischen Pflege-Läufen (geplante Aufgabe „Krypto-Website Pflege“) und von
Hand. Neueste Einträge oben. Einträge älter als 6 Wochen werden zu einer kurzen
Zusammenfassung verdichtet.

## 2026-11-17 (spät, von Hand)

**Kennzahlen:**
- KI-Trader, Tagesbilanz (geschlossen): 12.11. −0,58 R · 13.11. −0,46 R · 14.11. −0,16 R ·
  15.11. −0,23 R · 16.11. −0,42 R · 17.11. −0,19 R.
- Seit den Fixes (eröffnet ab 16.11. 16 Uhr): 45 Trades, −0,06 R netto, +0,03 R vor Gebühren,
  53 % Gewinner. Das ist kein Beleg für einen Vorteil (t −0,4), aber deutlich weniger Verlust als
  vorher (~−0,5 R).
- 15 offene KI-Trades mit +274 USDT unrealisiert (Paper).
- Live-Portfolio: Der Positions-Wächter sieht 14 Börsen-Positionen, alle dem Portfolio
  zugeordnet. Kein SL fehlt, keine Fehler.

**Fehler behoben (vom Trader gemeldet):**
- TP1 und TP-Full lagen bei 11 von 15 offenen KI-Trades auf demselben Kurs. Ursache:
  Detektoren liefern TP1 1 R / TP-Full 1,5 R, das CRV-Minimum 1,5 hob nur TP1 an. Jetzt folgt
  TP-Full im selben Verhältnis. Die Karte zeigt das echte R statt der Coin-Einstellung.
- Die Analyse-Statistik (PnL, Anzahl, Performance je Strategie) rechnete nur über die geladenen
  Trades. Jetzt kommt sie vom Server über alle Trades (`/api/autotrade/trade-summary`).

**Offen / beim nächsten Lauf prüfen:**
- Neue KI-Trades: Liegen TP1 und TP-Full auseinander? Wirkt sich der weitere TP-Full auf das R aus?
- Bewertungs-Stichtag im Leitstand auf den 17.11. 19:45 setzen. Das entscheidet der Trader;
  danach zählt die Prüfer-Bilanz nur saubere Daten.

## 2026-11-17 (Abend, von Hand)

**Kennzahlen (Produktion, nur lesend):**
- Analyst/Prüfer (GPT-6 Luna Pro): 220 Aufrufe, ~4,8 Mio. Tokens am 17.11.
- OpenRouter-Hauptguthaben: 7,44 $. Die Reichweiten-Anzeige liefert erst ab ~12 h Verlauf Werte.
- Prüfer seit dem Fix: 20 Signale geprüft, alle mit echter Begründung (kein „bereits offen“
  mehr). Fast alle waren Long-Signale gegen den Abwärtstrend (safe_haven_flow) und wurden
  abgelehnt.
- Portfolio (Rückrechnung, vorsichtig): 19 Shorts, alle im Plus. Funding-Korb 8 long / 8 short.
- TrendFolge2: vom Live-Wächter gestoppt (seit November −0,45 R).
- Trades außerhalb der Website („external“): 30 Trades, −1.088 USDT.

**Geändert heute:**
- KI-Prüfung entfällt für klare Gegentrend-Signale (LONG bei Tages-Bias down, SHORT bei up).
  Diese Signale können weder live gehen (Edge-Filter) noch einen Kontroll-Trade bekommen.
  Erwartung: deutlich weniger Analyst-Aufrufe in Trendphasen.
- Offline-Prüfkit `backend/tests/offline/` (Tests ohne Netzwerk, Frontend-Syntaxcheck).

**Beim nächsten Lauf prüfen:**
1. Analyst-Aufrufe pro Tag nach der Gegentrend-Sperre (vorher ~200/Tag).
2. KI-geprüfte Trades (`ki_geprueft`) und Veto-Bilanz: Gibt es erste Einstiege mit dem Trend?
3. Guthaben-Reichweite (`key_credits.runway_days`, `burn_usd_day`).
4. Nachtsuche: Ergebnisse auf dem Local Worker (`/api/optimizer/history`,
   `/api/optimizer/explore/best`). Neue Rotation: Krypto 1h Trend → 1h → 15m.
5. Fehler/Leerantworten (`/api/ai/providers/health` → `recent_failures`).

**Offene Ideen (noch nicht gebaut):**
- Limit- statt Marktorders im Live-Portfolio (geschätzt +3–4 Prozentpunkte pro Jahr). Betrifft
  die Live-Ausführung, deshalb nur als Pull Request.
- `review_allocation`: Wenn die KI ein Setup nie nimmt („genommen“ = 0), wird dauerhaft
  geprüft. Eine Stichproben-Regel wäre günstiger. Erst nach 1–2 Wochen sauberer Daten
  entscheiden.
- Not-Aus des Live-Portfolios (30 %) passt nicht ganz zu 1 % Risiko je Trade (Rückgänge bis
  44 % ab 2025). Das entscheidet der Trader.
