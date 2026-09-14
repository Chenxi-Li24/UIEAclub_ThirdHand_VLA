"""Offline contract tests for the contained Startouch bridge."""

from __future__ import annotations

import importlib
import json
import math
import socket
import struct
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from native.startouch.backends import (
    BackendError,
    CanOwner,
    ResourceLockedError,
    SdkBackend,
    SdkBackendConfig,
    SimulatedBackend,
    StartouchCanFeedbackProbe,
    StopNotConfirmedError,
)
from native.startouch.protocol import ProtocolError, validate_command
from native.startouch.startouch_bridge import BridgeRuntime


PROJECT_ROOT = Path(__file__).resolve().parents[3]
BRIDGE = PROJECT_ROOT / "native/startouch/startouch_bridge.py"


class CounterClock:
    """Return deterministic, strictly increasing monotonic timestamps."""

    def __init__(self, value: int = 1_000) -> None:
        self.value = value

    def __call__(self) -> int:
        self.value += 1
        return self.value


def _runtime() -> BridgeRuntime:
    runtime = BridgeRuntime(
        SimulatedBackend(),
        monotonic_ns=CounterClock(),
        bridge_content_id="sha256:" + "a" * 64,
        runtime_config_id="sha256:" + "b" * 64,
    )
    startup = runtime.start_events()
    assert [event["type"] for event in startup] == ["bridge_ready", "robot_state"]
    return runtime


def test_simulator_emits_explicit_flange_state_and_correlated_move_completion() -> None:
    runtime = _runtime()

    events = runtime.run_line(json.dumps({
        "cmd": "move_l",
        "request_id": "move-1",
        "flange_position_m": [0.40, 0.05, 0.18],
        "flange_euler_rad": [0.0, 0.0, 0.0],
        "duration_sec": 3.334,
        "source": "test:move",
    }))

    assert [event["type"] for event in events] == [
        "command_accepted", "command_complete", "robot_state",
    ]
    assert events[1]["request_id"] == "move-1"
    assert events[1]["command"] == "move_l"
    assert events[1]["reached"] is True
    assert events[1]["actual_flange_position_m"] == [0.40, 0.05, 0.18]
    state = events[2]
    assert state["pose_frame"] == "robot_flange"
    assert state["flange_position_m"] == [0.40, 0.05, 0.18]
    assert state["state_sequence"] > 0
    assert state["producer_monotonic_ns"] > 0


def test_ready_event_binds_protocol_units_and_local_content() -> None:
    runtime = BridgeRuntime(
        SimulatedBackend(),
        monotonic_ns=CounterClock(),
        bridge_content_id="sha256:" + "c" * 64,
        runtime_config_id="sha256:" + "d" * 64,
    )

    ready, state = runtime.start_events()

    assert ready == {
        "type": "bridge_ready",
        "schema": "thirdhand-startouch-bridge-v1",
        "protocol_version": "thirdhand-robot-lowlevel-v1",
        "commands": [
            "connect", "disconnect", "get_state", "gripper",
            "move_joint", "move_l", "software_stop",
        ],
        "correlated_completions": True,
        "pose_frame": "robot_flange",
        "software_stop_ack": True,
        "stop_proof_mode": "cleanup_ack_only",
        "state_units": {
            "gripper": "m",
            "joint_velocity": "deg/s",
            "joints": "deg",
            "orientation": "rad",
            "position": "m",
        },
        "state_stream": {
            "producer_monotonic_ns": "uint53",
            "sequence": "uint53",
            "strictly_increasing": True,
        },
        "bridge_content_id": "sha256:" + "c" * 64,
        "runtime_config_id": "sha256:" + "d" * 64,
        "runtime_identity": {
            "runtime_manifest_id": "simulation",
            "safety_config_sha256": "simulation",
            "safety_profile_id": "simulation",
            "startup_feedback_ids": [],
        },
    }
    assert state["connected"] is True
    assert state["flange_position_m"] == [0.45, 0.0, 0.25]
    assert state["gripper_width_m"] == 0.080


