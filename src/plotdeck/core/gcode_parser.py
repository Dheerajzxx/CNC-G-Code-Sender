"""G-code tokenizer, cleaner and toolpath extractor.

The parser is deliberately small: PlotDeck is a sender, not a CAM package, so
it only needs enough modal understanding to draw an accurate preview and
estimate job time.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

MAX_LINE_LENGTH = 80
RAPID_RATE_MM_MIN = 3000.0
ARC_SEGMENTS = 48

WORD_RE = re.compile(r"([A-Z])\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+))")
M6_RE = re.compile(r"(?:^|\s)M0?6(?:\D|$)")
TOOL_RE = re.compile(r"(?:^|\s)T(\d+)(?:\D|$)")


@dataclass(frozen=True)
class ProgramLine:
    """A single executable line, with its original 1-based line number."""

    text: str
    source_line: int
    length: int = 0

    def __post_init__(self) -> None:
        if not self.length:
            object.__setattr__(self, "length", len(self.text))

    @property
    def too_long(self) -> bool:
        return self.length > MAX_LINE_LENGTH

    @property
    def is_tool_change(self) -> bool:
        if M6_RE.search(self.text):
            return True
        # A standalone tool-select line (T2 with no motion) is also a change.
        if TOOL_RE.search(self.text):
            words = WORD_RE.findall(self.text)
            return bool(words) and all(letter in {"T", "N"} for letter, _ in words)
        return False

    @property
    def tool_number(self) -> int | None:
        match = TOOL_RE.search(self.text)
        return int(match.group(1)) if match else None


def strip_comments(line: str) -> str:
    """Remove ``;`` and ``(...)`` comments, respecting commented semicolons."""
    out: list[str] = []
    depth = 0
    for char in line:
        if depth:
            if char == ")":
                depth -= 1
            continue
        if char == "(":
            depth += 1
            continue
        if char == ";":
            break
        out.append(char)
    return "".join(out)


def clean_line(line: str) -> str:
    """Clean a source line into something GRBL will accept."""
    text = strip_comments(line).strip()
    if not text or text.startswith("%"):
        return ""
    text = re.sub(r"\s+", " ", text.upper())
    return text


def tokenize(text: str) -> list[tuple[str, float]]:
    """Split a cleaned line into ``(letter, value)`` words."""
    return [(match.group(1), float(match.group(2))) for match in WORD_RE.finditer(text)]


def parse_program(source: str) -> list[ProgramLine]:
    """Clean *source* and return the executable lines with source numbers."""
    program: list[ProgramLine] = []
    for index, raw in enumerate(source.splitlines(), start=1):
        text = clean_line(raw)
        if text:
            program.append(ProgramLine(text=text, source_line=index))
    return program


def line_count(source: str) -> int:
    return len(source.splitlines())


# --------------------------------------------------------------------------- #
# Toolpath model
# --------------------------------------------------------------------------- #
Point = tuple[float, float, float]


@dataclass
class Segment:
    kind: str  # "rapid" | "feed" | "arc_cw" | "arc_ccw"
    start: Point
    end: Point
    source_line: int
    points: list[Point] = field(default_factory=list)

    @property
    def length(self) -> float:
        if len(self.points) > 1:
            return sum(
                math.dist(self.points[i], self.points[i + 1]) for i in range(len(self.points) - 1)
            )
        return math.dist(self.start, self.end)


@dataclass
class Toolpath:
    segments: list[Segment] = field(default_factory=list)
    bounds: tuple[Point, Point] | None = None
    estimated_seconds: float = 0.0
    tools: list[int] = field(default_factory=list)
    min_z: float | None = None
    max_z: float | None = None
    warnings: list[str] = field(default_factory=list)
    unsupported: set[str] = field(default_factory=set)

    @property
    def total_length(self) -> float:
        return sum(segment.length for segment in self.segments)


class _Modal:
    def __init__(self) -> None:
        self.units = 1.0  # multiplier to millimetres
        self.absolute = True
        self.motion = 0
        self.plane = "XY"
        self.position: Point = (0.0, 0.0, 0.0)
        self.feed: float | None = None


def _plane_axes(plane: str) -> tuple[int, int, int]:
    if plane == "ZX":
        return 2, 0, 1
    if plane == "YZ":
        return 1, 2, 0
    return 0, 1, 2


def _arc_points(
    start: Point,
    end: Point,
    center: Point,
    clockwise: bool,
    plane: str,
) -> list[Point]:
    u, v, w = _plane_axes(plane)
    su, sv = start[u], start[v]
    eu, ev = end[u], end[v]
    cu, cv = center[u], center[v]

    radius = math.hypot(su - cu, sv - cv)
    start_angle = math.atan2(sv - cv, su - cu)
    end_angle = math.atan2(ev - cv, eu - cu)

    if clockwise:
        while end_angle >= start_angle:
            end_angle -= 2 * math.pi
    else:
        while end_angle <= start_angle:
            end_angle += 2 * math.pi

    sweep = end_angle - start_angle
    count = max(4, min(ARC_SEGMENTS, int(abs(sweep) / (math.pi / 24)) + 1))

    points: list[Point] = []
    for step in range(count + 1):
        fraction = step / count
        angle = start_angle + sweep * fraction
        point = list(start)
        point[u] = cu + radius * math.cos(angle)
        point[v] = cv + radius * math.sin(angle)
        point[w] = start[w] + (end[w] - start[w]) * fraction
        points.append((point[0], point[1], point[2]))
    points[-1] = end
    return points


def _arc_points_from_radius(
    start: Point, end: Point, radius: float, clockwise: bool, plane: str
) -> list[Point] | None:
    u, v, _ = _plane_axes(plane)
    chord = math.dist((start[u], start[v]), (end[u], end[v]))
    if chord == 0 or chord > 2 * abs(radius):
        return None
    half = chord / 2
    height = math.sqrt(max(0.0, radius * radius - half * half))
    mx = (start[u] + end[u]) / 2
    my = (start[v] + end[v]) / 2
    dx = end[u] - start[u]
    dy = end[v] - start[v]
    length = math.hypot(dx, dy) or 1.0
    nx, ny = -dy / length, dx / length

    # Positive R selects the minor arc; negative selects the major arc.
    minor = radius >= 0
    candidates = [(mx + nx * height, my + ny * height), (mx - nx * height, my - ny * height)]
    center = candidates[0]
    for candidate in candidates:
        cangle = math.atan2(start[v] - candidate[1], start[u] - candidate[0])
        eangle = math.atan2(end[v] - candidate[1], end[u] - candidate[0])
        sweep = eangle - cangle
        sweep = -(sweep % (2 * math.pi)) if clockwise else sweep % (2 * math.pi)
        if (abs(sweep) <= math.pi) == minor:
            center = candidate
            break
    cx, cy = center
    full_center = list(start)
    full_center[u] = cx
    full_center[v] = cy
    return _arc_points(start, end, tuple(full_center), clockwise, plane)  # type: ignore[arg-type]


def _segment_length(points: list[Point]) -> float:
    return sum(math.dist(points[i], points[i + 1]) for i in range(len(points) - 1))


def build_toolpath(program: list[ProgramLine], limits: Point | None = None) -> Toolpath:
    """Extract drawable segments and job statistics from *program*."""
    model = _Modal()
    path = Toolpath()
    tools: set[int] = set()
    seen_z: list[float] = []

    for line in program:
        if line.is_tool_change:
            tool = line.tool_number
            if tool is not None:
                tools.add(tool)
            continue

        if line.too_long:
            path.warnings.append(f"Line {line.source_line} is longer than 80 characters.")

        words = tokenize(line.text)
        values: dict[str, float] = {}
        for letter, value in words:
            values[letter] = value

        # Update modal state before motion. A block can carry several G words
        # (for example "G20 G90"), so process all of them in order.
        g_codes = [value for letter, value in words if letter == "G"]
        for code in g_codes:
            if code == 20:
                model.units = 25.4
            elif code == 21:
                model.units = 1.0
            elif code == 90:
                model.absolute = True
            elif code == 91:
                model.absolute = False
            elif code in (0, 1, 2, 3):
                model.motion = int(code)
            elif code == 17:
                model.plane = "XY"
            elif code == 18:
                model.plane = "ZX"
            elif code == 19:
                model.plane = "YZ"
        if "F" in values:
            model.feed = values["F"] * model.units

        if any(code in (4, 10, 28, 30, 53, 92) for code in g_codes) and not any(
            code in (0, 1, 2, 3) for code in g_codes
        ):
            # Dwells and coordinate-setting commands do not produce a segment.
            continue
        if model.motion not in (0, 1, 2, 3):
            continue
        if not any(axis in values for axis in ("X", "Y", "Z", "I", "J")):
            continue

        target = list(model.position)
        for index, axis in enumerate(("X", "Y", "Z")):
            if axis in values:
                value = values[axis] * model.units
                target[index] = value if model.absolute else model.position[index] + value
        end = (target[0], target[1], target[2])
        start = model.position
        points: list[Point] | None

        if model.motion == 0:
            kind = "rapid"
            points = [start, end]
        elif model.motion == 1:
            kind = "feed"
            points = [start, end]
        else:
            clockwise = model.motion == 2
            kind = "arc_cw" if clockwise else "arc_ccw"
            plane = model.plane
            u, v, _ = _plane_axes(plane)
            center = list(start)
            center_letters = {"XY": ("I", "J"), "ZX": ("K", "I"), "YZ": ("J", "K")}[plane]
            u_word, v_word = center_letters
            if u_word in values or v_word in values:
                center[u] = start[u] + values.get(u_word, 0.0) * model.units
                center[v] = start[v] + values.get(v_word, 0.0) * model.units
                points = _arc_points(start, end, tuple(center), clockwise, plane)  # type: ignore[arg-type]
            elif "R" in values:
                points = _arc_points_from_radius(
                    start, end, values["R"] * model.units, clockwise, plane
                )
            else:
                path.unsupported.add("arc without I/J/R")
                points = None
            if points is None:
                kind = "feed"
                points = [start, end]

        segment = Segment(
            kind=kind,
            start=start,
            end=end,
            source_line=line.source_line,
            points=points,
        )
        path.segments.append(segment)

        rate = RAPID_RATE_MM_MIN if kind == "rapid" else (model.feed or 0.0)
        if rate > 0:
            path.estimated_seconds += segment.length / rate * 60.0

        model.position = end
        seen_z.extend((start[2], end[2]))

    if path.segments:
        starts = [segment.start for segment in path.segments]
        ends = [segment.end for segment in path.segments]
        all_points = starts + ends
        low = tuple(min(point[i] for point in all_points) for i in range(3))
        high = tuple(max(point[i] for point in all_points) for i in range(3))
        path.bounds = (low, high)  # type: ignore[assignment]
        if limits and any(high[i] > limits[i] for i in range(3)):
            path.warnings.append("Toolpath extends beyond the configured machine travel.")
    if seen_z:
        path.min_z = min(seen_z)
        path.max_z = max(seen_z)
    path.tools = sorted(tools)
    return path


def transform_lines(
    lines: list[ProgramLine],
    dx: float = 0.0,
    dy: float = 0.0,
    dz: float = 0.0,
    scale: float = 1.0,
    rotate: float = 0.0,
) -> list[str]:
    """Offset/scale/rotate axis words, returning new text lines."""
    if rotate:
        cos_a = math.cos(math.radians(rotate))
        sin_a = math.sin(math.radians(rotate))
    result: list[str] = []
    for line in lines:
        words = tokenize(line.text)
        values = {letter: value for letter, value in words}
        if not any(axis in values for axis in ("X", "Y", "Z")):
            result.append(line.text)
            continue

        x = values.get("X", 0.0) * scale
        y = values.get("Y", 0.0) * scale
        z = values.get("Z", 0.0) * scale
        if rotate:
            x, y = x * cos_a - y * sin_a, x * sin_a + y * cos_a
        x += dx
        y += dy
        z += dz

        def fmt(value: float) -> str:
            text = f"{value:.4f}".rstrip("0").rstrip(".")
            return "0" if text in ("-0", "") else text

        out = line.text
        for axis, value in (("X", x), ("Y", y), ("Z", z)):
            if axis in values:
                out = re.sub(
                    rf"{axis}\s*[-+]?(?:\d+(?:\.\d*)?|\.\d+)",
                    f"{axis}{fmt(value)}",
                    out,
                    count=1,
                )
        result.append(out)
    return result
