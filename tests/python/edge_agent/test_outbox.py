import json
from pathlib import Path
import sys
import uuid

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "services/edge-agent/src"))
from thirdhand_edge.outbox import Outbox, OutboxCapacityError


def sample(index=0):
    return {"capturedAt": "2026-10-30T09:00:00.000Z", "monotonicNs": str(1000000000 + index),
            "clockQuality": "estimated", "jointPositionRad": [0, 1.57, -1.57, 0, 0, 0],
            "sdkConnected": True, "moving": False, "extra": {"sourceSequence": index}}


def test_immutable_batches_survive_restart_and_only_matching_committed_ack_clears_pending(tmp_path):
    path = tmp_path / "outbox.sqlite"
    device_id, boot_id = str(uuid.uuid4()), str(uuid.uuid4())
    box = Outbox(path, device_id=device_id, boot_id=boot_id)
    assert box.append_sample(sample(0)) == 0
    assert box.append_sample(sample(1)) == 1
    batch = box.seal_batch("robot_samples")
    assert batch["firstSequence"] == 0 and batch["lastSequence"] == 1
    saved = batch["payload"]
    box.close()
    reopened = Outbox(path, device_id=device_id, boot_id=boot_id)
    assert reopened.pending_batches()[0]["payload"] == saved
    assert reopened.ack_batch(batch["batchId"], "0" * 64, persisted=True) is False
    assert reopened.ack_batch(batch["batchId"], batch["digest"], persisted=False) is False
    assert len(reopened.pending_batches()) == 1
    assert reopened.ack_batch(batch["batchId"], batch["digest"], persisted=True) is True
    assert reopened.pending_batches() == []
    assert reopened.append_sample(sample(2)) == 2
    assert reopened.seal_batch("robot_samples")["batchSequence"] == 1
    reopened.close()


def test_contiguous_sequences_and_streams_are_independent_and_never_auto_delete(tmp_path):
    box = Outbox(tmp_path / "box.sqlite", device_id=str(uuid.uuid4()), boot_id=str(uuid.uuid4()))
    for index in range(5):
        box.append_sample(sample(index))
    first = box.seal_batch("robot_samples", max_rows=2)
    second = box.seal_batch("robot_samples", max_rows=3)
    assert (first["firstSequence"], first["lastSequence"], second["firstSequence"], second["lastSequence"]) == (0, 1, 2, 4)
    assert json.loads(first["payload"])["rows"][0]["jointPositionRad"][1] == 1.57
    assert box.append_event("device_events", {"eventId": str(uuid.uuid4()), "eventCode": "link.offline", "capturedAt": sample()["capturedAt"], "level": "warning", "details": {}}) == 0
    assert box.seal_batch("device_events")["firstSequence"] == 0
    assert box.seal_batch("robot_samples") is None
    assert len(box.pending_batches()) == 3
    for item in box.pending_batches():
        box.ack_batch(item["batchId"], item["digest"], persisted=True)
    assert box.retained_batch_count() == 3, "acknowledgement alone does not silently purge history copies"
    box.close()


def test_capacity_alarm_is_explicit_and_does_not_silently_overwrite_old_batches(tmp_path):
    box = Outbox(tmp_path / "full.sqlite", device_id=str(uuid.uuid4()), boot_id=str(uuid.uuid4()), max_bytes=262144)
    box.append_sample(sample())
    sealed = box.seal_batch("robot_samples")
    with pytest.raises(OutboxCapacityError):
        for index in range(300):
            box.append_sample({**sample(index), "extra": {"payload": "x" * 8000}})
    assert box.health()["writable"] is False
    assert box.health()["alarm"] == "OUTBOX_CAPACITY"
    assert any(item["batchId"] == sealed["batchId"] for item in box.pending_batches())
    box.close()
