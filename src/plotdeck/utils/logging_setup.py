"""Logging configuration: rotating file plus console."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


def log_directory() -> Path:
    path = Path.home() / "Library" / "Logs" / "PlotDeck"
    path.mkdir(parents=True, exist_ok=True)
    return path


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    logger = logging.getLogger("plotdeck")
    if logger.handlers:
        return logger
    logger.setLevel(level)
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S"
    )

    handler: logging.Handler
    try:
        handler = RotatingFileHandler(
            log_directory() / "plotdeck.log", maxBytes=1_000_000, backupCount=3
        )
    except OSError:
        handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    if sys.stderr is not None:
        console = logging.StreamHandler(sys.stderr)
        console.setFormatter(formatter)
        console.setLevel(logging.WARNING)
        logger.addHandler(console)

    return logger
