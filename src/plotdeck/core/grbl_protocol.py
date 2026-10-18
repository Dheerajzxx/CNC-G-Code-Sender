"""GRBL 1.1 protocol constants, response classification and lookup tables.

Pure Python; no Qt or serial imports. Everything the rest of the application
needs to know about the wire protocol lives here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

# --------------------------------------------------------------------------- #
# Wire constants
# --------------------------------------------------------------------------- #
BAUD_RATE = 115200
RX_BUFFER_SIZE = 127  # usable bytes, not 128
MAX_LINE_LENGTH = 80

STATUS_INTERVAL_MS = 200
UNO_RESET_DELAY_S = 2.0


class RealTime(bytes, Enum):
    """Single-byte commands that bypass the line queue and never get an ``ok``."""

    STATUS = b"?"
    FEED_HOLD = b"!"
    CYCLE_START = b"~"
    SOFT_RESET = b"\x18"
    SAFETY_DOOR = b"\x84"
    JOG_CANCEL = b"\x85"

    FEED_OVERRIDE_RESET = b"\x90"
    FEED_OVERRIDE_PLUS_10 = b"\x91"
    FEED_OVERRIDE_MINUS_10 = b"\x92"
    FEED_OVERRIDE_PLUS_1 = b"\x93"
    FEED_OVERRIDE_MINUS_1 = b"\x94"

    RAPID_OVERRIDE_100 = b"\x95"
    RAPID_OVERRIDE_50 = b"\x96"
    RAPID_OVERRIDE_25 = b"\x97"

    SPINDLE_OVERRIDE_RESET = b"\x99"
    SPINDLE_OVERRIDE_PLUS_10 = b"\x9a"
    SPINDLE_OVERRIDE_MINUS_10 = b"\x9b"
    SPINDLE_OVERRIDE_PLUS_1 = b"\x9c"
    SPINDLE_OVERRIDE_MINUS_1 = b"\x9d"
    SPINDLE_STOP = b"\x9e"


class ResponseKind(str, Enum):
    OK = "ok"
    ERROR = "error"
    ALARM = "alarm"
    STATUS = "status"
    MESSAGE = "message"
    BANNER = "banner"
    SETTING = "setting"
    OTHER = "other"


@dataclass(frozen=True)
class Response:
    kind: ResponseKind
    text: str
    code: int | None = None
    detail: str = ""

    @property
    def is_terminal(self) -> bool:
        """True for responses that acknowledge exactly one queued line."""
        return self.kind in (ResponseKind.OK, ResponseKind.ERROR)


_BANNER_RE = re.compile(r"^Grbl\s+([0-9]+\.[0-9]+[a-zA-Z]?)\b")
_ERROR_RE = re.compile(r"^error:(\d+)")
_ALARM_RE = re.compile(r"^ALARM:(\d+)")
_SETTING_RE = re.compile(r"^\$(\d+)=([-0-9.]+)")


def classify(line: str) -> Response:
    """Turn one raw line from GRBL into a :class:`Response`."""
    text = line.strip()
    if not text:
        return Response(ResponseKind.OTHER, line)

    if text == "ok":
        return Response(ResponseKind.OK, text)

    match = _ERROR_RE.match(text)
    if match:
        code = int(match.group(1))
        return Response(ResponseKind.ERROR, text, code, error_text(code))

    match = _ALARM_RE.match(text)
    if match:
        code = int(match.group(1))
        return Response(ResponseKind.ALARM, text, code, alarm_text(code))

    if text.startswith("<") and text.endswith(">"):
        return Response(ResponseKind.STATUS, text)

    if text.startswith("[") and text.endswith("]"):
        return Response(ResponseKind.MESSAGE, text, detail=message_text(text))

    match = _BANNER_RE.match(text)
    if match:
        return Response(ResponseKind.BANNER, text, detail=match.group(1))

    match = _SETTING_RE.match(text)
    if match:
        return Response(ResponseKind.SETTING, text, int(match.group(1)), match.group(2))

    return Response(ResponseKind.OTHER, text)


def message_text(raw: str) -> str:
    """Extract the human readable payload from a ``[TYPE:...]`` message."""
    body = raw.strip()
    if body.startswith("["):
        body = body[1:]
    if body.endswith("]"):
        body = body[:-1]
    if ":" in body:
        tag, _, value = body.partition(":")
        if tag in {"MSG", "GC", "PRB", "HLP", "OPT", "VER", "echo"}:
            return value
    return body


def banner_version(raw: str) -> str | None:
    """Return the firmware version from a welcome banner, if it is one."""
    match = _BANNER_RE.match(raw.strip())
    return match.group(1) if match else None


# --------------------------------------------------------------------------- #
# Error / alarm lookup tables (GRBL 1.1)
# --------------------------------------------------------------------------- #
ERROR_MESSAGES: dict[int, str] = {
    1: "G-code word is missing its letter.",
    2: "Numeric value is missing or malformed.",
    3: "Unsupported or unknown '$' system command.",
    4: "Negative value received where a positive value is required.",
    5: "Homing cycle is not enabled in settings ($22).",
    6: "Step pulse time must be greater than 3 microseconds.",
    7: "EEPROM read failed; settings restored to defaults. Reset required.",
    8: "'$' command can only be used while the machine is Idle.",
    9: "G-code commands are locked out during an alarm or jog.",
    10: "Soft limits require homing to be enabled ($22).",
    11: "Maximum characters per line exceeded (80).",
    12: "Value exceeds the maximum allowed (compile-time option).",
    13: "Value exceeds the maximum allowed (compile-time option).",
    14: "Value exceeds the maximum allowed (compile-time option).",
    15: "Value exceeds the maximum allowed (compile-time option).",
    16: "Value exceeds the maximum allowed (compile-time option).",
    17: "Value exceeds the maximum allowed (compile-time option).",
    18: "Value exceeds the maximum allowed (compile-time option).",
    19: "Value exceeds the maximum allowed (compile-time option).",
    20: "Unsupported or invalid G-code command in block.",
    21: "More than one G-code command from the same modal group in block.",
    22: "Feed rate has not been set or is undefined.",
    23: "G-code command requires an integer value.",
    24: "Two commands that require the same axis words were detected in block.",
    25: "A G-code word was repeated in the block.",
    26: "A G-code command is missing required axis or parameter words.",
    27: "Numeric value is out of range.",
    28: "Command value is not valid for the current state.",
    29: "Unsupported coordinate system or axis word.",
    30: "Command requires a valid value that was not supplied.",
    31: "Command is not allowed in the current machine state.",
    32: "Command is not allowed in the current machine state (laser mode).",
    33: "Motion command target is invalid.",
    34: "Arc radius value is invalid.",
    35: "Arc endpoint is invalid for the defined radius.",
    36: "Feed rate is required for this command.",
    37: "Command is not allowed in the current machine state.",
}

ALARM_MESSAGES: dict[int, str] = {
    1: "Hard limit triggered. Position is likely lost - re-home before continuing.",
    2: "Soft limit exceeded. Target is outside machine travel; unlock to recover.",
    3: "Reset while in motion. Position is likely lost - re-home before continuing.",
    4: "Probe failed: probe is not in the expected initial state.",
    5: "Probe failed: no contact with the workpiece within the travel distance.",
    6: "Homing failed: pull-off failed to clear the limit switch.",
    7: "Homing failed: limit switch not found within the search distance.",
    8: "Homing failed: limit switch triggered during the search.",
    9: "Homing failed: could not find the limit switch.",
    10: "Homing failed: could not clear the limit switch.",
}


def error_text(code: int | None) -> str:
    if code is None:
        return "Unknown error."
    return ERROR_MESSAGES.get(code, f"Unknown error {code}.")


def alarm_text(code: int | None) -> str:
    if code is None:
        return "Unknown alarm."
    return ALARM_MESSAGES.get(code, f"Unknown alarm {code}.")


# --------------------------------------------------------------------------- #
# Machine states
# --------------------------------------------------------------------------- #
IDLE_STATES = {"Idle"}
RUN_STATES = {"Run", "Jog", "Home", "Check", "Sleep"}
HOLD_STATES = {
    "Hold",
    "Hold:0",
    "Hold:1",
    "Door",
    "Door:0",
    "Door:1",
    "Door:2",
    "Door:3",
}
ALARM_STATES = {"Alarm"}


def state_family(state: str) -> str:
    """Collapse a GRBL state into one of: idle, run, hold, alarm, offline."""
    if state in ALARM_STATES:
        return "alarm"
    if state in IDLE_STATES:
        return "idle"
    if state in HOLD_STATES:
        return "hold"
    if state in RUN_STATES:
        return "run"
    return "offline"


# --------------------------------------------------------------------------- #
# GRBL settings metadata (for the settings editor / limits)
# --------------------------------------------------------------------------- #
SETTING_INFO: dict[int, tuple[str, str]] = {
    0: ("Step pulse, microseconds", "10"),
    1: ("Step idle delay, milliseconds", "25"),
    2: ("Step port invert, mask", "0"),
    3: ("Direction port invert, mask", "0"),
    4: ("Step enable invert, bool", "0"),
    5: ("Limit pins invert, bool", "0"),
    6: ("Probe pin invert, bool", "0"),
    10: ("Status report, mask", "3"),
    11: ("Junction deviation, mm", "0.010"),
    12: ("Arc tolerance, mm", "0.002"),
    13: ("Report inches, bool", "0"),
    20: ("Soft limits, bool", "0"),
    21: ("Hard limits, bool", "0"),
    22: ("Homing cycle, bool", "1"),
    23: ("Homing dir invert, mask", "0"),
    24: ("Homing feed, mm/min", "25.000"),
    25: ("Homing seek, mm/min", "500.000"),
    26: ("Homing debounce, milliseconds", "250"),
    27: ("Homing pull-off, mm", "1.000"),
    30: ("Max spindle speed, RPM", "1000"),
    31: ("Min spindle speed, RPM", "0"),
    32: ("Laser mode, bool", "0"),
    100: ("X steps/mm", "250.000"),
    101: ("Y steps/mm", "250.000"),
    102: ("Z steps/mm", "250.000"),
    110: ("X max rate, mm/min", "500.000"),
    111: ("Y max rate, mm/min", "500.000"),
    112: ("Z max rate, mm/min", "500.000"),
    120: ("X acceleration, mm/sec^2", "10.000"),
    121: ("Y acceleration, mm/sec^2", "10.000"),
    122: ("Z acceleration, mm/sec^2", "10.000"),
    130: ("X max travel, mm", "200.000"),
    131: ("Y max travel, mm", "200.000"),
    132: ("Z max travel, mm", "200.000"),
}

LIMIT_SETTINGS = (130, 131, 132)
