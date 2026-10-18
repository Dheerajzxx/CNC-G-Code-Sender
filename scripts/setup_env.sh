#!/usr/bin/env bash
# Create .venv (if needed) and install PlotDeck with development tooling.
set -euo pipefail

cd "$(dirname "$0")/.."

if ! command -v python3 >/dev/null 2>&1; then
    echo "python3 was not found. Install Python 3.10 or newer first." >&2
    exit 1
fi

python3 - <<'PY' || { echo "Python 3.10 or newer is required." >&2; exit 1; }
import sys
raise SystemExit(0 if sys.version_info >= (3, 10) else 1)
PY

echo "Python OK: $(python3 --version)"

if [ ! -d .venv ]; then
    echo "Creating .venv"
    python3 -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate

python -m pip install --upgrade pip
python -m pip install -e ".[dev,3d]"

echo
echo "Setup complete. Activate the environment with:"
echo "    source .venv/bin/activate"
echo "Then run:"
echo "    python -m plotdeck"
echo "    pytest"
