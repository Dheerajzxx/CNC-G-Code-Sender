# Project knowledge — PlotDeck

## What this is
PlotDeck is a macOS desktop **G-code sender and editor** for a small CNC router driven by an Arduino Uno running **GRBL 1.1** over USB serial. Python 3.10+, PySide6 (Qt 6), pyserial, pyqtgraph, numpy. It streams files with GRBL's 127-byte character-counting flow control, edits and previews toolpaths, and provides jog/zero/override/probing controls plus a Demo machine.

`GOAL.md` is the original consolidated development plan and remains the product/UX reference (phases, palette, control-enablement table, router specifics). `USER_MANUAL.md` is the end-user guide and is also rendered in-app via **Help → User Manual** (`ui/manual.py`, bundled as PyInstaller data); `README.md` covers install/build. The implementation follows the plan; where the app deviates, the README lists the limitation.

## Commands
| Task | Command |
|---|---|
| Setup | `bash scripts/setup_env.sh` (creates `.venv`, installs `.[dev,3d]`) |
| Activate | `source .venv/bin/activate` |
| Run app | `python -m plotdeck` or `plotdeck` |
| Test | `QT_QPA_PLATFORM=offscreen pytest -q` |
| Lint / format / types | `ruff check src tests` · `black --check src tests` · `mypy` |
| Package | `bash packaging/build_app.sh` → `dist/PlotDeck.app` |
| Demo mode | Click **Demo** in the toolbar (no hardware) |

## Architecture
Three layers with dependencies pointing down; `core/` imports no Qt.
- `src/plotdeck/core/` — `transport.py` (Transport ABC, threaded `SerialTransport`, async `MockTransport`), `grbl_protocol.py` (bytes, response classifier, error/alarm tables), `status.py` (`MachineStatus` + parser with WCO tracking), `gcode_parser.py` (cleaning, tokenizer, modal toolpath + arcs + time estimate), `streamer.py` (character-counting job state machine), `controller.py` (`MachineController`, status polling, manual-command ack tracking).
- `src/plotdeck/ui/` — `main_window.py` (layout/menus/shortcuts/enablement, `ControllerBridge` QObject marshals controller callbacks to the GUI thread), `editor.py`, `console.py`, `status_panel.py`, `jog_panel.py`, `visualizer.py` (2D pyqtgraph, optional PyOpenGL 3D), `job_panel.py`, `dialogs.py`, `connection_panel.py`, `theme.py`.
- `src/plotdeck/utils/` — `settings.py` (`AppSettings` wrapper over QSettings; accepts an INI path for tests), `logging_setup.py` (rotating log in `~/Library/Logs/PlotDeck/`).

Data flow: UI → controller → transport → GRBL; responses → controller → bridge signals → UI. The streamer does not own routing; the controller decides whether an `ok` acknowledges a job line or a manual command.

## Conventions
- UI colors come only from `theme.py` tokens; light/dark palettes both supported.
- Control enablement is derived centrally in `MainWindow._update_actions` from connection, `MachineStatus.family`, and streamer state — do not enable/disable controls ad hoc.
- Monospace for code, console, DRO values; compact custom widgets.
- Tests are table-driven with real GRBL strings; streamer/controller tests run against `tests/fake_grbl.py`.
- `core/` must stay Qt-free so headless tests and future CLI use work.

## Gotchas
- **127-byte RX buffer** (not 128); count each line as `len(line) + 1` for `\n`.
- **Real-time bytes** (`?`, `!`, `~`, `0x18`, `0x85`, override `0x90–0x9E`) bypass the queue and never return `ok`.
- **Manual ack accounting**: controller tracks `_manual_acks` so a `$C`/`$H` ok arriving after a job starts is not credited to a streamed line. Reset on banner/alarm/disconnect.
- **Uno resets on serial open**: wait ~2 s, flush, then treat the `Grbl 1.1h` banner as "connected".
- **`error:N` pauses** the streamer (and sends feed hold); never auto-continue. **`ALARM`** aborts the job.
- **Stop** = `!` then `0x18`, clear queue/pending, then re-sync from status.
- **`M6` is intercepted** and never forwarded; wait for the planner to drain, pause, prompt, then resume.
- **Tool change line limit / block length** is 80 chars; the editor flags longer lines.
- Status parser treats a missing WCO with no history as zero; otherwise it tracks the last WCO to derive WPos/MPos.
- Demo `MockTransport` acknowledges lines on a worker thread, never synchronously, to avoid re-entrant streamer pumping.
- 3D import is lazy and optional; never construct `GLViewWidget` in headless tests.

## Test layout
`tests/test_status.py`, `test_gcode_parser.py`, `test_streamer.py`, `test_controller.py`, `tests/fake_grbl.py`, and `test_ui_smoke.py` (pytest-qt, offscreen). UI smoke tests use an INI `AppSettings` path so they never write user preferences.
