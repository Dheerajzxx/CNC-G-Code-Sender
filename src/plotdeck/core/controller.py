"""MachineController - the GUI-free orchestration layer.

The controller owns the transport, the streamer and the latest machine status.
It never imports Qt; the UI subscribes through plain callbacks (wrapped in a
small QObject bridge in the UI layer) so the whole core can be unit-tested
without an event loop.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass

from .gcode_parser import ProgramLine, clean_line, parse_program
from .grbl_protocol import (
    BAUD_RATE,
    STATUS_INTERVAL_MS,
    RealTime,
    ResponseKind,
    alarm_text,
    banner_version,
    classify,
    error_text,
)
from .status import MachineStatus, parse_status
from .streamer import Streamer, StreamerState
from .transport import MockTransport, SerialTransport, Transport, TransportError, list_serial_ports

LineCallback = Callable[[ResponseKind, str], None]
StatusCallback = Callable[[MachineStatus], None]
ErrorCallback = Callable[[ProgramLine, int, str], None]


@dataclass
class SettingsEntry:
    number: int
    value: str
    description: str = ""


class MachineController:
    """Connect, stream, jog and query a GRBL machine."""

    def __init__(
        self,
        transport_factory: Callable[[str, int], Transport] | None = None,
    ) -> None:
        self._transport_factory = transport_factory or (
            lambda port, baud: SerialTransport(port, baud)
        )
        self._transport: Transport | None = None
        self._streamer: Streamer | None = None
        self._poll_thread: threading.Thread | None = None
        self._poll_stop = threading.Event()
        self._lock = threading.RLock()
        self._connected = False
        self._firmware = ""
        self._status = MachineStatus()
        self._settings: list[SettingsEntry] = []
        self._collecting_settings = False
        self._collecting_info = False
        self._demo = False
        self._manual_acks = 0

        # UI callbacks -----------------------------------------------------
        self.on_line: LineCallback | None = None
        self.on_sent: Callable[[str], None] | None = None
        self.on_status: StatusCallback | None = None
        self.on_connected: Callable[[str], None] | None = None
        self.on_disconnected: Callable[[str], None] | None = None
        self.on_alarm: Callable[[int, str], None] | None = None
        self.on_message: Callable[[str], None] | None = None
        self.on_command_error: Callable[[int, str], None] | None = None
        self.on_stream_error: ErrorCallback | None = None
        self.on_progress: Callable[[int, int, int], None] | None = None
        self.on_job_finished: Callable[[str], None] | None = None
        self.on_tool_change: Callable[[ProgramLine], None] | None = None
        self.on_stream_state: Callable[[StreamerState], None] | None = None
        self.on_settings: Callable[[list[SettingsEntry]], None] | None = None
        self.on_port_error: Callable[[str], None] | None = None

    # ------------------------------------------------------------------ #
    # Properties
    # ------------------------------------------------------------------ #
    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def firmware(self) -> str:
        return self._firmware

    @property
    def status(self) -> MachineStatus:
        return self._status

    @property
    def streamer(self) -> Streamer | None:
        return self._streamer

    @property
    def settings(self) -> list[SettingsEntry]:
        return list(self._settings)

    @property
    def demo_mode(self) -> bool:
        return self._demo

    @staticmethod
    def available_ports() -> list[tuple[str, str]]:
        return list_serial_ports()

    # ------------------------------------------------------------------ #
    # Connection
    # ------------------------------------------------------------------ #
    def connect(self, port: str, baud: int = BAUD_RATE, demo: bool = False) -> None:
        self.disconnect()
        self._demo = demo or port.upper() == "DEMO"
        self._connected = False
        self._firmware = ""
        self._manual_acks = 0
        transport = MockTransport() if self._demo else self._transport_factory(port, baud)
        transport.on_line = self._handle_line
        transport.on_error = self._handle_port_error
        transport.on_closed = self._handle_closed
        transport.on_open = self._handle_open
        self._transport = transport

        streamer = Streamer(
            transport,
            on_progress=self._stream_progress,
            on_state=self._stream_state,
            on_error=self._stream_error,
            on_finished=self._job_finished,
            on_tool_change=self._tool_change,
        )
        self._streamer = streamer
        try:
            transport.open()
        except Exception as exc:  # noqa: BLE001
            self._handle_port_error(str(exc))
            self._handle_closed(str(exc))

    def disconnect(self) -> None:
        self._poll_stop.set()
        transport = self._transport
        self._transport = None
        if self._streamer is not None and self._streamer.is_active:
            self._streamer.abort("disconnected")
        self._streamer = None
        self._connected = False
        self._collecting_settings = False
        self._collecting_info = False
        self._manual_acks = 0
        if transport is not None:
            with suppress(Exception):
                transport.close()
        self._emit_disconnected("Disconnected")

    def _handle_open(self) -> None:
        self._poll_stop.clear()
        self._poll_thread = threading.Thread(
            target=self._poll_loop, name="grbl-status", daemon=True
        )
        self._poll_thread.start()

    def _handle_port_error(self, message: str) -> None:
        if self.on_port_error is not None:
            self.on_port_error(message)

    def _handle_closed(self, reason: str) -> None:
        self._poll_stop.set()
        if self._streamer is not None and self._streamer.is_active:
            self._streamer.abort("disconnected")
        was_connected = self._connected
        self._connected = False
        if was_connected:
            self._emit_disconnected(reason)

    def _emit_disconnected(self, reason: str) -> None:
        if self.on_disconnected is not None:
            self.on_disconnected(reason)

    # ------------------------------------------------------------------ #
    # Polling
    # ------------------------------------------------------------------ #
    def _poll_loop(self) -> None:
        interval = max(0.05, STATUS_INTERVAL_MS / 1000.0)
        while not self._poll_stop.wait(interval):
            transport = self._transport
            if transport is None or not transport.is_open:
                continue
            try:
                transport.send_realtime(RealTime.STATUS.value)
            except TransportError:
                continue

    def request_status(self) -> None:
        self._write_realtime(RealTime.STATUS)

    # ------------------------------------------------------------------ #
    # Incoming data
    # ------------------------------------------------------------------ #
    def _handle_line(self, raw: str) -> None:
        if not raw:
            return
        response = classify(raw)
        self._emit_line(response.kind, raw)

        if response.kind is ResponseKind.BANNER:
            version = banner_version(raw) or ""
            self._manual_acks = 0
            self._firmware = version
            if self._streamer is not None and self._streamer.is_active:
                self._streamer.abort("reset")
            self._connected = True
            if self.on_connected is not None:
                self.on_connected(version)
            return

        if response.kind is ResponseKind.STATUS:
            self._status = parse_status(raw, self._status)
            if self.on_status is not None:
                self.on_status(self._status)
            return

        if response.kind is ResponseKind.OK:
            manual = self._manual_acks > 0
            if manual:
                self._manual_acks -= 1
            if self._collecting_info:
                self._collecting_info = False
            if self._collecting_settings:
                self._collecting_settings = False
                entries = self._settings
                if self.on_settings is not None:
                    self.on_settings(entries)
                return
            if manual:
                return
            if self._streamer is not None:
                self._streamer.handle_ok()
            return

        if response.kind is ResponseKind.ERROR:
            code = response.code or 0
            if self._manual_acks > 0:
                self._manual_acks -= 1
                if self.on_command_error is not None:
                    self.on_command_error(code, error_text(code))
            elif self._streamer is not None and self._streamer.is_active:
                self._streamer.handle_error(code, error_text(code))
            elif self.on_command_error is not None:
                self.on_command_error(code, error_text(code))
            return

        if response.kind is ResponseKind.ALARM:
            code = response.code or 0
            self._manual_acks = 0
            if self._streamer is not None:
                self._streamer.abort("alarm")
            if self.on_alarm is not None:
                self.on_alarm(code, alarm_text(code))
            return

        if response.kind is ResponseKind.SETTING:
            if self._collecting_settings:
                assert response.code is not None
                from .grbl_protocol import SETTING_INFO

                description = SETTING_INFO.get(response.code, ("", ""))[0]
                self._settings.append(SettingsEntry(response.code, response.detail, description))
            return

        if response.kind is ResponseKind.MESSAGE:
            if self.on_message is not None:
                self.on_message(response.detail)
            return

    def _emit_line(self, kind: ResponseKind, text: str) -> None:
        if self.on_line is not None:
            self.on_line(kind, text)

    # ------------------------------------------------------------------ #
    # Streamer callbacks
    # ------------------------------------------------------------------ #
    def _stream_progress(self, sent: int, total: int, line: int) -> None:
        if self.on_progress is not None:
            self.on_progress(sent, total, line)

    def _stream_state(self, state: StreamerState) -> None:
        if self.on_stream_state is not None:
            self.on_stream_state(state)

    def _stream_error(self, line: ProgramLine, code: int, detail: str) -> None:
        if self.on_stream_error is not None:
            self.on_stream_error(line, code, detail)

    def _job_finished(self, reason: str) -> None:
        if self.on_job_finished is not None:
            self.on_job_finished(reason)

    def _tool_change(self, line: ProgramLine) -> None:
        if self.on_tool_change is not None:
            self.on_tool_change(line)

    @property
    def _active_streamer(self) -> Streamer | None:
        streamer = self._streamer
        if streamer is not None and streamer.is_active:
            return streamer
        return None

    # ------------------------------------------------------------------ #
    # Commands
    # ------------------------------------------------------------------ #
    def send_line(self, text: str) -> bool:
        """Send one manual line. Manual lines are not buffer-accounted."""
        if self._active_streamer is not None:
            self._emit_line(ResponseKind.OTHER, "[MSG:Cannot send commands while a job is active]")
            return False
        cleaned = clean_line(text)
        if not cleaned:
            return False
        realtime = {
            "?": RealTime.STATUS,
            "!": RealTime.FEED_HOLD,
            "~": RealTime.CYCLE_START,
        }.get(cleaned)
        if realtime is not None:
            # Real-time bytes never produce an ok; counting one here would
            # make the next job's acknowledgement disappear.
            if self.on_sent is not None:
                self.on_sent(cleaned)
            return self._write_realtime(realtime)
        return self._write_line(cleaned)

    def _write_line(self, text: str) -> bool:
        transport = self._transport
        if transport is None or not transport.is_open:
            if self.on_port_error is not None:
                self.on_port_error("Not connected.")
            return False
        try:
            transport.send_line(text)
        except TransportError as exc:
            self._handle_port_error(str(exc))
            return False
        self._manual_acks += 1
        if self.on_sent is not None:
            self.on_sent(text)
        return True

    def _write_realtime(self, command: RealTime) -> bool:
        transport = self._transport
        if transport is None or not transport.is_open:
            return False
        try:
            transport.send_realtime(command.value)
            return True
        except TransportError:
            return False

    def run_program(self, program: list[ProgramLine], from_line: int | None = None) -> bool:
        if not self._connected or self._streamer is None:
            return False
        if self._status.is_alarm:
            return False
        if self._streamer.is_active:
            return False
        self._streamer.load(program)
        return self._streamer.start(from_line)

    def run_text(self, source: str, from_line: int | None = None) -> bool:
        return self.run_program(parse_program(source), from_line)

    def pause(self) -> None:
        if self._streamer is not None:
            self._streamer.pause()

    def resume(self) -> None:
        if self._streamer is not None:
            self._streamer.resume()

    def stop(self) -> None:
        if self._streamer is not None and self._streamer.is_active:
            self._streamer.stop()
        else:
            self._write_realtime(RealTime.SOFT_RESET)

    def hold(self) -> None:
        self._write_realtime(RealTime.FEED_HOLD)

    def cycle_start(self) -> None:
        self._write_realtime(RealTime.CYCLE_START)

    def reset(self) -> None:
        if self._streamer is not None and self._streamer.is_active:
            self._streamer.stop()
            return
        self._write_realtime(RealTime.SOFT_RESET)

    def jog_cancel(self) -> None:
        self._write_realtime(RealTime.JOG_CANCEL)

    def home(self) -> bool:
        return self._write_line("$H")

    def unlock(self) -> bool:
        return self._write_line("$X")

    def jog(self, axis: str, distance: float, feed: float = 1000.0) -> bool:
        if self._active_streamer is not None:
            return False
        axis = axis.upper()
        if axis not in "XYZ":
            return False
        return self._write_line(f"$J=G91 {axis}{distance:.4f} F{feed:.0f}")

    def zero_axis(self, axis: str, wcs: int = 1) -> bool:
        axis = axis.upper()
        if axis not in "XYZ":
            return False
        return self._write_line(f"G10 L20 P{wcs} {axis}0")

    def goto_zero(self, axes: str = "XY") -> bool:
        axes = "".join(char for char in axes.upper() if char in "XYZ")
        if not axes:
            return False
        return self._write_line("G90 G0 " + " ".join(f"{axis}0" for axis in axes))

    def goto_wcs(self, wcs: int) -> bool:
        if wcs < 1 or wcs > 6:
            return False
        return self._write_line("G54" if wcs == 1 else f"G5{wcs + 3}")

    def set_spindle(self, rpm: float, clockwise: bool = True) -> bool:
        return self._write_line(f"M3 S{rpm:.0f}" if clockwise else f"M4 S{rpm:.0f}")

    def spindle_off(self) -> bool:
        return self._write_line("M5")

    def request_settings(self) -> bool:
        if self._active_streamer is not None:
            return False
        self._settings = []
        self._collecting_settings = True
        if not self._write_line("$$"):
            self._collecting_settings = False
            return False
        return True

    def request_info(self) -> bool:
        self._collecting_info = True
        if not self._write_line("$I"):
            self._collecting_info = False
            return False
        return True

    def set_setting(self, number: int, value: str) -> bool:
        return self._write_line(f"${number}={value}")

    def set_check_mode(self, enabled: bool) -> bool:
        """Toggle GRBL check mode ($C). Only valid while idle."""
        _ = enabled
        return self._write_line("$C")

    def probe_z(
        self,
        plate_thickness: float,
        feed: float = 50.0,
        travel: float = 30.0,
        retract: float = 5.0,
    ) -> bool:
        """Probe down, set Z work zero to the plate thickness, and retract.

        The commands are queued together; they total well under the 127-byte
        RX buffer and only run while the machine is idle.
        """
        if not self._connected or self._status.is_alarm:
            return False
        steps = [
            f"G91 G38.2 Z-{abs(travel):.3f} F{abs(feed):.0f}",
            f"G10 L20 P1 Z{plate_thickness:.3f}",
            f"G91 G0 Z{abs(retract):.3f}",
            "G90",
        ]
        sent = 0
        for step in steps:
            if not self._write_line(step):
                break
            sent += 1
        return sent == len(steps)

    def set_override(self, kind: str, percent: int) -> None:
        commands = self._override_commands(kind, percent)
        for command in commands:
            self._write_realtime(command)

    @staticmethod
    def _override_commands(kind: str, percent: int) -> list[RealTime]:
        if kind == "feed":
            return MachineController._steps(
                percent,
                100,
                RealTime.FEED_OVERRIDE_RESET,
                RealTime.FEED_OVERRIDE_PLUS_10,
                RealTime.FEED_OVERRIDE_MINUS_10,
                RealTime.FEED_OVERRIDE_PLUS_1,
                RealTime.FEED_OVERRIDE_MINUS_1,
            )
        if kind == "spindle":
            return MachineController._steps(
                percent,
                100,
                RealTime.SPINDLE_OVERRIDE_RESET,
                RealTime.SPINDLE_OVERRIDE_PLUS_10,
                RealTime.SPINDLE_OVERRIDE_MINUS_10,
                RealTime.SPINDLE_OVERRIDE_PLUS_1,
                RealTime.SPINDLE_OVERRIDE_MINUS_1,
            )
        rapid = {
            25: RealTime.RAPID_OVERRIDE_25,
            50: RealTime.RAPID_OVERRIDE_50,
            100: RealTime.RAPID_OVERRIDE_100,
        }
        return [rapid.get(percent, RealTime.RAPID_OVERRIDE_100)]

    @staticmethod
    def _steps(
        percent: int,
        baseline: int,
        reset: RealTime,
        plus_ten: RealTime,
        minus_ten: RealTime,
        plus_one: RealTime,
        minus_one: RealTime,
    ) -> list[RealTime]:
        delta = max(10, min(200, percent)) - baseline
        commands = [reset]
        tens, ones = divmod(abs(delta), 10)
        commands.extend([plus_ten if delta > 0 else minus_ten] * tens)
        commands.extend([plus_one if delta > 0 else minus_one] * ones)
        return commands

    def soft_reset(self) -> None:
        self._write_realtime(RealTime.SOFT_RESET)

    def skip_error(self) -> None:
        if self._streamer is not None:
            self._streamer.skip_errored_line()

    def complete_tool_change(self) -> None:
        if self._streamer is not None:
            self._streamer.complete_tool_change()

    def cancel_tool_change(self) -> None:
        if self._streamer is not None:
            self._streamer.cancel_tool_change()
