"""Serial transport layer.

The transport is swappable: :class:`SerialTransport` talks to a real port,
while :class:`MockTransport` provides a self-contained demo machine. Both
deliver complete lines through plain callbacks, which keeps this module free
of Qt imports.
"""

from __future__ import annotations

import threading
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from contextlib import suppress
from typing import Any

from .grbl_protocol import BAUD_RATE, UNO_RESET_DELAY_S


class TransportError(RuntimeError):
    pass


class Transport(ABC):
    """Common interface for anything that can exchange lines with GRBL."""

    on_line: Callable[[str], None] | None = None
    on_error: Callable[[str], None] | None = None
    on_closed: Callable[[str], None] | None = None
    on_open: Callable[[], None] | None = None

    @property
    @abstractmethod
    def is_open(self) -> bool: ...

    @abstractmethod
    def open(self) -> None: ...

    @abstractmethod
    def close(self) -> None: ...

    @abstractmethod
    def write(self, data: bytes) -> None: ...

    # Convenience helpers ---------------------------------------------------
    def send_line(self, line: str) -> None:
        self.write(line.encode("utf-8") + b"\n")

    def send_realtime(self, byte: bytes) -> None:
        self.write(byte)

    def _emit_line(self, line: str) -> None:
        callback = self.on_line
        if callback is not None:
            # Never let a consumer exception kill the reader thread.
            with suppress(Exception):
                callback(line)

    def _emit_error(self, message: str) -> None:
        callback = self.on_error
        if callback is not None:
            with suppress(Exception):
                callback(message)

    def _emit_closed(self, reason: str) -> None:
        callback = self.on_closed
        if callback is not None:
            with suppress(Exception):
                callback(reason)

    def _emit_open(self) -> None:
        callback = self.on_open
        if callback is not None:
            with suppress(Exception):
                callback()


