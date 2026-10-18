"""QApplication bootstrap."""

from __future__ import annotations

import logging
import sys
import traceback

from PySide6.QtWidgets import QApplication, QMessageBox

from . import APP_NAME, __version__
from .ui.main_window import MainWindow
from .utils.logging_setup import setup_logging
from .utils.settings import AppSettings


def _install_exception_hook(logger: logging.Logger) -> None:
    def hook(exc_type, exc_value, exc_tb):  # noqa: ANN001
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        trace = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        logger.error("Unhandled exception:\n%s", trace)
        app = QApplication.instance()
        if app is not None:
            QMessageBox.critical(
                None,
                "PlotDeck crashed",
                "An unexpected error occurred. The traceback was written to "
                "~/Library/Logs/PlotDeck/plotdeck.log.\n\n"
                f"{exc_type.__name__}: {exc_value}",
            )

    sys.excepthook = hook


def main(argv: list[str] | None = None) -> int:
    logger = setup_logging()
    logger.info("Starting %s %s", APP_NAME, __version__)
    _install_exception_hook(logger)

    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setOrganizationName("PlotDeck")
    app.setApplicationVersion(__version__)

    settings = AppSettings()
    window = MainWindow(app_settings=settings)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
