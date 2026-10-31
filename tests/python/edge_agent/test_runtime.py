import json
from pathlib import Path
import sys
import uuid

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "services/edge-agent/src"))
from thirdhand_edge.outbox import Outbox
from thirdhand_edge.runtime import load_runtime_config


def test_old_boot_unsealed_records_are_recovered_without_rewriting_or_deleting_acked_batches(tmp_path):
    path, device, boot = tmp_path / "outbox.sqlite", str(uuid.uuid4()), str(uuid.uuid4())
    first = Outbox(path, device_id=device, boot_id=boot)
    first.append_event("device_events", {"eventId": str(uuid.uuid4()), "capturedAt": "2026-10-30T09:00:00Z", "eventCode": "fixture", "level": "info", "details": {}})
    first.close()
    second = Outbox(path, device_id=device, boot_id=str(uuid.uuid4()))
    assert second.seal_retained() == 1
    batch = second.pending_batches()[0]
    assert json.loads(batch["payload"])["bootId"] == boot
    assert second.ack_batch(batch["batchId"], batch["digest"], persisted=True)
    assert second.seal_retained() == 0
    assert second.retained_batch_count() == 1
    second.close()


def test_runtime_config_is_transport_only_and_refuses_implicit_hardware_or_unknown_flags(tmp_path):
    source = tmp_path / "edge.toml"
    text = f'''url = "wss://edge.example.invalid/edge/v1/connect"
device_id = "{uuid.uuid4()}"
certificate = "device.crt"
private_key = "device.key"
robot_origin = "http://127.0.0.1:3100"
robot_token_file = "edge-token"
signing_keys_file = "cloud-keys.json"
state_directory = "state"
'''
    source.write_text(text)
    config = load_runtime_config(source)
    assert config["state_directory"] == tmp_path / "state"
    assert config["robot_origin"] == "http://127.0.0.1:3100"
    source.write_text(text + "hardware_enabled = true\n")
    with pytest.raises(ValueError):
        load_runtime_config(source)
