"""Jog pad, step chips, zeroing and work-coordinate selection."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..core.grbl_protocol import state_family
from ..core.status import MachineStatus
from .theme import tokens

STEPS = ["0.01", "0.1", "1", "10", "100"]


class JogPanel(QWidget):
    jogRequested = Signal(str, float, float)
    cancelRequested = Signal()
    homeRequested = Signal()
    unlockRequested = Signal()
    zeroRequested = Signal(str)
    gotoZeroRequested = Signal()
    wcsChanged = Signal(int)

    def __init__(self, token: dict[str, str] | None = None, parent=None) -> None:  # noqa: ANN001
        super().__init__(parent)
        self._token = token or tokens()
        self.setObjectName("Panel")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        header = QLabel("JOG")
        header.setObjectName("SectionHeader")

        self._step = QComboBox()
        self._step.addItems(STEPS)
        self._step.setCurrentText("1")
        self._step.setToolTip("Jog step (mm). [ and ] change the step.")
        self._feed = QDoubleSpinBox()
        self._feed.setRange(10, 15000)
        self._feed.setValue(1000)
        self._feed.setDecimals(0)
        self._feed.setSuffix(" mm/min")
        step_row = QHBoxLayout()
        step_row.addWidget(QLabel("Step"))
        step_row.addWidget(self._step, 1)
        step_row.addWidget(self._feed, 1)

        self._pad: dict[str, QPushButton] = {}
        grid = QGridLayout()
        grid.setSpacing(4)
        positions = {
            "Y+": (0, 1),
            "X-": (1, 0),
            "HOME": (1, 1),
            "X+": (1, 2),
            "Y-": (2, 1),
        }
        for name, (row, column) in positions.items():
            button = QPushButton("⌂" if name == "HOME" else name)
            button.setMinimumSize(44, 44)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            if name == "HOME":
                button.setToolTip("Go to work zero (G0 X0 Y0)")
                button.clicked.connect(self.gotoZeroRequested)
            else:
                axis, direction = name[0], 1 if name[1] == "+" else -1
                button.clicked.connect(lambda _=False, a=axis, d=direction: self._jog(a, d))
            grid.addWidget(button, row, column)
            self._pad[name] = button

        z_column = QVBoxLayout()
        self._z_up = QPushButton("Z+")
        self._z_down = QPushButton("Z-")
        for button in (self._z_up, self._z_down):
            button.setMinimumSize(48, 44)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._z_up.clicked.connect(lambda: self._jog("Z", 1))
        self._z_down.clicked.connect(lambda: self._jog("Z", -1))
        z_column.addWidget(self._z_up)
        z_column.addWidget(self._z_down)
        z_column.addStretch(1)

        pad_row = QHBoxLayout()
        pad_row.addLayout(grid, 1)
        pad_row.addLayout(z_column)

        zero_row = QHBoxLayout()
        zero_row.addWidget(QLabel("Zero"))
        self._zero_buttons: list[QPushButton] = []
        for axis in ("X", "Y", "Z"):
            button = QPushButton(axis)
            button.setToolTip(f"Set work zero for {axis} (G10 L20)")
            button.clicked.connect(lambda _=False, a=axis: self.zeroRequested.emit(a))
            zero_row.addWidget(button)
            self._zero_buttons.append(button)
        all_zero = QPushButton("All")
        all_zero.setToolTip("Zero all axes")
        all_zero.clicked.connect(self._zero_all)
        zero_row.addWidget(all_zero)
        self._zero_buttons.append(all_zero)

        self._wcs = QComboBox()
        for index in range(1, 7):
            self._wcs.addItem(f"G5{index + 3}", index)
        self._wcs.currentIndexChanged.connect(
            lambda: self.wcsChanged.emit(int(self._wcs.currentData()))
        )
        machine_row = QHBoxLayout()
        self._home_button = QPushButton("Home")
        self._home_button.clicked.connect(self.homeRequested)
        self._unlock_button = QPushButton("Unlock")
        self._unlock_button.clicked.connect(self.unlockRequested)
        self._cancel_button = QPushButton("Cancel jog")
        self._cancel_button.clicked.connect(self.cancelRequested)
        machine_row.addWidget(self._home_button)
        machine_row.addWidget(self._unlock_button)
        machine_row.addWidget(self._cancel_button)

        wcs_row = QHBoxLayout()
        wcs_row.addWidget(QLabel("WCS"))
        wcs_row.addWidget(self._wcs, 1)

        self._notice = QLabel("")
        self._notice.setObjectName("Muted")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)
        layout.addWidget(header)
        layout.addLayout(step_row)
        layout.addLayout(pad_row)
        layout.addLayout(zero_row)
        layout.addLayout(wcs_row)
        layout.addLayout(machine_row)
        layout.addWidget(self._notice)
        layout.addStretch(1)

        self._connected = False
        self._state = "Unknown"
        self._job_active = False
        self._apply_enabled()

    # ------------------------------------------------------------------ #
    def _jog(self, axis: str, direction: int) -> None:
        step = float(self._step.currentText())
        self.jogRequested.emit(axis, direction * step, self._feed.value())

    def _zero_all(self) -> None:
        for axis in ("X", "Y", "Z"):
            self.zeroRequested.emit(axis)

    def set_machine(self, status: MachineStatus, connected: bool, job_active: bool) -> None:
        self._connected = connected
        self._state = status.state
        self._job_active = job_active
        self._apply_enabled()

    def set_wcs(self, index: int) -> None:
        if 0 <= index < self._wcs.count():
            self._wcs.setCurrentIndex(index)
            self.wcsChanged.emit(int(self._wcs.itemData(index)))

    def _apply_enabled(self) -> None:
        family = state_family(self._state) if self._connected else "offline"
        idle = self._connected and not self._job_active and family == "idle"
        allowed = idle
        for button in self._pad.values():
            button.setEnabled(allowed)
        self._z_up.setEnabled(allowed)
        self._z_down.setEnabled(allowed)
        self._step.setEnabled(allowed)
        self._feed.setEnabled(allowed)
        self._wcs.setEnabled(idle)
        for button in self._zero_buttons:
            button.setEnabled(idle)
        self._home_button.setEnabled(
            self._connected and not self._job_active and family in ("idle", "alarm")
        )
        self._unlock_button.setEnabled(self._connected and family == "alarm")
        self._cancel_button.setEnabled(self._connected and family == "run")
        if self._job_active:
            self._notice.setText("Jog is disabled while a job is running.")
        elif family == "alarm":
            self._notice.setText("Alarm: unlock or home before jogging.")
        elif not self._connected:
            self._notice.setText("Connect a machine to jog.")
        else:
            self._notice.setText("")

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        key = event.key()
        mapping: dict[int, tuple[str, int]] = {
            Qt.Key.Key_Up: ("Y", 1),
            Qt.Key.Key_Down: ("Y", -1),
            Qt.Key.Key_Left: ("X", -1),
            Qt.Key.Key_Right: ("X", 1),
            Qt.Key.Key_PageUp: ("Z", 1),
            Qt.Key.Key_PageDown: ("Z", -1),
        }
        if key in mapping and self._pad["X+"].isEnabled():
            axis, direction = mapping[key]
            self._jog(axis, direction)
            return
        if key == Qt.Key.Key_BracketLeft:
            self._step.setCurrentIndex(max(0, self._step.currentIndex() - 1))
            return
        if key == Qt.Key.Key_BracketRight:
            self._step.setCurrentIndex(min(self._step.count() - 1, self._step.currentIndex() + 1))
            return
        if key == Qt.Key.Key_Space:
            self.cancelRequested.emit()
            return
        super().keyPressEvent(event)
