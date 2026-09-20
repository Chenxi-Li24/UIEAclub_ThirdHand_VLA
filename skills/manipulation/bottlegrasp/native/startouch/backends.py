"""Startouch backend implementations and single-controller ownership."""

from __future__ import annotations

from dataclasses import dataclass
import fcntl
import importlib
import math
import os
from pathlib import Path
import socket
import struct
import sys
import time
from typing import Any, Callable, Protocol

from .protocol import RobotCommand
from .vendor_runtime import (
    PROFILE_ID,
    RuntimeValidation,
    StartouchRuntimeError,
    assert_loaded_startouch_library,
)


class BackendError(RuntimeError):
    """A backend cannot execute or prove a command."""


class ResourceLockedError(BackendError):
    """Another process owns the selected CAN controller."""


class StopNotConfirmedError(BackendError):
    """The SDK cleanup call did not return successfully."""


class CanOwner:
    """Hold a nonblocking advisory lock for one CAN control process."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._stream: Any | None = None

    @property
    def acquired(self) -> bool:
        return self._stream is not None

    def acquire(self) -> None:
        if self._stream is not None:
            raise ResourceLockedError("robot_resource_locked")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        stream = self.path.open("a+", encoding="ascii")
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            stream.close()
            raise ResourceLockedError("robot_resource_locked") from error
        stream.seek(0)
        stream.truncate()
        stream.write(f"{os.getpid()}\n")
        stream.flush()
        self._stream = stream

    def release(self) -> None:
        stream = self._stream
        self._stream = None
        if stream is None:
            return
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        finally:
            stream.close()


JOINT_LIMITS_RAD = (
    (-math.radians(162), math.radians(162)),
    (-math.radians(12), math.radians(201)),
    (-math.radians(183), 0.0),
    (-math.radians(98), math.radians(98)),
    (-math.radians(98), math.radians(98)),
    (-math.radians(164), math.radians(164)),
)
JOINT_LIMIT_STOP_MARGIN_RAD = 0.05236
EXPECTED_STARTOUCH_FEEDBACK_IDS = frozenset(range(0x11, 0x18))
_CAN_EFF_MASK = 0x1FFFFFFF
_CAN_RTR_FLAG = 0x40000000
_CAN_ERR_FLAG = 0x20000000

# Startouch idle feedback is quantized and reaches about 1.26 deg/s on J4
# while the arm is physically still.  Reuse the 2.0 deg/s envelope validated
# by TH-Fanxy's deployed arm-state bridge; commanded motion remains well above
# this threshold and command completion still requires measured pose proof.
STATIONARY_MAX_VELOCITY_DEG_S = 2.0


class FeedbackProbe(Protocol):
    def read_observed_ids(self) -> frozenset[int]: ...

    def close(self) -> None: ...


class StartouchCanFeedbackProbe:
    """Passively observe inbound SocketCAN frames without writing any frame."""

    def __init__(self, interface: str) -> None:
        try:
            self._socket = socket.socket(socket.PF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
            self._socket.setblocking(False)
            self._socket.bind((interface,))
        except OSError as error:
            if getattr(self, "_socket", None) is not None:
                self._socket.close()
            raise BackendError("can_feedback_probe_unavailable") from error

    def read_observed_ids(self) -> frozenset[int]:
        observed: set[int] = set()
        while True:
            try:
                frame, _ancillary, flags, _address = self._socket.recvmsg(16)
            except BlockingIOError:
                break
            except OSError as error:
                raise BackendError("can_feedback_probe_failed") from error
            if flags & socket.MSG_DONTROUTE:
                continue
            if len(frame) < 4:
                raise BackendError("can_feedback_frame_invalid")
            raw_id = struct.unpack_from("=I", frame)[0]
            if raw_id & (_CAN_RTR_FLAG | _CAN_ERR_FLAG):
                continue
            observed.add(raw_id & _CAN_EFF_MASK)
        return frozenset(observed)

    def close(self) -> None:
        self._socket.close()


@dataclass(frozen=True, slots=True)
class SdkBackendConfig:
    """Validated settings for one real Startouch SDK instance."""

    runtime: RuntimeValidation
    can_interface: str
    lock_file: Path
    gripper_max_width_m: float = 0.080
    initialization_warmup_sec: float = 2.0
    initialization_samples: int = 3
    initialization_interval_sec: float = 0.05
    initialization_max_drift_rad: float = math.radians(2.0)

    def __post_init__(self) -> None:
        object.__setattr__(self, "lock_file", Path(self.lock_file).resolve())
        if (
            getattr(self.runtime, "profile_id", None) != PROFILE_ID
            or getattr(self.runtime, "sdk_version", None) != "0.1.7"
            or getattr(self.runtime, "reproducible_build_verified", None) is not True
            or not isinstance(self.can_interface, str)
            or not self.can_interface
            or "/" in self.can_interface
            or not math.isfinite(self.gripper_max_width_m)
            or not 0 < self.gripper_max_width_m <= 0.080
            or not math.isfinite(self.initialization_warmup_sec)
            or not 2.0 <= self.initialization_warmup_sec <= 5.0
            or not isinstance(self.initialization_samples, int)
            or self.initialization_samples < 2
            or not math.isfinite(self.initialization_interval_sec)
            or not 0 <= self.initialization_interval_sec <= 1.0
            or not math.isfinite(self.initialization_max_drift_rad)
            or not 0 < self.initialization_max_drift_rad <= math.radians(5.0)
        ):
            raise ValueError("sdk_backend_config_invalid")


class SimulatedBackend:
    """In-memory Startouch behavior for unit tests and VS Code debugging."""

    def __init__(self, *, gripper_max_width_m: float = 0.080) -> None:
        if not math.isfinite(gripper_max_width_m) or not 0 < gripper_max_width_m <= 0.080:
            raise ValueError("gripper_max_width_m_invalid")
        self.gripper_max_width_m = float(gripper_max_width_m)
        self.connected = False
        self.healthy = False
        self.depowered = False
        self.moving = False
        self.flange_position_m = [0.45, 0.0, 0.25]
        self.flange_euler_rad = [0.0, 0.0, 0.0]
        self.joints_deg = [0.0] * 6
        self.velocities_deg_s = [0.0] * 6
        self.gripper_width_m = self.gripper_max_width_m
        self.safety_profile_id = "simulation"
        self.safety_config_sha256 = "simulation"
        self.runtime_manifest_id = "simulation"
        self.startup_feedback_ids: list[int] = []

    def connect(self) -> dict[str, Any]:
        self.connected = True
        self.healthy = True
        self.depowered = False
        return {"connected": True}

    def state(self) -> dict[str, Any]:
        return {
            "connected": self.connected,
            "healthy": self.healthy,
            "moving": self.moving,
            "flange_position_m": list(self.flange_position_m),
            "flange_euler_rad": list(self.flange_euler_rad),
            "joints_deg": list(self.joints_deg),
            "velocities_deg_s": list(self.velocities_deg_s),
            "gripper_width_m": self.gripper_width_m,
        }

    def execute(self, command: RobotCommand) -> dict[str, Any]:
        if command.cmd == "connect":
            return self.connect()
        if command.cmd == "get_state":
            return {"reached": True}
        if command.cmd == "software_stop":
            self.moving = False
            self.connected = False
            self.healthy = False
            self.depowered = False
            return {
                "cleanup_acknowledged": True,
                "cleanup_confirmation_mode": "simulation",
                "depower_independently_confirmed": False,
                "control_released": True,
            }
        if command.cmd == "disconnect":
            self.connected = False
            self.healthy = False
            return {"disconnected": True}
        if not self.connected or not self.healthy:
            raise BackendError("robot_not_connected")
        if command.cmd == "move_l":
            self.flange_position_m = list(command.payload["flange_position_m"])
            self.flange_euler_rad = list(command.payload["flange_euler_rad"])
            return {
                "reached": True,
                "actual_flange_position_m": list(self.flange_position_m),
                "actual_flange_euler_rad": list(self.flange_euler_rad),
                "position_error_m": 0.0,
                "orientation_error_rad": 0.0,
                "robot_healthy": True,
            }
        if command.cmd == "move_joint":
            self.joints_deg = [
                math.degrees(value) for value in command.payload["joints_rad"]
            ]
            return {
                "reached": True,
                "actual_joints_deg": list(self.joints_deg),
                "robot_healthy": True,
            }
        if command.cmd == "gripper":
            self.gripper_width_m = (
                float(command.payload["position"]) * self.gripper_max_width_m
            )
            return {
                "reached": True,
                "actual_width_m": self.gripper_width_m,
                "robot_healthy": True,
            }
        raise BackendError("command_unsupported")


def _finite_values(values: Any, count: int, reason: str) -> list[float]:
    try:
        result = [float(value) for value in values]
    except (TypeError, ValueError) as error:
        raise BackendError(reason) from error
    if len(result) != count or not all(math.isfinite(value) for value in result):
        raise BackendError(reason)
    return result


def _default_arm_factory(config: SdkBackendConfig) -> Any:
    interface_path = Path(config.runtime.interface_dir).resolve()
    if not interface_path.is_dir():
        raise BackendError("startouch_sdk_interface_missing")
    path_text = str(interface_path)
    if path_text not in sys.path:
        sys.path.insert(0, path_text)
    try:
        module = importlib.import_module("startouchclass")
        arm_type = module.SingleArm
    except (ImportError, AttributeError) as error:
        raise BackendError("startouch_sdk_import_failed") from error
    if getattr(module, "__version__", None) != config.runtime.sdk_version:
        raise BackendError("startouch_sdk_version_mismatch")
    try:
        assert_loaded_startouch_library(config.runtime.root)
    except StartouchRuntimeError as error:
        raise BackendError(str(error)) from error
    return arm_type(
        can_interface_=config.can_interface,
        gripper=True,
        enable_fd_=False,
        dry_run=False,
    )


class SdkBackend:
    """Minimal fail-closed adapter around the installed Startouch SDK."""

    def __init__(
        self,
        config: SdkBackendConfig,
        *,
        arm_factory: Callable[[SdkBackendConfig], Any] = _default_arm_factory,
        feedback_probe_factory: Callable[[str], FeedbackProbe] = (
            StartouchCanFeedbackProbe
        ),
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.config = config
        self.arm_factory = arm_factory
        self.feedback_probe_factory = feedback_probe_factory
        self.sleep = sleep
        self.owner = CanOwner(config.lock_file)
        self.arm: Any | None = None
        self.connected = False
        self.healthy = False
        self.depowered = False
        self.moving = False
        self._last_snapshot: dict[str, Any] | None = None
        self.startup_feedback_ids: list[int] = []
        self.safety_profile_id = config.runtime.profile_id
        self.safety_config_sha256 = config.runtime.config_sha256
        self.runtime_manifest_id = (
            "sha256:" + config.runtime.runtime_manifest_sha256
        )

    def connect(self) -> dict[str, Any]:
        if self.connected or self.arm is not None or self.owner.acquired:
            raise BackendError("robot_already_connected")
        self.owner.acquire()
        arm: Any | None = None
        feedback_probe: FeedbackProbe | None = None
        try:
            feedback_probe = self.feedback_probe_factory(self.config.can_interface)
            arm = self.arm_factory(self.config)
            self.sleep(self.config.initialization_warmup_sec)
            samples = []
            for index in range(self.config.initialization_samples):
                samples.append(self._read_snapshot(arm))
                if index + 1 < self.config.initialization_samples:
                    self.sleep(self.config.initialization_interval_sec)
            for previous, current in zip(samples, samples[1:]):
                drift = max(
                    abs(after - before_value)
                    for before_value, after in zip(
                        previous["joints_rad"], current["joints_rad"]
                    )
                )
                if drift > self.config.initialization_max_drift_rad:
                    raise BackendError("robot_state_not_settled")
            snapshot = samples[-1]
            observed_ids = feedback_probe.read_observed_ids()
            if not EXPECTED_STARTOUCH_FEEDBACK_IDS.issubset(observed_ids):
                raise BackendError("startouch_feedback_ids_missing")
            self.startup_feedback_ids = sorted(EXPECTED_STARTOUCH_FEEDBACK_IDS)
            self.arm = arm
            self.connected = True
            self.healthy = True
            self.depowered = False
            self._last_snapshot = snapshot
            return {"connected": True}
        except Exception as error:
            if arm is not None:
                try:
                    arm.cleanup()
                except Exception:
                    pass
            self.owner.release()
            if isinstance(error, BackendError):
                raise
            raise BackendError("robot_connect_failed") from error
        finally:
            if feedback_probe is not None:
                feedback_probe.close()

    def state(self) -> dict[str, Any]:
        if self.arm is not None and self.connected:
            self._last_snapshot = self._read_snapshot(self.arm)
        snapshot = self._last_snapshot
        if snapshot is None:
            return {
                "connected": False,
                "healthy": False,
                "moving": False,
                "flange_position_m": [0.0, 0.0, 0.0],
                "flange_euler_rad": [0.0, 0.0, 0.0],
                "joints_deg": [0.0] * 6,
                "velocities_deg_s": [0.0] * 6,
                "gripper_width_m": 0.0,
            }
        velocities_deg_s = [
            math.degrees(value) for value in snapshot["velocities_rad_s"]
        ]
        moving = any(
            abs(value) > STATIONARY_MAX_VELOCITY_DEG_S
            for value in velocities_deg_s
        )
        self.moving = moving
        return {
            "connected": self.connected,
            "healthy": self.healthy,
            "moving": moving,
            "flange_position_m": list(snapshot["flange_position_m"]),
            "flange_euler_rad": list(snapshot["flange_euler_rad"]),
            "joints_deg": [math.degrees(value) for value in snapshot["joints_rad"]],
            "velocities_deg_s": velocities_deg_s,
            "gripper_width_m": snapshot["gripper_width_m"],
        }

    def execute(self, command: RobotCommand) -> dict[str, Any]:
        if command.cmd == "connect":
            return self.connect()
        if command.cmd == "software_stop":
            return self.software_stop()
        if command.cmd == "disconnect":
            self.disconnect()
            return {"disconnected": True}
        if command.cmd == "get_state":
            if not self.connected:
                raise BackendError("robot_not_connected")
            return {"reached": True}
        arm = self._require_arm()
        if command.cmd == "move_l":
            return self._move_l(arm, command)
        if command.cmd == "move_joint":
            return self._move_joint(arm, command)
        if command.cmd == "gripper":
            return self._move_gripper(arm, command)
        raise BackendError("command_unsupported")

    def software_stop(self) -> dict[str, Any]:
        arm = self.arm
        if arm is None:
            raise BackendError("robot_not_connected")
        try:
            arm.cleanup()
        except Exception as error:
            self.connected = False
            self.healthy = False
            self.depowered = False
            raise StopNotConfirmedError(
                "software_stop_cleanup_not_acknowledged"
            ) from error
        self.arm = None
        self.connected = False
        self.healthy = False
        self.depowered = False
        self.moving = False
        self.owner.release()
        return {
            "cleanup_acknowledged": True,
            "cleanup_confirmation_mode": "vendor_cleanup_returned",
            "depower_independently_confirmed": False,
            "control_released": True,
        }

    def disconnect(self) -> None:
        if self.arm is None:
            self.connected = False
            self.healthy = False
            self.owner.release()
            return
        self.software_stop()

    def force_release_for_process_exit(self) -> None:
        """Release process resources without claiming that power was removed."""
        arm = self.arm
        self.arm = None
        self.connected = False
        self.healthy = False
        if arm is not None:
            try:
                arm.cleanup()
            except Exception:
                pass
        self.owner.release()

    def _require_arm(self) -> Any:
        if self.arm is None or not self.connected or not self.healthy:
            raise BackendError("robot_not_connected")
        return self.arm

    def _read_snapshot(self, arm: Any) -> dict[str, Any]:
        joints = _finite_values(
            arm.get_joint_positions(), 6, "joint_state_invalid"
        )
        velocities = _finite_values(
            arm.get_joint_velocities(), 6, "joint_velocity_invalid"
        )
        for value, limits in zip(joints, JOINT_LIMITS_RAD):
            if not limits[0] <= value <= limits[1]:
                raise BackendError("joint_state_out_of_limits")
            if (
                value - limits[0] <= JOINT_LIMIT_STOP_MARGIN_RAD
                or limits[1] - value <= JOINT_LIMIT_STOP_MARGIN_RAD
            ):
                raise BackendError("joint_state_inside_stop_margin")
        position, euler = arm.get_ee_pose_euler()
        position_values = _finite_values(position, 3, "flange_position_invalid")
        euler_values = _finite_values(euler, 3, "flange_euler_invalid")
        gripper_width = float(arm.get_gripper_distance())
        gripper_position = float(arm.get_gripper_position())
        if (
            not math.isfinite(gripper_width)
            or not 0 <= gripper_width <= self.config.gripper_max_width_m + 0.001
            or not math.isfinite(gripper_position)
            or not 0 <= gripper_position <= 1.0
        ):
            raise BackendError("gripper_state_invalid")
        return {
            "joints_rad": joints,
            "velocities_rad_s": velocities,
            "flange_position_m": position_values,
            "flange_euler_rad": euler_values,
            "gripper_position": gripper_position,
            "gripper_width_m": gripper_width,
        }

    def _move_l(self, arm: Any, command: RobotCommand) -> dict[str, Any]:
        target_position = list(command.payload["flange_position_m"])
        target_euler = list(command.payload["flange_euler_rad"])
        arm.move_l(
            [[*target_position, *target_euler]],
            time_sec=command.payload["duration_sec"],
            blend_radius_m=0.0,
            position_tolerance_m=command.payload["position_tolerance_m"],
            orientation_tolerance_rad=command.payload[
                "orientation_tolerance_rad"
            ],
        )
        snapshot = self._read_snapshot(arm)
        self._last_snapshot = snapshot
        actual_position = snapshot["flange_position_m"]
        actual_euler = snapshot["flange_euler_rad"]
        position_error = math.dist(target_position, actual_position)
        orientation_error = math.sqrt(sum(
            math.atan2(math.sin(actual - target), math.cos(actual - target)) ** 2
            for actual, target in zip(actual_euler, target_euler)
        ))
        reached = (
            position_error <= command.payload["position_tolerance_m"]
            and orientation_error <= command.payload["orientation_tolerance_rad"]
        )
        return {
            "reached": reached,
            "actual_flange_position_m": list(actual_position),
            "actual_flange_euler_rad": list(actual_euler),
            "position_error_m": position_error,
            "orientation_error_rad": orientation_error,
            "robot_healthy": self.healthy,
        }

    def _move_joint(self, arm: Any, command: RobotCommand) -> dict[str, Any]:
        target = list(command.payload["joints_rad"])
        arm.set_joint_waypoints(
            [target], time_sec=command.payload["duration_sec"]
        )
        snapshot = self._read_snapshot(arm)
        self._last_snapshot = snapshot
        max_error = max(
            abs(actual - expected)
            for actual, expected in zip(snapshot["joints_rad"], target)
        )
        return {
            "reached": max_error <= math.radians(0.5),
            "actual_joints_deg": [
                math.degrees(value) for value in snapshot["joints_rad"]
            ],
            "max_joint_error_deg": math.degrees(max_error),
            "robot_healthy": self.healthy,
        }

    def _move_gripper(self, arm: Any, command: RobotCommand) -> dict[str, Any]:
        target = float(command.payload["position"])
        arm.setGripperPosition(target)
        previous: float | None = None
        stable_samples = 0
        snapshot: dict[str, Any] | None = None
        for _ in range(30):
            snapshot = self._read_snapshot(arm)
            current = snapshot["gripper_position"]
            stable_samples = stable_samples + 1 if (
                previous is not None and abs(current - previous) <= 0.002
            ) else 0
            previous = current
            if stable_samples >= 3:
                break
            self.sleep(0.05)
        if snapshot is None:
            raise BackendError("gripper_feedback_missing")
        self._last_snapshot = snapshot
        return {
            "reached": stable_samples >= 3,
            "actual_width_m": snapshot["gripper_width_m"],
            "robot_healthy": self.healthy,
        }


__all__ = [
    "BackendError",
    "CanOwner",
    "ResourceLockedError",
    "SdkBackend",
    "SdkBackendConfig",
    "SimulatedBackend",
    "StartouchCanFeedbackProbe",
    "StopNotConfirmedError",
]