@pytest.mark.parametrize(
    ("message", "reason"),
    [
        ({"cmd": "move_l", "request_id": ""}, "request_id_invalid"),
        ({"cmd": "dance", "request_id": "x"}, "command_unsupported"),
        ({
            "cmd": "move_l", "request_id": "x",
            "flange_position_m": [0.4, 0.0],
            "flange_euler_rad": [0.0, 0.0, 0.0], "duration_sec": 1.0,
        }, "flange_position_m_invalid"),
        ({
            "cmd": "move_l", "request_id": "x",
            "flange_position_m": [0.4, math.nan, 0.2],
            "flange_euler_rad": [0.0, 0.0, 0.0], "duration_sec": 1.0,
        }, "flange_position_m_invalid"),
        ({
            "cmd": "move_l", "request_id": "x",
            "flange_position_m": [0.4, 0.0, 0.2],
            "flange_euler_rad": [0.0, 0.0, 0.0], "duration_sec": 30.001,
        }, "duration_sec_invalid"),
        ({
            "cmd": "gripper", "request_id": "x", "position": 1.01,
        }, "gripper_position_invalid"),
    ],
)
def test_command_validation_rejects_unsafe_or_malformed_input(
    message: dict[str, object], reason: str,
) -> None:
    with pytest.raises(ProtocolError, match=reason):
        validate_command(message)


def test_duplicate_request_id_is_correlated_and_cannot_repeat_motion() -> None:
    runtime = _runtime()
    command = json.dumps({
        "cmd": "move_l", "request_id": "duplicate",
        "flange_position_m": [0.41, 0.0, 0.25],
        "flange_euler_rad": [0.0, 0.0, 0.0], "duration_sec": 1.0,
    })
    first = runtime.run_line(command)

    duplicate = runtime.run_line(command)

    assert first[1]["reached"] is True
    assert duplicate == ({
        "type": "error",
        "command": "move_l",
        "request_id": "duplicate",
        "reason": "request_id_duplicate",
    },)


def test_simulated_stop_is_terminal_and_reports_cleanup_without_depower() -> None:
    runtime = _runtime()
    before = runtime.state_event()

    events = runtime.run_line(json.dumps({
        "cmd": "software_stop", "request_id": "stop-1",
    }))

    completion = events[1]
    assert completion["command"] == "software_stop"
    assert completion["request_id"] == "stop-1"
    assert completion["cleanup_acknowledged"] is True
    assert completion["cleanup_confirmation_mode"] == "simulation"
    assert completion["depower_independently_confirmed"] is False
    assert completion["control_released"] is True
    assert completion["applied_state_sequence"] >= before["state_sequence"]
    assert completion["applied_producer_monotonic_ns"] >= before[
        "producer_monotonic_ns"
    ]
    assert runtime.backend.connected is False


