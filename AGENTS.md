# Project knowledge

This file gives Freebuff context about your project: goals, commands, conventions, and gotchas. `knowledge.md` has the full detail.

## Quickstart
- Setup: `bash scripts/setup_env.sh` (creates `.venv`, installs `.[dev,3d]`)
- Dev: `source .venv/bin/activate && python -m plotdeck` (Demo button runs without hardware)
- Test: `QT_QPA_PLATFORM=offscreen pytest -q`
- Lint/format/types: `ruff check src tests`, `black --check src tests`, `mypy`
- Package: `bash packaging/build_app.sh` → `dist/PlotDeck.app`

## Architecture
- Key directories: `src/plotdeck/core/` (Qt-free transport, protocol, status, parser, streamer, controller), `src/plotdeck/ui/` (PySide6 widgets + `ControllerBridge` thread hop), `src/plotdeck/utils/`, `tests/` (includes in-process `fake_grbl.py`).
- Data flow: UI → `MachineController` → transport → GRBL; responses → controller → bridge signals (queued) → UI. Streamer state: IDLE → RUNNING ⇄ PAUSED → COMPLETED/STOPPED/ERROR.

## Conventions
- Formatting/linting: ruff (line length 100, E/F/I/UP/B/SIM), black 100, mypy on `src`. All must pass.
- Keep `core/` free of Qt imports and testable headless.
- Derive every control's enabled state in `MainWindow._update_actions`; colors only from `theme.py` tokens.
- Patterns to follow: character-counting streaming (127 bytes), callback-based core components, status-driven UI.
- Things to avoid: sending `M6` to GRBL, auto-continuing after `error:N`, treating real-time bytes as queue-acknowledged, blocking the UI thread on serial I/O.
