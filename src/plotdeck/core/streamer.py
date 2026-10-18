"""Character-counting G-code streamer.

GRBL has a 127-byte RX buffer and acknowledges every line with ``ok`` or
``error:N``. This class only sends a line if it still fits, which keeps the
controller from overrunning the machine.
"""

from __future__ import annotations

import threading
from collections import deque
from collections.abc import Callable, Iterable
from contextlib import suppress
from enum import Enum

from .gcode_parser import ProgramLine
from .grbl_protocol import RX_BUFFER_SIZE, RealTime
from .transport import Transport, TransportError


class StreamerState(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    STOPPED = "stopped"
    ERROR = "error"


class Streamer:
    """Send a parsed program to GRBL without overflowing the planner buffer."""

    def __init__(
        self,
        transport: Transport,
        *,
        on_progress: Callable[[int, int, int], None] | None = None,
        on_state: Callable[[StreamerState], None] | None = None,
        on_error: Callable[[ProgramLine, int, str], None] | None = None,
        on_finished: Callable[[str], None] | None = None,
        on_tool_change: Callable[[ProgramLine], None] | None = None,
    ) -> None:
        self.transport = transport
        self.on_progress = on_progress
        self.on_state = on_state
        self.on_error = on_error
        self.on_finished = on_finished
        self.on_tool_change = on_tool_change

        self._program: list[ProgramLine] = []
        self._index = 0
        self._sent = 0
        self._pending: deque[int] = deque()
        self._pending_bytes = 0
        self._inflight: deque[ProgramLine] = deque()
        self._state = StreamerState.IDLE
        self._error: tuple[ProgramLine, int] | None = None
        self._tool_change: ProgramLine | None = None
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ #
    # State
    # ------------------------------------------------------------------ #
    @property
    def state(self) -> StreamerState:
        return self._state

    @property
    def program(self) -> list[ProgramLine]:
        return list(self._program)

    @property
    def total(self) -> int:
        return len(self._program)

    @property
    def sent(self) -> int:
        return self._sent

    @property
    def current_line(self) -> int:
        if self._inflight:
            return self._inflight[0].source_line
        return self._program[self._index].source_line if self._index < len(self._program) else 0

    @property
    def error(self) -> tuple[ProgramLine, int] | None:
        return self._error

    @property
    def awaiting_tool_change(self) -> ProgramLine | None:
        return self._tool_change

    @property
    def is_active(self) -> bool:
        return self._state in (StreamerState.RUNNING, StreamerState.PAUSED)

    @property
    def pending_bytes(self) -> int:
        return self._pending_bytes

    # ------------------------------------------------------------------ #
    # Job control
    # ------------------------------------------------------------------ #
    def load(self, program: Iterable[ProgramLine]) -> None:
        with self._lock:
            if self._state in (StreamerState.RUNNING, StreamerState.PAUSED):
                raise RuntimeError("Cannot load a new program while a job is active.")
            self._program = list(program)
            self._reset_counters()

    def _reset_counters(self) -> None:
        self._index = 0
        self._sent = 0
        self._pending.clear()
        self._pending_bytes = 0
        self._inflight.clear()
        self._error = None
        self._tool_change = None
        self._state = StreamerState.IDLE

    def start(self, from_source_line: int | None = None) -> bool:
        with self._lock:
            if not self._program:
                return False
            if self._state in (StreamerState.RUNNING, StreamerState.PAUSED):
                return False
            self._reset_counters()
            if from_source_line is not None:
                self._index = self._index_for_line(from_source_line)
                self._sent = self._index
            self._state = StreamerState.RUNNING
            self._emit_state()
            self._emit_progress()
            self._pump()
            return True

    def _index_for_line(self, source_line: int) -> int:
        for index, line in enumerate(self._program):
            if line.source_line >= source_line:
                return index
        return len(self._program)

    def pause(self) -> None:
        with self._lock:
            if self._state is not StreamerState.RUNNING:
                return
            self._send_realtime(RealTime.FEED_HOLD)
            self._state = StreamerState.PAUSED
            self._emit_state()

    def resume(self) -> None:
        with self._lock:
            if self._state is not StreamerState.PAUSED:
                return
            if self._error is not None or self._tool_change is not None:
                return
            self._send_realtime(RealTime.CYCLE_START)
            self._state = StreamerState.RUNNING
            self._emit_state()
            self._pump()

    def stop(self, soft_reset: bool = True) -> None:
        with self._lock:
            if self._state is StreamerState.IDLE and not self._program:
                return
            if self.is_active:
                self._send_realtime(RealTime.FEED_HOLD)
                if soft_reset:
                    self._send_realtime(RealTime.SOFT_RESET)
            self._pending.clear()
            self._pending_bytes = 0
            self._inflight.clear()
            self._error = None
            self._tool_change = None
            was_active = self.is_active
            self._state = StreamerState.STOPPED
            self._emit_state()
            if was_active:
                self._emit_finished("stopped")

    def abort(self, reason: str = "alarm") -> None:
        """Halt without sending bytes (used for alarms and lost connections)."""
        with self._lock:
            was_active = self.is_active
            self._pending.clear()
            self._pending_bytes = 0
            self._inflight.clear()
            self._tool_change = None
            self._state = StreamerState.ERROR
            self._emit_state()
            if was_active:
                self._emit_finished(reason)

    # ------------------------------------------------------------------ #
    # GRBL responses
    # ------------------------------------------------------------------ #
    def handle_ok(self) -> None:
        with self._lock:
            if not self._inflight:
                return  # a manual command or a command sent outside the job
            self._acknowledge()
            if self._state is StreamerState.RUNNING:
                self._pump()
            elif self._state is StreamerState.PAUSED and not self._inflight:
                pass
            self._emit_progress()

    def handle_error(self, code: int, detail: str = "") -> None:
        with self._lock:
            if not self._inflight:
                return
            line = self._inflight.popleft()
            self._pop_pending()
            self._error = (line, code)
            self._state = StreamerState.PAUSED
            # Stop motion promptly rather than letting the planner run dry.
            self._send_realtime(RealTime.FEED_HOLD)
            self._emit_state()
            self._emit_progress()
            if self.on_error is not None:
                self.on_error(line, code, detail)

    def skip_errored_line(self) -> None:
        """Continue the job after the user reviewed an error."""
        with self._lock:
            if self._error is None:
                return
            self._error = None
            self._state = StreamerState.RUNNING
            self._send_realtime(RealTime.CYCLE_START)
            self._emit_state()
            self._pump()

    def complete_tool_change(self) -> None:
        with self._lock:
            if self._tool_change is None:
                return
            self._tool_change = None
            if self._state is StreamerState.PAUSED:
                self._send_realtime(RealTime.CYCLE_START)
                self._state = StreamerState.RUNNING
                self._emit_state()
                self._pump()

    def cancel_tool_change(self) -> None:
        with self._lock:
            if self._tool_change is None:
                return
            self._tool_change = None
            self.stop(soft_reset=False)

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #
    def _pump(self) -> None:
        while self._state is StreamerState.RUNNING and self._index < len(self._program):
            line = self._program[self._index]

            if line.is_tool_change:
                if self._pending:
                    return  # let the planner drain before pausing for the tool change
                self._tool_change = line
                self._index += 1
                self._send_realtime(RealTime.FEED_HOLD)
                self._state = StreamerState.PAUSED
                self._emit_state()
                if self.on_tool_change is not None:
                    self.on_tool_change(line)
                return

            need = len(line.text.encode("utf-8")) + 1
            if self._pending_bytes + need > RX_BUFFER_SIZE:
                return  # buffer full; wait for an ok

            try:
                self.transport.send_line(line.text)
            except TransportError as exc:
                self._state = StreamerState.ERROR
                self._emit_state()
                if self.on_error is not None:
                    self.on_error(line, -1, str(exc))
                self._emit_finished("error")
                return

            self._pending.append(need)
            self._pending_bytes += need
            self._inflight.append(line)
            self._index += 1
            self._emit_progress()

        if (
            self._state is StreamerState.RUNNING
            and self._index >= len(self._program)
            and not self._pending
        ):
            self._state = StreamerState.COMPLETED
            self._emit_state()
            self._emit_finished("completed")

    def _acknowledge(self) -> None:
        if not self._inflight:
            return
        self._inflight.popleft()
        self._pop_pending()
        self._sent += 1

    def _pop_pending(self) -> None:
        if self._pending:
            self._pending_bytes -= self._pending.popleft()
            if self._pending_bytes < 0:
                self._pending_bytes = 0

    def _send_realtime(self, byte: RealTime) -> None:
        with suppress(TransportError):
            self.transport.send_realtime(byte.value)

    def _emit_state(self) -> None:
        if self.on_state is not None:
            self.on_state(self._state)

    def _emit_progress(self) -> None:
        if self.on_progress is not None:
            self.on_progress(self._sent, len(self._program), self.current_line)

    def _emit_finished(self, reason: str) -> None:
        if self.on_finished is not None:
            self.on_finished(reason)
