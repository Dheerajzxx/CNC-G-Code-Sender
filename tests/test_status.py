from __future__ import annotations

import pytest

from plotdeck.core.status import parse_status


def test_parses_full_idle_report():
    status = parse_status(
        "<Idle|MPos:10.000,20.000,30.000|WPos:5.000,15.000,25.000"
        "|FS:1200,1000|Bf:14,127|Ov:100,100,100|Pn:XYZ|WCO:5.000,5.000,5.000>"
    )
    assert status.state == "Idle"
    assert status.is_idle
    assert status.mpos == (10.0, 20.0, 30.0)
    assert status.wpos == (5.0, 15.0, 25.0)
    assert status.wco == (5.0, 5.0, 5.0)
    assert status.feed == 1200
    assert status.spindle == 1000
    assert status.buffer == (14, 127)
    assert status.overrides == (100, 100, 100)
    assert status.pins == "XYZ"


def test_hold_state_family():
    status = parse_status("<Hold:1|MPos:0,0,0|FS:0,0>")
    assert status.state == "Hold"
    assert status.substate == "1"
    assert status.family == "hold"


@pytest.mark.parametrize(
    ("state", "family"),
    [
        ("Run", "run"),
        ("Jog", "run"),
        ("Home", "run"),
        ("Alarm", "alarm"),
        ("Door:2", "hold"),
        ("Idle", "idle"),
        ("Unknown", "offline"),
    ],
)
def test_state_families(state, family):
    assert parse_status(f"<{state}|MPos:0,0,0>").family == family


def test_derives_wpos_from_previous_wco():
    first = parse_status("<Idle|MPos:10,10,10|WCO:2,2,2>")
    second = parse_status("<Idle|MPos:12,12,12>", first)
    assert second.wco == (2.0, 2.0, 2.0)
    assert second.wpos == (10.0, 10.0, 10.0)


def test_derives_wco_when_only_positions_present():
    status = parse_status("<Run|MPos:10,10,10|WPos:4,4,4>")
    assert status.wco == (6.0, 6.0, 6.0)


def test_unknown_fields_preserved():
    status = parse_status("<Idle|MPos:0,0,0|NewField:42>")
    assert status.extra["NewField"] == "42"


def test_garbage_values_are_ignored():
    status = parse_status("<Idle|MPos:oops|FS:bad|Bf:x,y>")
    assert status.mpos is None
    assert status.feed is None
    assert status.buffer is None
