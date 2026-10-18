# PlotDeck: G-code Sender & Editor, Final Development Plan

**Target:** macOS desktop app, Python (PySide6), controlling a small CNC router via an Arduino Uno running GRBL 1.1
**Working name:** `PlotDeck` (rename freely)
**Status:** Final consolidated plan (core plan + UI/UX spec + CNC router specifics)

## Contents
1. Goals and Scope
2. Tech Stack
3. Hardware and Environment Setup
4. Architecture
5. GRBL Protocol Cheat Sheet
6. Development Phases (0-10)
7. Testing Strategy
8. Key Design Decisions and Pitfalls
9. Milestone Summary
10. Post-1.0 Ideas
11. Reference Resources
12. Suggested First Steps
13. UI/UX Design Specification
14. CNC Router Specifics (probing, tool changes, spindle, safety)
15. Tool and Material Library (post-1.0)
16. Uno Hardware Notes
17. Final Build Order

---

## 1. Goals and Scope

### Goals
- Connect to an Arduino Uno (GRBL 1.1) over USB serial.
- Edit, load, save and stream G-code files with live progress.
- Provide manual control (jog, home, zero, overrides) and a console.
- Visualize toolpaths and highlight the line currently executing.

### Non-goals (v1)
- Controllers other than GRBL (Marlin, FluidNC, etc.). Keep the design extensible, but do not implement them.
- CAM / toolpath generation (use Carbide Create, Fusion 360, or Inkscape G-code extensions for now). Material and bit selection is a post-1.0 convenience, not required for a sender.
- CAM (generating G-code from CAD/SVG). Possible later add-on.
- Windows/Linux packaging. Code should stay portable, but only macOS is tested.

### Success criteria for v1.0
- Streams a 10,000+ line file without buffer overruns or UI freezes.
- Pause, resume and soft-reset behave safely at any moment.
- Editor handles a 50,000 line file smoothly.
- Installable as a double-clickable `.app`.

---

## 2. Tech Stack

| Concern | Choice | Notes |
|---|---|---|
| Language | Python 3.10+ | Any 3.10+ works (pyenv, Homebrew or python.org). Only install if the check in Section 3 says it's missing or too old |
| GUI | **PySide6** (Qt 6) | Official Qt bindings, LGPL, good macOS support |
| Serial | **pyserial** | Run in a worker `QThread` |
| Editor | `QPlainTextEdit` + custom `QSyntaxHighlighter` | Upgrade to QScintilla only if needed |
| 2D/3D preview | **pyqtgraph** (2D first, OpenGL 3D later) | Fast, Qt-native |
| Settings storage | `QSettings` or JSON in `~/Library/Application Support` | Recent files, port, window layout |
| Testing | `pytest`, `pytest-qt` | Plus a fake GRBL simulator |
| Lint/format | `ruff`, `black`, `mypy` | |
| Packaging | **PyInstaller** (or `py2app`) | Produces `.app`, then `.dmg` |
| Version control | Git + GitHub | |

---

## 3. Hardware and Environment Setup (Day 0)

1. **Check first, then install only what's missing.** Run each check below; skip the install step for anything already present.

   **a) Check what you already have**
   ```bash
   python3 --version                 # need 3.10 or newer
   python3 -m pip --version          # pip available?
   git --version                     # git installed?
   python3 -m pip list 2>/dev/null | grep -i -E "^(PySide6|pyserial|pyqtgraph|numpy|pytest|pytest-qt|ruff|black|mypy) "
   ```
   Anything in the package list that doesn't show up in the output is missing.

   **b) Install only the missing pieces**
   - **Python missing or older than 3.10:** install a newer one with your manager of choice (`pyenv install 3.12` if you use pyenv, otherwise `brew install python@3.12`). If you already have 3.10 or newer, do nothing.
   - **git missing:** `xcode-select --install` (or `brew install git`).
   - **Python packages:** use the script below. It checks each package and installs only the ones that are missing.

   **c) Smart setup script** (save as `scripts/setup_env.sh`, run with `bash scripts/setup_env.sh`)
   ```bash
   #!/usr/bin/env bash
   set -e

   # 1. Python >= 3.10
   if ! command -v python3 >/dev/null; then echo "python3 not found, install Python 3.10+ first"; exit 1; fi
   python3 - <<'EOF' || { echo "Python 3.10+ required"; exit 1; }
   import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)
   EOF
   echo "Python OK: $(python3 --version)"

   # 2. pip
   python3 -m pip --version >/dev/null 2>&1 || python3 -m ensurepip --upgrade
   echo "pip OK"

   # 3. git (optional but recommended)
   command -v git >/dev/null && echo "git OK" || echo "git missing: run xcode-select --install"

   # 4. Packages: install only the missing ones
   PACKAGES=(PySide6 pyserial pyqtgraph numpy pytest pytest-qt ruff black mypy)
   MISSING=()
   for pkg in "${PACKAGES[@]}"; do
     if python3 -m pip show "$pkg" >/dev/null 2>&1; then
       echo "  [have]    $pkg"
     else
       echo "  [missing] $pkg"
       MISSING+=("$pkg")
     fi
   done

   if [ ${#MISSING[@]} -gt 0 ]; then
     echo "Installing: ${MISSING[*]}"
     python3 -m pip install "${MISSING[@]}"
   else
     echo "All packages already installed."
   fi
   ```

   **d) Virtual environment (recommended)**
   A virtual environment keeps this project's packages separate from your system Python, but it starts empty, so the check will report everything as missing inside it and install it there (this is expected, and small packages like pyserial reinstall in seconds):
   ```bash
   python3 -m venv .venv && source .venv/bin/activate
   bash scripts/setup_env.sh
   ```
   If you'd rather reuse packages you've already installed globally (for example `pyserial`), create the venv with `python3 -m venv --system-site-packages .venv` instead. The script will then see them and skip them.

   **Tips**
   - If an install seems stuck at "Collecting ...", press `Ctrl+C` once and re-run it (the first download can be slow on some networks).
   - A "new release of pip is available" notice is harmless. Upgrade whenever you like with `python3 -m pip install --upgrade pip`.

