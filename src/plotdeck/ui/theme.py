"""Theme tokens and stylesheet construction.

All colours live here; widgets read them from :func:`tokens` instead of
hard-coding hex values, so light and dark themes stay consistent.
"""

from __future__ import annotations

DARK = {
    "window": "#0F1215",
    "surface": "#1A1E23",
    "editor": "#14171A",
    "border": "#2A3038",
    "text": "#D7DDE4",
    "muted": "#8B95A1",
    "accent": "#4C9BF0",
    "accent_text": "#FFFFFF",
    "idle": "#3FB67A",
    "run": "#4C9BF0",
    "hold": "#E0A030",
    "alarm": "#E5584F",
    "offline": "#7D8896",
    "selection": "#233A52",
    "gutter": "#101316",
    "g_word": "#7CB7FF",
    "m_word": "#C792EA",
    "axis_word": "#E6C07B",
    "feed_word": "#7FD1AE",
    "comment": "#7D8896",
    "error": "#E5584F",
    "danger": "#C0453D",
    "danger_hover": "#D2544B",
    "primary": "#2F6FB5",
    "primary_hover": "#3A83D2",
    "tooltip": "#22282F",
}

LIGHT = {
    "window": "#F2F4F7",
    "surface": "#FFFFFF",
    "editor": "#FBFCFD",
    "border": "#D5DBE3",
    "text": "#1D242C",
    "muted": "#5C6773",
    "accent": "#1F6FD0",
    "accent_text": "#FFFFFF",
    "idle": "#1E8F58",
    "run": "#1F6FD0",
    "hold": "#A86A00",
    "alarm": "#C0392B",
    "offline": "#6B7682",
    "selection": "#D6E6FA",
    "gutter": "#EEF1F5",
    "g_word": "#1B5FA8",
    "m_word": "#7A3FA0",
    "axis_word": "#8A6200",
    "feed_word": "#117A5B",
    "comment": "#6B7682",
    "error": "#C0392B",
    "danger": "#C0392B",
    "danger_hover": "#D64B3D",
    "primary": "#1F6FD0",
    "primary_hover": "#2C82E8",
    "tooltip": "#FFFFFF",
}

UI_FONT = '"IBM Plex Sans", "SF Pro Text", "Helvetica Neue", sans-serif'
MONO_FONT = '"IBM Plex Mono", "SF Mono", Menlo, monospace'


def tokens(dark: bool = True) -> dict[str, str]:
    return dict(DARK if dark else LIGHT)


def is_dark_system() -> bool:
    """Best-effort detection of the macOS appearance without importing Qt."""
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QGuiApplication

        hints = QGuiApplication.styleHints()
        if hasattr(hints, "colorScheme"):
            return hints.colorScheme() == Qt.ColorScheme.Dark
    except Exception:  # noqa: BLE001
        pass
    return True


def state_color(token: dict[str, str], family: str) -> str:
    return {
        "idle": token["idle"],
        "run": token["run"],
        "hold": token["hold"],
        "alarm": token["alarm"],
    }.get(family, token["offline"])