class SerialTransport(Transport):
    """pyserial transport on a background thread.

    The Uno resets when the port opens, so the reader waits
    :data:`UNO_RESET_DELAY_S` before flushing and asking for a status report.
    The GRBL welcome banner then tells the controller the link is really up.
    """

    def __init__(
        self,
        port: str,
        baud: int = BAUD_RATE,
        reset_delay: float = UNO_RESET_DELAY_S,
    ) -> None:
        self.port = port
        self.baud = baud
        self.reset_delay = reset_delay
        self._serial: Any = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._write_lock = threading.Lock()
        self._open = False

    @property
    def is_open(self) -> bool:
        return self._open

    def open(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name=f"serial-{self.port}", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        import serial

        try:
            self._serial = serial.Serial(self.port, self.baud, timeout=0.05)
        except Exception as exc:  # serial.SerialException and OSError
            self._open = False
            self._emit_error(f"Could not open {self.port}: {exc}")
            self._emit_closed(str(exc))
            return

        self._open = True
        try:
            time.sleep(self.reset_delay)
            if self._stop.is_set():
                return
            with self._write_lock:
                self._serial.write(b"\r\n\r\n")
                self._serial.flush()
            # Start status polling only after the Uno has rebooted, so the
            # first '?' does not land in the bootloader.
            self._emit_open()
        except Exception as exc:  # noqa: BLE001
            self._emit_error(str(exc))

        while not self._stop.is_set():
            try:
                data = self._serial.readline()
            except Exception as exc:  # unplugged or closed
                if not self._stop.is_set():
                    self._emit_error(f"Serial connection lost: {exc}")
                    self._emit_closed(str(exc))
                break
            if not data:
                continue
            decoded = data.decode("utf-8", errors="replace").strip("\r\n ")
            if decoded:
                self._emit_line(decoded)

    def close(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=1.5)
        self._thread = None
        self._open = False
        serial_port = self._serial
        self._serial = None
        if serial_port is not None:
            with suppress(Exception):
                serial_port.close()

    def write(self, data: bytes) -> None:
        serial_port = self._serial
        if not self._open or serial_port is None:
            raise TransportError("Serial port is not open.")
        with self._write_lock:
            try:
                serial_port.write(data)
                serial_port.flush()
            except Exception as exc:  # noqa: BLE001
                self._emit_error(f"Write failed: {exc}")
                raise TransportError(str(exc)) from exc


class MockTransport(Transport):
    """A tiny GRBL stand-in so the UI can be explored without hardware.

    It implements the same character-counting contract as the real firmware:
    lines are queued and acknowledged one at a time, status reports work, and
    ``!``/``~`` change the state.
    """

    def __init__(self, line_delay: float = 0.004) -> None:
        self._delay = line_delay
        self._open = False
        self._state = "Idle"
        self._pos = [0.0, 0.0, 0.0]
        self._feed = 0.0
        self._spindle = 0.0
        self._settings = {
            0: "10",
            1: "25",
            2: "0",
            3: "0",
            4: "0",
            5: "0",
            6: "0",
            10: "3",
            11: "0.010",
            12: "0.002",
            13: "0",
            20: "0",
            21: "0",
            22: "1",
            23: "0",
            24: "25.000",
            25: "500.000",
            26: "250",
            27: "1.000",
            30: "1000",
            31: "0",
            32: "0",
            100: "250.000",
            101: "250.000",
            102: "250.000",
            110: "500.000",
            111: "500.000",
            112: "500.000",
            120: "10.000",
            121: "10.000",
            122: "10.000",
            130: "200.000",
            131: "200.000",
            132: "200.000",
        }
        self._thread: threading.Thread | None = None
        self._worker: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._pending: list[int] = []
        self._lines: list[str] = []

    @property
    def is_open(self) -> bool:
        return self._open

    def open(self) -> None:
        self._open = True
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="mock-grbl", daemon=True)
        self._thread.start()
        self._worker = threading.Thread(
            target=self._process_lines, name="mock-grbl-lines", daemon=True
        )
        self._worker.start()

    def _run(self) -> None:
        time.sleep(0.2)
        self._emit_open()
        self._emit_line("Grbl 1.1h ['$' for help]")
        while not self._stop.is_set():
            time.sleep(0.05)

    def _process_lines(self) -> None:
        # Line commands are acknowledged asynchronously, like real firmware.
        while not self._stop.is_set():
            with self._lock:
                line = self._lines.pop(0) if self._lines else None
            if line is None:
                time.sleep(0.002)
                continue
            self._dispatch(line)
            time.sleep(self._delay)

    def close(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=1.0)
        worker = self._worker
        if worker is not None and worker is not threading.current_thread():
            worker.join(timeout=1.0)
        self._thread = None
        self._worker = None
        if self._open:
            self._open = False
            self._emit_closed("Disconnected")

    def write(self, data: bytes) -> None:
        if not self._open:
            raise TransportError("Mock transport is not open.")
        with self._lock:
            for byte in data:
                self._handle_byte(byte)

    def _handle_byte(self, byte: int) -> None:
        if byte == 0x3F:  # '?'
            self._emit_status()
        elif byte == 0x21:  # '!'
            self._state = "Hold:0"
        elif byte == 0x7E:  # '~'
            self._state = "Idle"
        elif byte == 0x18:  # soft reset
            self._state = "Idle"
            self._feed = 0.0
            self._pending.clear()
            self._lines.clear()
            threading.Timer(0.05, lambda: self._emit_line("Grbl 1.1h ['$' for help]")).start()
        elif byte == 0x85:
            self._state = "Idle"
        elif byte in (0x0A, 0x0D):
            line = bytes(self._pending).decode("utf-8", errors="replace").strip()
            self._pending.clear()
            if line:
                self._lines.append(line)
        else:
            self._pending.append(byte)

    def _emit_status(self) -> None:
        pos = "MPos:{:.3f},{:.3f},{:.3f}".format(*self._pos)
        self._emit_line(
            f"<{self._state}|{pos}|FS:{self._feed:.0f},{self._spindle:.0f}"
            f"|Bf:0,127|Ov:100,100,100>"
        )

    # A line is dispatched when its newline arrives; handled in write().
    def _dispatch(self, line: str) -> None:
        text = line.strip()
        if not text:
            return
        if text == "?":
            self._emit_status()
            return
        if text == "$$":
            for key in sorted(self._settings):
                self._emit_line(f"${key}={self._settings[key]}")
            self._emit_line("ok")
            return
        if text == "$I":
            self._emit_line("[VER:1.1h.20190825:]")
            self._emit_line("[OPT:V,15,128]")
            self._emit_line("ok")
            return
        if text.startswith("$J="):
            self._emit_line("ok")
            return
        if text == "$H":
            self._state = "Home"
            self._pos = [0.0, 0.0, 0.0]
            self._state = "Idle"
            self._emit_line("ok")
            return
        if text in ("$X", "$C", "$G", "$#"):
            self._emit_line("ok")
            return
        if text.startswith("G0") or text.startswith("G1"):
            import re

            for axis, value in re.findall(r"([XYZ])([-+]?\d*\.?\d+)", text):
                index = "XYZ".index(axis)
                self._pos[index] = float(value)
            self._emit_line("ok")
            return
        if text.startswith("M3") or text.startswith("M5"):
            self._emit_line("ok")
            return
        self._emit_line("ok")


def list_serial_ports() -> list[tuple[str, str]]:
    """Return USB-looking serial ports as ``(device, description)``."""
    try:
        from serial.tools import list_ports
    except ImportError:
        return []
    ports: list[tuple[str, str]] = []
    for info in list_ports.comports():
        device = info.device
        if any(token in device for token in ("usbmodem", "usbserial", "wchusbserial")):
            ports.append((device, info.description or device))
    ports.sort()
    return ports
