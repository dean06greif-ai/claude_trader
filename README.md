# MarketMaker (MM)

Multi-Asset-Daytrading-Plattform (Krypto, Indizes, Rohstoffe, Forex) mit KI Trader,
Strategie-Labor, Regime-Lab und Regime-Copilot.

- `backend/` – FastAPI (Render Web Service, `uvicorn server:app`)
- `frontend/` – React/CRACO (Render Static Site, `yarn build`)
- `local_worker/` – optionaler lokaler Rechen-Worker
- `ibeam_gateway/` – IBKR-Gateway (separater Render-Service)

Hinweis: Der Datenbank-Name (`DB_NAME`) und alle Env-Keys bleiben unverändert,
nur der Anzeigename lautet MarketMaker (MM). Für den OpenRouter-Header kann
`OPENROUTER_TITLE="MarketMaker"` gesetzt werden.

## Dokumentation und Prüfwerkzeug

- `docs/` – Handbücher (Regime-Lab, Strategie-Labor, KI-Labor, IBKR-Setup, Testen) und
  `docs/AENDERUNGEN_2026-11-15.md` (was beim Aufräumen und bei der Validierung geändert wurde).
- `backend/scripts/systemcheck.py` – vier Prüfungen, alle nur lesend bzw. lokal
  (Aufruf aus `backend/`):
  - `python -m scripts.systemcheck stats` – Kennzahlen der echten Trades (Ø R, Streuung, t-Wert)
  - `python -m scripts.systemcheck live --url https://…` – laufende Instanz abfragen
  - `python -m scripts.systemcheck noise` – Zufalls-Benchmark der Strategie-Suche (erwartet: 0 Champions)
  - `python -m scripts.systemcheck selftest` – Selbsttest der Kernlogik
  - `python -m scripts.systemcheck tests` – Offline-Tests
- Selbsttest im Betrieb: läuft nach jedem Start (Ergebnis im Log, Fehler per Telegram);
  jederzeit abrufbar über `GET /api/selftest` (Admin).

Optionale Env-Variable: `FAST_PRICE_WATCH=1` startet den schnellen Preis-Wächter
(`services/price_watch.py`, Takt über `FAST_PRICE_INTERVAL`, Standard 3 s).
