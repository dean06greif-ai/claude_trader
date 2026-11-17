# Offline-Prüfung (Sandbox ohne Netzwerk)

Für automatische Claude-Läufe und lokale Schnellchecks, wenn nicht alle Pakete installiert
sind. Produktion (Render) nutzt diesen Ordner nicht.

- `bash backend/tests/offline/run_tests.sh /tmp/tests.txt` – komplette Test-Suite, meldet nur
  Tests, die **neu** gegenüber `baseline_failures.txt` fehlschlagen. Die Baseline enthält reine
  Umgebungs-Fehler (fehlendes fastapi/openai/motor in der Sandbox).
- `node backend/tests/offline/jscheck.js frontend/src` – Syntax aller Frontend-Dateien und
  Auflösung relativer Importe.
- `stubs/` – Minimal-Ersatz für Pakete ohne Netzwerkzugang (nur per PYTHONPATH im Testlauf).

Nach einer bewussten Änderung an der Umgebung die Baseline neu erzeugen:
`cp /tmp/tests.txt.fail backend/tests/offline/baseline_failures.txt`.