2. Flash GRBL to the Uno:
   - Download GRBL from `github.com/gnea/grbl`.
   - Arduino IDE: *Sketch → Include Library → Add .ZIP Library* (select the `grbl` folder), then open *File → Examples → grbl → grblUpload* and upload.
3. Verify the port with the Uno plugged in: `ls /dev/cu.usb*` or `python3 -m serial.tools.list_ports` (expect `/dev/cu.usbmodemXXXX`; CH340 clones appear as `/dev/cu.usbserial-XXXX` or `wchusbserial` and may need a driver). Entries such as `cu.Bluetooth-Incoming-Port`, `cu.debug-console`, `cu.wlan-debug` or a Bluetooth headset are normal macOS ports and are not your Arduino. If no `usbmodem`/`usbserial` entry appears, try another USB cable (some are charge-only) or port.
4. Smoke test: `screen /dev/cu.usbmodemXXXX 115200`, then type `$$` and `?`. Exit with `Ctrl+A`, `K`, `Y`.

> **Safety:** For early testing, keep motors/spindle/laser disconnected, or use only motors with no tool attached. Know where the power switch is.

---

## 4. Architecture

```
┌───────────────────────────── UI layer (PySide6) ──────────────────────────────┐
│ MainWindow │ ConnectionPanel │ Editor │ Console │ JogPanel │ Visualizer │ ... │
└───────────────▲───────────────────────────────────────────────┬───────────────┘
                │ Qt signals                                    │ Qt slots / calls
┌───────────────┴───────────────────────────────────────────────▼───────────────┐
│                          Controller layer (no GUI imports)                    │
│   MachineController  ──  Streamer (job state machine)  ──  StatusParser       │
└───────────────▲───────────────────────────────────────────────┬───────────────┘
                │ parsed events                                 │ bytes out
┌───────────────┴───────────────────────────────────────────────▼───────────────┐
│                      Transport layer: SerialWorker (QThread)                  │
│               pyserial │ MockTransport (for tests) │ real port                │
└────────────────────────────────────────────────────────────────────────────────┘
```

### Principles
- **UI never touches the serial port.** It talks to `MachineController` through signals/slots.
- **Controller layer is GUI-free** (plain Python + a thin signal adapter), so it can be unit-tested without Qt.
- **Transport is swappable** (real serial vs. mock) via a common interface.
- **Real-time commands bypass the queue**; line commands go through the streamer.

### Proposed project structure
```
plotdeck/
├── pyproject.toml
├── README.md
├── src/plotdeck/
│   ├── __main__.py              # entry point
│   ├── app.py                   # QApplication setup
│   ├── core/
│   │   ├── transport.py         # Transport ABC, SerialTransport, MockTransport
│   │   ├── grbl_protocol.py     # constants, real-time bytes, parsers
│   │   ├── status.py            # MachineStatus dataclass + status-report parser
│   │   ├── streamer.py          # character-counting streamer, job state machine
│   │   ├── controller.py        # MachineController (orchestrates everything)
│   │   └── gcode_parser.py      # tokenizer, comment stripper, move extraction
│   ├── ui/
│   │   ├── main_window.py
│   │   ├── connection_panel.py
│   │   ├── editor.py            # GcodeEditor + highlighter + line numbers
│   │   ├── console.py
│   │   ├── jog_panel.py
│   │   ├── status_panel.py      # DRO, state, overrides
│   │   ├── visualizer.py
│   │   ├── settings_dialog.py   # $$ editor
│   │   └── resources/           # icons, QSS themes
│   └── utils/
│       ├── settings.py
│       └── logging_setup.py
├── tests/
│   ├── fake_grbl.py             # GRBL simulator
│   ├── test_parser.py
│   ├── test_streamer.py
│   ├── test_status.py
│   └── test_ui_smoke.py
└── packaging/
    ├── plotdeck.spec            # PyInstaller
    └── icon.icns
```

---

## 5. GRBL Protocol Cheat Sheet (what the code must implement)

### Real-time commands (single byte, never queued, never wait for `ok`)
| Byte | Meaning |
|---|---|
| `?` | Status report request |
| `!` | Feed hold (pause) |
| `~` | Cycle start / resume |
| `0x18` (Ctrl-X) | Soft reset |
| `0x84` | Safety door |
| `0x85` | Jog cancel |
| `0x90–0x9E` | Feed / rapid / spindle override controls |

### Line commands
- Terminated with `\n`. GRBL replies `ok` or `error:N` for each line.
- System: `$$` (settings), `$H` (home), `$X` (unlock), `$G` (parser state), `$#` (offsets), `$J=...` (jog), `$N` (startup blocks).

