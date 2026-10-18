"""Serial console with colour-coded traffic and command history."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QKeyEvent, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..core.grbl_protocol import ResponseKind
from .theme import MONO_FONT, tokens


class ConsoleInput(QLineEdit):
    submitted = Signal(str)

    def __init__(self, parent=None) -> None:  # noqa: ANN001
        super().__init__(parent)
        self._history: list[str] = []
        self._index = 0
        self.setPlaceholderText("Send a command (↑/↓ for history)")
        self.setClearButtonEnabled(True)
        self.returnPressed.connect(self._submit)

    def _submit(self) -> None:
        text = self.text().strip()
        if not text:
            return
        self._history.append(text)
        self._history = self._history[-200:]
        self._index = len(self._history)
        self.submitted.emit(text)
        self.clear()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Up and self._history:
            self._index = max(0, self._index - 1)
            self.setText(self._history[self._index])
            return
        if event.key() == Qt.Key.Key_Down and self._history:
            self._index = min(len(self._history), self._index + 1)
            self.setText("" if self._index == len(self._history) else self._history[self._index])
            return
        super().keyPressEvent(event)


class Console(QWidget):
    commandSubmitted = Signal(str)

    def __init__(self, token: dict[str, str] | None = None, parent=None) -> None:  # noqa: ANN001
        super().__init__(parent)
        self._token = token or tokens()
        self._hide_status = True
        self.setObjectName("Panel")

        self._view = QPlainTextEdit()
        self._view.setReadOnly(True)
        self._view.setMaximumBlockCount(5000)
        self._view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        font = self._view.font()
        font.setFamily(MONO_FONT.split(",")[0].replace('"', "").strip())
        font.setPointSize(12)
        self._view.setFont(font)

        self._input = ConsoleInput()
        self._input.submitted.connect(self._on_submit)
        self._autoscroll = QCheckBox("Autoscroll")
        self._autoscroll.setChecked(True)
        self._hide_polls = QCheckBox("Hide status polls")
        self._hide_polls.setChecked(True)
        self._hide_polls.toggled.connect(self._set_hide_status)
        clear = QPushButton("Clear")
        clear.clicked.connect(self._view.clear)
        self._count_label = QLabel("")
        self._count_label.setObjectName("Muted")

        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.addWidget(self._autoscroll)
        controls.addWidget(self._hide_polls)
        controls.addWidget(self._count_label, 1)
        controls.addWidget(clear)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addLayout(controls)
        layout.addWidget(self._view, 1)
        layout.addWidget(self._input)

        self._formats = {
            "sent": self._format(self._token["accent"]),
            "ok": self._format(self._token["idle"]),
            "error": self._format(self._token["alarm"], bold=True),
            "alarm": self._format(self._token["alarm"], bold=True),
            "message": self._format(self._token["muted"]),
            "status": self._format(self._token["muted"]),
            "other": self._format(self._token["text"]),
            "banner": self._format(self._token["hold"], bold=True),
        }
        self._line_count = 0

    @staticmethod
    def _format(color: str, bold: bool = False) -> QTextCharFormat:
        style = QTextCharFormat()
        style.setForeground(QColor(color))
        if bold:
            style.setFontWeight(700)
        return style

    def set_token(self, token: dict[str, str]) -> None:
        self._token = token
        self._formats.update(
            {
                "sent": self._format(token["accent"]),
                "ok": self._format(token["idle"]),
                "error": self._format(token["alarm"], bold=True),
                "alarm": self._format(token["alarm"], bold=True),
                "message": self._format(token["muted"]),
                "status": self._format(token["muted"]),
                "other": self._format(token["text"]),
                "banner": self._format(token["hold"], bold=True),
            }
        )

    def _set_hide_status(self, value: bool) -> None:
        self._hide_status = value

    def append(self, kind: ResponseKind | str, text: str) -> None:
        key = kind.value if isinstance(kind, ResponseKind) else kind
        if key == "status" and self._hide_status:
            return
        if key == "other" and not text.strip():
            return
        if key == "banner":
            text = text or "(reset)"
        prefix = ">" if key == "sent" else "<"
        self._insert(f"{prefix} {text}", key)
        self._line_count += 1
        if self._line_count % 5 == 0:
            self._count_label.setText(f"{self._line_count} lines")

    def _insert(self, text: str, key: str) -> None:
        bar = self._view.verticalScrollBar()
        at_bottom = bar.value() >= bar.maximum() - 4
        cursor = self._view.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(text + "\n", self._formats.get(key, self._formats["other"]))
        if self._autoscroll.isChecked() or at_bottom:
            bar.setValue(bar.maximum())

    def _on_submit(self, text: str) -> None:
        self.append("sent", text)
        self.commandSubmitted.emit(text)

    def set_enabled(self, enabled: bool) -> None:
        self._input.setEnabled(enabled)

    def focus_input(self) -> None:
        self._input.setFocus()

    def log(self, text: str) -> None:
        self.append("message", text)
