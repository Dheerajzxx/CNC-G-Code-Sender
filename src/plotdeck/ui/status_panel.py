"""Position readout, state badge and override controls."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from ..core.grbl_protocol import state_family
from ..core.status import MachineStatus
from .theme import state_color, tokens


class StateBadge(QLabel):
    def __init__(self, token: dict[str, str]) -> None:
        super().__init__("OFFLINE")
        self._token = token
        self._state = "Unknown"
        self._connected = False
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumWidth(86)
        self.set_state("Unknown", False)

    def refresh(self) -> None:
        self.set_state(self._state, self._connected)

    def set_state(self, state: str, connected: bool = True) -> None:
        self._state = state
        self._connected = connected
        family = state_family(state) if connected else "offline"
        color = state_color(self._token, family)
        label = state.split(":")[0].upper() if connected else "OFFLINE"
        if label == "RUN":
            label = "RUN"
        self.setText(label)
        self.setStyleSheet(
            f"background: {color}; color: white; border-radius: 6px;"
            "padding: 4px 10px; font-weight: 700; font-size: 11px;"
        )
        self.setToolTip(state if connected else "Not connected")


class DroRow(QWidget):
    zeroRequested = Signal(str)

    def __init__(self, axis: str, token: dict[str, str], parent=None) -> None:  # noqa: ANN001
        super().__init__(parent)
        self._axis = axis
        self._token = token
        axis_label = QLabel(axis)
        axis_label.setObjectName("DroAxis")
        axis_label.setFixedWidth(18)
        self._value = QLabel("0.000")
        self._value.setObjectName("DroValue")
        self._secondary = QLabel("MPos 0.000")
        self._secondary.setObjectName("DroSecondary")
        zero = QPushButton("0")
        self._zero = zero
        zero.setFixedSize(24, 24)
        zero.setToolTip(f"Zero {axis}")
        zero.clicked.connect(lambda: self.zeroRequested.emit(self._axis))

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(6)
        layout.addWidget(axis_label)
        layout.addWidget(self._value, 1)
        text_column = QVBoxLayout()
        text_column.setSpacing(0)
        text_column.addWidget(self._secondary)
        layout.addLayout(text_column)
        layout.addWidget(zero)

    def set_zero_enabled(self, enabled: bool) -> bool:
        self._zero.setEnabled(enabled)
        return enabled

    def set_values(self, work: float | None, machine: float | None, units: str = "mm") -> None:
        work_text = "---" if work is None else f"{work:.3f}"
        machine_text = "---" if machine is None else f"{machine:.3f}"
        self._value.setText(work_text)
        self._secondary.setText(f"MPos {machine_text} {units}")


class OverrideSlider(QWidget):
    valueChanged = Signal(int)

    def __init__(self, label: str, minimum: int, maximum: int, token: dict[str, str]) -> None:
        super().__init__()
        self._label = QLabel(label)
        self._label.setObjectName("Muted")
        self._label.setFixedWidth(56)
        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setRange(minimum, maximum)
        self._slider.setValue(100)
        self._value = QLabel("100%")
        self._value.setFixedWidth(42)
        self._value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._token = token
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 1, 0, 1)
        layout.setSpacing(6)
        layout.addWidget(self._label)
        layout.addWidget(self._slider, 1)
        layout.addWidget(self._value)
        self._slider.valueChanged.connect(self._on_change)
        self._slider.sliderReleased.connect(self._emit_value)

    def _on_change(self, value: int) -> None:
        self._value.setText(f"{value}%")

    def _emit_value(self) -> None:
        self.valueChanged.emit(self._slider.value())

    def reset(self) -> None:
        self._slider.setValue(100)

    def value(self) -> int:
        return self._slider.value()


class StatusPanel(QWidget):
    zeroRequested = Signal(str)
    feedOverrideChanged = Signal(int)
    spindleOverrideChanged = Signal(int)
    rapidOverrideChanged = Signal(int)

    def __init__(self, token: dict[str, str] | None = None, parent=None) -> None:  # noqa: ANN001
        super().__init__(parent)
        self._token = token or tokens()
        self.setObjectName("Panel")

        self.badge = StateBadge(self._token)
        header = QHBoxLayout()
        header.addWidget(self.badge)
        self._firmware = QLabel("not connected")
        self._firmware.setObjectName("Muted")
        header.addWidget(self._firmware, 1, Qt.AlignmentFlag.AlignRight)

        self.rows = {axis: DroRow(axis, self._token) for axis in ("X", "Y", "Z")}
        for row in self.rows.values():
            row.zeroRequested.connect(self.zeroRequested)

        self._feed = QLabel("F 0")
        self._feed.setObjectName("Muted")
        self._spindle = QLabel("S 0")
        self._spindle.setObjectName("Muted")
        self._buffer = QLabel("Bf 0/127")
        self._buffer.setObjectName("Muted")
        footer = QHBoxLayout()
        footer.addWidget(self._feed)
        footer.addWidget(self._spindle)
        footer.addStretch(1)
        footer.addWidget(self._buffer)

        self.feed_override = OverrideSlider("Feed", 10, 200, self._token)
        self.spindle_override = OverrideSlider("Spindle", 10, 200, self._token)
        self._rapid = QComboBox()
        self._rapid.addItems(["100%", "50%", "25%"])
        rapid_row = QHBoxLayout()
        rapid_label = QLabel("Rapid")
        rapid_label.setObjectName("Muted")
        rapid_label.setFixedWidth(56)
        rapid_row.addWidget(rapid_label)
        rapid_row.addWidget(self._rapid, 1)

        overrides_header = QLabel("OVERRIDES")
        overrides_header.setObjectName("SectionHeader")

        self.feed_override.valueChanged.connect(self.feedOverrideChanged)
        self.spindle_override.valueChanged.connect(self.spindleOverrideChanged)
        self._rapid.currentIndexChanged.connect(self._rapid_changed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)
        layout.addLayout(header)
        position_header = QLabel("POSITION")
        position_header.setObjectName("SectionHeader")
        layout.addSpacing(4)
        layout.addWidget(position_header)
        for row in self.rows.values():
            layout.addWidget(row)
        layout.addLayout(footer)
        layout.addSpacing(8)
        layout.addWidget(overrides_header)
        layout.addWidget(self.feed_override)
        layout.addWidget(self.spindle_override)
        layout.addLayout(rapid_row)
        layout.addStretch(1)

    def set_token(self, token: dict[str, str]) -> None:
        self._token = token
        self.badge._token = token
        self.badge.refresh()

    def set_interactive(self, connected: bool, family: str, job_active: bool) -> None:
        overrides = connected and family in ("idle", "run", "hold")
        self.feed_override.setEnabled(overrides)
        self.spindle_override.setEnabled(overrides)
        self._rapid.setEnabled(overrides)
        zero = connected and family == "idle" and not job_active
        for row in self.rows.values():
            row.set_zero_enabled(zero)

    def _rapid_changed(self, index: int) -> None:
        self.rapidOverrideChanged.emit((100, 50, 25)[index])

    def update_status(self, status: MachineStatus, units: str = "mm") -> None:
        self.badge.set_state(status.state, True)
        for index, axis in enumerate(("X", "Y", "Z")):
            work = status.wpos[index] if status.wpos else None
            machine = status.mpos[index] if status.mpos else None
            self.rows[axis].set_values(work, machine, units)
        self._feed.setText(f"F {status.feed:.0f}" if status.feed is not None else "F --")
        self._spindle.setText(f"S {status.spindle:.0f}" if status.spindle is not None else "S --")
        if status.buffer:
            self._buffer.setText(f"Bf {status.buffer[0]}/{status.buffer[1]}")
            self._buffer.setToolTip(
                f"RX buffer {status.buffer[0]} of {status.buffer[1]} bytes used"
            )
        else:
            self._buffer.setText("Bf --")
        if status.pins:
            self._buffer.setToolTip(f"RX buffer | triggered pins: {status.pins}")

    def set_connected(self, connected: bool, firmware: str = "") -> None:
        if not connected:
            self.badge.set_state("Unknown", False)
            self._firmware.setText("not connected")
            for row in self.rows.values():
                row.set_values(None, None)
            self._feed.setText("F --")
            self._spindle.setText("S --")
            self._buffer.setText("Bf --")
        else:
            self._firmware.setText(f"GRBL {firmware}" if firmware else "GRBL")
