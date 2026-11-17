#!/bin/bash
# Offline-Testlauf für Sandboxen ohne Netzwerk/fehlende Pakete (Claude-Läufe).
# Aufruf:  bash backend/tests/offline/run_tests.sh /tmp/tests.txt
# Ergebnis: letzte pytest-Zeile + Liste der Tests, die NEU gegenüber
# baseline_failures.txt fehlschlagen (die Baseline sind reine Umgebungs-Fehler,
# z. B. fehlendes fastapi/openai in der Sandbox – in Produktion laufen sie).
HERE="$(cd "$(dirname "$0")" && pwd)"
BACKEND="$(cd "$HERE/../.." && pwd)"
OUT="${1:-/tmp/offline_tests.txt}"
cd "$BACKEND" || exit 1
PYTHONPATH="$HERE/stubs" PYTHONDONTWRITEBYTECODE=1 MONGO_URL= DB_NAME=sandbox_none \
  timeout 900 python3 -m pytest -p no:cacheprovider -c /dev/null --rootdir=. tests \
  -m "not live" --continue-on-collection-errors -q --maxfail=100000 \
  -o markers="unit: u
live: l" -rfE --tb=short > "$OUT" 2>&1
tail -1 "$OUT"
grep -E "^(FAILED|ERROR) " "$OUT" | awk '{print $2}' | sort -u > "$OUT.fail"
echo "Neu fehlgeschlagen gegenüber baseline_failures.txt:"
comm -13 "$HERE/baseline_failures.txt" "$OUT.fail"
