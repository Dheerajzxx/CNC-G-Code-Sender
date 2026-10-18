"""Modal dialogs: pre-flight summary, tool change, Z probe and settings."""

from __future__ import annotations

import re

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core.controller import SettingsEntry
from ..core.gcode_parser import Toolpath
from .job_panel import format_duration


class PreflightDialog(QDialog):
    def __init__(
        self,
        file_name: str,
        line_count: int,
        toolpath: Toolpath | None,
        warnings: list[str],
        parent=None,  # noqa: ANN001
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Pre-flight check")
        self.setMinimumWidth(480)
        self.choice = "cancel"

        title = QLabel(file_name or "Untitled")
        font = title.font()
        font.setPointSize(15)
        font.setBold(True)
        title.setFont(font)

        grid = QGridLayout()
        grid.setColumnStretch(1, 1)

        rows = [("Lines", f"{line_count:,}")]
        if toolpath is not None:
            rows.append(("Estimated time", format_duration(toolpath.estimated_seconds)))
            rows.append(("Moves", f"{len(toolpath.segments):,}"))
            if toolpath.bounds:
                low, high = toolpath.bounds
                rows.append(
                    (
                        "Bounding box",
                        f"{high[0] - low[0]:.2f} × {high[1] - low[1]:.2f} × "
                        f"{high[2] - low[2]:.2f} mm",
                    )
                )
            rows.append(
                (
                    "Max cut depth",
                    f"{toolpath.min_z:.2f} mm" if toolpath.min_z is not None else "--",
                )
            )
            rows.append(
                (
                    "Tools",
                    ", ".join(f"T{tool}" for tool in toolpath.tools) if toolpath.tools else "none",
                )
            )
        for row, (label, value) in enumerate(rows):
            key = QLabel(label)
            key.setObjectName("Muted")
            grid.addWidget(key, row, 0)
            grid.addWidget(QLabel(value), row, 1)

        warning_box = QWidget()
        warning_layout = QVBoxLayout(warning_box)
        warning_layout.setContentsMargins(0, 6, 0, 0)
        if warnings:
            heading = QLabel("Warnings")
            heading.setObjectName("SectionHeader")
            warning_layout.addWidget(heading)
            for warning in warnings:
                warning_label = QLabel(f"• {warning}")
                warning_label.setWordWrap(True)
                warning_label.setStyleSheet("color: #E0A030;")
                warning_layout.addWidget(warning_label)
        else:
            ready = QLabel("No problems detected.")
            ready.setObjectName("Muted")
            warning_layout.addWidget(ready)

        self._dry_run = QCheckBox("Dry run (GRBL check mode, no motion)")
        self._dry_run.setToolTip("Runs the job with GRBL check mode enabled ($C).")

        start = QPushButton("Start")
        start.setObjectName("Primary")
        cancel = QPushButton("Cancel")
        start.setDefault(True)
        start.clicked.connect(self._start)
        cancel.clicked.connect(self.reject)

        buttons = QHBoxLayout()
        buttons.addWidget(self._dry_run)
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        buttons.addWidget(start)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(10)
        layout.addWidget(title)
        layout.addLayout(grid)
        layout.addWidget(warning_box)
        layout.addStretch(1)
        layout.addLayout(buttons)

    def _start(self) -> None:
        self.choice = "dry_run" if self._dry_run.isChecked() else "start"
        self.accept()


class ToolChangeDialog(QDialog):
    def __init__(self, tool_number: int | None, parent=None) -> None:  # noqa: ANN001
        super().__init__(parent)
        self.setWindowTitle("Tool change")
        self.setMinimumWidth(420)

        title = QLabel(
            f"Insert tool {tool_number}" if tool_number is not None else "Insert the next tool"
        )
        font = title.font()
        font.setPointSize(14)
        font.setBold(True)
        title.setFont(font)

        body = QLabel(
            "The job has stopped and the machine is on hold. Change the tool, "
            "re-probe Z if needed, then resume.\n\n"
            "M6 is handled by PlotDeck and is never sent to GRBL."
        )
        body.setWordWrap(True)
        note = QLabel(
            "Make sure the spindle is off and the machine has stopped before reaching in."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #E0A030;")

        buttons = QDialogButtonBox()
        resume = buttons.addButton("Resume job", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton("Abort job", QDialogButtonBox.ButtonRole.RejectRole)
        resume.setObjectName("Primary")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(10)
        layout.addWidget(title)
        layout.addWidget(body)
        layout.addWidget(note)
        layout.addWidget(buttons)


class ProbeDialog(QDialog):
    def __init__(self, parent=None) -> None:  # noqa: ANN001
        super().__init__(parent)
        self.setWindowTitle("Probe Z")
        self.setMinimumWidth(360)

        intro = QLabel(
            "Attach the touch-plate clip, place the plate under the bit and press Probe. "
            "PlotDeck probes down slowly, sets work zero to the plate thickness, "
            "then retracts."
        )
        intro.setWordWrap(True)

        self.thickness = QDoubleSpinBox()
        self.thickness.setRange(0.0, 50.0)
        self.thickness.setDecimals(2)
        self.thickness.setValue(10.0)
        self.thickness.setSuffix(" mm")
        self.feed = QDoubleSpinBox()
        self.feed.setRange(1, 500)
        self.feed.setValue(50)
        self.feed.setSuffix(" mm/min")
        self.travel = QDoubleSpinBox()
        self.travel.setRange(1, 200)
        self.travel.setValue(30)
        self.travel.setSuffix(" mm")
        self.retract = QDoubleSpinBox()
        self.retract.setRange(0, 50)
        self.retract.setValue(5)
        self.retract.setSuffix(" mm")

        form = QFormLayout()
        form.addRow("Plate thickness", self.thickness)
        form.addRow("Probe feed", self.feed)
        form.addRow("Max travel", self.travel)
        form.addRow("Retract height", self.retract)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Probe")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(10)
        layout.addWidget(intro)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def values(self) -> tuple[float, float, float, float]:
        return (
            self.thickness.value(),
            self.feed.value(),
            self.travel.value(),
            self.retract.value(),
        )


class SettingsDialog(QDialog):
    """Editable ``$$`` settings table."""

    refreshRequested = Signal()
    writeRequested = Signal(int, str)

    def __init__(self, token: dict[str, str] | None = None, parent=None) -> None:  # noqa: ANN001
        super().__init__(parent)
        self._token = token or {}
        self.setWindowTitle("GRBL settings")
        self.setMinimumSize(640, 520)

        intro = QLabel(
            "Values are read from the controller with $$. Select a row, edit the value "
            "and press Write. Changes take effect immediately."
        )
        intro.setWordWrap(True)
        intro.setObjectName("Muted")

        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels(["#", "Value", "Description"])
        self._table.verticalHeader().setVisible(False)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(
            QTableWidget.EditTrigger.DoubleClicked | QTableWidget.EditTrigger.EditKeyPressed
        )

        self._status = QLabel("Press Refresh to read settings from the machine.")
        self._status.setObjectName("Muted")

        refresh = QPushButton("Refresh")
        write = QPushButton("Write selected")
        close = QPushButton("Close")
        refresh.clicked.connect(self.refreshRequested)
        write.clicked.connect(self._write)
        close.clicked.connect(self.accept)

        buttons = QHBoxLayout()
        buttons.addWidget(self._status, 1)
        buttons.addWidget(refresh)
        buttons.addWidget(write)
        buttons.addWidget(close)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 12)
        layout.setSpacing(8)
        layout.addWidget(intro)
        layout.addWidget(self._table, 1)
        layout.addLayout(buttons)

    def set_settings(self, entries: list[SettingsEntry]) -> None:
        self._table.setRowCount(0)
        for entry in entries:
            row = self._table.rowCount()
            self._table.insertRow(row)
            number = QTableWidgetItem(f"${entry.number}")
            number.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            value = QTableWidgetItem(entry.value)
            number.setData(Qt.ItemDataRole.UserRole, entry.number)
            self._table.setItem(row, 0, number)
            self._table.setItem(row, 1, value)
            description = QTableWidgetItem(entry.description)
            description.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self._table.setItem(row, 2, description)
        self._status.setText(f"{len(entries)} settings loaded.")

    def _write(self) -> None:
        row = self._table.currentRow()
        if row < 0:
            self._status.setText("Select a setting first.")
            return
        number_item = self._table.item(row, 0)
        value_item = self._table.item(row, 1)
        if number_item is None or value_item is None:
            return
        value = value_item.text().strip()
        if not re.fullmatch(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)", value):
            self._status.setText("Enter a numeric value.")
            return
        self.writeRequested.emit(int(number_item.data(Qt.ItemDataRole.UserRole)), value)
        self._status.setText(f"Wrote ${number_item.data(Qt.ItemDataRole.UserRole)}={value}")
