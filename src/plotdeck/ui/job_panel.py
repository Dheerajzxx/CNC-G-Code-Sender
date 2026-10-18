"""Job progress, elapsed time and line counter."""

from __future__ import annotations

import time

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QGridLayout,
    QLabel,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)


def format_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


class JobPanel(QWidget):
    def __init__(self, parent=None) -> None:  # noqa: ANN001
        super().__init__(parent)
        self.setObjectName("Panel")
        self._started: float | None = None
        self._total = 0
        self._sent = 0
        self._estimate = 0.0
        self._running = False

        header = QLabel("JOB")
        header.setObjectName("SectionHeader")
        self._progress = QProgressBar()
        self._progress.setRange(0, 1000)
        self._progress.setValue(0)
        self._progress.setFormat("0%")

        self._line = QLabel("line -- / --")
        self._line.setObjectName("Muted")
        self._elapsed = QLabel("elapsed 00:00")
        self._elapsed.setObjectName("Muted")
        self._remaining = QLabel("remaining --:--")
        self._remaining.setObjectName("Muted")

        grid = QGridLayout()
        grid.addWidget(self._line, 0, 0)
        grid.addWidget(self._elapsed, 1, 0)
        grid.addWidget(self._remaining, 1, 1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)
        layout.addWidget(header)
        layout.addWidget(self._progress)
        layout.addLayout(grid)
        layout.addStretch(1)

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)

    def begin(self, total: int, estimate_seconds: float = 0.0) -> None:
        self._total = total
        self._sent = 0
        self._estimate = estimate_seconds
        self._started = time.monotonic()
        self._running = True
        self._progress.setValue(0)
        self._progress.setFormat("0%")
        self._line.setText(f"line -- / {total}")
        self._elapsed.setText("elapsed 00:00")
        self._remaining.setText(
            f"remaining {format_duration(estimate_seconds)}"
            if estimate_seconds
            else "remaining --:--"
        )
        self._timer.start()

    def update_progress(self, sent: int, total: int, line: int) -> None:
        if not self._running:
            return
        self._sent = sent
        self._total = max(1, total)
        fraction = sent / self._total
        self._progress.setValue(int(fraction * 1000))
        self._progress.setFormat(f"{fraction * 100:.0f}%")
        self._line.setText(f"line {line} / {self._total}")

    def finish(self, reason: str) -> None:
        self._running = False
        self._timer.stop()
        label = {
            "completed": "completed",
            "stopped": "stopped",
            "alarm": "stopped by alarm",
            "disconnected": "interrupted - disconnected",
            "error": "stopped by error",
        }.get(reason, reason)
        self._line.setText(f"Job {label}")
        if reason == "completed":
            self._progress.setValue(1000)
            self._progress.setFormat("100%")
            self._remaining.setText("remaining 00:00")
        else:
            self._remaining.setText("remaining --:--")

    def reset(self) -> None:
        self._running = False
        self._timer.stop()
        self._total = 0
        self._sent = 0
        self._progress.setValue(0)
        self._progress.setFormat("0%")
        self._line.setText("line -- / --")
        self._elapsed.setText("elapsed 00:00")
        self._remaining.setText("remaining --:--")

    def _tick(self) -> None:
        if self._started is None:
            return
        elapsed = time.monotonic() - self._started
        self._elapsed.setText(f"elapsed {format_duration(elapsed)}")
        if self._estimate and self._total:
            remaining = self._estimate * (1 - self._sent / self._total)
            self._remaining.setText(f"remaining {format_duration(remaining)}")