def build_stylesheet(token: dict[str, str]) -> str:
    return f"""
    * {{
        font-family: {UI_FONT};
        font-size: 13px;
    }}
    QMainWindow, QDialog {{
        background: {token["window"]};
        color: {token["text"]};
    }}
    QWidget#Panel, QDockWidget > QWidget {{
        background: {token["surface"]};
        color: {token["text"]};
    }}
    QDockWidget {{
        color: {token["muted"]};
        titlebar-close-icon: none;
        titlebar-normal-icon: none;
    }}
    QDockWidget::title {{
        background: {token["window"]};
        border-bottom: 1px solid {token["border"]};
        padding: 6px 8px;
        font-size: 11px;
        font-weight: 600;
        letter-spacing: 1px;
        text-transform: uppercase;
    }}
    QToolBar {{
        background: {token["surface"]};
        border-bottom: 1px solid {token["border"]};
        spacing: 6px;
        padding: 5px 8px;
    }}
    QToolBar::separator {{
        background: {token["border"]};
        width: 1px;
        margin: 4px 6px;
    }}
    QStatusBar {{
        background: {token["surface"]};
        border-top: 1px solid {token["border"]};
        color: {token["muted"]};
    }}
    QLabel {{
        background: transparent;
        color: {token["text"]};
    }}
    QLabel#Muted, QLabel#Legend {{
        color: {token["muted"]};
    }}
    QLabel#SectionHeader {{
        color: {token["muted"]};
        font-size: 11px;
        font-weight: 600;
        letter-spacing: 1px;
    }}
    QLabel#DroValue {{
        font-family: {MONO_FONT};
        font-size: 26px;
        font-weight: 600;
    }}
    QLabel#DroAxis {{
        font-family: {MONO_FONT};
        font-size: 14px;
        font-weight: 700;
        color: {token["muted"]};
    }}
    QLabel#DroSecondary {{
        font-family: {MONO_FONT};
        font-size: 11px;
        color: {token["muted"]};
    }}
    QPushButton, QToolButton {{
        background: {token["surface"]};
        color: {token["text"]};
        border: 1px solid {token["border"]};
        border-radius: 6px;
        padding: 6px 12px;
        min-height: 20px;
    }}
    QPushButton:hover, QToolButton:hover {{
        background: {token["selection"]};
    }}
    QPushButton:pressed, QToolButton:pressed {{
        background: {token["border"]};
    }}
    QPushButton:disabled, QToolButton:disabled {{
        color: {token["muted"]};
        background: {token["window"]};
    }}
    QToolButton:checked {{
        background: {token["selection"]};
        border-color: {token["accent"]};
    }}
    QPushButton#Primary {{
        background: {token["primary"]};
        border-color: {token["primary"]};
        color: {token["accent_text"]};
        font-weight: 600;
    }}
    QPushButton#Primary:hover {{
        background: {token["primary_hover"]};
    }}
    QPushButton#Danger, QToolButton#Danger {{
        background: {token["danger"]};
        border-color: {token["danger"]};
        color: {token["accent_text"]};
        font-weight: 700;
        min-width: 72px;
    }}
    QPushButton#Danger:hover, QToolButton#Danger:hover {{
        background: {token["danger_hover"]};
    }}
    QPlainTextEdit, QTextEdit, QTextBrowser, QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
        background: {token["editor"]};
        color: {token["text"]};
        border: 1px solid {token["border"]};
        border-radius: 6px;
        selection-background-color: {token["selection"]};
        selection-color: {token["text"]};
    }}
    QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
        padding: 5px 8px;
        min-height: 20px;
    }}
    QPlainTextEdit, QTextEdit {{
        padding: 4px;
    }}
    QComboBox::drop-down {{
        border: none;
        width: 20px;
    }}
    QComboBox QAbstractItemView {{
        background: {token["surface"]};
        color: {token["text"]};
        border: 1px solid {token["border"]};
        selection-background-color: {token["selection"]};
    }}
    QCheckBox {{
        color: {token["text"]};
        spacing: 6px;
    }}
    QSlider::groove:horizontal {{
        height: 4px;
        background: {token["border"]};
        border-radius: 2px;
    }}
    QSlider::sub-page:horizontal {{
        background: {token["accent"]};
        border-radius: 2px;
    }}
    QSlider::handle:horizontal {{
        background: {token["text"]};
        width: 14px;
        margin: -6px 0;
        border-radius: 7px;
    }}
    QProgressBar {{
        background: {token["editor"]};
        border: 1px solid {token["border"]};
        border-radius: 4px;
        text-align: center;
        color: {token["text"]};
        min-height: 16px;
    }}
    QProgressBar::chunk {{
        background: {token["accent"]};
        border-radius: 3px;
    }}
    QSplitter::handle {{
        background: {token["border"]};
    }}
    QMenuBar, QMenu {{
        background: {token["surface"]};
        color: {token["text"]};
    }}
    QMenuBar::item:selected, QMenu::item:selected {{
        background: {token["selection"]};
    }}
    QMenu::separator {{
        height: 1px;
        background: {token["border"]};
        margin: 4px 8px;
    }}
    QScrollBar:vertical {{
        background: {token["editor"]};
        width: 12px;
        margin: 0;
    }}
    QScrollBar::handle:vertical {{
        background: {token["border"]};
        min-height: 24px;
        border-radius: 6px;
        margin: 2px;
    }}
    QScrollBar:horizontal {{
        background: {token["editor"]};
        height: 12px;
        margin: 0;
    }}
    QScrollBar::handle:horizontal {{
        background: {token["border"]};
        min-width: 24px;
        border-radius: 6px;
        margin: 2px;
    }}
    QScrollBar::add-line, QScrollBar::sub-line {{
        width: 0;
        height: 0;
    }}
    QToolTip {{
        background: {token["tooltip"]};
        color: {token["text"]};
        border: 1px solid {token["border"]};
        padding: 4px;
    }}
    QHeaderView::section {{
        background: {token["window"]};
        color: {token["muted"]};
        border: none;
        border-bottom: 1px solid {token["border"]};
        padding: 5px;
    }}
    QTableWidget {{
        background: {token["editor"]};
        color: {token["text"]};
        gridline-color: {token["border"]};
        border: 1px solid {token["border"]};
        border-radius: 6px;
    }}
    """
