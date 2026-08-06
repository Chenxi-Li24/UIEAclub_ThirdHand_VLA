from __future__ import annotations

import ast
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).parents[2]
PYTHON_BRIDGE = ROOT / "web-control/server/camera_bridge.py"
NODE_BRIDGE = ROOT / "web-control/server/camera-bridge.js"
SERVER = ROOT / "web-control/server"
SESSION_ID = "11111111-1111-4111-8111-111111111111"
PROPOSAL_ID = "22222222-2222-4222-8222-222222222222"
REQUEST_ID = "33333333-3333-4333-8333-333333333333"


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


def test_d435_debug_inner_quality_roi_uses_configured_central_fraction():
    bridge = load_python_bridge()

    assert bridge.inner_roi_bounds(640, 480, 0.60) == (128, 96, 511, 383)
    with pytest.raises(ValueError, match="fraction"):
        bridge.inner_roi_bounds(640, 480, 0.0)


def test_stdin_contract_rejects_targets_detections_and_motion_commands():
    bridge = load_python_bridge()

    assert bridge.accepted_command_type(valid_arm_state()) == "arm_state"
    assert bridge.accepted_command_type({"cmd": "get_status"}) == "get_status"
    assert bridge.accepted_command_type({"cmd": "shutdown"}) == "shutdown"
    for forbidden in ("detection_result", "grasp_target", "move", "trajectory"):
        assert bridge.accepted_command_type({"type": forbidden}) is None


@pytest.mark.parametrize(
    "command",
    [
        {"type": "active_view_start", "session_id": SESSION_ID, "identity_id": 7},
        {
            "type": "active_view_motion_started",
            "session_id": SESSION_ID,
            "proposal_id": PROPOSAL_ID,
            "request_id": REQUEST_ID,
        },
        {
            "type": "active_view_motion_completed",
            "session_id": SESSION_ID,
            "request_id": REQUEST_ID,
        },
        {"type": "active_view_cancel", "session_id": SESSION_ID},
        {
            "type": "active_view_operator_confirmed",
            "session_id": SESSION_ID,
            "proposal_id": PROPOSAL_ID,
        },
    ],
)
def test_session_commands_accept_ids_only(command):
    bridge = load_python_bridge()
    assert bridge.accepted_command_type(command) == command["type"]


def test_session_command_with_coordinates_or_invalid_ids_is_rejected():
    bridge = load_python_bridge()
    with_coordinates = {
        "type": "active_view_start",
        "session_id": SESSION_ID,
        "identity_id": 7,
        "position": [0.1, 0.2, 0.3],
    }
    assert bridge.accepted_command_type(with_coordinates) is None
    assert bridge.accepted_command_type(
        {"type": "active_view_cancel", "session_id": "not-a-uuid"}
    ) is None
    assert bridge.accepted_command_type(
        {"type": "active_view_cancel", "session_id": "a" * 200}
    ) is None


def valid_arm_state(timestamp: str = "1000000000") -> dict:
    return {
        "type": "arm_state",
        "tcp_position_m": [0.1, 0.0, 0.3],
        "tcp_euler_rad": [0.0, 0.0, 0.0],
        "joints_deg": [1, 2, -3, 4, 5, 6],
        "velocities_deg_s": [0, 0, 0, 0, 0, 0],
        "stationary": True,
        "monotonic_ns": timestamp,
    }


def test_arm_state_requires_sender_timestamp_and_explicit_stationarity():
    bridge = load_python_bridge()

    accepted = bridge.parse_arm_state(valid_arm_state(), now_ns=1_100_000_000)

    assert accepted.stationary is True
    assert accepted.stamp.monotonic_ns == 1_000_000_000
    np.testing.assert_allclose(accepted.joints_deg, [1, 2, -3, 4, 5, 6])
    np.testing.assert_allclose(accepted.velocities_deg_s, np.zeros(6))


@pytest.mark.parametrize(
    "mutation,match",
    [
        (lambda value: value.pop("monotonic_ns"), "keys"),
        (lambda value: value.update(monotonic_ns=True), "timestamp"),
        (lambda value: value.update(monotonic_ns="1200000000"), "future"),
        (lambda value: value.update(monotonic_ns="700000000"), "stale"),
        (lambda value: value.update(stationary=1), "stationary"),
        (lambda value: value.update(velocities_deg_s=[0, 0, 0, 0, 0, 0.6]), "velocity"),
    ],
)
def test_arm_state_rejects_invalid_provenance_and_false_stationarity(mutation, match):
    bridge = load_python_bridge()
    command = valid_arm_state()
    mutation(command)

    with pytest.raises(ValueError, match=match):
        bridge.parse_arm_state(command, now_ns=1_100_000_000)


