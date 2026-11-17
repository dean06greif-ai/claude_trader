# Beobachtungen und offene Punkte (laufendes Protokoll)

Geführt von den automatischen Pflege-Läufen (geplante Aufgabe „Krypto-Website Pflege“) und von
Hand. Neueste Einträge oben. Einträge älter als 6 Wochen werden zu einer kurzen
Zusammenfassung verdichtet.

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