### Messages from GRBL
- **Status report:** `<Idle|MPos:0.000,0.000,0.000|FS:0,0>` (fields vary: `WPos`, `Bf`, `Ov`, `WCO`, `Pn`).
- **Alarms:** `ALARM:N`; **Errors:** `error:N`; **Feedback:** `[MSG:...]`, `[GC:...]`, `[PRB:...]`.
- **Welcome banner:** `Grbl 1.1h ['$' for help]` (sent after every reset; use it to detect connect/reset).

### States
`Idle`, `Run`, `Hold:0/1`, `Jog`, `Alarm`, `Door:n`, `Check`, `Home`, `Sleep`

### Streaming: character-counting algorithm
GRBL's RX buffer is **127 usable bytes**. Track the length of each sent-but-unacknowledged line and only send the next line if it fits.

```python
RX_BUFFER = 127

def pump(self):
    while self.queue and self.state == RUNNING:
        line = self.queue[0]                      # already cleaned, no newline
        need = len(line) + 1                      # + '\n'
        if sum(self.pending) + need > RX_BUFFER:
            break
        self.transport.write(line.encode() + b"\n")
        self.pending.append(need)
        self.sent_index.append(self.queue.popleft().source_line)

def on_response(self, resp):                      # "ok" or "error:N"
    self.pending.popleft()
    done_line = self.sent_index.popleft()
    self.progress.emit(done_line)
    if resp.startswith("error"):
        self.handle_error(done_line, resp)
    self.pump()
```

---

## 6. Development Phases

Estimated for one developer working part-time (~8–10 hrs/week). Adjust as needed.

### Phase 0: Foundation (Week 1)
**Tasks**
- Create repo, `pyproject.toml`, virtualenv, `ruff`/`black`/`mypy` config, `pytest` config.
- Scaffold the package structure above.
- Set up logging (rotating file in `~/Library/Logs/PlotDeck/`).
- Write `fake_grbl.py` (see Phase 1).
- CI: GitHub Actions running lint + tests on `macos-latest`.

**Done when:** `python -m plotdeck` opens an empty window; `pytest` passes.

---

### Phase 1: Core serial and protocol layer (Weeks 1–2)
**Tasks**
1. `Transport` interface: `open()`, `close()`, `write(bytes)`, signal/callback on `line_received`, `error`.
2. `SerialTransport` using pyserial in a `QThread`:
   - Non-blocking read loop (`timeout=0.05`), assemble lines on `\n`.
   - Handle port disappearing (USB unplugged) gracefully.
   - Wait ~2 seconds after open (Uno auto-resets), then send `\r\n\r\n` and flush.
3. Port discovery: `serial.tools.list_ports.comports()`, filter `usbmodem|usbserial|wchusbserial`, refresh button.
4. `grbl_protocol.py`: real-time byte constants, response classifiers (`ok`, `error:N`, `ALARM:N`, status, messages).
5. Lookup tables for GRBL **error codes** and **alarm codes** with human-readable text.
6. `status.py`: parse `<...>` reports into a `MachineStatus` dataclass (state, MPos/WPos, WCO tracking, feed/spindle, buffer, overrides, pins).
7. `fake_grbl.py`: simulator implementing the 127-byte buffer, `ok`/`error` replies, `?` status, `!`/`~`/`0x18`, and basic motion timing. Used by tests and for development without hardware.

**Tests:** parser unit tests with real GRBL strings; transport tests against the mock.

**Done when:** a CLI script connects, prints status every 200 ms, and sends `$$`.

---

### Phase 2: Controller and streamer (Weeks 2–3)
**Tasks**
1. `gcode_parser.py`:
   - Strip `;` comments and `(...)` comments, `%` lines, blank lines.
   - Uppercase, collapse whitespace; keep the **original line number** mapping for UI highlighting.
   - Optional: warn on lines longer than 80 characters (GRBL limit is 80 per block).
2. `Streamer` state machine: `IDLE → RUNNING ⇄ PAUSED → (COMPLETED | STOPPED | ERROR)`.
   - Character-counting streaming (above).
   - Pause sends `!`; resume sends `~`; stop sends `!` then `0x18` and clears the queue.
   - **On `error:N`:** pause the job and ask the user (continue/abort) rather than blindly continuing.
   - On `ALARM`: halt the job immediately.
   - Option: **simple "send/ok"** mode for debugging.
3. `MachineController`:
   - Periodic status polling (`?` every 200 ms; slower while idle if desired).
   - Holds the latest `MachineStatus`; emits `status_changed`, `alarm`, `message`, `job_progress`, `job_finished`.
   - Command API: `send_line()`, `jog()`, `home()`, `unlock()`, `reset()`, `hold()`, `resume()`, `set_override()`.
   - Detect GRBL banner → reset internal state.
   - Check mode (`$C`) support for "dry-run" a file.
4. Job statistics: elapsed time, estimated time remaining (from parsed moves and feed rates).

**Tests:** simulate buffer-full conditions, errors mid-job, pause/resume, alarm mid-job, unplug mid-job.

**Done when:** a 5,000-line file streams to the fake GRBL and the real Uno without gaps or errors, and Stop is safe at any moment.

---

### Phase 3: Basic GUI, connect and console (Weeks 3–4)
**Tasks**
- `MainWindow` with dockable panels (`QDockWidget`) so the layout is customizable and persists via `saveState()`.
- **ConnectionPanel:** port dropdown, baud (default 115200), Connect/Disconnect, refresh, auto-reconnect option.
- **Console:** read-only log (color-coded: sent / received / error / alarm), input box with history (↑/↓), clear, autoscroll toggle, and filter to hide status polling.
- **StatusPanel:** state badge (color per state), DRO showing MPos/WPos X/Y/Z, feed & spindle values, buffer fill.
- Toolbar: Hold, Resume, Reset, Unlock, Home.
- Status bar: connection state, GRBL version.
- Error/alarm dialogs with human-readable explanation.

