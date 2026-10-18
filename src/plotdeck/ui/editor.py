"""G-code editor: line-number gutter, syntax highlighting and job markers."""

from __future__ import annotations

import re

from PySide6.QtCore import QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QKeyEvent,
    QPainter,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextFormat,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..core.gcode_parser import (
    ProgramLine,
    clean_line,
    parse_program,
    strip_comments,
    tokenize,
    transform_lines,
)
from ..core.grbl_protocol import MAX_LINE_LENGTH
from .theme import tokens


class GcodeHighlighter(QSyntaxHighlighter):
    def __init__(self, document: QTextDocument, token: dict[str, str]) -> None:
        super().__init__(document)
        self._token = token
        self._comment = QTextCharFormat()
        self._comment.setForeground(QColor(token["comment"]))
        self._comment.setFontItalic(True)

        def fmt(color: str, bold: bool = False) -> QTextCharFormat:
            style = QTextCharFormat()
            style.setForeground(QColor(color))
            if bold:
                style.setFontWeight(QFont.Weight.DemiBold)
            return style

        self._keyword_formats: list[tuple[re.Pattern[str], QTextCharFormat]] = [
            (re.compile(r"\bN\d+\b"), fmt(token["muted"])),
            (re.compile(r"\bG\d+(?:\.\d+)?\b"), fmt(token["g_word"], True)),
            (re.compile(r"\bM\d+(?:\.\d+)?\b"), fmt(token["m_word"], True)),
            (re.compile(r"\b[XYZIJKR][-+]?(?:\d+(?:\.\d*)?|\.\d+)"), fmt(token["axis_word"])),
            (re.compile(r"\b[FST][-+]?(?:\d+(?:\.\d*)?|\.\d+)"), fmt(token["feed_word"])),
            (re.compile(r"\$[A-Z#]+\d*"), fmt(token["accent"], True)),
            (re.compile(r"\[[^\]]*\]"), fmt(token["comment"])),
        ]

    def highlightBlock(self, text: str) -> None:  # noqa: N802 - Qt override
        for pattern, style in self._keyword_formats:
            for match in pattern.finditer(text):
                self.setFormat(match.start(), match.end() - match.start(), style)
        # Comments win over everything else.
        for match in re.finditer(r";.*$", text):
            self.setFormat(match.start(), len(text) - match.start(), self._comment)
        for match in re.finditer(r"\([^)]*\)", text):
            self.setFormat(match.start(), match.end() - match.start(), self._comment)


class LineNumberArea(QWidget):
    def __init__(self, editor: GcodeEditor) -> None:
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(self._editor.line_number_width(), 0)

    def paintEvent(self, event) -> None:  # noqa: N802, ANN001
        self._editor.paint_gutter(event)