def test_simulate_cli_does_not_import_vendor_sdk() -> None:
    result = subprocess.run(
        [sys.executable, str(BRIDGE), "--simulate", "--self-test"],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload == {
        "hardware_connected": False,
        "ok": True,
        "vendor_sdk_imported": False,
    }

    importlib.invalidate_caches()
    assert "startouch" not in sys.modules


def test_real_cli_rejects_before_sdk_import_without_exact_authorization(
    tmp_path: Path,
) -> None:
    sdk_path = tmp_path / "startouch_sdk"
    (sdk_path / "interface_py").mkdir(parents=True)
    result = subprocess.run(
        [
            sys.executable,
            str(BRIDGE),
            "--real",
            "--runtime-root",
            str(sdk_path),
            "--source-manifest",
            str(tmp_path / "source.json"),
            "--expected-safety-config-sha256",
            "a" * 64,
            "--lock-file",
            str(tmp_path / "startouch-web-can0.lock"),
        ],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )

    assert result.returncode == 2
    assert json.loads(result.stderr.strip().splitlines()[-1]) == {
        "reason": "real_robot_authorization_missing",
        "type": "bridge_error",
    }


def test_real_cli_rejects_unverified_binary_provenance_before_backend_init(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    from native.startouch import startouch_bridge as bridge

    runtime_root = tmp_path / "startouch_sdk"
    monkeypatch.setattr(bridge, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        bridge,
        "validate_startouch_runtime",
        lambda *_: SimpleNamespace(
            root=runtime_root,
            interface_dir=runtime_root / "interface_py",
            library_dir=runtime_root / "src",
            profile_id="thirdhand-conservative-safety-v1",
            sdk_version="0.1.7",
            config_sha256="a" * 64,
            runtime_manifest_sha256="b" * 64,
            reproducible_build_verified=False,
        ),
    )

    result = bridge.main([
        "--real",
        "--runtime-root", str(runtime_root),
        "--source-manifest", str(tmp_path / "source.json"),
        "--expected-safety-config-sha256", "a" * 64,
        "--lock-file", str(tmp_path / "robot.lock"),
        "--allow-real", "I_ACCEPT_SUPERVISED_ROBOT_MOTION",
    ])

    assert result == 2
    assert json.loads(capsys.readouterr().err.strip()) == {
        "reason": "startouch_binary_provenance_unverified",
        "type": "bridge_error",
    }


class FakeSdkArm:
    """Complete fake for every installed SDK method consumed by SdkBackend."""

    def __init__(
        self,
        *,
        actual_position: list[float] | None = None,
        cleanup_error: Exception | None = None,
    ) -> None:
        self.position = actual_position or [0.45, 0.0, 0.25]
        self.euler = [0.0, 0.0, 0.0]
        self.joints = [0.0, 0.20, -0.20, 0.10, 0.0, 0.0]
        self.velocities = [0.0] * 6
        self.gripper_position = 1.0
        self.gripper_distance = 0.080
        self.cleanup_error = cleanup_error
        self.hold_calls: list[tuple[list[float], list[float]]] = []
        self.move_l_calls: list[dict[str, object]] = []
        self.joint_waypoint_calls: list[dict[str, object]] = []
        self.gripper_calls: list[float] = []
        self.cleaned = False

    def get_joint_positions(self) -> list[float]:
        return list(self.joints)

    def get_joint_velocities(self) -> list[float]:
        return list(self.velocities)

    def get_ee_pose_euler(self) -> tuple[list[float], list[float]]:
        return list(self.position), list(self.euler)

    def get_gripper_position(self) -> float:
        return self.gripper_position

    def get_gripper_distance(self) -> float:
        return self.gripper_distance

    def set_joint_raw(self, positions: list[float], velocities: list[float]) -> bool:
        self.hold_calls.append((list(positions), list(velocities)))
        return True

    def move_l(self, poses: list[list[float]], **kwargs: object) -> float:
        self.move_l_calls.append({"poses": poses, **kwargs})
        return float(kwargs["time_sec"])

    def set_joint_waypoints(
        self, waypoints: list[list[float]], **kwargs: object,
    ) -> float:
        self.joint_waypoint_calls.append({"waypoints": waypoints, **kwargs})
        self.joints = list(waypoints[-1])
        return float(kwargs["time_sec"])

    def setGripperPosition(self, position: float) -> bool:
        self.gripper_calls.append(position)
        self.gripper_position = position
        self.gripper_distance = position * 0.080
        return True

    def cleanup(self) -> None:
        if self.cleanup_error is not None:
            raise self.cleanup_error
        self.cleaned = True


class StartupFeedbackArm(FakeSdkArm):
    """Expose the zero-to-real feedback transition seen on physical startup."""

    def __init__(self, actual_joints: list[float]) -> None:
        super().__init__()
        self.actual_joints = list(actual_joints)
        self.feedback_ready = False

    def get_joint_positions(self) -> list[float]:
        return list(self.actual_joints if self.feedback_ready else [0.0] * 6)


class FakeFeedbackProbe:
    def __init__(self, observed_ids: object) -> None:
        self.observed_ids = frozenset(observed_ids)
        self.closed = False

    def read_observed_ids(self) -> frozenset[int]:
        return self.observed_ids

    def close(self) -> None:
        self.closed = True


class FakeCanSocket:
    def __init__(self, frames: list[tuple[bytes, list[object], int, object]]) -> None:
        self.frames = iter(frames)

    def recvmsg(self, _size: int) -> tuple[bytes, list[object], int, object]:
        try:
            return next(self.frames)
        except StopIteration as exc:
            raise BlockingIOError from exc

    def close(self) -> None:
        pass


def _sdk_config(tmp_path: Path) -> SdkBackendConfig:
    sdk_path = tmp_path / "startouch_sdk"
    interface = sdk_path / "interface_py"
    interface.mkdir(parents=True, exist_ok=True)
    return SdkBackendConfig(
        runtime=SimpleNamespace(
            root=sdk_path,
            interface_dir=interface,
            profile_id="thirdhand-conservative-safety-v1",
            sdk_version="0.1.7",
            config_sha256="a" * 64,
            runtime_manifest_sha256="b" * 64,
            reproducible_build_verified=True,
        ),
        can_interface="can0",
        lock_file=tmp_path / "startouch-web-can0.lock",
        gripper_max_width_m=0.080,
    )


def _sdk_backend(
    tmp_path: Path,
    arm: FakeSdkArm,
    *,
    observed_ids: object = range(0x11, 0x18),
) -> SdkBackend:
    return SdkBackend(
        _sdk_config(tmp_path),
        arm_factory=lambda _config: arm,
        feedback_probe_factory=lambda _interface: FakeFeedbackProbe(observed_ids),
        sleep=lambda _seconds: None,
    )


def test_can_feedback_probe_discards_locally_looped_back_command_ids() -> None:
    local_frames = [
        (struct.pack("=I", can_id) + b"\0" * 12, [], socket.MSG_DONTROUTE, ("can0",))
        for can_id in range(0x11, 0x18)
    ]
    inbound = (struct.pack("=I", 0x11) + b"\0" * 12, [], 0, ("can0",))
    probe = object.__new__(StartouchCanFeedbackProbe)
    probe._socket = FakeCanSocket([*local_frames, inbound])

    assert probe.read_observed_ids() == frozenset({0x11})


def test_sdk_connect_requires_all_real_startouch_feedback_ids(tmp_path: Path) -> None:
    arm = FakeSdkArm()
    backend = _sdk_backend(tmp_path, arm, observed_ids=range(0x11, 0x17))

    with pytest.raises(BackendError, match="startouch_feedback_ids_missing"):
        backend.connect()

    assert arm.cleaned is True


def test_sdk_connect_preserves_contained_library_origin_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from native.startouch import backends
    from native.startouch.vendor_runtime import StartouchRuntimeError

    monkeypatch.setattr(
        backends.importlib,
        "import_module",
        lambda _name: SimpleNamespace(
            __version__="0.1.7", SingleArm=lambda **_kwargs: FakeSdkArm()
        ),
    )
    monkeypatch.setattr(
        backends,
        "assert_loaded_startouch_library",
        lambda _root: (_ for _ in ()).throw(
            StartouchRuntimeError("runtime_library_not_loaded")
        ),
    )
    backend = SdkBackend(
        _sdk_config(tmp_path),
        feedback_probe_factory=lambda _interface: FakeFeedbackProbe(
            range(0x11, 0x18)
        ),
        sleep=lambda _seconds: None,
    )

    with pytest.raises(BackendError, match="runtime_library_not_loaded"):
        backend.connect()


def test_same_can_lock_rejects_second_owner(tmp_path: Path) -> None:
    first = CanOwner(tmp_path / "startouch-web-can0.lock")
    second = CanOwner(tmp_path / "startouch-web-can0.lock")
    first.acquire()
    try:
        with pytest.raises(ResourceLockedError, match="robot_resource_locked"):
            second.acquire()
    finally:
        first.release()


def test_sdk_connect_latches_measured_pose_and_reports_explicit_flange_state(
    tmp_path: Path,
) -> None:
    arm = FakeSdkArm()
    backend = _sdk_backend(tmp_path, arm)

    backend.connect()

    assert arm.hold_calls == []
    assert backend.state() == {
        "connected": True,
        "healthy": True,
        "moving": False,
        "flange_position_m": [0.45, 0.0, 0.25],
        "flange_euler_rad": [0.0, 0.0, 0.0],
        "joints_deg": [
            math.degrees(value) for value in [0.0, 0.20, -0.20, 0.10, 0.0, 0.0]
        ],
        "velocities_deg_s": [0.0] * 6,
        "gripper_width_m": 0.080,
    }
    backend.disconnect()


def test_sdk_state_accepts_validated_tracker_idle_velocity_noise(
    tmp_path: Path,
) -> None:
    """Reuse TH-Fanxy's measured 2 deg/s stationary noise envelope."""
    arm = FakeSdkArm()
    arm.velocities = [
        math.radians(value) for value in [0.11, 0.34, 0.11, 1.26, 0.42, -0.42]
    ]
    backend = _sdk_backend(tmp_path, arm)

    backend.connect()
    state = backend.state()

    assert state["moving"] is False
    backend.disconnect()


def test_sdk_connect_waits_through_zero_to_real_feedback_transition(
    tmp_path: Path,
) -> None:
    actual = [-0.001, 0.20, -0.10, 0.577, 0.006, 0.0]
    arm = StartupFeedbackArm(actual)
    sleep_calls: list[float] = []

    def sdk_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)
        if seconds >= 2.0:
            arm.feedback_ready = True

    backend = SdkBackend(
        _sdk_config(tmp_path),
        arm_factory=lambda _config: arm,
        feedback_probe_factory=lambda _interface: FakeFeedbackProbe(
            range(0x11, 0x18)
        ),
        sleep=sdk_sleep,
    )

    backend.connect()

    assert sleep_calls[0] >= 2.0
    assert arm.hold_calls == []
    assert backend.state()["joints_deg"] == pytest.approx([
        math.degrees(value) for value in actual
    ])
    backend.disconnect()


def test_sdk_rejects_startup_joint_inside_three_degree_stop_margin(
    tmp_path: Path,
) -> None:
    arm = FakeSdkArm()
    arm.joints = [0.0, 0.20, -0.004, 0.10, 0.0, 0.0]
    backend = _sdk_backend(tmp_path, arm)

    with pytest.raises(BackendError, match="joint_state_inside_stop_margin"):
        backend.connect()

    assert arm.cleaned is True


def test_real_cli_keeps_vendor_stdout_out_of_json_protocol(tmp_path: Path) -> None:
    sdk_path = tmp_path / "startouch_sdk"
    sdk_path.mkdir()
    script = f"""
import json
import os
from native.startouch import startouch_bridge as bridge
from pathlib import Path
from types import SimpleNamespace

runtime_root = Path({str(sdk_path)!r})
bridge.PROJECT_ROOT = runtime_root.parent
bridge.validate_startouch_runtime = lambda *_: SimpleNamespace(
    root=runtime_root,
    interface_dir=runtime_root / "interface_py",
    library_dir=runtime_root / "src",
    profile_id="thirdhand-conservative-safety-v1",
    sdk_version="0.1.7",
    config_sha256="a" * 64,
    runtime_manifest_sha256="b" * 64,
    reproducible_build_verified=True,
)
os.environ["LD_LIBRARY_PATH"] = str(runtime_root / "src")

class NoisyBackend:
    def __init__(self, config):
        self.connected = False
        self.depowered = False
        self.config = config
        self.safety_profile_id = config.runtime.profile_id
        self.safety_config_sha256 = config.runtime.config_sha256
        self.runtime_manifest_id = "sha256:" + config.runtime.runtime_manifest_sha256
        self.startup_feedback_ids = list(range(0x11, 0x18))

    def connect(self):
        print("vendor startup log", flush=True)
        self.connected = True
        return {{"connected": True}}

    def state(self):
        return {{
            "connected": self.connected,
            "healthy": self.connected,
            "moving": False,
            "flange_position_m": [0.45, 0.0, 0.25],
            "flange_euler_rad": [0.0, 0.0, 0.0],
            "joints_deg": [0.0] * 6,
            "velocities_deg_s": [0.0] * 6,
            "gripper_width_m": 0.08,
        }}

    def execute(self, command):
        if command.cmd == "get_state":
            return {{"reached": True}}
        if command.cmd == "software_stop":
            print("vendor cleanup log", flush=True)
            self.connected = False
            return {{
                "cleanup_acknowledged": True,
                "cleanup_confirmation_mode": "vendor_cleanup_returned",
                "depower_independently_confirmed": False,
                "control_released": True,
            }}
        raise RuntimeError(command.cmd)

    def force_release_for_process_exit(self):
        self.connected = False

bridge.SdkBackend = NoisyBackend
raise SystemExit(bridge.main([
        "--real",
        "--runtime-root", {str(sdk_path)!r},
        "--source-manifest", {str(tmp_path / 'source.json')!r},
        "--expected-safety-config-sha256", {('a' * 64)!r},
        "--lock-file", {str(tmp_path / 'startouch.lock')!r},
        "--allow-real", "I_ACCEPT_SUPERVISED_ROBOT_MOTION",
]))
"""
    commands = "\n".join([
        json.dumps({"cmd": "get_state", "request_id": "state"}),
        json.dumps({"cmd": "software_stop", "request_id": "stop"}),
        "",
    ])

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=PROJECT_ROOT,
        input=commands,
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    messages = [json.loads(line) for line in result.stdout.splitlines() if line]
    assert messages[0]["type"] == "bridge_ready"
    assert any(message.get("request_id") == "stop" for message in messages)
    assert "vendor startup log" not in result.stdout
    assert "vendor cleanup log" not in result.stdout
    assert "vendor startup log" in result.stderr
    assert "vendor cleanup log" in result.stderr


def test_move_completion_uses_actual_flange_feedback_not_sdk_return(
    tmp_path: Path,
) -> None:
    arm = FakeSdkArm(actual_position=[0.410, 0.0, 0.25])
    backend = _sdk_backend(tmp_path, arm)
    backend.connect()
    command = validate_command({
        "cmd": "move_l", "request_id": "move-feedback",
        "flange_position_m": [0.400, 0.0, 0.25],
        "flange_euler_rad": [0.0, 0.0, 0.0],
        "duration_sec": 1.0,
        "position_tolerance_m": 0.005,
        "orientation_tolerance_rad": 0.035,
    })

    completion = backend.execute(command)

    assert completion["reached"] is False
    assert completion["actual_flange_position_m"] == [0.410, 0.0, 0.25]
    assert completion["position_error_m"] == pytest.approx(0.010)
    backend.disconnect()


def test_cleanup_failure_never_claims_depowered_or_releases_owner(
    tmp_path: Path,
) -> None:
    arm = FakeSdkArm(cleanup_error=RuntimeError("cleanup failed"))
    backend = _sdk_backend(tmp_path, arm)
    backend.connect()

    with pytest.raises(
        StopNotConfirmedError, match="software_stop_cleanup_not_acknowledged"
    ):
        backend.execute(validate_command({
            "cmd": "software_stop", "request_id": "stop-failed",
        }))

    assert backend.depowered is False
    contender = CanOwner(_sdk_config(tmp_path).lock_file)
    with pytest.raises(ResourceLockedError, match="robot_resource_locked"):
        contender.acquire()
    backend.force_release_for_process_exit()


def test_cleanup_failure_can_retry_only_cleanup(
    tmp_path: Path,
) -> None:
    arm = FakeSdkArm(cleanup_error=RuntimeError("cleanup failed once"))
    backend = _sdk_backend(tmp_path, arm)
    backend.connect()
    stop = validate_command({
        "cmd": "software_stop", "request_id": "stop-retry",
    })

    with pytest.raises(
        StopNotConfirmedError, match="software_stop_cleanup_not_acknowledged"
    ):
        backend.execute(stop)
    with pytest.raises(BackendError, match="robot_not_connected"):
        backend.execute(validate_command({
            "cmd": "move_joint", "request_id": "motion-after-stop-failure",
            "joints_rad": [0.0] * 6, "duration_sec": 1.0,
        }))

    arm.cleanup_error = None
    assert backend.execute(stop) == {
        "cleanup_acknowledged": True,
        "cleanup_confirmation_mode": "vendor_cleanup_returned",
        "depower_independently_confirmed": False,
        "control_released": True,
    }
    assert backend.depowered is False
    contender = CanOwner(_sdk_config(tmp_path).lock_file)
    contender.acquire()
    contender.release()


def test_successful_software_stop_acknowledges_cleanup_without_claiming_depower(
    tmp_path: Path,
) -> None:
    arm = FakeSdkArm()
    backend = _sdk_backend(tmp_path, arm)
    backend.connect()

    result = backend.execute(validate_command({
        "cmd": "software_stop", "request_id": "stop-ok",
    }))

    assert result == {
        "cleanup_acknowledged": True,
        "cleanup_confirmation_mode": "vendor_cleanup_returned",
        "depower_independently_confirmed": False,
        "control_released": True,
    }
    assert arm.cleaned is True
    assert backend.depowered is False
    contender = CanOwner(_sdk_config(tmp_path).lock_file)
    contender.acquire()
    contender.release()
