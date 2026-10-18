"""PlotDeck main window."""

from __future__ import annotations

import subprocess
import sys
import time
from contextlib import suppress
from pathlib import Path

from PySide6.QtCore import QObject, QSettings, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QActionGroup, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDockWidget,
    QFileDialog,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSizePolicy,
    QSplitter,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from .. import APP_NAME
from ..core.controller import MachineController, SettingsEntry
from ..core.gcode_parser import ProgramLine, Toolpath, build_toolpath
from ..core.grbl_protocol import ResponseKind
from ..core.status import MachineStatus
from ..core.streamer import StreamerState
from ..utils.settings import AppSettings
from .connection_panel import ConnectionPanel
from .console import Console
from .dialogs import PreflightDialog, ProbeDialog, SettingsDialog, ToolChangeDialog
from .editor import FindBar, GcodeEditor
from .job_panel import JobPanel
from .jog_panel import JogPanel
from .manual import ManualDialog
from .status_panel import StatusPanel
from .theme import build_stylesheet, is_dark_system, tokens
from .visualizer import Visualizer

GCODE_FILTER = "G-code (*.nc *.gcode *.ngc *.tap *.txt *.cnc);;All files (*)"


class ControllerBridge(QObject):
    line = Signal(object, str)
    sent = Signal(str)
    status = Signal(object)
    connected = Signal(str)
    disconnected = Signal(str)
    alarm = Signal(int, str)
    message = Signal(str)
    commandError = Signal(int, str)
    streamError = Signal(object, int, str)
    progress = Signal(int, int, int)
    jobFinished = Signal(str)
    toolChange = Signal(object)
    streamState = Signal(object)
    settings = Signal(object)
    portError = Signal(str)


