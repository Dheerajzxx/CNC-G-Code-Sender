"""Persistent application settings backed by QSettings."""

from __future__ import annotations

from PySide6.QtCore import QByteArray, QSettings


class AppSettings:
    def __init__(self, path: str | None = None) -> None:
        if path:
            self._settings = QSettings(path, QSettings.Format.IniFormat)
        else:
            self._settings = QSettings("PlotDeck", "PlotDeck")

    def value(self, key: str, default=None, kind=None):  # noqa: ANN001, ANN201
        if kind is not None:
            return self._settings.value(key, default, type=kind)
        return self._settings.value(key, default)

    def set_value(self, key: str, value) -> None:  # noqa: ANN001
        self._settings.setValue(key, value)

    def sync(self) -> None:
        self._settings.sync()

    # -- recent files --------------------------------------------------- #
    def recent_files(self) -> list[str]:
        value: object = self._settings.value("files/recent", [])
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, (list, tuple)):
            return []
        return [str(item) for item in value if item]

    def add_recent_file(self, path: str) -> None:
        files = [item for item in self.recent_files() if item != path]
        files.insert(0, path)
        self._settings.setValue("files/recent", files[:8])

    def clear_recent_files(self) -> None:
        self._settings.setValue("files/recent", [])

    # -- window --------------------------------------------------------- #
    def geometry(self) -> QByteArray | None:
        value = self._settings.value("window/geometry")
        return value if isinstance(value, QByteArray) else None

    def save_geometry(self, geometry: QByteArray) -> None:
        self._settings.setValue("window/geometry", geometry)

    def window_state(self) -> QByteArray | None:
        value = self._settings.value("window/state")
        return value if isinstance(value, QByteArray) else None

    def save_window_state(self, state: QByteArray) -> None:
        self._settings.setValue("window/state", state)

    # -- preferences ---------------------------------------------------- #
    def dark_theme(self, fallback: bool = True) -> bool:
        value = self._settings.value("ui/dark", fallback)
        return str(value).lower() in ("1", "true", "yes")

    def set_dark_theme(self, dark: bool) -> None:
        self._settings.setValue("ui/dark", dark)

    def last_port(self) -> str:
        return str(self._settings.value("machine/port", ""))

    def set_last_port(self, port: str) -> None:
        self._settings.setValue("machine/port", port)

    def last_baud(self) -> int:
        try:
            return int(str(self._settings.value("machine/baud", 115200)))
        except (TypeError, ValueError):
            return 115200

    def set_last_baud(self, baud: int) -> None:
        self._settings.setValue("machine/baud", baud)

    def auto_reconnect(self) -> bool:
        return str(self._settings.value("machine/auto_reconnect", False)).lower() in (
            "1",
            "true",
            "yes",
        )