**Done when:** you can connect, type `$$`, see the reply, and watch live position while moving the machine with typed commands.

---

### Phase 4: File handling and streaming UI (Weeks 4–5)
**Tasks**
- File menu: Open, Save, Save As, Recent Files, drag-and-drop onto the window.
- Job controls: **Run / Pause / Resume / Stop**, "Start from line N", progress bar, elapsed/remaining time.
- Confirmations: "Machine not at zero. Continue?", "Unsaved changes. Save before running?".
- Highlight the currently executing line in the editor (see Phase 5).
- Run-from-cursor and "run selection" options.
- Pre-flight checks: connected, state is Idle, no alarm, file has been parsed, bounds within the machine's soft limits (`$130-$132`) if known.

---

### Phase 5: G-code editor (Weeks 5–7)
**Tasks**
1. `GcodeEditor(QPlainTextEdit)`:
   - Line-number gutter (custom `QWidget` paint).
   - Monospace font, tab/space handling, current-line highlight.
2. `GcodeHighlighter(QSyntaxHighlighter)` with distinct colors for:
   - `G` words, `M` words, axis words (`X Y Z I J K`), `F`/`S`/`T`, numbers, comments, `$` commands, N-numbers, errors.
3. Editing features:
   - Undo/redo (built in), find & replace (regex), go to line.
   - Toggle comment, uppercase selection, strip comments.
   - **Transform tools:** offset X/Y/Z, scale, rotate, mirror, renumber lines.
   - Autocomplete for G/M codes with a tooltip description (e.g., `G1 – Linear move`).
   - Hover docs for G/M codes.
4. Inline validation (background timer, debounced):
   - Unknown codes, GRBL-unsupported codes, missing feed rate before `G1`, line length > 80, invalid numbers.
   - Squiggly underline + marker in gutter.
5. Execution markers: green for sent/done, yellow for in-flight, red for lines that errored.
6. Performance: for files >50k lines, disable expensive validation and use `setUndoRedoEnabled(False)` while loading; load with `setPlainText` in a single call.

**Done when:** you can edit a large file comfortably and see the run-line marker follow the machine.

---

### Phase 6: Jog, zero and work coordinates (Weeks 7–8)
**Tasks**
- **Jog panel:** X/Y/Z ± buttons, step selector (0.01/0.1/1/10/100), feed rate input, continuous jog (hold button) using `$J=G91 ...` and cancel with `0x85`.
- Keyboard jogging (arrows, PgUp/PgDn) with a focus-safe toggle.
- Zero buttons: `G10 L20 P1 X0` etc. (Zero X, Y, Z, All); go-to-zero (`G0 X0 Y0`).
- Work coordinate system selector (G54–G59), view `$#` offsets.
- Homing (`$H`), and "Set machine position" helpers.
- Probing (`G38.2`) UI (optional).
- Macros: user-defined buttons mapped to G-code snippets, stored in settings.
- Feed/rapid/spindle **override sliders** (real-time bytes `0x90`+).

---

### Phase 7: Visualizer (Weeks 8–10)
**Tasks**
1. Parse the file into segments: `G0` (rapid), `G1` (feed), `G2/G3` arcs (tessellate), track modal state (`G90/G91`, `G20/G21`, `G17-19`, `G54-59`).
2. **2D view (pyqtgraph):** XY plot, rapids as dashed gray, feeds colored by Z-depth or feed rate, zoom/pan, fit-to-view.
3. Live machine position marker updated from status reports.
4. Executed portion drawn in a different color as the job progresses.
5. **3D view (pyqtgraph.opengl)** with orbit camera and axes/grid, view presets (Top, Front, Iso).
6. Show bounding box, min/max values, total path length, and estimated time.
7. Click a segment, jump to its line in the editor (and vice versa).
8. Performance: batch segments into a single `PlotCurveItem`/`GLLinePlotItem` with `connect='finite'`; downsample for huge files.

---

### Phase 8: GRBL settings and utilities (Weeks 10–11)
- **Settings editor:** `$$` table with descriptions, units, validation, edit, write back, export/import JSON backup.
- Display `$I` build info, `$G` parser state, `$N` startup lines editor.
- Alarm recovery wizard (unlock, re-home, explain cause).
- Firmware helper: detect version mismatches; link to the GRBL docs.
- Preferences dialog: default baud, units (mm/in display), jog defaults, polling rate, theme, editor font, auto-reconnect.

---

### Phase 9: Polish, UX and quality (Weeks 11–12)
- Dark/light theme following macOS appearance (`QStyleHints.colorScheme`) + QSS tweaks.
- Menus with standard macOS shortcuts (`⌘O`, `⌘S`, `⌘F`, `⌘,` for Preferences).
- Persist window layout, last port, recent files.
- Crash-safe handling: global exception hook shows a dialog and logs a traceback; on unexpected disconnect during a job, show a clear "job interrupted at line N" message and offer to resume from that line (after re-homing).
- Keep the Mac awake while a job runs (`caffeinate -i` subprocess or `IOPMAssertion` via `pyobjc`).
- Accessibility: tooltips, keyboard focus order, reasonable minimum sizes.
- Documentation: README with screenshots, user guide, troubleshooting (ports, drivers, permissions).

---

