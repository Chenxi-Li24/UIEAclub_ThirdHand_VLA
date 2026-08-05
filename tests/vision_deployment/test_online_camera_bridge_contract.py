from __future__ import annotations

import ast
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import numpy as np


ROOT = Path(__file__).parents[2]
PYTHON_BRIDGE = ROOT / "web-control/server/camera_bridge.py"
NODE_BRIDGE = ROOT / "web-control/server/camera-bridge.js"
SERVER = ROOT / "web-control/server"


def load_python_bridge():
    spec = importlib.util.spec_from_file_location("online_camera_bridge_contract", PYTHON_BRIDGE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_latest_value_buffer_discards_queued_frames_and_strictly_advances():
    bridge = load_python_bridge()
    latest = bridge.LatestValueBuffer()

    first = latest.publish("old")
    second = latest.publish("new")

    assert second == first + 1
    assert latest.get_after(0, timeout_s=0.0) == (second, "new")
    assert latest.get_after(second, timeout_s=0.0) is None
    assert latest.capacity == 1


def test_d435_depth_is_converted_once_with_device_scale_and_zero_is_nan():
    bridge = load_python_bridge()
    raw = np.array([[0, 500, 1_000]], dtype=np.uint16)

    depth_m = bridge.depth_to_metres(raw, 0.001)

    assert np.isnan(depth_m[0, 0])
    assert np.allclose(depth_m[0, 1:], [0.5, 1.0])
    assert depth_m.dtype == np.float32
    assert depth_m.flags.writeable is False


def test_stdin_contract_rejects_targets_detections_and_motion_commands():
    bridge = load_python_bridge()

    assert bridge.accepted_command_type({"type": "arm_state"}) == "arm_state"
    assert bridge.accepted_command_type({"cmd": "get_status"}) == "get_status"
    assert bridge.accepted_command_type({"cmd": "shutdown"}) == "shutdown"
    for forbidden in ("detection_result", "grasp_target", "move", "trajectory"):
        assert bridge.accepted_command_type({"type": forbidden}) is None


def test_d435_capture_supervisor_retries_after_transient_start_failure(monkeypatch):
    bridge = load_python_bridge()
    attempts = []

    def fake_once():
        attempts.append(len(attempts) + 1)
        if len(attempts) == 2:
            bridge.shutdown_flag.set()

    monkeypatch.setattr(bridge, "_capture_d435_once", fake_once)
    bridge.shutdown_flag.clear()
    try:
        bridge.capture_d435(retry_initial_s=0.0)
    finally:
        bridge.shutdown_flag.clear()

    assert attempts == [1, 2]


def test_d435_and_lumos_outputs_cannot_block_each_other():
    bridge = load_python_bridge()

    assert bridge._d435_output_lock is not bridge._overlay_lock


def test_python_bridge_import_graph_has_no_robot_can_or_motion_dependency():
    tree = ast.parse(PYTHON_BRIDGE.read_text(encoding="utf-8"))
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)

    assert not any("startouch" in item.lower() for item in imports)
    assert not any("singlearm" in item.lower() for item in imports)
    assert not any(item in {"can", "canopen", "python_can"} for item in imports)


def test_node_bridge_uses_separate_overlay_fd_and_rejects_untrusted_messages():
    script = f"""
const {{ PassThrough }} = require('stream');
const {{ CameraBridge }} = require({json.dumps(str(NODE_BRIDGE))});
const bridge = new CameraBridge({{
  onlineEnabled: true,
  visionConfig: '/tmp/vision.yaml',
  lumosSnapshotUrl: 'http://127.0.0.1:3001/frame.jpg'
}});
const writes = [];
const overlay = new PassThrough();
bridge.child = {{
  stdout: new PassThrough(),
  stdio: [null, null, null, new PassThrough(), overlay],
  stdin: {{ writable: true, write: value => writes.push(value) }}
}};
const spec = bridge.buildSpawnSpec();
const rejected = bridge.send({{ type: 'detection_result', targets: [{{ actionable: true }}] }});
const accepted = bridge.send({{ type: 'arm_state', tcp_position_m: [0,0,0], tcp_euler_rad: [0,0,0] }});
const paused = new PassThrough();
paused.pause();
bridge.releaseMjpegStream(paused, new PassThrough());
process.stdout.write(JSON.stringify({{
  stdioLength: spec.stdio.length,
  overlayMatches: bridge.getVisionMjpegStream() === overlay,
  rejected,
  accepted,
  writes,
  onlineEnabled: spec.env.VISION_ONLINE_ENABLED,
  visionConfig: spec.env.VISION_CONFIG,
  lumosUrl: spec.env.LUMOS_SNAPSHOT_URL,
  overlayFd: spec.env.VISION_OVERLAY_FD,
  releasedStreamFlowing: paused.readableFlowing
}}));
"""
    result = subprocess.run(
        ["node", "-e", script],
        cwd=SERVER,
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
        env=os.environ.copy(),
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload == {
        "stdioLength": 5,
        "overlayMatches": True,
        "rejected": False,
        "accepted": True,
        "writes": [
            '{"type":"arm_state","tcp_position_m":[0,0,0],"tcp_euler_rad":[0,0,0]}\n'
        ],
        "onlineEnabled": "1",
        "visionConfig": "/tmp/vision.yaml",
        "lumosUrl": "http://127.0.0.1:3001/frame.jpg",
        "overlayFd": "4",
        "releasedStreamFlowing": True,
    }
