"""In-process GRBL simulator used by the test-suite and headless demos."""

from __future__ import annotations

import threading
from collections import deque

from plotdeck.core.grbl_protocol import RX_BUFFER_SIZE
from plotdeck.core.transport import Transport


class FakeGrbl(Transport):
    def __init__(
        self,
        rx_buffer: int = RX_BUFFER_SIZE,
        ack_delay: float = 0.0005,
        banner_delay: float = 0.01,
        error_lines: dict[int, int] | None = None,
    ) -> None:
        self.rx_buffer = rx_buffer
        self.ack_delay = ack_delay
        self.banner_delay = banner_delay
        self.error_lines = error_lines or {}

        self.received: list[str] = []
        self.realtime: list[int] = []
        self.overruns = 0
        self.max_buffered = 0
        self._buffer_used = 0
        self._queue: deque[tuple[int, str, int]] = deque()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._open = False
        self._threads: list[threading.Thread] = []
        self._state = "Idle"
        self._pos = [0.0, 0.0, 0.0]
        self._feed = 0
        self._spindle = 0
        self._byte_buffer = bytearray()

    @property
    def is_open(self) -> bool:
        return self._open

    def open(self) -> None:
        self._open = True
        self._stop.clear()
        self._spawn(self._banner_loop)
        self._spawn(self._ack_loop)

    def _spawn(self, target) -> None:  # noqa: ANN001
        thread = threading.Thread(target=target, daemon=True)
        thread.start()
        self._threads.append(thread)

    def close(self) -> None:
        self._stop.set()
        self._open = False
        for thread in self._threads:
            thread.join(timeout=0.5)
        self._threads.clear()

    # ------------------------------------------------------------------ #
    def _banner_loop(self) -> None:
        if self._stop.wait(self.banner_delay):
            return
        self._emit_open()
        self._emit_line("Grbl 1.1h ['$' for help]")

    def _ack_loop(self) -> None:
        while not self._stop.is_set():
            if self._stop.wait(self.ack_delay):
                return
            with self._lock:
                item = self._queue.popleft() if self._queue else None
                if item is None:
                    continue
                size, line, index = item
                self._buffer_used -= size
                self._buffer_used = max(0, self._buffer_used)
            error = self.error_lines.get(index)
            if error is not None:
                self._emit_line(f"error:{error}")
            else:
                self._emit_line("ok")

    # ------------------------------------------------------------------ #
    def write(self, data: bytes) -> None:
        if not self._open:
            raise RuntimeError("FakeGrbl is not open")
        for byte in data:
            if byte == 0x3F:
                self._record_realtime(byte)
                self._emit_line(self.status_report())
            elif byte == 0x21:
                self._record_realtime(byte)
                self._state = "Hold:0"
            elif byte == 0x7E:
                self._record_realtime(byte)
                self._state = "Idle"
            elif byte == 0x18:
                self._record_realtime(byte)
                self._state = "Idle"
                with self._lock:
                    self._queue.clear()
                    self._buffer_used = 0
                self._emit_line("Grbl 1.1h ['$' for help]")
            elif byte == 0x85:
                self._record_realtime(byte)
            elif byte in (0x0A, 0x0D):
                line = bytes(self._byte_buffer).decode("utf-8", errors="replace").strip()
                self._byte_buffer.clear()
                if line:
                    self._dispatch(line)
            elif byte >= 0x80:
                self._record_realtime(byte)
            else:
                self._byte_buffer.append(byte)

    def _record_realtime(self, byte: int) -> None:
        with self._lock:
            self.realtime.append(byte)

    def _dispatch(self, line: str) -> None:
        with self._lock:
            self.received.append(line)
            index = len(self.received)
            size = len(line) + 1
            self._buffer_used += size
            self.max_buffered = max(self.max_buffered, self._buffer_used)
            if self._buffer_used > self.rx_buffer:
                self.overruns += 1
            self._queue.append((size, line, index))
        if line == "$$":
            # Settings replies are not queued; they precede the ok.
            for number, value in ((100, "250.000"), (130, "200.000")):
                self._emit_line(f"${number}={value}")
            with self._lock:
                self._queue.pop()
                self._buffer_used -= size
            self._emit_line("ok")
        elif line.startswith("$J="):
            self._state = "Jog"
            self._state = "Idle"
        elif line == "G10 L20 P1 X0":
            pass

    def status_report(self) -> str:
        position = "MPos:{:.3f},{:.3f},{:.3f}".format(*self._pos)
        return (
            f"<{self._state}|{position}|FS:{self._feed},{self._spindle}"
            f"|Bf:{self._buffer_used},127|Ov:100,100,100>"
        )

    def emit_alarm(self, code: int = 1) -> None:
        self._state = "Alarm"
        self._emit_line(f"ALARM:{code}")

    def emit_status(self, state: str = "Idle") -> None:
        self._state = state
        self._emit_line(self.status_report())

    def emit_message(self, text: str) -> None:
        self._emit_line(f"[MSG:{text}]")

    def emit_error(self, code: int = 20) -> None:
        self._emit_line(f"error:{code}")

    def buffered_bytes(self) -> int:
        with self._lock:
            return self._buffer_used
