"""In-app user manual rendered from USER_MANUAL.md."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QPalette,
    QTextCursor,
    QTextDocument,
)
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
)

from .theme import tokens

MISSING_MANUAL = """# PlotDeck User Manual

The manual file (`USER_MANUAL.md`) could not be found in this installation.

From a source checkout, it lives in the project root next to `README.md`.
"""


def manual_path() -> Path | None:
    """Find USER_MANUAL.md in a source checkout or a frozen application."""
    candidates: list[Path] = []
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        candidates.append(Path(bundle) / "USER_MANUAL.md")
    candidates.append(Path(__file__).resolve().parents[3] / "USER_MANUAL.md")
    candidates.append(Path(__file__).resolve().parent / "resources" / "USER_MANUAL.md")
    candidates.append(Path.cwd() / "USER_MANUAL.md")
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def manual_text() -> str:
    path = manual_path()
    if path is None:
        return MISSING_MANUAL
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return MISSING_MANUAL


class ManualDialog(QDialog):
    """Non-modal, searchable viewer for the user manual."""

    def __init__(self, token: dict[str, str] | None = None, parent=None) -> None:  # noqa: ANN001
        super().__init__(parent)
        self._token = token or tokens()
        self.setWindowTitle("PlotDeck User Manual")
        self.resize(940, 760)
        self.setMinimumSize(620, 480)

        self.browser = QTextBrowser()
        self.browser.setOpenExternalLinks(False)
        self.browser.setOpenLinks(False)
        self.browser.anchorClicked.connect(self._open_link)
        self.browser.setMarkdown(manual_text())
        self.browser.setStyleSheet(
            f"QTextBrowser {{ background: {self._token['editor']};"
            f" color: {self._token['text']};"
            f" border: 1px solid {self._token['border']}; border-radius: 6px;"
            " padding: 10px; }"
        )
        palette = self.browser.palette()
        palette.setColor(QPalette.ColorRole.Link, QColor(self._token["accent"]))
        self.browser.setPalette(palette)
        self._search = QLineEdit()
        self._search.setPlaceholderText("Find in manual…")
        self._search.setClearButtonEnabled(True)
        self._search.returnPressed.connect(self._find_next)
        previous = QPushButton("Previous")
        next_button = QPushButton("Next")
        previous.clicked.connect(self._find_previous)
        next_button.clicked.connect(self._find_next)

        top = QHBoxLayout()
        top.addWidget(self._search, 1)
        top.addWidget(previous)
        top.addWidget(next_button)

        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        open_external = QPushButton("Open in browser")
        open_external.setToolTip("Open the markdown file in your default Markdown viewer")
        open_external.clicked.connect(self._open_external)

        bottom = QHBoxLayout()
        bottom.addStretch(1)
        bottom.addWidget(open_external)
        bottom.addWidget(close)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 10)
        layout.setSpacing(8)
        layout.addLayout(top)
        layout.addWidget(self.browser, 1)
        layout.addLayout(bottom)

    # ------------------------------------------------------------------ #
    def _find_next(self) -> None:
        text = self._search.text()
        if not text:
            return
        if not self.browser.find(text):
            self.browser.moveCursor(QTextCursor.MoveOperation.Start)
            if not self.browser.find(text):
                self._search.setStyleSheet(f"color: {self._token['alarm']};")
                return
        self._search.setStyleSheet("")

    def _find_previous(self) -> None:
        text = self._search.text()
        if not text:
            return
        if not self.browser.find(text, QTextDocument.FindFlag.FindBackward):
            cursor = self.browser.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            self.browser.setTextCursor(cursor)
            self.browser.find(text, QTextDocument.FindFlag.FindBackward)

    def _open_link(self, url: QUrl) -> None:
        anchor = url.toString()
        if anchor.startswith("#"):
            self.browser.scrollToAnchor(anchor[1:])
            return
        if url.scheme() in ("http", "https", "mailto"):
            QDesktopServices.openUrl(url)
            return
        # Relative links such as README.md live next to the manual.
        path = manual_path()
        if path is not None:
            target = path.parent / url.toLocalFile() if url.isLocalFile() else path.parent / anchor
            if target.is_file():
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))

    def _open_external(self) -> None:
        path = manual_path()
        if path is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
