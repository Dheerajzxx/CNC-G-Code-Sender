#!/usr/bin/env bash
# Build dist/PlotDeck.app. Run from an activated project environment.
set -euo pipefail

cd "$(dirname "$0")/.."

if ! python -c "import PyInstaller" >/dev/null 2>&1; then
    echo "PyInstaller is missing. Run: python -m pip install -e '.[dev,3d]'" >&2
    exit 1
fi

python -m PyInstaller --noconfirm --clean packaging/plotdeck.spec
echo "Built dist/PlotDeck.app"

if command -v create-dmg >/dev/null 2>&1; then
    create-dmg --volname PlotDeck --window-size 600 400 \
        --icon "PlotDeck.app" 150 190 --app-drop-link 450 190 \
        dist/PlotDeck-1.0.0.dmg dist/PlotDeck.app || true
    echo "DMG (if create-dmg succeeded): dist/PlotDeck-1.0.0.dmg"
else
    echo "Install create-dmg (brew install create-dmg) to produce a .dmg."
fi
