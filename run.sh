#!/usr/bin/env bash
# One command to run the simulator. No pip install, no build step: Python 3.9+ standard library only.
#   ./run.sh            start on port 8080 and open a browser
#   PORT=9000 ./run.sh  use another port
#   ./run.sh --test     run the test suite and a headless expert case, then exit
set -euo pipefail
cd "$(dirname "$0")"
PY="${PYTHON:-python3}"
command -v "$PY" >/dev/null || { echo "python3 not found. On DGX OS / Ubuntu: sudo apt install -y python3"; exit 1; }
"$PY" - <<'PYEOF'
import sys
if sys.version_info < (3, 9):
    sys.exit(f"Python 3.9 or newer is required (found {sys.version.split()[0]}).")
PYEOF
if [[ "${1:-}" == "--test" ]]; then
  "$PY" -m unittest discover -s tests
  "$PY" scripts/play_case.py
  exit 0
fi
OPEN="--open"
[[ -z "${DISPLAY:-}${WAYLAND_DISPLAY:-}" && "$(uname)" == "Linux" ]] && OPEN=""   # headless / over SSH: just print the URL
exec "$PY" -m perfusion.server --port "${PORT:-8080}" $OPEN "$@"
