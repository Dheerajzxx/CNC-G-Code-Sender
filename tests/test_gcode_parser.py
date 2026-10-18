from __future__ import annotations

import math

import pytest

from plotdeck.core.gcode_parser import (
    ProgramLine,
    build_toolpath,
    clean_line,
    parse_program,
    strip_comments,
    tokenize,
    transform_lines,
)


def test_strip_comments_handles_semicolon_and_parens():
    assert strip_comments("G1 X10 ; move (ignored)") == "G1 X10 "
    assert strip_comments("G1 (rapid) X1") == "G1  X1"
    assert strip_comments("G1 X1 ; (nested") == "G1 X1 "


def test_clean_line_uppercases_and_collapses_whitespace():
    assert clean_line("  g1   x10.5   y  2 ; ok  ") == "G1 X10.5 Y 2"
    assert clean_line("(only a comment)") == ""
    assert clean_line("%") == ""


def test_parse_program_keeps_source_line_numbers():
    source = "G21\n\n; comment\nG1 X10\nM3 S1000\n"
    program = parse_program(source)
    assert [line.source_line for line in program] == [1, 4, 5]
    assert [line.text for line in program] == ["G21", "G1 X10", "M3 S1000"]


def test_tokenize():
    assert tokenize("G1 X-1.5 Y2 Z.5 F300") == [
        ("G", 1),
        ("X", -1.5),
        ("Y", 2),
        ("Z", 0.5),
        ("F", 300),
    ]


def test_long_lines_flagged():
    line = ProgramLine("G1 X" + "1" * 90, 1)
    assert line.too_long
    assert line.length > 80


def test_tool_change_detection():
    assert ProgramLine("M6 T2", 1).is_tool_change
    assert ProgramLine("M06", 1).is_tool_change
    assert ProgramLine("T2 M6", 1).tool_number == 2
    assert ProgramLine("T2", 1).is_tool_change
    assert ProgramLine("T2", 1).tool_number == 2
    assert not ProgramLine("M3 S1000", 1).is_tool_change
    assert not ProgramLine("G1 X1 T2", 1).is_tool_change


def test_toolpath_linear_and_bounds():
    program = parse_program("G21 G90\nG0 X0 Y0 Z5\nG1 Z-1 F100\nG1 X10 Y0\nG1 X10 Y10")
    path = build_toolpath(program)
    assert len(path.segments) == 4
    assert path.bounds is not None
    assert path.bounds[0] == (0.0, 0.0, -1.0)
    assert path.bounds[1] == (10.0, 10.0, 5.0)
    assert path.min_z == -1.0
    assert path.max_z == 5.0
    # 5 mm rapid + 6 mm down + 10 mm + 10 mm at the programmed rates.
    assert path.estimated_seconds == pytest.approx(15.7, rel=1e-6)


def test_relative_moves_accumulate():
    program = parse_program("G91\nG1 X10 F100\nG1 X10")
    path = build_toolpath(program)
    assert path.segments[-1].end == (20.0, 0.0, 0.0)


def test_inch_units_are_converted():
    program = parse_program("G20 G90\nG1 X1 F10")
    path = build_toolpath(program)
    assert path.segments[0].end[0] == pytest.approx(25.4)
    assert path.segments[0].start == (0.0, 0.0, 0.0)


def test_arc_tessellation_and_length():
    program = parse_program("G21 G90\nG0 X0 Y0\nG2 X10 Y0 I5 J0 F600")
    path = build_toolpath(program)
    arc = path.segments[-1]
    assert arc.kind == "arc_cw"
    assert len(arc.points) > 4
    # Half circle of radius 5, travelled the long way is 15.7 mm.
    assert arc.length == pytest.approx(math.pi * 5, rel=0.02)


def test_arc_in_zx_plane_uses_i_and_k():
    program = parse_program("G21 G90 G18\nG3 X0 Z10 I0 K5 F300")
    path = build_toolpath(program)
    arc = path.segments[-1]
    assert arc.kind == "arc_ccw"
    assert arc.length == pytest.approx(math.pi * 5, rel=0.02)


def test_radius_arc_falls_back_gracefully():
    program = parse_program("G21 G90\nG3 X10 Y0 R5")
    path = build_toolpath(program)
    assert path.segments
    assert path.segments[-1].kind == "arc_ccw"


def test_toolpath_warns_about_oversized_travel():
    program = parse_program("G1 X30")
    path = build_toolpath(program, limits=(20.0, 20.0, 20.0))
    assert any("travel" in warning for warning in path.warnings)
    assert path.tools == []


def test_tools_collected_from_m6_lines():
    program = parse_program("T1 M6\nG0 X0\nT2 M6\nG0 X1")
    path = build_toolpath(program)
    assert path.tools == [1, 2]


def test_transform_offset_scale_rotate():
    lines = parse_program("G1 X1 Y0 F100\nG0 Z5")
    transformed = transform_lines(lines, dx=10, dy=2, scale=2)
    assert transformed[0] == "G1 X12 Y2 F100"
    rotated = transform_lines(parse_program("G1 X10 Y0"), rotate=90)
    assert rotated[0].startswith("G1 X0 Y10")
