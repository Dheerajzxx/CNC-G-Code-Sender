# PlotDeck

A G-code sender and editor for small CNC routers running **GRBL 1.1** on an
Arduino Uno. macOS desktop app, Python + PySide6.

PlotDeck connects over USB serial, lets you edit and preview a G-code file,
streams it with GRBL's character-counting flow control, and gives you manual
control (jog, home, zero, overrides) with live position and toolpath feedback.

**New here? Read [USER_MANUAL.md](USER_MANUAL.md), or open it inside the app
from the Manual toolbar button or Help → User Manual (F1).**

## Features

- **Connection** — USB port discovery, 115200 baud default, GRBL banner
  detection (the Uno resets when the port opens), 5 Hz status polling, and a
  **Demo** mode that runs a simulated machine with no hardware.
- **Streaming** — 127-byte character-counting sender, pause/resume, safe stop
  (feed hold + soft reset), start from a line, and GRBL check mode (`$C`) dry
  runs.
- **Editor** — line numbers, G/M/axis/feed syntax colours, current-line and
  executed-line markers, error markers, find/replace, go-to-line, toggle
  comment, strip comments, renumber, and offset/scale/rotate transforms.
- **Visualizer** — 2D toolpath with executed (green) and remaining (dashed)
  paths, live tool position, fit-to-view, bounding box and time estimate.
  Optional 3D view when PyOpenGL is installed.
- **Machine control** — jog pad with step chips and keyboard control, work
  zeroing per axis, G54–G59 selection, homing, unlock, jog cancel, feed /
  rapid / spindle overrides, spindle on/off, and a Z-probe wizard.
- **Safety workflows** — pre-flight summary (time, bounds, depth, tools,
  warnings), `M6` interception with a tool-change pause, `error:N` pauses the
  job instead of blindly continuing, alarm dialog with unlock/home recovery,
  and automatic job-interrupted reporting on disconnect.
- **Settings** — editable `$$` table with descriptions, plus persistence of
  recent files, port, theme and window layout via QSettings.
- **Help** — the full user manual is bundled and rendered in-app from the
  **Manual** toolbar button or **Help → User Manual** (F1), with search and links.

## Requirements

- macOS (only platform tested), Python 3.10 or newer
- Arduino Uno with GRBL 1.1 and a CNC shield (for real hardware)
- Python packages: PySide6, pyserial, pyqtgraph, numpy
- Optional: PyOpenGL (3D view), PyInstaller (packaging)

## Setup

```bash
bash scripts/setup_env.sh      # creates .venv and installs .[dev,3d]
source .venv/bin/activate
```

