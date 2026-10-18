"""Parser for GRBL ``<...>`` status reports."""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass, field, replace

from .grbl_protocol import state_family

Triple = tuple[float, float, float]


def _triple(value: str) -> Triple | None:
    parts = value.split(",")
    if len(parts) != 3:
        return None
    try:
        return (float(parts[0]), float(parts[1]), float(parts[2]))
    except ValueError:
        return None


def _pair(value: str) -> tuple[float, float] | None:
    parts = value.split(",")
    if len(parts) != 2:
        return None
    try:
        return (float(parts[0]), float(parts[1]))
    except ValueError:
        return None


@dataclass
class MachineStatus:
    """Latest known machine state.

    ``wco`` is tracked across reports because GRBL only includes ``WCO:``
    intermittently; ``wpos`` can therefore still be derived when only
    ``MPos`` arrives.
    """

    state: str = "Unknown"
    substate: str | None = None
    mpos: Triple | None = None
    wpos: Triple | None = None
    wco: Triple | None = None
    feed: float | None = None
    spindle: float | None = None
    buffer: tuple[int, int] | None = None
    overrides: tuple[int, int, int] | None = None
    pins: str = ""
    raw: str = ""
    extra: dict[str, str] = field(default_factory=dict)

    @property
    def family(self) -> str:
        return state_family(self.state)

    @property
    def is_idle(self) -> bool:
        return self.family == "idle"

    @property
    def is_alarm(self) -> bool:
        return self.family == "alarm"

    @property
    def buffer_fill(self) -> int:
        return self.buffer[0] if self.buffer else 0

    @property
    def buffer_size(self) -> int:
        return self.buffer[1] if self.buffer else 0

    def copy(self) -> MachineStatus:
        return replace(self, extra=dict(self.extra))


def parse_status(raw: str, previous: MachineStatus | None = None) -> MachineStatus:
    """Parse one ``<...>`` report.

    Unknown fields are preserved in ``extra`` rather than rejected, so a
    firmware extension never breaks the UI.
    """
    text = raw.strip()
    if text.startswith("<") and text.endswith(">"):
        text = text[1:-1]

    status = MachineStatus(raw=raw)
    if previous is not None:
        status.wco = previous.wco

    for index, chunk in enumerate(text.split("|")):
        if not chunk:
            continue
        if index == 0:
            state, _, substate = chunk.partition(":")
            status.state = state
            status.substate = substate or None
            continue

        key, sep, value = chunk.partition(":")
        if not sep:
            status.extra[chunk] = ""
            continue

        if key == "MPos":
            status.mpos = _triple(value)
        elif key == "WPos":
            status.wpos = _triple(value)
        elif key == "WCO":
            status.wco = _triple(value)
        elif key == "FS":
            pair = _pair(value)
            if pair:
                status.feed, status.spindle = pair
        elif key == "F":
            with suppress(ValueError):
                status.feed = float(value)
        elif key == "Bf":
            parts = value.split(",")
            if len(parts) == 2:
                with suppress(ValueError):
                    status.buffer = (int(parts[0]), int(parts[1]))
        elif key == "Ov":
            parts = value.split(",")
            if len(parts) == 3:
                with suppress(ValueError):
                    status.overrides = (int(parts[0]), int(parts[1]), int(parts[2]))
        elif key == "Pn":
            status.pins = value
        else:
            status.extra[key] = value

    # GRBL omits WCO while the offset is zero and only sends it intermittently
    # afterwards. Treat a missing offset as zero when we have no history.
    if status.mpos is not None and status.wpos is None and status.wco is None:
        status.wco = (0.0, 0.0, 0.0)

    # Derive the missing pair using the current work-coordinate offset.
    if status.mpos is not None and status.wco is not None:
        status.wpos = tuple(a - b for a, b in zip(status.mpos, status.wco, strict=True))  # type: ignore[assignment]
    elif status.wpos is not None and status.wco is not None and status.mpos is None:
        status.mpos = tuple(a + b for a, b in zip(status.wpos, status.wco, strict=True))  # type: ignore[assignment]
    elif status.mpos is not None and status.wpos is not None and status.wco is None:
        status.wco = tuple(a - b for a, b in zip(status.mpos, status.wpos, strict=True))  # type: ignore[assignment]

    return status
