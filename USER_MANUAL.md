# PlotDeck User Manual

PlotDeck is a macOS G-code sender and editor for CNC routers controlled by an
Arduino Uno running **GRBL 1.1**. It connects over USB serial, lets you edit and
preview a file, streams it with GRBL's flow control, and provides manual
machine control.

> **Safety first.** A CNC machine can injure you and destroy workpieces.
> Wear eye protection, secure the workpiece, know where the power switch is and
> keep a hand near it for the first cut. A software stop is **not** an
> emergency stop — use a hardware e-stop that cuts motor and spindle power.
> Test with the tool removed or raised before cutting material.

---

## Contents

1. [Requirements and installation](#1-requirements-and-installation)
2. [First launch](#2-first-launch)
3. [Connecting to a machine](#3-connecting-to-a-machine)
4. [Interface tour](#4-interface-tour)
5. [Opening, saving and editing G-code](#5-opening-saving-and-editing-g-code)
6. [Preparing a job](#6-preparing-a-job)
7. [Running a job](#7-running-a-job)
8. [Errors, alarms and interruptions](#8-errors-alarms-and-interruptions)
9. [Tool changes](#9-tool-changes)
10. [Console](#10-console)
11. [GRBL settings](#11-grbl-settings)
12. [Appearance and saved state](#12-appearance-and-saved-state)
13. [Keyboard shortcuts](#13-keyboard-shortcuts)
14. [Error and alarm reference](#14-error-and-alarm-reference)
15. [Troubleshooting](#15-troubleshooting)
16. [Files and logs](#16-files-and-logs)
17. [Limitations](#17-limitations)
18. [Demo mode](#18-demo-mode)

---

## 1. Requirements and installation

| Item | Requirement |
| --- | --- |
| Operating system | macOS (only platform tested) |
| Python (from source) | 3.10 or newer |
| Machine | Arduino Uno + GRBL 1.1, CNC shield and stepper drivers |
| Python packages | PySide6, pyserial, pyqtgraph, numpy |
| Optional | PyOpenGL for the 3D toolpath view; PyInstaller for packaging |

### Install from source

```bash
bash scripts/setup_env.sh
source .venv/bin/activate
python -m plotdeck
```

The setup script creates `.venv` and installs the app with development and 3D
extras. To install manually:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev,3d]"
```

### Build a double-clickable app

```bash
bash packaging/build_app.sh
open dist/PlotDeck.app
```

The `.app` is unsigned unless you sign it yourself. On another Mac, right-click
the app and choose **Open** the first time, or sign and notarize it with an
Apple Developer identity (see `README.md`).

### Install GRBL on the Uno

PlotDeck expects **GRBL 1.1**. Flash it with the Arduino IDE (open
*File → Examples → grbl → grblUpload* after installing the GRBL library), then
verify the port and settings. PlotDeck does not flash firmware.

---

## 2. First launch

1. Start the app (`python -m plotdeck`, the `plotdeck` command, or
   `dist/PlotDeck.app`).
2. The window opens **offline**: the state badge is grey and motion controls are
   disabled.
3. Choose **Dark** or **Light** under **View → Theme** if the automatic macOS
   appearance is not what you want. The choice is remembered.
4. The window layout, last serial port and recent files are restored on the
   next launch.

If you do not have hardware, click **Demo** in the toolbar to explore every
screen against a simulated GRBL machine (see [Demo mode](#18-demo-mode)).
Click **Manual** in the toolbar (or press F1) at any time to open this guide
inside PlotDeck.

---

## 3. Connecting to a machine

1. Plug the Uno into USB. macOS should show a port such as
   `/dev/cu.usbmodem14201` (official boards) or `/dev/cu.usbserial-XXXX`
   (CH340 clones).
2. Press the **⟳** button next to the port list to refresh.
3. Select the port. Entries such as `cu.Bluetooth-Incoming-Port`,
   `cu.debug-console` or `cu.wlan-debug` are normal macOS ports and are not the
   Arduino, so they are filtered out.
4. Leave the baud rate at **115200** and press **Connect**.
5. The Uno resets when the serial port opens. PlotDeck waits about two seconds,
   flushes the port and waits for the `Grbl 1.1h` banner. The button reads
   **Connecting…** during this time.
6. When the banner arrives, the state badge turns **IDLE**, the console shows the
   firmware version and status polling starts (five times per second).

Click **Disconnect** (or use **Machine → Connect / Disconnect**, ⌘K) to close
the port. Only one program can own a serial port — close the Arduino IDE serial
monitor, `screen`, or any other sender before connecting.

### Connection troubleshooting

| Symptom | Try |
| --- | --- |
| “No USB serial ports found” | Another USB cable (some are charge-only), another port, press ⟳, install the CH340 driver for clone boards |
| Stuck on “Connecting…” | Wrong port, another app owns the port, cable/driver problem, or the board is not running GRBL |
| Garbled responses | Confirm GRBL at 115200 baud; check the cable and USB hub; cheap clones can be sensitive to electrical noise |
| Works in `screen` but not here | Close `screen`/Arduino IDE first — the port is exclusive |

---

## 4. Interface tour

```
┌───────────────────────────────────────────────────────────────────────────┐
│ Port ▾  ⟳  Baud ▾  Connect  Demo │ Run Pause Stop │ Home Unlock Reset     │
├──────────────┬───────────────────────────────────────────┬────────────────┤
│ POSITION     │ EDITOR                                    │ TOOLPATH       │
│ X/Y/Z DRO    │ line numbers, syntax colours, run marker  │ 2D / 3D / Fit  │
│ Feed/Spindle │                                           │                │
│ OVERRIDES    │───────────────────────────────────────────│────────────────│
│ JOG          │ CONSOLE (commands + replies)              │ JOB            │
├──────────────┴───────────────────────────────────────────┴────────────────┤
│ Connected · port · baud                  notice · Ln/Col · WCS · state     │
└───────────────────────────────────────────────────────────────────────────┘
```

### Toolbar

- **Port / baud / Connect / Demo** — serial connection.
- **Run** — start the loaded file after a pre-flight check.
- **Pause** — feed hold. The button changes to **Resume** and sends cycle start.
- **Stop** — feed hold plus soft reset; always available while a job is active.
- **Home / Unlock / Reset** — `$H`, `$X` and soft reset.
- **Manual** — opens this guide inside the app (also **Help → User Manual**, F1).

### Machine panel (left)

- **Position** — large **work position** (WPos) values and small machine
  position (MPos), feed, spindle and RX buffer usage. Press the small **0** next
  to an axis to set its work zero.
- **Overrides** — feed and spindle sliders (10–200%) and rapid override
  (100/50/25%). The feed/spindle value is sent when you release the slider.
- **Jog** — XY pad, Z buttons, step size, feed rate, zero buttons, work
  coordinate system, Home, Unlock and Cancel jog.

### Editor and console (centre)

The editor and console share a vertical splitter (roughly 3:2). The find bar
appears above the editor when needed.

### Toolpath and job (right)

- **Toolpath** — 2D preview by default, with an optional 3D view when PyOpenGL
  is installed. Green is executed motion, dashed grey is remaining motion, and
  the dot is the live tool position.
- **Job** — progress, percentage, `line x / n`, elapsed time and estimated
  remaining time.

### Status bar

Connection state, active port/baud, a notice line, cursor position, and the
active work coordinate system, machine state and triggered pins (if any).

---

## 5. Opening, saving and editing G-code

### Files

| Action | How |
| --- | --- |
| Open | **File → Open…** (⌘O) or drag a file onto the window |
| Save | **File → Save** (⌘S) |
| Save as | **File → Save As…** (⌘⇧S) |
| Recent files | **File → Open Recent** (last eight files) |
| New | **File → New** (⌘N) |

Supported extensions in the file dialog: `.nc`, `.gcode`, `.ngc`, `.tap`,
`.txt`, `.cnc` (any file can still be opened). If the editor has unsaved
changes, PlotDeck asks before opening another file, quitting, or dropping a new
one.

Opening a file clears previous job markers and rebuilds the toolpath preview.
Files over 50,000 lines load with undo temporarily disabled; validation is
skipped above 20,000 lines.

### Editor features

- Line-number gutter; the current line is highlighted in blue.
- Syntax colours for G words, M words, axis words, F/S/T, comments, `$`
  commands and line numbers.
- Gutter markers: **green** = line executed, **blue** = current line,
  **red** = line that returned an error, **amber** = line longer than GRBL's
  80-character limit.
- Long lines also get a wavy underline. GRBL may reject blocks over 80
  characters, so shorten them (or split the block) before running.
- The editor auto-scrolls to the executing line **only while it does not have
  focus**, so it never moves your insertion point while you are typing.

### Find and replace

| Action | Shortcut |
| --- | --- |
| Find | ⌘F |
| Replace | ⌘⌥F |
| Next / previous | Enter, or the **Prev** / **Next** buttons |
| Replace one / all | **Replace** / **All** |
| Close the bar | Esc |

Find is literal text (case-sensitive only if **Match case** is checked), not a
regular expression. Replace all updates the editor in one step.

### Edit commands

| Command | Location |
| --- | --- |
| Undo / redo | **Edit** menu, standard shortcuts |
| Go to line | **Edit → Go to Line…** (⌘L) |
| Toggle comment | **Edit → Toggle Comment** (⌘/) |
| Uppercase selection | **Edit → Uppercase Selection** |
| Strip comments | **Edit → Strip Comments** (selected lines) |
| Renumber lines | **Edit → Renumber Lines** (adds `N<line × 10>`, keeps comments) |
| Offset / scale / rotate | **Edit → Transform** |

**Transform** operates on the selected file content:

- **Offset…** — enter `dx, dy, dz` in millimetres, e.g. `10, 0, -1`.
- **Scale…** — multiply all axis words by a factor.
- **Rotate…** — rotate X/Y around Z by an angle in degrees.

Transforms rewrite axis words, preserve `;` comments and leave non-motion lines
alone. Review the preview after transforming; offsets are applied in the file's
programmed units.

---

## 6. Preparing a job

### Home the machine

Press **Home** (`$H`) with the machine clear of clamps and the tool. Homing is
only possible if it is enabled in GRBL (`$22=1`); otherwise GRBL returns
`error:5`. Homing sets machine zero and protects soft limits.

The app tracks whether the machine was homed in this session and includes a
warning in the pre-flight dialog if it was not.

### Jog

1. Click the jog panel background so it has keyboard focus.
2. Choose a **step**: 0.01, 0.1, 1, 10 or 100 mm.
3. Set a jog **feed** in mm/min.
4. Use the XY pad or Z buttons, or the keyboard:

| Key | Motion |
| --- | --- |
| Arrow keys | X/Y |
| Page Up / Page Down | Z up / down |
| `[` / `]` | Decrease / increase step |
| Space | Cancel the current jog |

Jogging is disabled while a job is running, during feed hold and in an alarm.
The keyboard shortcuts only act while the jog panel has focus.

### Zero the work coordinates

Use the **0** button next to an axis in the Position panel, or the **X/Y/Z/All**
buttons in the jog panel. This sends `G10 L20 P<n>` for the selected work
coordinate system, so the current position becomes zero in that system.

- The selector offers **G54–G59**; G54 is the default.
- PlotDeck remembers whether Z was zeroed this session and warns if not.
- After a tool change, re-zero Z.

### Probe Z (touch plate)

**Machine → Probe Z…** opens a wizard for a touch plate wired to GRBL's probe
input.

| Field | Meaning |
| --- | --- |
| Plate thickness | Work zero is set to this height above the contact point |
| Probe feed | Slow probing speed (default 50 mm/min) |
| Max travel | Largest distance to search downward before giving up |
| Retract height | Distance to raise after a successful probe |

The sequence sent is:

1. `G91 G38.2 Z-<travel> F<feed>` — probe downward in relative mode.
2. `G10 L20 P1 Z<thickness>` — set **G54** Z work zero to the plate thickness.
3. `G91 G0 Z<retract>` — retract.
4. `G90` — return to absolute mode.

If the probe does not make contact, GRBL raises `ALARM:5`; check the clip,
plate and wiring, unlock, and try again. The probe wizard always writes to
**G54**, regardless of the selector.

### Work coordinate systems

Selecting **G54–G59** in the jog panel switches the active system with a
`G55`/`G56`/… command. Zeroing uses the selected system. Be aware that your
G-code may contain its own `G54`–`G59` commands that override the selection.

### Spindle

If the spindle is controlled through GRBL, use **Machine → Spindle On…**
(prompts for RPM, sends `M3 S<rpm>`) and **Machine → Spindle Off** (`M5`).
With a manually switched router, leave these alone and turn the router on by
hand; the pre-flight dialog reminds you to verify the spindle is running.

### Overrides

- **Feed** — 10–200%; released slider sends the matching real-time override
  bytes.
- **Spindle** — 10–200%.
- **Rapid** — 100%, 50% or 25%; GRBL only accepts these three values.

Overrides are applied live and are not written to the G-code file. Move the
slider back to 100% to restore normal feed.

---

## 7. Running a job

1. Load the file and check the toolpath preview.
2. Press **Run** (⌘R). PlotDeck shows a **pre-flight check**:
   - file name and line count;
   - estimated time, number of moves and bounding box;
   - maximum cut depth and tools found (`T` words/M6);
   - warnings (not homed, Z not zeroed, unsaved changes, overlong lines, travel
     limits from `$130–$132`, tool changes, spindle reminder).
3. Choose **Start**, **Cancel**, or enable **Dry run** first.
4. During the job the state badge reads **RUN**, the editor follows the
   executing line, the DRO and toolpath update live, and the Job panel shows
   progress and time.

### Run from a line

Click the line in the editor and choose **Machine → Run From Cursor**
(⌘⇧R), or press Run after placing the cursor. The pre-flight dialog warns
“Starting from line N”. Nothing before that line is sent, so the machine must
already be at the correct position for that point in the program (re-home and
re-establish work zero first).

### Pause and resume

- **Pause** sends a feed hold (`!`) and lets the planner stop. GRBL reports
  `Hold:0`/`Hold:1`.
- The button changes to **Resume**; pressing it sends cycle start (`~`).
- Queued lines remain accounted for. Pause is safe mid-arc.

While paused you can inspect the machine, but motion commands are disabled
until the job is resumed or stopped.

### Stop

**Stop** (⌘.) sends a feed hold and then a soft reset, clears the send queue,
and marks the job stopped. This is the fastest way to end a job, but position
may be lost — re-home before continuing work.

### Soft reset

**Reset** (⌘⇧.) sends Ctrl-X. If a job is active, PlotDeck asks for
confirmation. After reset, the streamer clears its queue and re-syncs from the
next status report; position and modal state may need to be re-established.

### Dry run (check mode)

Tick **Dry run** in the pre-flight dialog. PlotDeck enables GRBL check mode
(`$C`), streams the whole file without motion or spindle output, and disables
check mode when the job finishes or is stopped. Check mode still reports
G-code errors, making it useful before a first cut.

### Keeping the Mac awake

While a job is running PlotDeck starts `caffeinate -i` and stops it when the
job ends, so macOS does not sleep mid-cut.

---

## 8. Errors, alarms and interruptions

### G-code errors (`error:N`)

When GRBL rejects a line, PlotDeck pauses the streamer **immediately** and
sends a feed hold — it never continues past an error automatically. A dialog
shows the code, line number and explanation, with:

- **Skip line** — resume after the rejected line (use only if you are sure the
  machine state is still correct).
- **Abort job** — stop the job and reset.

The offending line is marked red in the editor. Because GRBL has already
consumed it, editing it in place does not resend it; fix the file, position at
the line before, and use **Run From Cursor** to retry.

### Alarms

An `ALARM:N` stops the job and locks motion. The dialog explains the cause and
offers:

- **Unlock ($X)** — clear the alarm when the position is still valid (typical
  for a soft-limit alarm).
- **Home ($H)** — re-home when position may be lost (hard limit, reset while
  moving).
- **Close** — dismiss and decide manually.

The state badge turns red. Run, jog and zero stay disabled until the alarm is
cleared and the machine is idle. Z zero tracking is reset after an alarm, so
re-probe before cutting again.

### Connection lost mid-job

PlotDeck marks the last executed line, reports “Job interrupted”, and returns to
**OFFLINE**. Reconnect, wait for **IDLE**, re-home, re-establish work zero, then
**Run From Cursor** from a safe line after the interruption. A USB interruption
during motion can lose steps — inspect the machine before resuming.

### Tool change prompt

An M6 pauses the job and opens the tool-change dialog. See the next section.

---

## 9. Tool changes

GRBL 1.1 does not implement `M6`, so PlotDeck intercepts it and **never sends
the M6 line**. When the next block is an M6 (or a standalone `T<n>` line):

1. Sending continues until the machine's planner is drained.
2. PlotDeck sends a feed hold and shows the tool-change dialog with the tool
   number.
3. Change the tool. **PlotDeck does not automatically stop a manually switched
   spindle or retract Z** — turn the spindle off and raise Z yourself before
   reaching in.
4. Re-probe Z if the tool length changed.
5. Press **Resume job** to continue from the line after M6, or **Abort job**.

The M6 flow trusts you to leave the machine in a safe state. Never reach into a
spindle that may start unexpectedly.

---

## 10. Console

The console shows serial traffic and accepts manual commands:

- **Sent** lines are blue (`>`), `ok` is green, messages are grey, and
  `error:`/`ALARM:` are red with an explanation.
- **Hide status polls** is on by default; turn it off to see every `<...>`
  status report.
- **Autoscroll** follows new lines; **Clear** empties the view.
- The input remembers the last 200 commands; use ↑/↓.
- Enter sends the command.

Console commands work **while idle**. During a job, line commands are refused
(“Cannot send commands while a job is active”) — use the toolbar Pause/Stop.
Real-time bytes `?`, `!` and `~` are accepted when idle and sent as single
bytes, not lines.

Useful commands:

| Command | Meaning |
| --- | --- |
| `?` | One status report |
| `$$` | Dump all GRBL settings |
| `$I` | Firmware/build info |
| `$G` | Parser modal state |
| `$#` | Work coordinate offsets |
| `$H` | Home |
| `$X` | Unlock alarm |
| `$J=G91 X10 F1000` | Jog 10 mm in X |

---

## 11. GRBL settings

**Machine → GRBL Settings…** opens the `$$` editor:

- **Refresh** reads all settings from the controller.
- The table shows `$<number>`, value and a description for common settings.
- Double-click a **Value**, edit it, select the row and press **Write selected**.
- Writes are sent as `$<number>=<value>` and take effect immediately.

PlotDeck also reads settings automatically on connect so it can warn when a
toolpath exceeds the configured travel (`$130`, `$131`, `$132`).

Common settings:

| Setting | Meaning |
| --- | --- |
| `$20`, `$21` | Soft / hard limits |
| `$22` | Homing enabled |
| `$32` | Laser mode (changes spindle behaviour) |
| `$100–$102` | Steps per mm for X/Y/Z |
| `$110–$112` | Maximum rate for X/Y/Z |
| `$120–$122` | Acceleration for X/Y/Z |
| `$130–$132` | Maximum travel for X/Y/Z |

Be careful: wrong steps/mm or travel values can command the machine into its
frame. Keep a backup of the settings you rely on.

---

## 12. Appearance and saved state

- **View → Theme → Dark / Light** switches immediately. On first launch
  PlotDeck follows the macOS appearance.
- Panels are dockable: drag them by their title bar, float them, or hide/show
  them from the **View** menu. The layout is saved on exit.
- Window size and position, last port and baud, theme and recent files persist
  via macOS user settings.
- The application does not modify your G-code file unless you press Save.

---

## 13. Keyboard shortcuts

| Action | Shortcut |
| --- | --- |
| New / Open / Save / Save As | ⌘N / ⌘O / ⌘S / ⌘⇧S |
| Close window / Quit | ⌘W / ⌘Q |
| Undo / Redo | ⌘Z / ⌘⇧Z |
| Find / Replace | ⌘F / ⌘⌥F |
| Go to line | ⌘L |
| Toggle comment | ⌘/ |
| Run / Run from cursor | ⌘R / ⌘⇧R |
| Stop | ⌘. |
| Soft reset | ⌘⇧. |
| Connect / Disconnect | ⌘K |
| Fit toolpath | ⌘0 |
| Focus console | ⌘` |
| Fit toolpath (preview focused) | F |
| Jog X/Y / Z | Arrow keys / Page Up, Page Down |
| Jog step | `[` / `]` |
| Cancel jog | Space |

Jog keys are active only while the jog panel has focus. Pause/Resume has no
global shortcut by design — use the toolbar or **Machine** menu so a stray
keypress cannot cycle-start the machine.

---

## 14. Error and alarm reference

### Common GRBL errors

| Code | Meaning / action |
| --- | --- |
| `error:1` | Malformed word — missing letter or value |
| `error:2` | Invalid numeric format |
| `error:3` | Unsupported `$` command |
| `error:5` | Homing not enabled (`$22`) |
| `error:8` | `$` command only allowed while idle |
| `error:9` | Locked out during alarm or jog |
| `error:11` | Line longer than 80 characters |
| `error:20` | Unsupported/invalid G-code command |
| `error:21` | Two commands from the same modal group in one block |
| `error:22` | Feed rate is not set |
| `error:26` | Missing required axis or parameter word |
| `error:31` | Command not allowed in the current state |
| `error:34` / `error:35` | Invalid arc radius or endpoint |

### Common GRBL alarms

| Code | Meaning / action |
| --- | --- |
| `ALARM:1` | Hard limit hit; position likely lost — re-home |
| `ALARM:2` | Soft limit exceeded; target outside travel — unlock if position is valid |
| `ALARM:3` | Reset while moving; position likely lost — re-home |
| `ALARM:4` | Probe not in the expected initial state |
| `ALARM:5` | Probe did not contact within the search distance |
| `ALARM:6–9` | Homing failures; check switches, wiring and `$22`/`$25`/`$27` |

---

## 15. Troubleshooting

| Problem | Likely cause and fix |
| --- | --- |
| Run is disabled although a file is loaded | Not connected, not idle, alarm active, or a job is already running |
| Port list is empty | Refresh, try another cable/port, install the CH340 driver |
| Connect never completes | Another app owns the port, wrong port, no GRBL firmware, bad cable |
| Machine does not move when jogging | Alarm, feed hold, not idle, jog disabled during a job, or the drivers are disabled |
| Position shows `---` | No status report yet; check the connection |
| Feed/spindle show `--` | GRBL has not reported `FS` yet |
| Toolpath is empty | File contains only comments/dwells, or the parser found no drawable moves |
| 3D button says unavailable | Install PyOpenGL: `pip install -e ".[3d]"` |
| Preview bounds look wrong | Check units (`G20/G21`) and absolute/relative mode (`G90/G91`) in the file |
| Job stops with `error:20` | A command GRBL does not support; fix the line, then run from before it |
| Probe fails with `ALARM:5` | Clip/plate wiring, probe input invert (`$6`), travel too short, or no contact |
| Machine sleeps mid-job | PlotDeck starts `caffeinate`; check that the `caffeinate` command exists |
| App won’t start from source | Activate `.venv` and reinstall with `pip install -e ".[dev,3d]"` |
| macOS blocks the app | It is unsigned; right-click → **Open**, or sign/notarize it |
| Need to see what happened | Read `~/Library/Logs/PlotDeck/plotdeck.log` |

---

## 16. Files and logs

| Item | Location |
| --- | --- |
| G-code files | Anywhere you choose; recent list holds the last eight |
| Application log | `~/Library/Logs/PlotDeck/plotdeck.log` (rotating, up to 3 backups) |
| Preferences, layout, recent files | Managed by Qt `QSettings` for the `PlotDeck` application |

The log records startup, connection events, crashes with tracebacks, and
unexpected exceptions. Attach it when reporting a problem.

---

## 17. Limitations

- Only GRBL 1.1 is supported. Marlin, FluidNC, grblHAL and other controllers
  are out of scope.
- PlotDeck is a sender/editor, not CAM: it does not generate toolpaths from
  CAD/SVG/images.
- Find/replace is literal text; there is no regex mode, hover documentation or
  G/M-code autocomplete.
- Clicking a toolpath segment does not jump to the corresponding line yet.
- There are no saved macros, tool/material library, height-map leveling or
  automatic reconnect.
- Manual spindle routers are not controlled by GRBL; M6 does not retract Z or
  stop a manual spindle.
- The app icon is optional; the packaged `.app` is unsigned unless you sign it.
- Only macOS is tested. The core is portable, but Windows/Linux packaging is
  not provided.
- Software stop, feed hold and reset are not substitutes for a hardware
  emergency stop.

---

## 18. Demo mode

Click **Demo** in the toolbar to connect to an in-process simulated GRBL 1.1
machine. The demo accepts line commands, acknowledges them, reports status and
responds to real-time commands, so you can:

- practise connecting, running a file, pausing/resuming and stopping;
- explore the editor, preview, jog panel, console and settings dialog;
- verify the interface without risking a real machine.

The demo does **not** move a physical machine, run a spindle, or perform a real
probe. M6 prompts, alarms and disconnects can only be produced by real hardware
or the developer test suite.

---

For installation, architecture and packaging details see `README.md`. For the
original product plan and UI specification see `GOAL.md`.
