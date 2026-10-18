from __future__ import annotations

import time

from plotdeck.core.gcode_parser import ProgramLine, parse_program
from plotdeck.core.streamer import Streamer, StreamerState

from .fake_grbl import FakeGrbl


def wait_for(predicate, timeout: float = 5.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.002)
    return False


def make_program(count: int, start: int = 1) -> list[ProgramLine]:
    return [ProgramLine(f"G1 X{index} Y0 F1000", index) for index in range(start, start + count)]


def make_streamer(fake: FakeGrbl, **callbacks) -> Streamer:
    streamer = Streamer(fake, **callbacks)

    def route(line: str) -> None:
        if line == "ok":
            streamer.handle_ok()
        elif line.startswith("error:"):
            streamer.handle_error(int(line.split(":", 1)[1]))

    fake.on_line = route
    return streamer


def test_streams_large_program_without_overrun():
    fake = FakeGrbl(ack_delay=0.0002)
    finished: list[str] = []
    progress: list[tuple[int, int, int]] = []
    streamer = make_streamer(
        fake,
        on_finished=finished.append,
        on_progress=lambda sent, total, line: progress.append((sent, total, line)),
    )
    fake.open()

    program = make_program(400)
    streamer.load(program)
    assert streamer.start()

    assert wait_for(lambda: streamer.state is StreamerState.COMPLETED)
    assert fake.overruns == 0
    assert fake.max_buffered <= 127
    assert len(fake.received) == 400
    assert finished == ["completed"]
    assert progress[-1][0] == 400
    assert progress[-1][1] == 400
    fake.close()


def test_streams_ten_thousand_lines_without_overrun():
    # v1.0 success criterion: stream 10k+ lines without overflowing GRBL.
    fake = FakeGrbl(ack_delay=0.0001)
    fake.open()
    streamer = make_streamer(fake)
    streamer.load(make_program(10_000))
    assert streamer.start()
    assert wait_for(lambda: streamer.state is StreamerState.COMPLETED, timeout=20)
    assert len(fake.received) == 10_000
    assert fake.overruns == 0
    assert fake.max_buffered <= 127
    fake.close()


def test_error_pauses_job_until_skipped():
    fake = FakeGrbl(ack_delay=0.0005, error_lines={5: 20})
    errors: list[tuple[ProgramLine, int, str]] = []
    fake.open()
    streamer = make_streamer(
        fake,
        on_error=lambda line, code, detail: errors.append((line, code, detail)),
    )
    streamer.load(make_program(200))
    streamer.start()

    assert wait_for(lambda: streamer.state is StreamerState.PAUSED)
    assert errors and errors[0][1] == 20
    assert errors[0][0].source_line == 5
    assert streamer.error is not None

    streamer.skip_errored_line()
    assert wait_for(lambda: streamer.state is StreamerState.COMPLETED)
    assert fake.overruns == 0
    fake.close()


def test_tool_change_is_intercepted_and_resumes():
    fake = FakeGrbl(ack_delay=0.0002)
    changes: list[ProgramLine] = []
    fake.open()
    program = parse_program("G1 X1\nG1 X2\nM6 T2\nG1 X3\nG1 X4")
    streamer = make_streamer(fake, on_tool_change=changes.append)
    streamer.load(program)
    streamer.start()

    assert wait_for(lambda: streamer.awaiting_tool_change is not None)
    assert changes and changes[0].tool_number == 2
    assert "M6 T2" not in fake.received
    assert streamer.state is StreamerState.PAUSED

    streamer.complete_tool_change()
    assert wait_for(lambda: streamer.state is StreamerState.COMPLETED)
    assert fake.received == ["G1 X1", "G1 X2", "G1 X3", "G1 X4"]
    fake.close()


def test_stop_clears_queue_and_sends_reset():
    fake = FakeGrbl(ack_delay=0.02)
    fake.open()
    streamer = make_streamer(fake)
    streamer.load(make_program(100))
    streamer.start()
    assert wait_for(lambda: len(fake.received) >= 2)

    streamer.stop()
    assert streamer.state is StreamerState.STOPPED
    assert 0x21 in fake.realtime  # feed hold
    assert 0x18 in fake.realtime  # soft reset
    assert len(fake.received) < 100
    fake.close()


def test_pause_and_resume_send_realtime_bytes():
    fake = FakeGrbl(ack_delay=0.01)
    fake.open()
    streamer = make_streamer(fake)
    streamer.load(make_program(50))
    streamer.start()
    streamer.pause()
    assert streamer.state is StreamerState.PAUSED
    streamer.resume()
    assert streamer.state is StreamerState.RUNNING
    assert 0x21 in fake.realtime and 0x7E in fake.realtime
    streamer.stop()
    fake.close()


def test_start_from_source_line():
    fake = FakeGrbl(ack_delay=0.0002)
    fake.open()
    streamer = make_streamer(fake)
    streamer.load(make_program(20))
    streamer.start(from_source_line=15)
    assert wait_for(lambda: streamer.state is StreamerState.COMPLETED)
    assert len(fake.received) == 6
    assert fake.received[0] == "G1 X15 Y0 F1000"
    fake.close()


def test_alarm_abort_marks_error():
    fake = FakeGrbl(ack_delay=0.01)
    fake.open()
    streamer = make_streamer(fake)
    streamer.load(make_program(100))
    streamer.start()
    streamer.abort("alarm")
    assert streamer.state is StreamerState.ERROR
    assert streamer.pending_bytes == 0
    fake.close()


def test_load_rejected_while_active():
    fake = FakeGrbl(ack_delay=0.01)
    fake.open()
    streamer = make_streamer(fake)
    streamer.load(make_program(10))
    streamer.start()
    try:
        streamer.load(make_program(5))
    except RuntimeError:
        pass
    else:
        raise AssertionError("load should be rejected while a job is active")
    streamer.stop()
    fake.close()
