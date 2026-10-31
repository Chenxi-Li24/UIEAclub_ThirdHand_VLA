import json
from pathlib import Path
import sys
import uuid

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "services/edge-agent/src"))
from thirdhand_edge.capture import CaptureRecorder
from thirdhand_edge.capture import capture_stream
from thirdhand_edge.outbox import Outbox


def test_capture_records_source_rate_without_downsampling_and_exposes_source_gaps(tmp_path):
    box = Outbox(tmp_path / "capture.sqlite", device_id=str(uuid.uuid4()), boot_id=str(uuid.uuid4()))
    recorder = CaptureRecorder(box)
    executor = str(uuid.uuid4())
    recorder.consume({"type": "source_snapshot", "sequence": 0, "executorEpoch": executor, "receivedAt": "2026-10-30T09:00:00.000Z"})
    for sequence in (1, 2, 4):
        recorder.consume({"type": "robot_event", "sequence": sequence, "executorEpoch": executor, "hardwareFingerprint": "a" * 64, "receivedAt": "2026-10-30T09:00:00.100Z", "commandId": None,
                          "message": {"type": "robot_state", "joints_deg": [0, 90, -90, 0, 0, 0], "ts": 1793350800000, "connected": True, "moving": False}})
    samples = json.loads(box.seal_batch("robot_samples")["payload"])["rows"]
    assert len(samples) == 3
    assert [row["extra"]["sourceSequence"] for row in samples] == [1, 2, 4]
    events = json.loads(box.seal_batch("device_events")["payload"])["rows"]
    gap = next(row for row in events if row["eventCode"] == "capture.source_gap")
    assert gap["details"]["firstSourceSequence"] == gap["details"]["lastSourceSequence"] == 3
    box.close()


def test_capture_cursor_survives_restart_and_command_outcome_is_recorded_separately(tmp_path):
    path = tmp_path / "capture.sqlite"
    device, boot, executor, command = [str(uuid.uuid4()) for _ in range(4)]
    box = Outbox(path, device_id=device, boot_id=boot)
    recorder = CaptureRecorder(box)
    recorder.consume({"type": "source_snapshot", "sequence": 0, "executorEpoch": executor, "receivedAt": "2026-10-30T09:00:00.000Z"})
    recorder.consume({"type": "robot_event", "sequence": 1, "executorEpoch": executor, "receivedAt": "2026-10-30T09:00:00.100Z", "message": {"type": "remote_command_outcome", "commandId": command, "opcode": "move_joint", "state": "completed", "ts": 1793350800000}})
    box.close()
    reopened = Outbox(path, device_id=device, boot_id=boot)
    resumed = CaptureRecorder(reopened)
    assert resumed.cursor["sequence"] == 1
    rows = json.loads(reopened.seal_batch("command_events")["payload"])["rows"]
    assert rows[0]["commandId"] == command and rows[0]["state"] == "completed"
    with pytest.raises(ValueError):
        resumed.consume({"type": "robot_event", "sequence": 1, "executorEpoch": executor, "receivedAt": "2026-10-30T09:00:00.100Z", "message": {"type": "connection", "connected": True}})
    reopened.close()


def test_executor_rotation_during_health_report_preserves_stream_and_never_marks_old_epoch_healthy(tmp_path, monkeypatch):
    from urllib.error import HTTPError
    import thirdhand_edge.capture as capture
    old, current = str(uuid.uuid4()), str(uuid.uuid4())
    box = Outbox(tmp_path / 'rotate.sqlite', device_id=str(uuid.uuid4()), boot_id=str(uuid.uuid4()))
    ticks = iter(range(1000, 100000)); monkeypatch.setattr(capture.time, 'monotonic', lambda: next(ticks))
    class Robot:
        def __init__(self): self.accepted = []
        def iter_events(self):
            for epoch in [old, current]:
                yield {'type':'source_snapshot','sequence':0,'executorEpoch':epoch,'receivedAt':'2026-10-31T09:00:00Z'}
        async def report_capture_health(self, **value):
            if value['executor_epoch'] == old:
                raise HTTPError('http://127.0.0.1/edge-control/v1/capture-health',403,'rejected',{},None)
            self.accepted.append(value)
        async def get_context(self): return {'executorEpoch': current}
    robot = Robot()
    try:
        capture_stream(robot, box)
        assert robot.accepted and all(v['executor_epoch'] == current for v in robot.accepted)
        assert any(v['writable'] is True for v in robot.accepted)
        assert robot.accepted[-1]['writable'] is False
        events = [r for b in box.pending_batches() for r in json.loads(b['payload'])['rows']]
        assert any(v.get('eventCode') == 'capture.executor_changed' for v in events)
    finally: box.close()