Or manually:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev,3d]"
```

## Run

```bash
python -m plotdeck
```

Pick a `/dev/cu.usbmodem*` port (or `/dev/cu.usbserial*` for CH340 boards) and
press **Connect**. Click **Demo** to explore the interface without hardware.

## Typical workflow

1. Connect and wait for the state badge to read **IDLE**.
2. Home the machine, jog to the workpiece origin, and zero X/Y (and Z, or use
   **Machine → Probe Z…** with a touch plate).
3. Open a G-code file (⌘O or drag and drop). Check the toolpath preview.
4. Press **Run**. The pre-flight dialog shows the time estimate, bounding box,
   tools and warnings; **Dry run** uses GRBL check mode.
5. Watch progress in the Job panel; the editor follows the executing line.
   **Pause** sends feed hold, **Stop** (⌘.) sends feed hold then soft reset.
6. If GRBL returns `error:N`, the job pauses and asks whether to skip the line
   or abort. Insert tool changes when the M6 dialog appears.

> **Tool changes:** PlotDeck pauses and prompts for `M6`, but it does not
> automatically stop a manually switched spindle or retract Z. Turn the spindle
> off and raise Z before reaching in, then re-probe Z if the tool length
> changed. Only an automatic spindle relay wired to GRBL can be stopped by
> GRBL itself.

## Keyboard shortcuts

| Action | Shortcut |
| --- | --- |
| Open / Save | ⌘O / ⌘S |
| Find / Go to line | ⌘F / ⌘L |
| Run / Run from cursor | ⌘R / ⌘⇧R |
| Pause / Resume | toolbar (feed hold / cycle start) |
| Stop | ⌘. |
| Soft reset | ⌘⇧. |
| Toggle comment | ⌘/ |
| Connect / Disconnect | ⌘K |
| Fit toolpath | ⌘0 (or `F` with the preview focused) |
| Jog | arrows (X/Y), PgUp/PgDn (Z), `[` `]` step, Space cancel |

Jog keys only act while the jog panel has focus. The console accepts commands
when idle; during a job line commands are refused (real-time commands such as
`?` or `!` still work from a serial terminal, but the app controls them).

## Tests

```bash
source .venv/bin/activate
QT_QPA_PLATFORM=offscreen pytest -q
ruff check src tests
black --check src tests
mypy
```

The suite drives the core against an in-process GRBL simulator
(`tests/fake_grbl.py`) that enforces the 127-byte buffer, and includes headless
UI smoke tests (`pytest-qt`). CI runs the same checks on macOS.

## Packaging

```bash
bash packaging/build_app.sh
```

The built `dist/PlotDeck.app` was launched headlessly during development to
confirm the bundle starts (PySide6, pyqtgraph and the Qt platform plugins are
collected; PyOpenGL is included when installed).

This produces `dist/PlotDeck.app` via `packaging/plotdeck.spec`, and a `.dmg`
when `create-dmg` is installed. For distribution outside your own Mac, sign and
notarize with your Apple Developer identity:

```bash
codesign --deep --options runtime --sign "Developer ID Application: …" dist/PlotDeck.app
xcrun notarytool submit … --wait
xcrun stapler staple dist/PlotDeck.app
```

## Architecture

```
src/plotdeck/
├── core/            # no Qt imports; unit-testable headless
│   ├── transport.py     # Transport ABC, SerialTransport thread, MockTransport
│   ├── grbl_protocol.py # real-time bytes, response classifier, error tables
│   ├── status.py        # <...> status reports → MachineStatus
│   ├── gcode_parser.py  # cleaning, tokenizing, toolpath + time estimate
│   ├── streamer.py      # character-counting job state machine
│   └── controller.py    # MachineController orchestration
├── ui/              # PySide6 widgets
│   ├── main_window.py   # layout, menus, shortcuts, state-driven enablement
│   ├── editor.py        # editor, gutter, highlighter, find bar
│   ├── console.py       # colour-coded console + history
│   ├── status_panel.py  # DRO, state badge, override sliders
│   ├── jog_panel.py     # jog pad, zeroing, WCS
│   ├── visualizer.py    # 2D/3D toolpath preview
│   ├── job_panel.py     # progress and timing
│   ├── dialogs.py       # pre-flight, tool change, probe, settings
│   └── theme.py         # colour tokens and QSS
└── utils/           # settings (QSettings) and logging
```

The UI never touches the serial port. Controller callbacks are marshalled to
the main thread through a small `QObject` signal bridge. The controller and
streamer are plain Python, so tests and CLI use do not need a Qt event loop.

## GRBL notes

- Buffer size is 127 usable bytes; lines are counted as `len(line) + 1`.
- Real-time bytes (`?`, `!`, `~`, `0x18`, `0x85`, override bytes) bypass the
  queue and never produce `ok`.
- Manual commands are acknowledged separately from the job stream, so a `$C`
  or `$H` ok cannot corrupt buffer accounting.
- `M6` is never forwarded (GRBL would return `error:20`); the streamer pauses,
  the UI prompts, then the job resumes after the tool change.
- On soft reset the streamer clears its queue and pending bytes and the app
  re-syncs from the next status report.

## Limitations / not implemented

- Only GRBL 1.1 is supported; Marlin/FluidNC are out of scope.
- No CAM: PlotDeck sends G-code produced elsewhere.
- No auto-reconnect, macros editor, tool/material library, or height-map
  leveling (post-1.0 in the plan).
- The 3D view requires `PyOpenGL` (`pip install -e ".[3d]"`); without it the
  3D button reports that the view is unavailable.
- Clicking a toolpath segment does not jump to its line yet.
- Find/replace is literal text, not regular expressions; hover documentation
  and G/M-code autocomplete are not implemented.
- Continuous (hold-to-jog) motion and saved macros are not implemented.
- The app icon is optional; drop `packaging/icon.icns` in place before building
  if you want one.

## Safety

This software controls a machine that can injure you. Wear eye protection,
secure the workpiece, know where the power switch is, and keep a hand near it
for the first cut. A software stop is **not** an emergency stop — wire a
hardware e-stop that cuts motor and spindle power. Test with the tool
disconnected or raised before cutting material.