### Phase 10: Packaging and release (Week 12+)
1. Build `.app` with PyInstaller:
   ```bash
   pip install pyinstaller
   pyinstaller --windowed --name PlotDeck --icon packaging/icon.icns \
       --collect-all pyqtgraph src/plotdeck/__main__.py
   ```
2. Create `.dmg` (`create-dmg` via Homebrew).
3. **Code signing & notarization** (needed so other Macs don't block the app):
   - Apple Developer account, `codesign --deep --options runtime`, `xcrun notarytool submit`, `xcrun stapler staple`.
   - For personal use only, you can skip this and right-click → Open.
4. Test on a clean Mac/user account, including Apple Silicon and Intel if distributing.
5. Tag `v1.0.0`, publish release notes on GitHub.

---

## 7. Testing Strategy

| Level | What | How |
|---|---|---|
| Unit | Parsers, status decoder, error tables, transforms, arc tessellation | `pytest`, table-driven tests with real GRBL strings |
| Streamer | Buffer accounting, pause/resume/stop, error handling | Drive against `fake_grbl` with randomized delays |
| Integration | Controller ↔ transport ↔ fake GRBL | End-to-end job runs, unplug simulation |
| UI smoke | Windows open, buttons enable/disable by state | `pytest-qt` |
| Hardware-in-loop | Real Uno | Manual checklist below |

### Manual hardware checklist (run before each release)
- [ ] Connect / disconnect / reconnect, unplug USB mid-idle and mid-job
- [ ] `$$` read and write
- [ ] Home, jog all axes, zero, go-to-zero
- [ ] Stream small, medium and 20k-line files with no `error:`
- [ ] Pause/resume repeatedly mid-arc
- [ ] Stop mid-job leaves the machine safe and the app consistent
- [ ] Alarm (trigger a limit switch) is shown and recoverable
- [ ] Feed override and spindle override work live
- [ ] Mac sleep/wake during idle connection

---

## 8. Key Design Decisions and Pitfalls

1. **Uno resets when the port opens.** Wait ~2s, flush, and look for the GRBL banner before declaring "connected."
2. **Never block the UI thread** on serial I/O. All reads/writes live in the worker thread; communicate through signals.
3. **Status polling must not use the line queue.** `?` is real-time and does not return `ok`; mixing it into the counted buffer corrupts accounting.
4. **Jog commands** (`$J=`) also return `ok`, so they must be counted too (or only allowed when no job is running).
5. **After a soft reset (`0x18`)** GRBL loses queued commands and may lose position (depending on state); clear the streamer queue and `pending` list, and re-sync modal state (`$G`).
6. **Do not auto-continue after `error:N`.** One bad line can mean a wrong tool state; pause and ask.
7. **Line length limit:** GRBL rejects blocks over 80 chars; validate before sending.
8. **Units and modal state:** The visualizer and time estimator must track `G20/G21`, `G90/G91`, and `G91.1` to be accurate.
9. **Buffer size is 127 bytes, not 128;** stay under it to avoid overruns.
10. **Cheap Uno clones/CH340** sometimes drop data at high rates; offer a "safe mode" (simple send-response) toggle.
11. **Laser mode:** if `$32=1`, the app should show a laser-mode indicator and block spindle-style commands where appropriate.

---

## 9. Milestone Summary

| Milestone | Deliverable | Target |
|---|---|---|
| M0 | Environment + scaffold + CI | End of Week 1 |
| M1 | Serial/protocol core + fake GRBL | End of Week 2 |
| M2 | Streamer + controller (headless) | End of Week 3 |
| M3 | **MVP**: connect, console, load & stream, pause/stop | End of Week 5 |
| M4 | Editor with highlighting + run-line marker | End of Week 7 |
| M5 | Jog, zero, overrides, macros | End of Week 8 |
| M6 | 2D/3D visualizer | End of Week 10 |
| M7 | Settings editor, preferences | End of Week 11 |
| M8 | Polish + docs | End of Week 12 |
| M9 | Signed `.app` / `.dmg` release v1.0 | Week 12–13 |

> **MVP tip:** Aim for M3 first. Once you can reliably stream a file and stop safely, everything else is incremental.

---

## 10. Post-1.0 Ideas

- SVG/DXF/image → G-code importer (e.g., via `svgpathtools`, `shapely`).
- Support for Marlin and FluidNC/grblHAL (extend the `Transport`/protocol layer).
- Camera overlay and alignment.
- Height-map auto-leveling (probe grid + Z-compensation).
- Plugin system (Python scripts as macros).
- Job history, material presets, and time/cost logging.
- Remote monitoring via a small web UI.

---

## 11. Reference Resources

- GRBL wiki and interface spec: `github.com/gnea/grbl/wiki`
- GRBL streaming example (`stream.py`): `github.com/gnea/grbl/blob/master/doc/script/stream.py`
- Open-source senders to study: **bCNC** (Python/Tk), **Universal G-code Sender** (Java), **CNCjs** (Node)
- Qt for Python docs: `doc.qt.io/qtforpython-6`
- pyserial docs: `pythonhosted.org/pyserial`
- pyqtgraph docs: `pyqtgraph.readthedocs.io`
- G-code reference supported by GRBL 1.1: GRBL wiki → "Supported G-codes"

---

## 12. Suggested First Steps (This Weekend)

1. Flash GRBL and confirm `$$` works in `screen`.
2. Create the repo and virtualenv, and install dependencies.
3. Write `fake_grbl.py` and `grbl_protocol.py` with tests.
4. Build a 100-line CLI streamer using the character-counting logic.
5. Wrap it in a minimal PySide6 window (port dropdown + console), the seed of Phase 3.

---

## 13. UI/UX Design Specification

A visual mockup of the main window accompanies this plan (the "PlotDeck – Main Window Mockup" artifact). This section is the written spec behind it.

### 13.1 Design principles
1. **Safety first.** Stop/Hold are always visible and never disabled while connected. Dangerous actions (Reset, Run from line N) ask for confirmation.
2. **State drives the UI.** Every control's enabled/disabled status is derived from the machine state (table in 13.5), never set ad hoc.
3. **Glanceable.** From a meter away you should see: connected or not, current state, position, and job progress.
4. **Native feel.** Follows macOS light/dark mode, uses standard shortcuts, remembers window layout.
5. **Dense but calm.** Monospace for all numbers/code, a neutral dark palette, color reserved for meaning (state, syntax, progress).

### 13.2 Window layout (1440 × 900 default, min 1100 × 700)

```
┌───────────────────────────────────────────────────────────────────────────────┐
│ ● ● ●                      PlotDeck - file.nc                                 │ title bar
├───────────────────────────────────────────────────────────────────────────────┤
│ [Port ▾][Baud ▾][Connect] │ [Run][Pause][Stop] │ [Home][Unlock][Reset]  [STATE]│ toolbar
├──────────────┬──────────────────────────────────────────────┬─────────────────┤
│ POSITION     │ EDITOR (line numbers, syntax colors,         │ TOOLPATH        │
│  X  52.318   │ executing-line highlight)                    │ 2D / 3D / Fit   │
│  Y  22.417   │                                              │                 │
│  Z  -0.500   │                                              │                 │
│ Feed/Spindle │──────────────────────────────────────────────│─────────────────│
│              │ CONSOLE (sent / ok / errors) + input         │ JOB             │
│ JOG          │                                              │ progress, time, │
│ OVERRIDES    │                                              │ line x / n      │
├──────────────┴──────────────────────────────────────────────┴─────────────────┤
│ ● Connected  port · baud                                  units · G90 · G54   │ status bar
└───────────────────────────────────────────────────────────────────────────────┘
```

- Left column fixed at ~290 px, right column ~440 px, center flexible. Implemented with `QDockWidget`s so panels can be rearranged, floated or hidden (View menu) and the layout is persisted via `saveState()`.
- Editor : console height ratio about 3 : 2, adjustable with a splitter.

### 13.3 Visual style

**Palette (dark theme)**

| Role | Hex |
|---|---|
| Window background | `#0F1215` |
| Panel surface | `#1A1E23` |
| Editor / console background | `#14171A` |
| Borders | `#2A3038` |
| Text | `#D7DDE4` |
| Muted text | `#8B95A1` |
| Primary accent (info, progress) | `#4C9BF0` |

**Machine state colors**

| State | Color | Badge |
|---|---|---|
| Idle | green `#3FB67A` | IDLE |
| Run / Jog / Home | blue `#4C9BF0` | RUN |
| Hold / Door | amber `#E0A030` | HOLD |
| Alarm | red `#E5584F` | ALARM |
| Disconnected | gray `#7D8896` | OFFLINE |

**Syntax colors:** G-words `#7CB7FF`, M-words `#C792EA`, axis words `#E6C07B`, F/S/T `#7FD1AE`, comments `#7D8896`, errors `#E5584F` (wavy underline).

**Typography:** IBM Plex Sans for UI (fallback: system font / SF Pro), IBM Plex Mono for code, console and numbers (fallback: Menlo). Sizes: UI 13 px, console 12 px, DRO values 28 px, section headers 11 px caps with letter-spacing. Bundle the fonts with the app.

**Spacing and shape:** 8 px base grid, 10 px gaps between panels, 8 px panel radius, 6 px control radius, buttons 34 px tall, jog buttons at least 44 px (large touch targets, easy to hit without looking).

**Light theme:** build the palette as a token table (`theme.py`) and provide a light set; switch automatically with `QStyleHints.colorScheme()`.

### 13.4 Component specs

**Toolbar**
- Connection group: port dropdown (auto-refresh, filters to USB serial), baud dropdown, Connect/Disconnect (toggle, green when connected).
- Job group: Run (green), Pause/Resume (amber, toggles label), **Stop (red, largest, always enabled when connected)**.
- Machine group: Home, Unlock, Reset.
- Right side: GRBL version and the state badge.

**Position panel (DRO)**
- Large WPos values, with MPos small beside them. Click the label (X/Y/Z) to zero that axis; right-click for "Set to value...".
- Footer shows feed, spindle, and RX buffer fill.

**Jog panel**
- XY pad (arrows + center "go to zero"), Z up/down column, step chips (0.1, 1, 10, 100) and a feed input.
- Keyboard: arrows = XY, PgUp/PgDn = Z, `[` `]` change step. Shortcuts only active while the jog panel has focus.
- Disabled and dimmed during a job, with a visible explanation.

**Overrides**
- Feed (10-200%), Rapid (25/50/100%), Spindle (10-200%) sliders with numeric readout, double-click to reset to 100%. Sends GRBL real-time override bytes.

**Editor**
- Line-number gutter, current-line highlight, syntax colors, find/replace bar (`⌘F`), go-to-line (`⌘L`), inline validation squiggles.
- Execution tracking: lines already sent get green line numbers, the executing line gets a blue row highlight, error lines get a red marker. Clicking a line number sets "start from here".
- Footer legend plus cursor position.

**Console**
- Color-coded: sent (blue), `ok` (green), messages (gray), `error:`/`ALARM:` (red, with a plain-English explanation on hover).
- Filters: hide status polls (default on), auto-scroll.
- Input with command history (↑/↓) and Enter to send.

**Toolpath view**
- 2D by default: grid, executed path solid green, remaining path dashed gray, live tool marker, bounding-box size.
- 3D and Fit toggles; click a segment to select its line in the editor.

**Job panel**
- Progress bar with percentage, elapsed, remaining, `line x / n`.

**Status bar**
- Connection state, port and baud, active modal info (units, distance mode, work coordinate system), and notices such as "Mac kept awake while job runs".

### 13.5 Control enablement by machine state

| Control | Offline | Idle | Run | Hold | Alarm | Jog |
|---|---|---|---|---|---|---|
| Connect / Disconnect | Connect | Disconnect | Disconnect (confirm) | Disconnect (confirm) | Disconnect | Disconnect (confirm) |
| Run | ✗ | ✓ (file loaded) | ✗ | Resume | ✗ | ✗ |
| Pause | ✗ | ✗ | ✓ | ✗ | ✗ | ✗ |
| **Stop** | ✗ | ✗ | ✓ | ✓ | ✓ | ✓ |
| Home | ✗ | ✓ | ✗ | ✗ | ✓ ($H) | ✗ |
| Unlock ($X) | ✗ | ✗ | ✗ | ✗ | ✓ | ✗ |
| Reset (Ctrl-X) | ✗ | ✓ | ✓ (confirm) | ✓ | ✓ | ✓ |
| Jog pad | ✗ | ✓ | ✗ | ✗ | ✗ | ✓ |
| Zero axes / WCS | ✗ | ✓ | ✗ | ✗ | ✗ | ✗ |
| Overrides | ✗ | ✓ | ✓ | ✓ | ✗ | ✗ |
| Console input | ✗ | ✓ | Real-time cmds only | Real-time cmds only | `$` cmds only | ✗ |
| Editor (read/write) | ✓ | ✓ | Read-only for sent lines | Read-only for sent lines | ✓ | ✓ |

Disabled controls are dimmed (about 40% opacity) and show a tooltip explaining why.

### 13.6 Key interaction flows

1. **First connect:** pick port, Connect, wait for the GRBL banner (spinner on the button), badge turns IDLE, console shows version. On failure, show a dialog with likely causes (wrong port, driver, another app using the port).
2. **Run a job:** Open file → preview appears → pre-flight dialog if anything is off (not homed, unsaved changes, bounds exceed limits) → Run → badge RUN, editor follows the executing line, DRO and toolpath update live.
3. **Error mid-job:** the job auto-pauses (amber), a non-blocking banner shows "error:20 on line 42: unsupported G-code" with buttons **Skip line**, **Edit line**, **Abort**.
4. **Alarm:** the state badge turns red, a banner explains the cause (for example "Hard limit triggered") and offers **Unlock** and **Home**. All motion controls stay disabled until cleared.
5. **USB unplugged:** immediately show OFFLINE, a banner "Job interrupted at line N", and an offer to resume from line N after reconnect and re-homing.

### 13.7 Keyboard shortcuts

| Action | Shortcut |
|---|---|
| Open / Save | `⌘O` / `⌘S` |
| Find / Go to line | `⌘F` / `⌘L` |
| Run / Pause-Resume | `⌘R` / `Space` (when editor not focused) |
| **Stop (feed hold)** | `⌘.` |
| Soft reset | `⌘⇧.` |
| Toggle comment | `⌘/` |
| Connect / Disconnect | `⌘K` |
| Preferences | `⌘,` |
| Zoom toolpath fit | `F` |

### 13.8 Implementation notes (PySide6)

- Theme via a central `theme.py` token dict, turned into one QSS string; avoid hard-coded colors in widgets.
- Custom widgets: `StateBadge`, `DroRow`, `JogPad`, `OverrideSlider`, `LineNumberArea`, `ProgressBarThin`. Keep each under about 150 lines and give them a signal-only interface.
- Use `QActionGroup` for step chips and the 2D/3D toggle; `QToolBar` for the toolbar; `QStatusBar` for the footer.
- Use `QPalette` + QSS together so native dialogs (file open, message boxes) also match dark mode.
- Accessibility: set `accessibleName` on icon-only buttons, ensure a logical Tab order, keep contrast at 4.5:1 or better.
- Build the UI in this order (matches Phases 3-7): toolbar + status bar → console → DRO/state badge → editor → jog/overrides → visualizer → job panel → polish (themes, animations kept minimal).

### 13.9 UI acceptance checklist
- [ ] Stop is visible and works from every connected state
- [ ] Every control follows the enablement table in 13.5
- [ ] No UI freezes while streaming a 20k-line file (main thread stays under 16 ms per frame)
- [ ] Light and dark themes both pass contrast checks
- [ ] Window layout, theme, last port and recent files persist across restarts
- [ ] All primary actions are reachable by keyboard


---

## 14. CNC Router Specifics

The target machine is a small CNC router. A sender doesn't need material or bit data, because feeds, speeds and depths are already in the G-code from your CAM software. These router-specific features matter more than they would for a plotter or laser, and they slot into the phases above.

| Feature | Fits into | Priority |
|---|---|---|
| Z probing wizard (`G38.2`) | Phase 6 | High |
| Manual tool change handling (`M6`) | Phase 2 (streamer) + Phase 4 (UI) | High |
| Job summary / pre-flight (bounds, depth, tools, time) | Phase 4 | High |
| Safety controls and reminders | Phase 3 onward | High |
| Spindle on/off and RPM override | Phase 6 | Medium (optional, depends on wiring) |

### 14.1 Z probing wizard
- Dialog guiding the user: attach the touch-plate clip, place the plate under the bit, press **Probe**.
- Sends `G91 G38.2 Z-30 F50` (slow, bounded travel), then on success `G10 L20 P1 Z<plate thickness>` and `G91 G0 Z5` / `G90` to retract.
- Handles failure: if no contact within the travel limit, GRBL raises an alarm, so show a clear message and offer retry.
- Reads the `[PRB:x,y,z:1]` message to confirm success.
- Settings: plate thickness, probe feed rate, max travel, retract height. Store in preferences.
- Also offer XYZ corner probing later (post-1.0).

### 14.2 Manual tool change (`M6`)
- GRBL does not implement `M6`, so the streamer must intercept it **before sending**.
- Detect `M6` and `T<n>` in the cleaned line (and the tool comment such as `(T1: 3mm endmill)` if present).
- Flow: wait for the buffer to drain (planner empty) → spindle off (`M5`) → raise Z to safe height → pause job → show dialog "Insert Tool 2: 3 mm ball nose. Then re-probe Z." → run Z probe wizard → resume the job from the next line.
- Never forward `M6` to GRBL (it would return `error:20`).

### 14.3 Spindle control (optional)
- Spindle on/off buttons (`M3 S<rpm>` / `M5`) and RPM field, shown only when the "spindle controlled by GRBL" preference is on.
- Spindle override slider (already in the UI spec) sends real-time override bytes.
- For manual-switch spindles: hide these controls and show a reminder in the pre-flight check ("Start the spindle manually before running").

### 14.4 Pre-flight job summary
Shown when pressing Run:
- File name, line count, estimated time.
- Bounding box and max cut depth (min Z).
- Tools used (from `T` words/comments) and feed range.
- Warnings: exceeds machine travel (`$130-$132`), Z zero not set this session, not homed, unsaved edits, spindle reminder.
- Buttons: **Start**, **Cancel**, and **Dry run** (uses GRBL check mode `$C`).

### 14.5 Safety
- Stop and Feed Hold always prominent (already in UI spec); shortcut `⌘.`.
- First-run safety note: wear eye protection, keep a hand near the power switch for the first cuts, secure the workpiece.
- Confirmation on Reset during a job and on Run when the machine hasn't been homed.
- Soft limits and hard limits setup helper in the settings editor (Phase 8): explain `$20`, `$21`, `$22` and show current values.
- Remind users that software stop is not an e-stop: recommend a hardware emergency stop on the power supply.

---

## 15. Tool and Material Library (post-1.0)

Optional, and worth adding only after the sender and editor are solid.

- **Tool library:** name, diameter, flutes, type (end mill, V-bit, ball nose), tool number. Stored as JSON in the app support folder, with import/export.
- **Material presets:** wood, MDF, acrylic, aluminum, each with suggested chip load.
- **Feeds and speeds calculator:** feed = RPM × flutes × chip load. User picks a bit and material and gets a suggested feed and depth per pass.
- **Sanity check on loaded G-code:** compare `F` and `S` values with the calculator and warn if they look off (for example, "Feed 3000 mm/min is high for a 3 mm bit in pine").
- **Job history:** log tool, material and time per job.
- **Tool change dialog** (14.2) uses the library to show the tool's name and diameter.

True CAM (SVG/DXF import and toolpath generation using `shapely` / `svgpathtools`) remains a separate, large project.

---

## 16. Uno Hardware Notes

An Uno running GRBL works for a small router, with limits:
- Use a **CNC Shield V3** with A4988 or DRV8825 stepper drivers.
- Maximum step rate is about 30 kHz: fine for small machines, but limits speed on setups with high steps/mm.
- Few spare pins beyond limit switches, a probe input, spindle enable/PWM and coolant, so plan the wiring early.
- Isolate the Uno from spindle electrical noise (shielded cables, ferrites, an isolated spindle driver).
- Wire a hardware emergency stop that cuts motor/spindle power.
- If you outgrow the Uno, an ESP32 with grblHAL or FluidNC is the usual upgrade. Keeping the transport/protocol layer abstract (Section 4) makes this feasible later.

---

## 17. Final Build Order

1. **Weekend 1:** flash GRBL, verify `$$` with `screen`, create repo, write `fake_grbl.py`, CLI streamer.
2. **Weeks 1-3:** transport, protocol, streamer and controller (Phases 0-2), headless and tested.
3. **Weeks 3-5:** GUI shell, connect, console, file load and streaming (Phases 3-4). **This is the MVP; cut a first release here.**
4. **Weeks 5-8:** editor, jog, zero, overrides, and the **Z probing wizard and `M6` tool-change handling** (Phases 5-6 + Sections 14.1-14.2).
5. **Weeks 8-11:** visualizer, settings editor, pre-flight summary (Phases 7-8 + Section 14.4).
6. **Weeks 11-13:** polish, packaging, signed `.app` / `.dmg` (Phases 9-10).
7. **After 1.0:** tool/material library, corner probing, height-map leveling, CAM importer.

> **Rule of thumb:** a reliable stream-and-stop (Milestone 3) first, safety features (probing, tool change, pre-flight) second, everything else after.