def test_arm_state_rejects_backward_sender_timestamp():
    bridge = load_python_bridge()

    with pytest.raises(ValueError, match="backward"):
        bridge.parse_arm_state(
            valid_arm_state("1000000000"),
            now_ns=1_100_000_000,
            previous_monotonic_ns=1_000_000_001,
        )


def test_online_inputs_fail_closed_when_evidence_changes_or_pose_is_stale():
    bridge = load_python_bridge()
    sample = bridge.parse_arm_state(valid_arm_state(), now_ns=1_100_000_000)

    class Guard:
        def __init__(self, unchanged):
            self.unchanged = unchanged
            self.evidence = type("Evidence", (), {"camera": object()})()

        def verify_unchanged(self):
            return self.unchanged

    calibration, robot_pose, stationary, blockers = bridge.select_online_inputs(
        Guard(True), sample, now_ns=1_100_000_000
    )
    assert calibration is not None
    assert robot_pose is not None
    assert stationary is True
    assert blockers == ()

    changed = bridge.select_online_inputs(Guard(False), sample, now_ns=1_100_000_000)
    assert changed[0] is None
    assert changed[2] is False
    assert "calibration_changed" in changed[3]

    stale = bridge.select_online_inputs(Guard(True), sample, now_ns=1_300_000_001)
    assert stale[1] is None
    assert stale[2] is False
    assert "robot_pose_stale" in stale[3]


def test_calibration_change_expires_the_active_view_session_once():
    bridge = load_python_bridge()
    calls = []

    class Coordinator:
        session = type(
            "Session",
            (),
            {"phase": bridge.ActiveViewPhase.TARGET_LOCKED},
        )()

        def expire_evidence(self, evidence_id, *, now_ns):
            calls.append((evidence_id, now_ns))
            self.session.phase = bridge.ActiveViewPhase.ABORTED
            return [{"type": "active_view_state", "phase": "aborted"}]

    guard = type(
        "Guard",
        (),
        {
            "evidence": type(
                "Evidence",
                (),
                {"evidence_id": "a" * 64},
            )()
        },
    )()
    coordinator = Coordinator()

    events = bridge.expire_active_view_on_evidence_failure(
        coordinator,
        guard,
        ("calibration_changed",),
        now_ns=123,
    )
    duplicate = bridge.expire_active_view_on_evidence_failure(
        coordinator,
        guard,
        ("calibration_changed",),
        now_ns=124,
    )

    assert events == ({"type": "active_view_state", "phase": "aborted"},)
    assert duplicate == ()
    assert calls == [("a" * 64, 123)]


def test_active_view_command_mailbox_preserves_fifo_for_one_owner():
    bridge = load_python_bridge()
    mailbox = bridge.ActiveViewCommandMailbox()
    first = {"type": "active_view_start", "session_id": SESSION_ID, "identity_id": 7}
    second = {"type": "active_view_cancel", "session_id": SESSION_ID}

    mailbox.publish(first)
    mailbox.publish(second)

    assert mailbox.drain() == (first, second)
    assert mailbox.drain() == ()


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
  activeViewConfig: '/tmp/active-view.yaml',
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
const accepted = bridge.sendArmState(
  [0.1,0,0.3], [0,0,0], [1,2,-3,4,5,6], [0,0,0,0,0,0], true, '1000000'
);
const sessionAccepted = bridge.send({{
  type: 'active_view_cancel', session_id: {json.dumps(SESSION_ID)}
}});
const sessionRejected = bridge.send({{
  type: 'active_view_cancel', session_id: {json.dumps(SESSION_ID)}, position: [0.1,0.2,0.3]
}});
const paused = new PassThrough();
paused.pause();
bridge.releaseMjpegStream(paused, new PassThrough());
process.stdout.write(JSON.stringify({{
  stdioLength: spec.stdio.length,
  overlayMatches: bridge.getVisionMjpegStream() === overlay,
  rejected,
  accepted,
  sessionAccepted,
  sessionRejected,
  writes,
  onlineEnabled: spec.env.VISION_ONLINE_ENABLED,
  visionConfig: spec.env.VISION_CONFIG,
  activeViewConfig: spec.env.ACTIVE_VIEW_CONFIG,
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
        "sessionAccepted": True,
        "sessionRejected": False,
        "writes": [
            '{"type":"arm_state","tcp_position_m":[0.1,0,0.3],"tcp_euler_rad":[0,0,0],"joints_deg":[1,2,-3,4,5,6],"velocities_deg_s":[0,0,0,0,0,0],"stationary":true,"monotonic_ns":"1000000"}\n',
            f'{{"type":"active_view_cancel","session_id":"{SESSION_ID}"}}\n',
        ],
        "onlineEnabled": "1",
        "visionConfig": "/tmp/vision.yaml",
        "activeViewConfig": "/tmp/active-view.yaml",
        "lumosUrl": "http://127.0.0.1:3001/frame.jpg",
        "overlayFd": "4",
        "releasedStreamFlowing": True,
    }