class GcodeEditor(QPlainTextEdit):
    cursorLineChanged = Signal(int)

    def __init__(self, token: dict[str, str] | None = None, parent=None) -> None:  # noqa: ANN001
        super().__init__(parent)
        self._token = token or tokens()
        self._gutter = LineNumberArea(self)
        self._highlighter = GcodeHighlighter(self.document(), self._token)
        self._current_line = 0
        self._markers: dict[int, str] = {}
        self._validation_lines: set[int] = set()
        self._gutter_font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        self._gutter_font.setPointSize(11)

        font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        font.setPointSize(12)
        font.setFamily("Menlo")
        self.setFont(font)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(" ") * 4)
        self.setCursorWidth(2)

        self.blockCountChanged.connect(self._update_gutter_width)
        self.updateRequest.connect(self._update_gutter)
        self.cursorPositionChanged.connect(self._on_cursor_moved)
        self.textChanged.connect(self._queue_validation)
        self._validate_timer = QTimer(self)
        self._validate_timer.setSingleShot(True)
        self._validate_timer.setInterval(450)
        self._validate_timer.timeout.connect(self._validate)

        self._update_gutter_width()
        self._refresh_extra_selections()

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def set_token(self, token: dict[str, str]) -> None:
        self._token = token
        self._highlighter.setDocument(None)
        self._highlighter = GcodeHighlighter(self.document(), token)
        self._refresh_extra_selections()
        self._gutter.update()

    def source_text(self) -> str:
        return self.toPlainText()

    def set_source_text(self, text: str) -> None:
        lines = text.count("\n") + 1
        self.setUndoRedoEnabled(not (lines > 50_000))
        self.setPlainText(text)
        self.setUndoRedoEnabled(True)
        self.clear_markers()
        self._current_line = 0
        self.moveCursor(QTextCursor.MoveOperation.Start)
        self._update_gutter_width()
        self._refresh_extra_selections()

    def program(self) -> list[ProgramLine]:
        return parse_program(self.toPlainText())

    def go_to_line(self, line: int, focus: bool = True) -> None:
        block = self.document().findBlockByLineNumber(max(0, line - 1))
        if not block.isValid():
            return
        cursor = QTextCursor(block)
        self.setTextCursor(cursor)
        self.centerCursor()
        if focus:
            self.setFocus()

    def current_line(self) -> int:
        return self.textCursor().blockNumber() + 1

    def selected_or_current_line(self) -> int:
        return self.current_line()

    def set_execution_line(self, line: int) -> None:
        if line <= 0:
            return
        if self._current_line and self._current_line != line:
            self._markers[self._current_line] = "done"
        self._current_line = line
        self._markers[line] = "current"
        self._refresh_extra_selections()
        # Never yank the insertion point away from someone typing while a job
        # runs; only auto-scroll when the editor is not focused.
        if not self.hasFocus():
            self.go_to_line(line, focus=False)

    def mark_error(self, line: int) -> None:
        self._markers[line] = "error"
        self._refresh_extra_selections()

    def clear_markers(self) -> None:
        self._markers.clear()
        self._current_line = 0
        self._refresh_extra_selections()

    def mark_all_done(self) -> None:
        for line in list(self._markers):
            if self._markers[line] == "current":
                self._markers[line] = "done"
        self._current_line = 0
        self._refresh_extra_selections()

    # ------------------------------------------------------------------ #
    # Editing actions
    # ------------------------------------------------------------------ #
    def toggle_comment(self) -> None:
        cursor = self.textCursor()
        start = cursor.selectionStart()
        end = cursor.selectionEnd()
        cursor.setPosition(start)
        first = cursor.blockNumber()
        cursor.setPosition(end)
        last = cursor.blockNumber()
        blocks = [self.document().findBlockByNumber(index) for index in range(first, last + 1)]
        commented = all(
            block.text().lstrip().startswith(";") for block in blocks if block.text().strip()
        )
        cursor.beginEditBlock()
        for block in blocks:
            if not block.text().strip():
                continue
            edit = QTextCursor(block)
            text = block.text()
            if commented:
                stripped = text.lstrip()
                offset = len(text) - len(stripped)
                edit.setPosition(block.position() + offset)
                edit.movePosition(
                    QTextCursor.MoveOperation.Right,
                    QTextCursor.MoveMode.KeepAnchor,
                    2 if stripped.startswith("; ") else 1,
                )
                edit.removeSelectedText()
            else:
                edit.movePosition(QTextCursor.MoveOperation.StartOfBlock)
                edit.insertText("; ")
        cursor.endEditBlock()

    def strip_comments(self) -> None:
        cursor = self.textCursor()
        start_block = self.document().findBlock(cursor.selectionStart()).blockNumber()
        end_block = self.document().findBlock(cursor.selectionEnd()).blockNumber()
        cursor.beginEditBlock()
        for index in range(start_block, end_block + 1):
            block = self.document().findBlockByNumber(index)
            cleaned = strip_comments(block.text()).strip()
            edit = QTextCursor(block)
            edit.select(QTextCursor.SelectionType.BlockUnderCursor)
            edit.insertText(cleaned)
        cursor.endEditBlock()

    def uppercase_selection(self) -> None:
        cursor = self.textCursor()
        text = cursor.selectedText()
        if text:
            cursor.insertText(text.upper())

    def renumber(self) -> None:
        program = parse_program(self.toPlainText())
        cursor = QTextCursor(self.document())
        cursor.beginEditBlock()
        for line in program:
            block = self.document().findBlockByNumber(line.source_line - 1)
            if not block.isValid():
                continue
            raw = block.text().lstrip()
            if raw.upper().startswith("N"):
                continue
            edit = QTextCursor(block)
            edit.select(QTextCursor.SelectionType.BlockUnderCursor)
            edit.insertText(f"N{line.source_line * 10} {raw}")
        cursor.endEditBlock()

    def transform(
        self,
        dx: float = 0.0,
        dy: float = 0.0,
        dz: float = 0.0,
        scale: float = 1.0,
        rotate: float = 0.0,
    ) -> None:
        source = self.toPlainText()
        output: list[str] = []
        for number, raw in enumerate(source.splitlines(), start=1):
            clean = clean_line(raw)
            if not clean:
                output.append(raw)
                continue
            words = tokenize(clean)
            if not any(letter in "XYZ" for letter, _ in words):
                output.append(raw)
                continue
            transformed = transform_lines(
                [ProgramLine(clean, number)], dx=dx, dy=dy, dz=dz, scale=scale, rotate=rotate
            )[0]
            comment = ""
            if ";" in raw:
                comment = " ;" + raw.split(";", 1)[1]
            output.append(transformed + comment)
        self.set_source_text("\n".join(output))

    # ------------------------------------------------------------------ #
    # Gutter
    # ------------------------------------------------------------------ #
    def line_number_width(self) -> int:
        digits = max(2, len(str(max(1, self.blockCount()))))
        return 14 + digits * 8

    def _update_gutter_width(self) -> None:
        self.setViewportMargins(self.line_number_width(), 0, 0, 0)

    def _update_gutter(self, rect: QRect, dy: int) -> None:
        if dy:
            self._gutter.scroll(0, dy)
        else:
            self._gutter.update(0, rect.y(), self._gutter.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_gutter_width()

    def resizeEvent(self, event) -> None:  # noqa: N802, ANN001
        super().resizeEvent(event)
        area = self.contentsRect()
        self._gutter.setGeometry(
            QRect(area.left(), area.top(), self.line_number_width(), area.height())
        )

    def paint_gutter(self, event) -> None:  # noqa: ANN001
        painter = QPainter(self._gutter)
        painter.fillRect(event.rect(), QColor(self._token["gutter"]))
        painter.setFont(self._gutter_font)
        block = self.firstVisibleBlock()
        number = block.blockNumber() + 1
        top = self.blockBoundingGeometry(block).translated(self.contentOffset()).top()
        bottom = top + self.blockBoundingRect(block).height()
        current = self.current_line()

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                height = int(self.blockBoundingRect(block).height())
                if number == current:
                    painter.setPen(QColor(self._token["accent"]))
                else:
                    painter.setPen(QColor(self._token["muted"]))
                painter.drawText(
                    0,
                    int(top),
                    self.line_number_width() - 10,
                    height,
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                    str(number),
                )
                marker = self._markers.get(number)
                if marker == "current":
                    color = self._token["run"]
                elif marker == "done":
                    color = self._token["idle"]
                elif marker == "error":
                    color = self._token["alarm"]
                else:
                    color = ""
                if color:
                    painter.fillRect(
                        self.line_number_width() - 5, int(top), 3, height, QColor(color)
                    )
                elif number in self._validation_lines:
                    painter.fillRect(
                        self.line_number_width() - 5,
                        int(top),
                        3,
                        height,
                        QColor(self._token["hold"]),
                    )
            block = block.next()
            top = bottom
            bottom = top + self.blockBoundingRect(block).height()
            number += 1

    # ------------------------------------------------------------------ #
    # Selections / validation
    # ------------------------------------------------------------------ #
    def _on_cursor_moved(self) -> None:
        self.cursorLineChanged.emit(self.current_line())

    def _refresh_extra_selections(self) -> None:
        selections: list[QTextEdit.ExtraSelection] = []
        if self._current_line:
            block = self.document().findBlockByNumber(self._current_line - 1)
            if block.isValid():
                selection = QTextEdit.ExtraSelection()
                selection.format.setBackground(QColor(self._token["selection"]))
                selection.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
                cursor = QTextCursor(block)
                cursor.clearSelection()
                selection.cursor = cursor
                selections.append(selection)

        error_format = QTextCharFormat()
        error_format.setUnderlineStyle(QTextCharFormat.UnderlineStyle.WaveUnderline)
        error_format.setUnderlineColor(QColor(self._token["error"]))
        for line in sorted(self._validation_lines)[:200]:
            block = self.document().findBlockByNumber(line - 1)
            if not block.isValid():
                continue
            selection = QTextEdit.ExtraSelection()
            selection.format = error_format
            cursor = QTextCursor(block)
            selection.cursor = cursor
            selections.append(selection)

        self.setExtraSelections(selections)

    def _queue_validation(self) -> None:
        self._validate_timer.start()

    def _validate(self) -> None:
        if self.blockCount() > 20_000:
            self._validation_lines = set()
            self._gutter.update()
            return
        invalid: set[int] = set()
        block = self.document().firstBlock()
        while block.isValid():
            if len(block.text()) > MAX_LINE_LENGTH:
                invalid.add(block.blockNumber() + 1)
            block = block.next()
        if invalid != self._validation_lines:
            self._validation_lines = invalid
            self._gutter.update()
            self._refresh_extra_selections()


class FindBar(QWidget):
    """Inline find/replace bar used by the main window."""

    def __init__(self, editor: GcodeEditor, parent=None) -> None:  # noqa: ANN001
        super().__init__(parent)
        self._editor = editor
        self.setObjectName("Panel")
        self._find = QLineEdit()
        self._find.setPlaceholderText("Find")
        self._find.setClearButtonEnabled(True)
        self._replace = QLineEdit()
        self._replace.setPlaceholderText("Replace with")
        self._case = QCheckBox("Match case")
        self._status = QLabel("")
        self._status.setObjectName("Muted")
        self._prev = QPushButton("Prev")
        self._next = QPushButton("Next")
        self._replace_button = QPushButton("Replace")
        self._replace_all_button = QPushButton("All")
        close = QPushButton("✕")
        close.setFixedWidth(30)

        first = QHBoxLayout()
        first.addWidget(QLabel("Find"))
        first.addWidget(self._find, 1)
        first.addWidget(self._case)
        first.addWidget(self._prev)
        first.addWidget(self._next)
        first.addWidget(close)

        second = QHBoxLayout()
        second.addWidget(QLabel("Replace"))
        second.addWidget(self._replace, 1)
        second.addWidget(self._replace_button)
        second.addWidget(self._replace_all_button)
        second.addWidget(self._status, 1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)
        layout.addLayout(first)
        layout.addLayout(second)

        self._next.clicked.connect(self.find_next)
        self._prev.clicked.connect(self.find_previous)
        self._replace_button.clicked.connect(self.replace_one)
        self._replace_all_button.clicked.connect(self.replace_all)
        close.clicked.connect(self.hide)
        self._find.returnPressed.connect(self.find_next)
        self._find.textChanged.connect(self._clear_status)
        self.hide()

    def activate(self, replace: bool = False) -> None:
        self.show()
        if replace:
            self._replace.setFocus()
            self._replace.selectAll()
        else:
            self._find.setFocus()
            self._find.selectAll()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
            self._editor.setFocus()
            return
        super().keyPressEvent(event)

    def _flags(self) -> QTextDocument.FindFlag:
        flags = QTextDocument.FindFlag(0)
        if self._case.isChecked():
            flags |= QTextDocument.FindFlag.FindCaseSensitively
        return flags

    def find_next(self) -> None:
        if not self._find.text():
            return
        if not self._editor.find(self._find.text(), self._flags()):
            cursor = self._editor.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.Start)
            self._editor.setTextCursor(cursor)
            if not self._editor.find(self._find.text(), self._flags()):
                self._status.setText("Not found")

    def find_previous(self) -> None:
        if not self._find.text():
            return
        flags = self._flags() | QTextDocument.FindFlag.FindBackward
        if not self._editor.find(self._find.text(), flags):
            cursor = self._editor.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            self._editor.setTextCursor(cursor)
            if not self._editor.find(self._find.text(), flags):
                self._status.setText("Not found")

    def replace_one(self) -> None:
        cursor = self._editor.textCursor()
        if cursor.hasSelection():
            cursor.insertText(self._replace.text())
        self.find_next()

    def replace_all(self) -> None:
        needle = self._find.text()
        if not needle:
            return
        text = self._editor.toPlainText()
        replacement = self._replace.text()
        if self._case.isChecked():
            count = text.count(needle)
            updated = text.replace(needle, replacement)
        else:
            count = len(re.findall(re.escape(needle), text, flags=re.IGNORECASE))
            updated = re.sub(re.escape(needle), lambda _: replacement, text, flags=re.IGNORECASE)
        self._editor.set_source_text(updated)
        self._status.setText(f"Replaced {count}")

    def _clear_status(self) -> None:
        self._status.setText("")
