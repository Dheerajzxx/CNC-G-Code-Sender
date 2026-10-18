from __future__ import annotations

import time

from plotdeck.core.controller import MachineController
from plotdeck.core.grbl_protocol import ResponseKind
from plotdeck.core.streamer import StreamerState

from .fake_grbl import FakeGrbl


def wait_for(predicate, timeout: float = 5.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return False


def build_controller(fake: FakeGrbl, **callbacks) -> MachineController:
    controller = MachineController(transport_factory=lambda port, baud: fake)
    for name, callback in callbacks.items():
        setattr(controller, name, callback)
    return controller


def test_connect_reads_banner_and_reports_firmware():
    fake = FakeGrbl()
    connected: list[str] = []
    controller = build_controller(fake, on_connected=connected.append)
    controller.connect("FAKE")
    assert wait_for(lambda: controller.connected)
    assert connected == ["1.1h"]
    assert controller.firmware == "1.1h"
    controller.disconnect()
    fake.close()


def test_status_poll_produces_parsed_status():
    fake = FakeGrbl()
    statuses = []
    controller = build_controller(fake, on_status=statuses.append)
    controller.connect("FAKE")
    assert wait_for(lambda: controller.connected)
    fake.emit_status("Run")
    controller.request_status()
    assert wait_for(lambda: statuses and statuses[-1].state == "Run")
    assert statuses[-1].mpos == (0.0, 0.0, 0.0)
    controller.disconnect()
    fake.close()


def test_run_program_completes_and_reports_progress():
    fake = FakeGrbl(ack_delay=0.0002)
    finished: list[str] = []
    progress: list[tuple[int, int, int]] = []
    controller = build_controller(
        fake,
        on_job_finished=finished.append,
        on_progress=lambda sent, total, line: progress.append((sent, total, line)),
    )
    controller.connect("FAKE")
    assert wait_for(lambda: controller.connected)

    lines = "\n".join(f"G1 X{index} Y0" for index in range(1, 51))
    assert controller.run_text(lines)
    assert wait_for(lambda: finished == ["completed"])
    assert len(fake.received) == 50
    assert fake.overruns == 0
    assert progress[-1][0] == 50
    controller.disconnect()
    fake.close()


def test_manual_command_rejected_during_job():
    fake = FakeGrbl(ack_delay=0.01)
    messages: list[tuple[ResponseKind, str]] = []
    controller = build_controller(fake, on_line=lambda kind, text: messages.append((kind, text)))
    controller.connect("FAKE")
    assert wait_for(lambda: controller.connected)
    controller.run_text("\n".join(f"G1 X{index}" for index in range(40)))
    assert not controller.send_line("G0 X0")
    assert any("Cannot send commands" in text for _, text in messages)
    controller.stop()
    controller.disconnect()
    fake.close()


def test_error_during_job_pauses_streamer():
    fake = FakeGrbl(ack_delay=0.0005, error_lines={3: 20})
    errors: list[tuple] = []
    controller = build_controller(
        fake, on_stream_error=lambda line, code, detail: errors.append((line, code, detail))
    )
    controller.connect("FAKE")
    assert wait_for(lambda: controller.connected)
    controller.run_text("\n".join(f"G1 X{index}" for index in range(1, 30)))
    assert wait_for(lambda: bool(errors))
    assert errors[0][1] == 20
    assert controller.streamer is not None
    assert controller.streamer.state is StreamerState.PAUSED

    controller.skip_error()
    assert wait_for(
        lambda: controller.streamer is not None
        and controller.streamer.state is StreamerState.COMPLETED
    )
    controller.disconnect()
    fake.close()


def test_alarm_halts_job_and_notifies():
    fake = FakeGrbl(ack_delay=0.01)
    alarms: list[tuple[int, str]] = []
    finished: list[str] = []
    controller = build_controller(
        fake,
        on_alarm=lambda code, text: alarms.append((code, text)),
        on_job_finished=finished.append,
    )
    controller.connect("FAKE")
    assert wait_for(lambda: controller.connected)
    controller.run_text("\n".join(f"G1 X{index}" for index in range(80)))
    assert wait_for(lambda: len(fake.received) > 0)
    assert not controller.run_text("G1 X1")  # a second job is refused

    fake.emit_alarm(1)
    assert wait_for(lambda: bool(alarms))
    assert alarms[0][0] == 1
    assert "Hard limit" in alarms[0][1]
    assert "alarm" in finished
    assert controller.streamer is not None
    assert controller.streamer.state is StreamerState.ERROR
    controller.disconnect()
    fake.close()


def test_settings_collection():
    fake = FakeGrbl()
    settings = []
    controller = build_controller(fake, on_settings=settings.append)
    controller.connect("FAKE")
    assert wait_for(lambda: controller.connected)
    assert controller.request_settings()
    assert wait_for(lambda: bool(settings))
    entries = settings[0]
    assert [(entry.number, entry.value) for entry in entries] == [
        (100, "250.000"),
        (130, "200.000"),
    ]
    assert entries[0].description == "X steps/mm"
    controller.disconnect()
    fake.close()


def test_jog_and_override_bytes():
    fake = FakeGrbl()
    controller = build_controller(fake)
    controller.connect("FAKE")
    assert wait_for(lambda: controller.connected)

    assert controller.jog("X", 5.0, 800)
    assert wait_for(lambda: "$J=G91 X5.0000 F800" in fake.received)

    controller.set_override("rapid", 50)
    controller.set_override("feed", 120)
    controller.set_override("spindle", 90)
    assert wait_for(lambda: fake.realtime)
    assert 0x96 in fake.realtime  # rapid 50%
    assert 0x90 in fake.realtime and 0x91 in fake.realtime
    controller.disconnect()
    fake.close()


def test_manual_ack_does_not_corrupt_job_accounting():
    fake = FakeGrbl(ack_delay=0.0005)
    finished: list[str] = []
    controller = build_controller(fake, on_job_finished=finished.append)
    controller.connect("FAKE")
    assert wait_for(lambda: controller.connected)

    # Check mode is sent as a manual command immediately before the job; its ok
    # can arrive after the streamer has already queued motion lines.
    assert controller.send_line("$C")
    assert controller.run_text("\n".join(f"G1 X{index}" for index in range(30)))
    assert wait_for(lambda: finished == ["completed"])
    assert len(fake.received) == 31
    assert fake.overruns == 0
    controller.disconnect()
    fake.close()


def test_realtime_console_command_does_not_consume_job_acks():
    fake = FakeGrbl(ack_delay=0.0005)
    finished: list[str] = []
    controller = build_controller(fake, on_job_finished=finished.append)
    controller.connect("FAKE")
    assert wait_for(lambda: controller.connected)

    # '?' is a real-time byte and never returns ok; sending it must not leave a
    # phantom manual acknowledgement behind for the next job line.
    assert controller.send_line("?")
    assert controller.run_text("\n".join(f"G1 X{index}" for index in range(20)))
    assert wait_for(lambda: finished == ["completed"])
    assert len(fake.received) == 20
    controller.disconnect()
    fake.close()


def test_disconnect_stops_polling():
    fake = FakeGrbl()
    controller = build_controller(fake)
    controller.connect("FAKE")
    assert wait_for(lambda: controller.connected)
    controller.disconnect()
    assert not controller.connected
    fake.close()
