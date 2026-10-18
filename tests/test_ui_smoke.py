from __future__ import annotations

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent, QTextCursor

from plotdeck.core.status import MachineStatus
from plotdeck.ui.main_window import MainWindow
from plotdeck.ui.manual import ManualDialog, manual_path, manual_text
from plotdeck.utils.settings import AppSettings


@pytest.fixture
def window(qtbot, tmp_path):
    app_settings = AppSettings(str(tmp_path / "settings.ini"))
    window = MainWindow(app_settings=app_settings)
    qtbot.addWidget(window)
    window.show()
    return window


def test_window_builds_offline(window):
    assert window.windowTitle().startswith("PlotDeck")
    assert not window.action_run.isEnabled()
    assert not window.action_pause.isEnabled()
    assert not window.action_stop.isEnabled()
    assert not window.action_home.isEnabled()
    assert window.dock_machine is not None
    assert window.dock_toolpath is not None


def test_loading_a_program_updates_preview(window):
    window.editor.set_source_text("G21\nG0 X0 Y0 Z5\nG1 Z-1 F100\nG1 X10 Y10 F300")
    window.editor.document().setModified(False)
    window._refresh_program()

    assert len(window._program) == 4
    assert window.visualizer.toolpath is not None
    assert len(window.visualizer.toolpath.segments) == 3
    # Offline, so Run stays disabled even though a program is loaded.
    assert not window.action_run.isEnabled()


def test_state_drives_enablement(window):
    program = "\n".join(f"G1 X{index} F100" for index in range(5))
    window.editor.set_source_text(program)
    window._refresh_program()
    window._connected = True

    window._on_status(MachineStatus(state="Idle"))
    assert window.action_run.isEnabled()
    assert not window.action_stop.isEnabled()

    window._on_status(MachineStatus(state="Run"))
    assert not window.action_run.isEnabled()
    assert window.action_home.isEnabled() is False
    assert window.action_reset.isEnabled()

    window._on_status(MachineStatus(state="Alarm"))
    assert window.action_unlock.isEnabled()
    assert window.action_home.isEnabled()
    assert not window.action_run.isEnabled()


def test_editor_actions(window):
    window.editor.set_source_text("G1 X10\nG1 Y10\n")
    cursor = window.editor.textCursor()
    cursor.select(QTextCursor.SelectionType.Document)
    window.editor.setTextCursor(cursor)
    window.editor.toggle_comment()
    assert window.editor.toPlainText().startswith("; G1 X10")
    window.editor.toggle_comment()
    assert window.editor.toPlainText().startswith("G1 X10")

    window.editor.transform(dx=5)
    assert "X15" in window.editor.toPlainText()


def test_large_editor_file_loads(window):
    # v1.0 success criterion: a 50k-line file opens without loading delays.
    text = "\n".join("G1 X1 Y1 F100" for _ in range(50_000))
    window.editor.set_source_text(text)
    assert window.editor.blockCount() == 50_000
    assert window.editor.document().characterCount() > 500_000


def test_toolpath_zoom_controls(window):
    window.editor.set_source_text("G21\nG0 X0 Y0\nG1 X50 Y30 F100")
    window._refresh_program()
    view = window.visualizer._plot.getViewBox()
    before = view.viewRange()
    before_width = before[0][1] - before[0][0]

    window.visualizer._zoom_in_button.click()
    zoomed = view.viewRange()
    zoomed_width = zoomed[0][1] - zoomed[0][0]
    assert zoomed_width < before_width

    window.visualizer._zoom_out_button.click()
    restored = view.viewRange()
    restored_width = restored[0][1] - restored[0][0]
    assert restored_width > zoomed_width


def test_toolpath_zoom_in_3d_adjusts_camera_distance(window):
    class FakeGl:
        def __init__(self):
            self.opts = {"distance": 100.0}

        def setCameraPosition(self, **kwargs):
            self.opts.update(kwargs)

        def update(self):
            pass

    window.editor.set_source_text("G21\nG0 X0 Y0\nG1 X10 Y10 F100")
    window._refresh_program()
    fake = FakeGl()
    window.visualizer._gl = fake
    window.visualizer._stack.setCurrentIndex(1)

    window.visualizer.zoom_in()
    assert fake.opts["distance"] == pytest.approx(80.0)
    window.visualizer.zoom_out()
    assert fake.opts["distance"] == pytest.approx(100.0)


def test_user_manual_is_available_and_renders(window, qtbot):
    assert manual_path() is not None
    assert "PlotDeck User Manual" in manual_text()

    assert window.action_manual.shortcut().toString() == "F1"
    window.action_manual.trigger()
    dialog = window._manual_dialog
    assert isinstance(dialog, ManualDialog)
    qtbot.addWidget(dialog)
    assert dialog.isVisible()
    rendered = dialog.browser.toPlainText()
    assert "Safety first" in rendered
    assert "Troubleshooting" in rendered
    dialog.close()


def test_theme_switch(window):
    window.apply_theme(False)
    assert window._dark is False
    window.apply_theme(True)
    assert window._dark is True


def test_demo_connection_and_job(window, qtbot):
    window._connect("DEMO", 115200, True)
    qtbot.waitUntil(lambda: window._connected, timeout=5000)
    qtbot.waitUntil(lambda: window._status.state == "Idle", timeout=5000)

    window.editor.set_source_text("G21\nG0 X0 Y0 Z5\nG1 Z-1 F100\nG1 X10 Y10 F300")
    window._refresh_program()
    qtbot.waitUntil(lambda: window.action_run.isEnabled(), timeout=3000)

    window.job_panel.begin(len(window._program))
    assert window.controller.run_program(window._program)
    qtbot.waitUntil(
        lambda: window.controller.streamer is not None
        and window.controller.streamer.state.name == "COMPLETED",
        timeout=5000,
    )
    qtbot.waitUntil(lambda: window.job_panel._progress.value() == 1000, timeout=3000)
    assert window.status_panel.rows["X"]._value.text() != "---"
    window.controller.disconnect()


def test_jog_panel_keyboard_guard(window):
    # Jogging must be disabled while offline even if keys are pressed.
    window.jog_panel.setFocus(Qt.FocusReason.OtherFocusReason)
    assert not window.jog_panel._pad["X+"].isEnabled()
    event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Right, Qt.KeyboardModifier.NoModifier)
    window.jog_panel.keyPressEvent(event)
    assert not event.isAccepted()