class MainWindow(QMainWindow):
    def __init__(
        self,
        controller: MachineController | None = None,
        app_settings: AppSettings | None = None,
    ) -> None:
        super().__init__()
        self.app_settings = app_settings or AppSettings()
        self.controller = controller or MachineController()
        self._settings: QSettings = self.app_settings._settings

        self._current_path: Path | None = None
        self._program: list[ProgramLine] = []
        self._toolpath: Toolpath | None = None
        self._limits: tuple[float, float, float] | None = None
        self._status = MachineStatus()
        self._connected = False
        self._stream_state = StreamerState.IDLE
        self._last_progress_line = 0
        self._last_editor_update = 0.0
        self._wcs = 1
        self._homed = False
        self._z_zeroed = False
        self._dry_run = False
        self._alarm_open = False
        self._caffeinate: subprocess.Popen | None = None
        self._settings_dialog: SettingsDialog | None = None
        self._manual_dialog: ManualDialog | None = None
        self._dark = self.app_settings.dark_theme(is_dark_system())

        self.setWindowTitle(APP_NAME)
        self.resize(1440, 900)
        self.setMinimumSize(1100, 700)
        self.setAcceptDrops(True)

        self.bridge = ControllerBridge()
        self._build_ui()
        self._build_toolbar()
        self._build_menus()
        self._build_statusbar()
        self._wire_controller()
        self._wire_ui()
        self._refresh_ports()
        self._rebuild_recent_menu()
        self._update_actions()
        self._restore_window()

        self.apply_theme(self._dark, persist=False)
        self.editor.document().modificationChanged.connect(lambda _: self._update_title())
        self._update_title()

    # ------------------------------------------------------------------ #
    # Construction
    # ------------------------------------------------------------------ #
    def _build_ui(self) -> None:
        self.editor = GcodeEditor()
        self.editor.setPlaceholderText("Open a G-code file (⌘O), drop one here, or start typing…")
        self.console = Console()
        self.find_bar = FindBar(self.editor)
        self.status_panel = StatusPanel()
        self.jog_panel = JogPanel()
        self.visualizer = Visualizer()
        self.job_panel = JobPanel()

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.find_bar)
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self.editor)
        splitter.addWidget(self.console)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([560, 340])
        layout.addWidget(splitter, 1)
        self.setCentralWidget(central)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(1)
        left_layout.addWidget(self.status_panel)
        left_layout.addWidget(self.jog_panel)
        left_layout.addStretch(1)

        self.dock_machine = QDockWidget("Machine", self)
        self.dock_machine.setObjectName("MachineDock")
        self.dock_machine.setWidget(left)
        self.dock_machine.setMinimumWidth(300)

        self.dock_toolpath = QDockWidget("Toolpath", self)
        self.dock_toolpath.setObjectName("ToolpathDock")
        self.dock_toolpath.setWidget(self.visualizer)
        self.dock_toolpath.setMinimumWidth(340)

        self.dock_job = QDockWidget("Job", self)
        self.dock_job.setObjectName("JobDock")
        self.dock_job.setWidget(self.job_panel)
        self.dock_job.setMinimumHeight(140)

        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.dock_machine)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock_toolpath)
        self.splitDockWidget(self.dock_toolpath, self.dock_job, Qt.Orientation.Vertical)
        self.resizeDocks([self.dock_machine], [310], Qt.Orientation.Horizontal)
        self.resizeDocks([self.dock_toolpath, self.dock_job], [620, 200], Qt.Orientation.Vertical)

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("Main")
        toolbar.setObjectName("MainToolbar")
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.addToolBar(toolbar)

        self.connection_panel = ConnectionPanel()
        toolbar.addWidget(self.connection_panel)
        toolbar.addSeparator()

        self.action_run = self._action("Run", self._run, "Ctrl+R", "Run the loaded file (⌘R)")
        self.action_pause = self._action(
            "Pause", self._toggle_pause, None, "Feed hold / cycle start"
        )
        self.action_stop = self._action(
            "Stop", self._stop, QKeySequence("Ctrl+."), "Stop the job (⌘.)"
        )
        toolbar.addAction(self.action_run)
        toolbar.addAction(self.action_pause)
        toolbar.addAction(self.action_stop)
        toolbar.addSeparator()

        self.action_home = self._action("Home", self._home, None, "Run the homing cycle ($H)")
        self.action_unlock = self._action("Unlock", self._unlock, None, "Clear an alarm ($X)")
        self.action_reset = self._action(
            "Reset", self._soft_reset, QKeySequence("Ctrl+Shift+."), "Soft reset (Ctrl-X)"
        )
        toolbar.addAction(self.action_home)
        toolbar.addAction(self.action_unlock)
        toolbar.addAction(self.action_reset)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        toolbar.addWidget(spacer)
        self.action_manual = self._action(
            "Manual", self._show_manual, "F1", "Open the PlotDeck user manual"
        )
        toolbar.addAction(self.action_manual)
        toolbar.addSeparator()

        self.firmware_label = QLabel("GRBL")
        self.firmware_label.setObjectName("Muted")
        toolbar.addWidget(self.firmware_label)

        stop_button = toolbar.widgetForAction(self.action_stop)
        if stop_button is not None:
            stop_button.setObjectName("Danger")

    def _build_menus(self) -> None:
        menu = self.menuBar()

        file_menu = menu.addMenu("&File")
        file_menu.addAction(self._action("New", self._new_file, QKeySequence.StandardKey.New))
        file_menu.addAction(self._action("Open…", self._open_file, QKeySequence.StandardKey.Open))
        self.recent_menu = file_menu.addMenu("Open Recent")
        file_menu.addSeparator()
        file_menu.addAction(self._action("Save", self._save, QKeySequence.StandardKey.Save))
        file_menu.addAction(
            self._action("Save As…", self._save_as, QKeySequence.StandardKey.SaveAs)
        )
        file_menu.addSeparator()
        file_menu.addAction(self._action("Close", self.close, QKeySequence.StandardKey.Close))
        file_menu.addAction("Quit", self.close, QKeySequence.StandardKey.Quit)

        edit_menu = menu.addMenu("&Edit")
        edit_menu.addAction(self._action("Undo", self.editor.undo, QKeySequence.StandardKey.Undo))
        edit_menu.addAction(self._action("Redo", self.editor.redo, QKeySequence.StandardKey.Redo))
        edit_menu.addSeparator()
        edit_menu.addAction(self._action("Find…", self._show_find, QKeySequence.StandardKey.Find))
        edit_menu.addAction(
            self._action("Replace…", self._show_replace, QKeySequence("Ctrl+Alt+F"))
        )
        edit_menu.addAction(self._action("Go to Line…", self._go_to_line, QKeySequence("Ctrl+L")))
        edit_menu.addSeparator()
        edit_menu.addAction(
            self._action("Toggle Comment", self._toggle_comment, QKeySequence("Ctrl+/"))
        )
        edit_menu.addAction("Uppercase Selection", self.editor.uppercase_selection)
        edit_menu.addAction("Strip Comments", self._strip_comments)
        edit_menu.addAction("Renumber Lines", self.editor.renumber)
        transform = edit_menu.addMenu("Transform")
        transform.addAction("Offset…", self._transform_offset)
        transform.addAction("Scale…", self._transform_scale)
        transform.addAction("Rotate…", self._transform_rotate)

        view_menu = menu.addMenu("&View")
        view_menu.addAction(self.dock_machine.toggleViewAction())
        view_menu.addAction(self.dock_toolpath.toggleViewAction())
        view_menu.addAction(self.dock_job.toggleViewAction())
        view_menu.addSeparator()
        view_menu.addAction(
            self._action(
                "Zoom In",
                self.visualizer.zoom_in,
                QKeySequence.StandardKey.ZoomIn,
                "Zoom into the toolpath",
            )
        )
        view_menu.addAction(
            self._action(
                "Zoom Out",
                self.visualizer.zoom_out,
                QKeySequence.StandardKey.ZoomOut,
                "Zoom out of the toolpath",
            )
        )
        view_menu.addAction(self._action("Fit Toolpath", self.visualizer.fit, "Ctrl+0"))
        theme_menu = view_menu.addMenu("Theme")
        self._theme_group = QActionGroup(self)
        dark_action = QAction("Dark", self, checkable=True)
        light_action = QAction("Light", self, checkable=True)
        self._theme_group.addAction(dark_action)
        self._theme_group.addAction(light_action)
        dark_action.setChecked(self._dark)
        light_action.setChecked(not self._dark)
        dark_action.triggered.connect(lambda: self.apply_theme(True))
        light_action.triggered.connect(lambda: self.apply_theme(False))
        theme_menu.addActions([dark_action, light_action])
        view_menu.addSeparator()
        view_menu.addAction(self._action("Focus Console", self.console.focus_input, "Ctrl+`"))

        machine_menu = menu.addMenu("&Machine")
        machine_menu.addAction(
            self._action("Connect / Disconnect", self._toggle_connection, "Ctrl+K")
        )
        machine_menu.addSeparator()
        machine_menu.addAction(self.action_run)
        machine_menu.addAction(self.action_pause)
        machine_menu.addAction(self.action_stop)
        machine_menu.addAction(
            self._action("Run From Cursor", self._run_from_cursor, "Ctrl+Shift+R")
        )
        machine_menu.addSeparator()
        machine_menu.addAction(self.action_home)
        machine_menu.addAction(self.action_unlock)
        machine_menu.addAction(self.action_reset)
        machine_menu.addSeparator()
        machine_menu.addAction("Cancel Jog", self.controller.jog_cancel)
        machine_menu.addAction("Probe Z…", self._probe_dialog)
        machine_menu.addAction("Spindle On…", self._spindle_on)
        machine_menu.addAction("Spindle Off", self.controller.spindle_off)
        machine_menu.addSeparator()
        machine_menu.addAction("GRBL Settings…", self._show_settings)

        help_menu = menu.addMenu("&Help")
        help_menu.addAction(self.action_manual)
        help_menu.addAction("Keyboard Shortcuts", self._show_shortcuts)
        help_menu.addAction("About PlotDeck", self._about)

        fit_shortcut = QShortcut(QKeySequence("F"), self.visualizer)
        fit_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        fit_shortcut.activated.connect(self.visualizer.fit)

    def _build_statusbar(self) -> None:
        bar = self.statusBar()
        self._status_connection = QLabel("Offline")
        self._status_port = QLabel("")
        self._status_modal = QLabel("G21 · G90 · G54")
        self._status_cursor = QLabel("Ln 1, Col 1")
        self._status_notice = QLabel("")
        for label in (
            self._status_connection,
            self._status_port,
            self._status_cursor,
            self._status_modal,
            self._status_notice,
        ):
            label.setObjectName("Muted")
        bar.addWidget(self._status_connection)
        bar.addWidget(self._status_port)
        bar.addPermanentWidget(self._status_notice, 1)
        bar.addPermanentWidget(self._status_cursor)
        bar.addPermanentWidget(self._status_modal)

    def _wire_controller(self) -> None:
        controller = self.controller
        bridge = self.bridge
        controller.on_line = bridge.line.emit
        controller.on_sent = bridge.sent.emit
        controller.on_status = bridge.status.emit
        controller.on_connected = bridge.connected.emit
        controller.on_disconnected = bridge.disconnected.emit
        controller.on_alarm = bridge.alarm.emit
        controller.on_message = bridge.message.emit
        controller.on_command_error = bridge.commandError.emit
        controller.on_stream_error = bridge.streamError.emit
        controller.on_progress = bridge.progress.emit
        controller.on_job_finished = bridge.jobFinished.emit
        controller.on_tool_change = bridge.toolChange.emit
        controller.on_stream_state = bridge.streamState.emit
        controller.on_settings = bridge.settings.emit
        controller.on_port_error = bridge.portError.emit

        bridge.line.connect(self._on_line)
        bridge.sent.connect(lambda text: self.console.append("sent", text))
        bridge.status.connect(self._on_status)
        bridge.connected.connect(self._on_connected)
        bridge.disconnected.connect(self._on_disconnected)
        bridge.alarm.connect(self._on_alarm)
        bridge.message.connect(self._on_message)
        bridge.commandError.connect(self._on_command_error)
        bridge.streamError.connect(self._on_stream_error)
        bridge.progress.connect(self._on_progress)
        bridge.jobFinished.connect(self._on_job_finished)
        bridge.toolChange.connect(self._on_tool_change)
        bridge.streamState.connect(self._on_stream_state)
        bridge.settings.connect(self._on_settings)
        bridge.portError.connect(self._on_port_error)

    def _wire_ui(self) -> None:
        self.connection_panel.connectRequested.connect(self._connect)
        self.connection_panel.disconnectRequested.connect(self.controller.disconnect)
        self.console.commandSubmitted.connect(self._send_command)
        self.jog_panel.jogRequested.connect(self.controller.jog)
        self.jog_panel.cancelRequested.connect(self.controller.jog_cancel)
        self.jog_panel.homeRequested.connect(self._home)
        self.jog_panel.unlockRequested.connect(self._unlock)
        self.jog_panel.zeroRequested.connect(self._zero_axis)
        self.jog_panel.gotoZeroRequested.connect(lambda: self.controller.goto_zero("XY"))
        self.jog_panel.wcsChanged.connect(self._change_wcs)
        self.status_panel.zeroRequested.connect(self._zero_axis)
        self.status_panel.feedOverrideChanged.connect(
            lambda value: self.controller.set_override("feed", value)
        )
        self.status_panel.spindleOverrideChanged.connect(
            lambda value: self.controller.set_override("spindle", value)
        )
        self.status_panel.rapidOverrideChanged.connect(
            lambda value: self.controller.set_override("rapid", value)
        )
        self.editor.cursorLineChanged.connect(self._update_cursor_label)

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    def _action(
        self,
        text: str,
        slot,  # noqa: ANN001
        shortcut=None,  # noqa: ANN001
        tip: str = "",
    ) -> QAction:
        action = QAction(text, self)
        if shortcut is not None:
            action.setShortcut(
                QKeySequence(shortcut) if not isinstance(shortcut, QKeySequence) else shortcut
            )
        if tip:
            action.setStatusTip(tip)
            action.setToolTip(tip)
        action.triggered.connect(slot)
        return action

    def _update_title(self) -> None:
        name = self._current_path.name if self._current_path else "Untitled"
        modified = self.editor.document().isModified()
        self.setWindowTitle(f"{APP_NAME} — {name}{' *' if modified else ''}")

    def _update_cursor_label(self, line: int) -> None:
        column = self.editor.textCursor().positionInBlock() + 1
        self._status_cursor.setText(f"Ln {line}, Col {column}")

    def _refresh_ports(self) -> None:
        self.connection_panel.refresh_ports()
        last = self.app_settings.last_port()
        if last:
            self.connection_panel.select_port(last)
        self.connection_panel.set_baud(self.app_settings.last_baud())

    # ------------------------------------------------------------------ #
    # Files
    # ------------------------------------------------------------------ #
    def _maybe_save(self) -> bool:
        if not self.editor.document().isModified():
            return True
        box = QMessageBox(self)
        box.setWindowTitle("Unsaved changes")
        box.setText("Save changes before continuing?")
        box.setStandardButtons(
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel
        )
        box.setDefaultButton(QMessageBox.StandardButton.Save)
        result = box.exec()
        if result == QMessageBox.StandardButton.Save:
            return self._save()
        return result == QMessageBox.StandardButton.Discard

    def _new_file(self) -> None:
        if not self._maybe_save():
            return
        self.editor.set_source_text("")
        self._current_path = None
        self._program = []
        self._toolpath = None
        self.visualizer.clear()
        self.job_panel.reset()
        self.editor.document().setModified(False)
        self._update_title()
        self._update_actions()

    def _open_file(self) -> None:
        if not self._maybe_save():
            return
        path, _ = QFileDialog.getOpenFileName(self, "Open G-code", str(Path.home()), GCODE_FILTER)
        if path:
            self.open_path(path)

    def open_path(self, path: str) -> None:
        try:
            text = Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            QMessageBox.critical(self, "Could not open file", str(exc))
            return
        self._current_path = Path(path)
        self.editor.set_source_text(text)
        self.editor.document().setModified(False)
        self.app_settings.add_recent_file(str(self._current_path))
        self._rebuild_recent_menu()
        self._update_title()
        self._refresh_program()
        self.job_panel.reset()
        self.console.log(f"Loaded {self._current_path.name} ({len(self._program)} lines)")
        self._update_actions()

    def _save(self) -> bool:
        if self._current_path is None:
            return self._save_as()
        try:
            self._current_path.write_text(self.editor.source_text(), encoding="utf-8")
        except OSError as exc:
            QMessageBox.critical(self, "Could not save file", str(exc))
            return False
        self.editor.document().setModified(False)
        self.app_settings.add_recent_file(str(self._current_path))
        self._rebuild_recent_menu()
        self._update_title()
        return True

    def _save_as(self) -> bool:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save G-code",
            str(self._current_path or Path.home() / "job.nc"),
            GCODE_FILTER,
        )
        if not path:
            return False
        self._current_path = Path(path)
        return self._save()

    def _rebuild_recent_menu(self) -> None:
        self.recent_menu.clear()
        files = self.app_settings.recent_files()
        if not files:
            action = self.recent_menu.addAction("No recent files")
            action.setEnabled(False)
            return
        for path in files:
            action = self.recent_menu.addAction(Path(path).name)
            action.setToolTip(path)
            action.triggered.connect(lambda _=False, p=path: self.open_path(p))
        self.recent_menu.addSeparator()
        self.recent_menu.addAction("Clear Menu", self.app_settings.clear_recent_files)

    def _refresh_program(self) -> None:
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self._program = self.editor.program()
            self.visualizer.set_program(self._program, limits=self._limits)
            self._toolpath = self.visualizer.toolpath
            if self._program:
                self._status_notice.setText(
                    f"{len(self._program):,} lines · "
                    f"{self._toolpath.total_length:.0f} mm of motion"
                )
        finally:
            QApplication.restoreOverrideCursor()
        self._update_actions()

    def _toggle_comment(self) -> None:
        self.editor.toggle_comment()
        self.editor.document().setModified(True)
        self._refresh_program()

    def _strip_comments(self) -> None:
        self.editor.strip_comments()
        self._refresh_program()

    def _transform_offset(self) -> None:
        text, ok = QInputDialog.getText(
            self, "Offset", "dx, dy, dz in mm (for example: 10, 0, -1)", text="0, 0, 0"
        )
        if not ok:
            return
        try:
            dx, dy, dz = (float(part.strip()) for part in text.split(","))
        except ValueError:
            QMessageBox.warning(self, "Offset", "Enter three numbers separated by commas.")
            return
        self.editor.transform(dx=dx, dy=dy, dz=dz)
        self._after_transform()

    def _transform_scale(self) -> None:
        factor, ok = QInputDialog.getDouble(self, "Scale", "Scale factor", 1.0, 0.01, 100.0, 3)
        if ok:
            self.editor.transform(scale=factor)
            self._after_transform()

    def _transform_rotate(self) -> None:
        angle, ok = QInputDialog.getDouble(
            self, "Rotate", "Rotation around Z (degrees)", 0.0, -360.0, 360.0, 2
        )
        if ok:
            self.editor.transform(rotate=angle)
            self._after_transform()

    def _after_transform(self) -> None:
        self.editor.document().setModified(True)
        self._refresh_program()
        self._update_title()

    def _show_find(self) -> None:
        self.find_bar.activate(replace=False)

    def _show_replace(self) -> None:
        self.find_bar.activate(replace=True)

    def _go_to_line(self) -> None:
        line, ok = QInputDialog.getInt(
            self,
            "Go to line",
            "Line number",
            self.editor.current_line(),
            1,
            max(1, self.editor.blockCount()),
        )
        if ok:
            self.editor.go_to_line(line)

    # ------------------------------------------------------------------ #
    # Connection
    # ------------------------------------------------------------------ #
    def _connect(self, port: str, baud: int, demo: bool) -> None:
        self.app_settings.set_last_port(port)
        self.app_settings.set_last_baud(baud)
        self._status_connection.setText("Connecting…")
        self._status_notice.setText(
            "Waiting for the GRBL banner (the Uno resets when the port opens)…"
        )
        self.controller.connect(port, baud, demo)

    def _toggle_connection(self) -> None:
        if self._connected:
            self.controller.disconnect()
        else:
            self.connection_panel.toggle()

    def _on_connected(self, version: str) -> None:
        self._connected = True
        self._homed = False
        self._z_zeroed = False
        self._alarm_open = False
        self._status_connection.setText("Connected")
        self._status_port.setText(
            f"{self.app_settings.last_port()} · {self.app_settings.last_baud()} baud"
        )
        self.connection_panel.set_connected(True, self.app_settings.last_port())
        self.status_panel.set_connected(True, version)
        self.firmware_label.setText(f"GRBL {version}" if version else "GRBL")
        self.console.log(f"Connected: GRBL {version}")
        self._status_notice.setText(f"Connected to GRBL {version}")
        self._update_actions()
        QTimer.singleShot(350, self._request_settings_silently)

    def _on_disconnected(self, reason: str) -> None:
        self._connected = False
        self.status_panel.set_connected(False)
        self.connection_panel.set_connected(False)
        self._status_connection.setText("Offline")
        self._status_port.setText("")
        self._status_notice.setText(reason)
        self.console.log(f"Disconnected: {reason}")
        if self._last_progress_line and self._stream_state in (
            StreamerState.RUNNING,
            StreamerState.PAUSED,
        ):
            self.editor.mark_error(self._last_progress_line)
            self.console.log(
                f"Job interrupted near line {self._last_progress_line}. "
                "Re-home before resuming from that line."
            )
        self._stream_state = StreamerState.IDLE
        self._update_actions()

    def _on_port_error(self, message: str) -> None:
        self.connection_panel.set_error(message)
        self.console.append("error", message)
        self._status_connection.setText("Offline")
        self._status_notice.setText(message)

    def _request_settings_silently(self) -> None:
        if self._connected and not (
            self.controller.streamer and self.controller.streamer.is_active
        ):
            self.controller.request_settings()

    # ------------------------------------------------------------------ #
    # Running jobs
    # ------------------------------------------------------------------ #
    def _run(self) -> None:
        self._start_job()

    def _run_from_cursor(self) -> None:
        self._start_job(from_line=self.editor.current_line())

    def _start_job(self, from_line: int | None = None) -> None:
        if not self._connected:
            QMessageBox.information(self, "Not connected", "Connect to the machine first.")
            return
        streamer = self.controller.streamer
        if streamer is not None and streamer.is_active:
            return
        if self._status.is_alarm:
            QMessageBox.warning(
                self,
                "Alarm active",
                "Clear the alarm (Unlock) and home the machine before running a job.",
            )
            return
        program = self.editor.program()
        if not program:
            QMessageBox.information(self, "Nothing to run", "The file has no executable lines.")
            return

        self._refresh_program()
        toolpath = build_toolpath(program, limits=self._limits)
        warnings = self._collect_warnings(program, toolpath, from_line)
        dialog = PreflightDialog(
            self._current_path.name if self._current_path else "Untitled",
            len(program),
            toolpath,
            warnings,
            self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        dry_run = dialog.choice == "dry_run"
        if dry_run and not self.controller.send_line("$C"):
            QMessageBox.warning(self, "Dry run", "Could not enable GRBL check mode.")
            return
        started = self.controller.run_program(program, from_line)
        if not started:
            if dry_run:
                self.controller.send_line("$C")
            QMessageBox.warning(
                self,
                "Could not start",
                "The job could not start. Check the connection and machine state.",
            )
            return

        self._dry_run = dry_run
        self._keep_awake(True)
        self._last_progress_line = from_line or 0
        self._last_editor_update = 0.0
        self.job_panel.begin(len(program), toolpath.estimated_seconds)
        self.editor.clear_markers()
        self.visualizer.set_progress_line(0, force=True)
        self._status_notice.setText("Dry run started (check mode)" if dry_run else "Job running")
        self._update_actions()

    def _collect_warnings(
        self, program: list[ProgramLine], toolpath: Toolpath, from_line: int | None
    ) -> list[str]:
        warnings: list[str] = []
        if not self._homed:
            warnings.append(
                "The machine has not been homed in this session. Soft limits and "
                "work coordinates may not be where you expect."
            )
        if not self._z_zeroed:
            warnings.append("Z zero has not been set in this session.")
        if self.editor.document().isModified():
            warnings.append("The file has unsaved changes; the editor contents will run.")
        long_lines = sum(1 for line in program if line.too_long)
        if long_lines:
            warnings.append(
                f"{long_lines} line(s) exceed GRBL's 80-character limit and may be rejected."
            )
        warnings.extend(toolpath.warnings)
        if toolpath.tools:
            warnings.append(
                "This file has tool changes (M6). They are intercepted and will pause the job."
            )
        if from_line:
            warnings.append(f"Starting from line {from_line}.")
        warnings.append("Verify the spindle is running and the workpiece is secure.")
        return warnings

    def _toggle_pause(self) -> None:
        streamer = self.controller.streamer
        if streamer is None:
            return
        if streamer.state is StreamerState.PAUSED:
            if streamer.error is not None or streamer.awaiting_tool_change is not None:
                return
            self.controller.resume()
        elif streamer.state is StreamerState.RUNNING:
            self.controller.pause()

    def _stop(self) -> None:
        self.controller.stop()
        self._status_notice.setText("Stopping…")
        if self._dry_run:
            QTimer.singleShot(400, self._disable_check_mode)

    def _soft_reset(self) -> None:
        streamer = self.controller.streamer
        active = streamer is not None and streamer.is_active
        if active:
            box = QMessageBox.question(
                self,
                "Soft reset",
                "Reset the controller now? The job will be aborted and position " "may be lost.",
            )
            if box != QMessageBox.StandardButton.Yes:
                return
        self.controller.reset()
        self.editor.mark_all_done()

    def _home(self) -> None:
        if self.controller.home():
            self._homed = True
            self.console.log("Homing cycle requested")
            self._status_notice.setText("Homing…")

    def _unlock(self) -> None:
        if self.controller.unlock():
            self._status_notice.setText("Alarm unlock requested")

    def _zero_axis(self, axis: str) -> None:
        if self.controller.zero_axis(axis, self._wcs):
            if axis.upper() == "Z":
                self._z_zeroed = True
            self._status_notice.setText(f"Work zero set for {axis}")
            self.console.log(f"Zeroed {axis} in G5{self._wcs + 3}")

    def _change_wcs(self, index: int) -> None:
        self._wcs = index
        self.controller.goto_wcs(index)
        self._status_modal.setText(f"G21 · G90 · G5{index + 3}")

    def _probe_dialog(self) -> None:
        if not self._connected:
            QMessageBox.information(self, "Not connected", "Connect to the machine first.")
            return
        dialog = ProbeDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        thickness, feed, travel, retract = dialog.values()
        if self.controller.probe_z(thickness, feed, travel, retract):
            self._z_zeroed = True
            self._status_notice.setText("Probing Z…")
            self.console.log(
                f"Probing Z (plate {thickness} mm, feed {feed} mm/min, travel {travel} mm)"
            )
        else:
            QMessageBox.warning(self, "Probe", "Could not start the probe cycle.")

    def _spindle_on(self) -> None:
        if not self._connected:
            return
        rpm, ok = QInputDialog.getDouble(self, "Spindle", "RPM", 1000, 1, 60000, 0)
        if ok:
            self.controller.set_spindle(rpm)

    # ------------------------------------------------------------------ #
    # Controller events
    # ------------------------------------------------------------------ #
    def _on_line(self, kind: ResponseKind, text: str) -> None:
        self.console.append(kind, text)

    def _on_status(self, status: MachineStatus) -> None:
        self._status = status
        self.status_panel.update_status(status)
        active = self._stream_state in (StreamerState.RUNNING, StreamerState.PAUSED)
        self.jog_panel.set_machine(status, self._connected, active)
        if status.wpos:
            self.visualizer.set_position(*status.wpos)
        if status.is_idle and self._alarm_open:
            self._alarm_open = False
        pins = f" · pins {status.pins}" if status.pins else ""
        self._status_modal.setText(f"G5{self._wcs + 3} · {status.state}{pins}")
        self._update_actions()

    def _on_progress(self, sent: int, total: int, line: int) -> None:
        self.job_panel.update_progress(sent, total, line)
        if line:
            self._last_progress_line = line
            self.visualizer.set_progress_line(line)
            now = time.monotonic()
            if now - self._last_editor_update > 0.12:
                self._last_editor_update = now
                self.editor.set_execution_line(line)

    def _on_stream_state(self, state: StreamerState) -> None:
        self._stream_state = state
        if state is StreamerState.PAUSED:
            self.action_pause.setText("Resume")
        else:
            self.action_pause.setText("Pause")
        active = state in (StreamerState.RUNNING, StreamerState.PAUSED)
        self.jog_panel.set_machine(self._status, self._connected, active)
        self._update_actions()

    def _on_job_finished(self, reason: str) -> None:
        self._keep_awake(False)
        self.job_panel.finish(reason)
        if reason == "completed":
            self.editor.mark_all_done()
            self.visualizer.set_progress_line(self._last_progress_line, force=True)
            self._status_notice.setText("Job completed")
        elif reason == "stopped":
            self._status_notice.setText("Job stopped")
        elif reason == "alarm":
            self._status_notice.setText("Job halted by alarm")
        elif reason == "disconnected":
            self._status_notice.setText("Job interrupted: connection lost")
        self._stream_state = StreamerState.IDLE
        if self._dry_run:
            QTimer.singleShot(350, self._disable_check_mode)
        self._update_actions()

    def _disable_check_mode(self) -> None:
        if self._dry_run:
            self.controller.send_line("$C")
            self._dry_run = False

    def _on_stream_error(self, line: ProgramLine, code: int, detail: str) -> None:
        self.editor.mark_error(line.source_line)
        self.editor.go_to_line(line.source_line)
        self.console.append("error", f"error:{code} on line {line.source_line}: {detail}")
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("G-code error")
        box.setText(f"error:{code} on line {line.source_line}")
        box.setInformativeText(f"{detail}\n\n{line.text}")
        skip = box.addButton("Skip line", QMessageBox.ButtonRole.AcceptRole)
        abort = box.addButton("Abort job", QMessageBox.ButtonRole.DestructiveRole)
        box.setDefaultButton(abort)
        box.exec()
        if box.clickedButton() is skip:
            self.controller.skip_error()
        else:
            self.controller.stop()

    def _on_tool_change(self, line: ProgramLine) -> None:
        self._status_notice.setText(f"Tool change at line {line.source_line}")
        dialog = ToolChangeDialog(line.tool_number, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.controller.complete_tool_change()
        else:
            self.controller.cancel_tool_change()

    def _on_alarm(self, code: int, detail: str) -> None:
        self._alarm_open = True
        self._z_zeroed = False
        self._status_notice.setText(f"ALARM:{code} {detail}")
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Critical)
        box.setWindowTitle(f"ALARM:{code}")
        box.setText(detail)
        box.setInformativeText(
            "Motion is locked until the alarm is cleared. Unlock if the position is "
            "still valid, otherwise home the machine."
        )
        unlock = box.addButton("Unlock ($X)", QMessageBox.ButtonRole.ActionRole)
        home = box.addButton("Home ($H)", QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Close)
        box.exec()
        if box.clickedButton() is unlock:
            self.controller.unlock()
        elif box.clickedButton() is home:
            self._home()

    def _on_command_error(self, code: int, detail: str) -> None:
        self.console.append("error", f"error:{code} {detail}")
        self._status_notice.setText(f"error:{code}: {detail}")

    def _on_message(self, text: str) -> None:
        if text:
            self.console.log(text)
            self._status_notice.setText(text)

    def _on_settings(self, entries: list[SettingsEntry]) -> None:
        values = {entry.number: entry for entry in entries}
        limits = []
        for number in (130, 131, 132):
            entry = values.get(number)
            if entry is not None:
                with suppress(ValueError):
                    limits.append(float(entry.value))
        if len(limits) == 3:
            new_limits = (limits[0], limits[1], limits[2])
            streamer = self.controller.streamer
            if new_limits != self._limits:
                self._limits = new_limits
                if self._program and not (streamer and streamer.is_active):
                    self._refresh_program()
        if self._settings_dialog is not None and self._settings_dialog.isVisible():
            self._settings_dialog.set_settings(entries)

    def _show_settings(self) -> None:
        if not self._connected:
            QMessageBox.information(self, "Not connected", "Connect to the machine first.")
            return
        if self._settings_dialog is None:
            self._settings_dialog = SettingsDialog(parent=self)
            self._settings_dialog.refreshRequested.connect(self.controller.request_settings)
            self._settings_dialog.writeRequested.connect(self.controller.set_setting)
        self._settings_dialog.show()
        self._settings_dialog.raise_()
        self.controller.request_settings()

    def _send_command(self, text: str) -> None:
        if not self.controller.send_line(text):
            self.console.log("Command was not sent (not connected or job active).")

    # ------------------------------------------------------------------ #
    # Theme / persistence
    # ------------------------------------------------------------------ #
    def apply_theme(self, dark: bool, persist: bool = True) -> None:
        self._dark = dark
        token = tokens(dark)
        app = QApplication.instance()
        if isinstance(app, QApplication):
            app.setStyleSheet(build_stylesheet(token))
        self.editor.set_token(token)
        self.console.set_token(token)
        self.visualizer.set_token(token)
        self.status_panel.set_token(token)
        if persist:
            self.app_settings.set_dark_theme(dark)

    def _restore_window(self) -> None:
        geometry = self.app_settings.geometry()
        if geometry is not None:
            self.restoreGeometry(geometry)
        state = self.app_settings.window_state()
        if state is not None:
            self.restoreState(state)

    def _keep_awake(self, enabled: bool) -> None:
        if sys.platform != "darwin":
            return
        if enabled and self._caffeinate is None:
            with suppress(OSError):
                self._caffeinate = subprocess.Popen(
                    ["caffeinate", "-i"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
                self._status_notice.setText("Mac kept awake while the job runs")
        elif not enabled and self._caffeinate is not None:
            self._caffeinate.terminate()
            self._caffeinate = None

    def closeEvent(self, event) -> None:  # noqa: N802, ANN001
        if not self._maybe_save():
            event.ignore()
            return
        self.app_settings.save_geometry(self.saveGeometry())
        self.app_settings.save_window_state(self.saveState())
        self.app_settings.sync()
        self._keep_awake(False)
        self.controller.disconnect()
        super().closeEvent(event)

    # ------------------------------------------------------------------ #
    # Enablement
    # ------------------------------------------------------------------ #
    def _update_actions(self) -> None:
        streamer = self.controller.streamer
        active = streamer is not None and streamer.is_active
        family = self._status.family if self._connected else "offline"
        paused = streamer is not None and streamer.state is StreamerState.PAUSED
        error = streamer is not None and streamer.error is not None
        tool_change = streamer is not None and streamer.awaiting_tool_change is not None

        self.action_run.setEnabled(
            self._connected and family == "idle" and not active and bool(self._program)
        )
        self.action_pause.setText("Resume" if paused else "Pause")
        self.action_pause.setEnabled(bool(active and not error and not tool_change))
        self.action_stop.setEnabled(self._connected and (active or family in ("hold", "alarm")))
        self.action_home.setEnabled(self._connected and not active and family in ("idle", "alarm"))
        self.action_unlock.setEnabled(self._connected and family == "alarm")
        self.action_reset.setEnabled(self._connected)
        self.console.set_enabled(self._connected)
        self.status_panel.set_interactive(self._connected, family, bool(active))

    # ------------------------------------------------------------------ #
    # Misc
    # ------------------------------------------------------------------ #
    def _show_manual(self) -> None:
        if self._manual_dialog is None:
            self._manual_dialog = ManualDialog(parent=self)
        self._manual_dialog.show()
        self._manual_dialog.raise_()
        self._manual_dialog.activateWindow()
        self._manual_dialog.browser.setFocus()

    def _show_shortcuts(self) -> None:
        QMessageBox.information(
            self,
            "Keyboard shortcuts",
            "⌘O Open · ⌘S Save · ⌘F Find · ⌘L Go to line\n"
            "⌘R Run · ⌘. Stop · ⌘⇧. Soft reset\n"
            "⌘/ Toggle comment · ⌘K Connect · ⌘0 Fit toolpath\n"
            "Jog panel: arrows X/Y · PgUp/PgDn Z · [ ] step · Space cancel jog",
        )

    def _about(self) -> None:
        QMessageBox.about(
            self,
            f"About {APP_NAME}",
            f"{APP_NAME}\n\nA G-code sender and editor for GRBL 1.1 on "
            "Arduino Uno.\n\nKeep a hand near the power switch and wear eye "
            "protection. Software stop is not an emergency stop.",
        )

    def dragEnterEvent(self, event) -> None:  # noqa: N802, ANN001
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802, ANN001
        urls = event.mimeData().urls()
        if urls and urls[0].isLocalFile() and self._maybe_save():
            self.open_path(urls[0].toLocalFile())
            event.acceptProposedAction()
