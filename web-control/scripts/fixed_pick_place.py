#!/usr/bin/env python3
"""Run a taught, fixed-joint Pick and Place through the Startouch bridge."""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
from pathlib import Path
import queue
import signal
import subprocess
import sys
import threading
import time
import uuid
from typing import Any, Callable

import yaml


POINT_NAMES = (
    "home",
    "pre_pick",
    "pick",
    "lift",
    "pre_place",
    "place",
    "retreat",
    "a_up",
    "b_up",
)

ACTION_SEQUENCE = (
    ("MOVE_HOME", "move", "home"),
    ("MOVE_PRE_PICK", "move", "pre_pick"),
    ("MOVE_PICK", "move", "pick"),
    ("CLOSE_GRIPPER", "gripper", "close"),
    ("MOVE_LIFT", "move", "lift"),
    ("MOVE_PRE_PLACE", "move", "pre_place"),
    ("MOVE_PLACE", "move", "place"),
    ("OPEN_GRIPPER", "gripper", "open"),
    ("MOVE_RETREAT", "move", "retreat"),
    ("RETURN_HOME", "move", "home"),
)

SIMPLE_AB_ACTION_SEQUENCE = (
    ("OPEN_GRIPPER_READY", "gripper", "open"),
    ("MOVE_A", "move", "pre_pick"),
    ("CLOSE_GRIPPER", "gripper", "close"),
    ("MOVE_B", "move", "place"),
    ("OPEN_GRIPPER", "gripper", "open"),
)

HOME_TRANSIT_AB_ACTION_SEQUENCE = (
    ("OPEN_GRIPPER_READY", "gripper", "open"),
    ("MOVE_HOME_START", "move", "home"),
    ("APPROACH_A_UP", "move", "a_up"),
    ("DESCEND_TO_A_PICK", "move", "pre_pick"),
    ("ADAPTIVE_GRASP_A", "adaptive_gripper", "grasp"),
    ("LIFT_A", "move", "a_up"),
    ("TRANSFER_A_UP_TO_B_UP", "move", "b_up"),
    ("DESCEND_TO_B", "move", "place"),
    ("RELEASE_AT_B", "gripper", "open"),
    ("LIFT_AFTER_RELEASE_B", "move", "b_up"),
    ("RETURN_B_UP_TO_HOME", "move", "home"),
    ("MOVE_HOME_TO_B_UP", "move", "b_up"),
    ("DESCEND_TO_B_RETURN", "move", "place"),
    ("ADAPTIVE_GRASP_B", "adaptive_gripper", "grasp"),
    ("LIFT_B", "move", "b_up"),
    ("TRANSFER_B_UP_TO_A_UP", "move", "a_up"),
    ("DESCEND_TO_A", "move", "pre_pick"),
    ("RELEASE_AT_A", "gripper", "open"),
    ("LIFT_AFTER_RELEASE_A", "move", "a_up"),
    ("RETURN_A_UP_TO_HOME", "move", "home"),
)


def action_sequence_for(config: dict[str, Any]) -> tuple[tuple[str, str, str], ...]:
    if config.get("workflow") == "home_transit_ab":
        return HOME_TRANSIT_AB_ACTION_SEQUENCE
    if config.get("workflow") == "simple_ab":
        return SIMPLE_AB_ACTION_SEQUENCE
    return ACTION_SEQUENCE


def interpolate_joint_path(
    start_deg: list[float],
    target_deg: list[float],
    max_step_deg: float,
) -> list[list[float]]:
    """Build a linear joint path with bounded adjacent joint increments."""
    if max_step_deg <= 0 or not math.isfinite(max_step_deg):
        raise ConfigurationError("motion.execution_chunk_deg must be positive")
    remaining = max(
        abs(target - start)
        for start, target in zip(start_deg, target_deg)
    )
    segment_count = max(1, math.ceil(remaining / max_step_deg))
    return [
        [
            start + (target - start) * index / segment_count
            for start, target in zip(start_deg, target_deg)
        ]
        for index in range(1, segment_count + 1)
    ]


class PickPlaceError(RuntimeError):
    """Base error for fixed Pick and Place."""


class ConfigurationError(PickPlaceError):
    """The point configuration is missing or unsafe."""


class BridgeError(PickPlaceError):
    """The Startouch bridge rejected or failed a command."""


class MotionTimeout(PickPlaceError):
    """A Startouch command did not complete before its deadline."""


class UserAbort(PickPlaceError):
    """The operator cancelled a progressively confirmed run."""


def validate_waypoint(
    name: str,
    values: Any,
    limits: list[list[float]],
) -> list[float]:
    if values is None:
        raise ConfigurationError(f"waypoint '{name}' has not been taught")
    if not isinstance(values, (list, tuple)) or len(values) != 6:
        raise ConfigurationError(f"waypoint '{name}' must contain exactly six joints")
    try:
        joints = [float(value) for value in values]
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(f"waypoint '{name}' contains a non-numeric joint") from exc
    if not all(math.isfinite(value) for value in joints):
        raise ConfigurationError(f"waypoint '{name}' contains NaN or infinity")
    if max(abs(value) for value in joints) < 0.05:
        raise ConfigurationError(f"waypoint '{name}' is an unsafe all-zero target")
    for index, (value, bounds) in enumerate(zip(joints, limits), start=1):
        if value < bounds[0] or value > bounds[1]:
            raise ConfigurationError(
                f"waypoint '{name}' J{index}={value:.3f} is outside "
                f"[{bounds[0]:.3f}, {bounds[1]:.3f}] degrees"
            )
    return joints


def load_config(path: Path, *, require_all_points: bool = True) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigurationError(f"configuration not found: {path}") from exc
    except yaml.YAMLError as exc:
        raise ConfigurationError(f"invalid YAML in {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigurationError("configuration root must be a mapping")

    limits = raw.get("joint_limits_deg")
    if (
        not isinstance(limits, list)
        or len(limits) != 6
        or any(not isinstance(item, list) or len(item) != 2 for item in limits)
    ):
        raise ConfigurationError("joint_limits_deg must contain six [min, max] pairs")
    limits = [[float(item[0]), float(item[1])] for item in limits]
    if any(not all(math.isfinite(value) for value in item) or item[0] >= item[1] for item in limits):
        raise ConfigurationError("joint_limits_deg contains invalid bounds")

    max_speeds = raw.get("joint_max_speeds_deg_s")
    if not isinstance(max_speeds, list) or len(max_speeds) != 6:
        raise ConfigurationError("joint_max_speeds_deg_s must contain six values")
    max_speeds = [float(value) for value in max_speeds]
    if any(not math.isfinite(value) or value <= 0 for value in max_speeds):
        raise ConfigurationError("joint_max_speeds_deg_s must be finite and positive")

    waypoints = raw.get("waypoints")
    if not isinstance(waypoints, dict):
        raise ConfigurationError("waypoints must be a mapping")
    workflow = str(raw.get("workflow", "full"))
    if workflow not in {"full", "simple_ab", "home_transit_ab"}:
        raise ConfigurationError(
            "workflow must be 'full', 'simple_ab', or 'home_transit_ab'"
        )
    required_points = (
        {"home", "pre_pick", "place"}
        if workflow == "simple_ab"
        else {"home", "pre_pick", "place", "a_up", "b_up"}
        if workflow == "home_transit_ab"
        else {
            "home",
            "pre_pick",
            "pick",
            "lift",
            "pre_place",
            "place",
            "retreat",
        }
    )
    normalized: dict[str, list[float] | None] = {}
    for name in POINT_NAMES:
        value = waypoints.get(name)
        normalized[name] = (
            validate_waypoint(name, value, limits)
            if value is not None or (require_all_points and name in required_points)
            else None
        )

    speed_scale = float(raw.get("speed_scale", 0.05))
    if not math.isfinite(speed_scale) or not 0 < speed_scale <= 1:
        raise ConfigurationError("speed_scale must be in (0, 1]")

    motion = raw.get("motion", {})
    gripper = raw.get("gripper", {})
    if not isinstance(motion, dict) or not isinstance(gripper, dict):
        raise ConfigurationError("motion and gripper must be mappings")
    min_time = float(motion.get("min_time_s", 0.5))
    timeout = float(motion.get("timeout_s", 45.0))
    settle = float(motion.get("settle_s", 0.2))
    target_tolerance = float(motion.get("target_tolerance_deg", 2.0))
    gripper_timeout = float(gripper.get("timeout_s", 5.0))
    open_position = float(gripper.get("open_position", 1.0))
    close_position = float(gripper.get("close_position", 0.0))
    grasp_position = float(gripper.get("grasp_position", close_position))
    adaptive_grasp = raw.get("adaptive_grasp", {})
    if not isinstance(adaptive_grasp, dict):
        raise ConfigurationError("adaptive_grasp must be a mapping")
    adaptive_preload = float(adaptive_grasp.get("preload_position", 0.025))
    adaptive_min_contact = float(
        adaptive_grasp.get("min_contact_position", 0.08)
    )
    adaptive_kp = float(adaptive_grasp.get("kp", 2.0))
    adaptive_kd = float(adaptive_grasp.get("kd", 0.1))
    open_kp = float(gripper.get("open_kp", 8.0))
    if (
        min_time <= 0
        or timeout <= 0
        or settle < 0
        or target_tolerance <= 0
        or gripper_timeout <= 0
    ):
        raise ConfigurationError("motion/gripper timing values are invalid")
    if (
        not 0 <= open_position <= 1
        or not 0 <= close_position <= 1
        or not 0 <= grasp_position <= 1
    ):
        raise ConfigurationError("gripper positions must be between 0 and 1")
    if (
        not 0 < adaptive_preload <= 0.10
        or not 0 < adaptive_min_contact < 1
        or not 0.1 <= adaptive_kp <= 20.0
        or not 0.1 <= adaptive_kd <= 1.0
        or not 0.1 <= open_kp <= 20.0
    ):
        raise ConfigurationError("adaptive gripper values are invalid")

    raw["joint_limits_deg"] = limits
    raw["joint_max_speeds_deg_s"] = max_speeds
    raw["waypoints"] = normalized
    raw["workflow"] = workflow
    raw["speed_scale"] = speed_scale
    raw["motion"] = {
        **motion,
        "min_time_s": min_time,
        "timeout_s": timeout,
        "settle_s": settle,
        "target_tolerance_deg": target_tolerance,
    }
    max_segment_delta = motion.get("max_segment_delta_deg")
    if max_segment_delta is not None:
        if not isinstance(max_segment_delta, list) or len(max_segment_delta) != 6:
            raise ConfigurationError(
                "motion.max_segment_delta_deg must contain six values"
            )
        max_segment_delta = [float(value) for value in max_segment_delta]
        if any(
            not math.isfinite(value) or value <= 0
            for value in max_segment_delta
        ):
            raise ConfigurationError(
                "motion.max_segment_delta_deg must be finite and positive"
            )
        raw["motion"]["max_segment_delta_deg"] = max_segment_delta
    raw["gripper"] = {
        **gripper,
        "timeout_s": gripper_timeout,
        "open_position": open_position,
        "close_position": close_position,
        "grasp_position": grasp_position,
        "open_kp": open_kp,
    }
    raw["adaptive_grasp"] = {
        **adaptive_grasp,
        "preload_position": adaptive_preload,
        "min_contact_position": adaptive_min_contact,
        "kp": adaptive_kp,
        "kd": adaptive_kd,
    }
    demo = raw.get("demo", {})
    if not isinstance(demo, dict):
        raise ConfigurationError("demo must be a mapping")
    validated_cycles = int(demo.get("validated_real_cycles", 0))
    if validated_cycles < 0:
        raise ConfigurationError("demo.validated_real_cycles cannot be negative")
    cycles = int(demo.get("cycles", 1))
    if not 1 <= cycles <= 100:
        raise ConfigurationError("demo.cycles must be between 1 and 100")
    demo_speed = float(demo.get("speed_scale", speed_scale))
    if not math.isfinite(demo_speed) or not 0 < demo_speed <= 0.20:
        raise ConfigurationError("demo.speed_scale must be in (0, 0.20]")
    raw["demo"] = {
        **demo,
        "cycles": cycles,
        "validated_real_cycles": validated_cycles,
        "speed_scale": demo_speed,
        "require_step_confirmation": bool(
            demo.get("require_step_confirmation", validated_cycles < 3)
        ),
    }
    return raw


class BridgeClient:
    """JSON-lines client for the existing hardware-tested Startouch bridge."""

    def __init__(self, bridge_path: Path, mode: str, logger: logging.Logger):
        self.bridge_path = bridge_path
        self.mode = mode
        self.log = logger
        self.process: subprocess.Popen[str] | None = None
        self.events: queue.Queue[dict[str, Any]] = queue.Queue()
        self.latest_joints_deg: list[float] | None = None
        self.latest_gripper_position: float | None = None
        self.latest_tcp_position_m: list[float] | None = None
        self.latest_tcp_euler_rad: list[float] | None = None
        self._event_stream = None
        self._reader_threads: list[threading.Thread] = []

    def start(self) -> None:
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        env["STARTOUCH_SIMULATE"] = "1" if self.mode == "simulate" else "0"
        env["STARTOUCH_DRY_RUN"] = "1" if self.mode == "dry-run" else "0"
        popen_kwargs: dict[str, Any] = {
            "cwd": str(self.bridge_path.parent),
            "env": env,
            "stdin": subprocess.PIPE,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": True,
            "bufsize": 1,
        }
        event_read_fd = event_write_fd = None
        if os.name == "posix":
            event_read_fd, event_write_fd = os.pipe()
            env["STARTOUCH_EVENT_FD"] = str(event_write_fd)
            popen_kwargs["pass_fds"] = (event_write_fd,)
        self.process = subprocess.Popen(
            [sys.executable, "-u", str(self.bridge_path)],
            **popen_kwargs,
        )
        if event_write_fd is not None:
            os.close(event_write_fd)
            self._event_stream = os.fdopen(event_read_fd, "r", encoding="utf-8")
            assert self.process.stdout is not None
            self._start_drain(self.process.stdout, logging.INFO, "SDK")
        else:
            self._event_stream = self.process.stdout
        assert self.process.stderr is not None
        self._start_drain(self.process.stderr, logging.WARNING, "bridge stderr")
        reader = threading.Thread(target=self._read_events, daemon=True)
        reader.start()
        self._reader_threads.append(reader)
        self._wait_for(lambda event: event.get("type") == "bridge_ready", 5.0)

    def _start_drain(self, stream, level: int, label: str) -> None:
        def drain() -> None:
            for line in stream:
                if line.strip():
                    self.log.log(level, "%s: %s", label, line.rstrip())

        thread = threading.Thread(target=drain, daemon=True)
        thread.start()
        self._reader_threads.append(thread)

    def _read_events(self) -> None:
        assert self._event_stream is not None
        for line in self._event_stream:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                self.log.warning("unparseable bridge event: %s", line.rstrip())
                continue
            if event.get("type") == "robot_state":
                joints = event.get("joints_rad")
                if isinstance(joints, list) and len(joints) == 6:
                    self.latest_joints_deg = [math.degrees(float(value)) for value in joints]
                position = event.get("gripper_position")
                if isinstance(position, (int, float)) and math.isfinite(position):
                    self.latest_gripper_position = float(position)
                tcp_position = event.get("tcp_position_m")
                tcp_euler = event.get("tcp_euler_rad")
                if isinstance(tcp_position, list) and len(tcp_position) == 3:
                    self.latest_tcp_position_m = [
                        float(value) for value in tcp_position
                    ]
                if isinstance(tcp_euler, list) and len(tcp_euler) == 3:
                    self.latest_tcp_euler_rad = [
                        float(value) for value in tcp_euler
                    ]
            if event.get("type") in {
                "connection",
                "motion_state",
                "command_accepted",
                "command_complete",
                "error",
            }:
                self.log.info("bridge event: %s", json.dumps(event, ensure_ascii=False))
            self.events.put(event)

    def _send(self, command: dict[str, Any]) -> None:
        if self.process is None or self.process.poll() is not None or self.process.stdin is None:
            raise BridgeError("Startouch bridge is not running")
        self.process.stdin.write(json.dumps(command, separators=(",", ":")) + "\n")
        self.process.stdin.flush()

    def _wait_for(
        self,
        predicate: Callable[[dict[str, Any]], bool],
        timeout_s: float,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout_s
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise MotionTimeout(f"bridge event timed out after {timeout_s:.1f}s")
            try:
                event = self.events.get(timeout=remaining)
            except queue.Empty as exc:
                raise MotionTimeout(f"bridge event timed out after {timeout_s:.1f}s") from exc
            if event.get("type") == "error":
                raise BridgeError(str(event.get("message", "unknown bridge error")))
            if predicate(event):
                return event

    def connect(self, timeout_s: float = 10.0) -> list[float]:
        self._send({"cmd": "connect"})
        event = self._wait_for(
            lambda item: item.get("type") == "connection",
            timeout_s,
        )
        if not event.get("connected"):
            raise BridgeError(str(event.get("error") or event.get("reason") or "connect failed"))
        if self.latest_joints_deg is None:
            self._send({"cmd": "get_state"})
            self._wait_for(lambda item: item.get("type") == "robot_state", timeout_s)
        if self.latest_joints_deg is None:
            raise BridgeError("bridge did not publish six joint positions")
        return list(self.latest_joints_deg)

    def move(
        self,
        target_deg: list[float],
        *,
        speed_scale: float,
        max_speeds_deg_s: list[float],
        min_time_s: float,
        timeout_s: float,
        target_tolerance_deg: float,
        source: str,
    ) -> None:
        self.move_path(
            [target_deg],
            speed_scale=speed_scale,
            max_speeds_deg_s=max_speeds_deg_s,
            min_time_s=min_time_s,
            timeout_s=timeout_s,
            target_tolerance_deg=target_tolerance_deg,
            source=source,
            command="move_joint",
        )

    def move_path(
        self,
        waypoints_deg: list[list[float]],
        *,
        speed_scale: float,
        max_speeds_deg_s: list[float],
        min_time_s: float,
        timeout_s: float,
        target_tolerance_deg: float,
        source: str,
        command: str = "move_joint_path",
    ) -> None:
        if self.latest_joints_deg is None:
            raise BridgeError("current joint state is unavailable")
        if not waypoints_deg:
            raise ConfigurationError("joint path must contain at least one waypoint")
        target_deg = waypoints_deg[-1]
        # The SDK uses a smooth quintic trajectory whose peak velocity is
        # 1.875 times average delta/duration. Account for that factor so the
        # requested speed scale is also a peak-speed limit.
        duration = max(
            min_time_s,
            1.875 * max(
                abs(target - current) / (speed * speed_scale)
                for target, current, speed in zip(
                    target_deg,
                    self.latest_joints_deg,
                    max_speeds_deg_s,
                )
            ),
        )
        if duration > 30.0:
            raise ConfigurationError(
                f"required move duration {duration:.2f}s exceeds bridge limit; "
                "teach a closer waypoint or increase the non-real test speed"
            )
        request_id = str(uuid.uuid4())
        payload: dict[str, Any] = {
            "cmd": command,
            "time_sec": duration,
            "request_id": request_id,
            "source": source,
        }
        if command == "move_joint":
            payload["joints_rad"] = [
                math.radians(value) for value in target_deg
            ]
        else:
            payload["waypoints_rad"] = [
                [math.radians(value) for value in point]
                for point in waypoints_deg
            ]
        self._send(payload)
        self._wait_for(
            lambda item: (
                item.get("type") == "command_complete"
                and item.get("command") == command
                and item.get("request_id") == request_id
            ),
            min(timeout_s, duration + 10.0),
        )
        if self.mode == "dry-run":
            self.latest_joints_deg = list(target_deg)
            return
        requested_after_ms = int(time.time() * 1000)
        self._send({"cmd": "get_state"})
        self._wait_for(
            lambda item: (
                item.get("type") == "robot_state"
                and int(item.get("ts", 0)) >= requested_after_ms
            ),
            3.0,
        )
        if self.latest_joints_deg is None:
            raise BridgeError("post-motion joint feedback is unavailable")
        errors = [
            abs(actual - target)
            for actual, target in zip(self.latest_joints_deg, target_deg)
        ]
        if max(errors) > target_tolerance_deg:
            details = ", ".join(
                f"J{index + 1}={error:.3f}deg"
                for index, error in enumerate(errors)
            )
            raise BridgeError(
                "post-motion target error exceeds "
                f"{target_tolerance_deg:.3f}deg: {details}"
            )
        self.log.info(
            "post-motion feedback target_error_deg=%s",
            ", ".join(f"{error:.3f}" for error in errors),
        )

    def set_gripper(
        self,
        position: float,
        timeout_s: float,
        *,
        kp: float | None = None,
        kd: float | None = None,
    ) -> None:
        start = self.latest_gripper_position
        command: dict[str, Any] = {"cmd": "gripper", "position": position}
        if kp is not None:
            command["kp"] = kp
        if kd is not None:
            command["kd"] = kd
        self._send(command)
        event = self._wait_for(
            lambda item: (
                item.get("type") == "command_complete"
                and item.get("command") == "gripper"
            ),
            timeout_s,
        )
        if event.get("reached", False):
            return
        # A close command normally stops on the object (or the gripper's
        # mechanical minimum), so exact zero-position convergence is not a
        # valid success requirement.  Still require meaningful motion and a
        # substantially closed feedback position; opening remains strict.
        actual = event.get("actual_position")
        closing = (
            isinstance(start, (int, float))
            and math.isfinite(start)
            and position < start
        )
        if (
            closing
            and event.get("moved", False)
            and isinstance(actual, (int, float))
            and math.isfinite(actual)
            and actual <= start - 0.03
        ):
            self.log.info(
                "gripper close accepted on obstruction "
                "target=%.3f actual_position=%.3f",
                position,
                actual,
            )
            return
        raise BridgeError(str(event.get("message", "gripper failed to reach target")))

    def adaptive_grasp(
        self,
        timeout_s: float,
        *,
        preload_position: float,
        min_contact_position: float,
        kp: float,
        kd: float,
    ) -> None:
        if self.mode == "dry-run":
            self.set_gripper(0.5, timeout_s)
            self.log.info("adaptive grasp dry-run contact_position=0.500")
            return
        start = self.latest_gripper_position
        if not isinstance(start, (int, float)) or not math.isfinite(start):
            raise BridgeError("gripper feedback is unavailable before adaptive grasp")
        self._send(
            {"cmd": "gripper", "position": 0.0, "kp": kp, "kd": kd}
        )
        contact = self._wait_for(
            lambda item: (
                item.get("type") == "command_complete"
                and item.get("command") == "gripper"
            ),
            timeout_s,
        )
        actual = contact.get("actual_position")
        if not isinstance(actual, (int, float)) or not math.isfinite(actual):
            raise BridgeError("adaptive grasp did not produce valid feedback")
        if (
            contact.get("reached", False)
            or actual < min_contact_position
            or actual > 0.95
        ):
            raise BridgeError(
                "adaptive grasp reached the closed limit without detecting an object"
            )
        if not contact.get("moved", False):
            self.log.info(
                "adaptive grasp detected pre-existing contact at %.3f",
                actual,
            )
        self.log.info(
            "adaptive grasp contact_position=%.3f "
            "holding_with_low_stiffness_kp=%.3f",
            actual,
            kp,
        )

    def software_stop(self) -> None:
        try:
            self._send({"cmd": "software_stop"})
            self._wait_for(
                lambda item: (
                    item.get("type") == "connection"
                    and not item.get("connected")
                ),
                3.0,
            )
        except PickPlaceError as exc:
            self.log.error("software stop could not be confirmed: %s", exc)

    def close(self, *, failed: bool = False) -> None:
        if self.process is None:
            return
        if self.process.poll() is None:
            if failed:
                self.software_stop()
            else:
                try:
                    self._send({"cmd": "disconnect", "reason": "pick_place_complete"})
                    self._wait_for(
                        lambda item: (
                            item.get("type") == "connection"
                            and not item.get("connected")
                        ),
                        3.0,
                    )
                except PickPlaceError as exc:
                    self.log.warning("normal disconnect was not confirmed: %s", exc)
            try:
                self._send({"cmd": "shutdown"})
            except PickPlaceError:
                pass
            try:
                self.process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                try:
                    self.process.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    self.process.kill()
        self.process = None


class FixedPickPlaceRunner:
    def __init__(
        self,
        bridge: Any,
        config: dict[str, Any],
        mode: str,
        logger: logging.Logger,
        *,
        confirm_each_step: bool = False,
        motion_only: bool = False,
        resume_at_adaptive_a: bool = False,
        resume_at_adaptive_b: bool = False,
        confirm: Callable[[str], str] = input,
    ):
        self.bridge = bridge
        self.config = config
        self.mode = mode
        self.log = logger
        self.confirm_each_step = confirm_each_step
        self.motion_only = motion_only
        self.resume_at_adaptive_a = resume_at_adaptive_a
        self.resume_at_adaptive_b = resume_at_adaptive_b
        self.confirm = confirm

    def _confirm_step(self, state: str) -> None:
        if not self.confirm_each_step:
            return
        print(f"AWAITING_CONFIRMATION={state}", flush=True)
        try:
            answer = self.confirm(
                f"[{state}] Press Enter to execute this step; type STOP to abort: "
            )
        except EOFError as exc:
            raise UserAbort("operator confirmation channel closed") from exc
        if answer.strip().upper() == "STOP":
            raise UserAbort(f"operator aborted before {state}")

    def _move_closed_loop(self, target: str, joints: list[float]) -> None:
        motion = self.config["motion"]
        chunk_deg = float(motion.get("execution_chunk_deg", 0.0))
        final_tolerance = float(
            motion.get("final_target_tolerance_deg", 1.0)
        )
        if self.mode == "simulate" or chunk_deg <= 0:
            self.bridge.move(
                joints,
                speed_scale=self.config["speed_scale"],
                max_speeds_deg_s=self.config["joint_max_speeds_deg_s"],
                min_time_s=motion["min_time_s"],
                timeout_s=motion["timeout_s"],
                target_tolerance_deg=motion.get(
                    "target_tolerance_deg",
                    2.0,
                ),
                source=f"fixed_pick_place:{target}",
            )
            return

        current = getattr(self.bridge, "latest_joints_deg", None)
        if current is None:
            raise BridgeError("current joint feedback is unavailable")
        remaining = max(
            abs(goal - actual) for goal, actual in zip(joints, current)
        )
        if remaining <= final_tolerance:
            self.log.info(
                "%s reached final_tolerance_deg=%.3f remaining=%.3f",
                target,
                final_tolerance,
                remaining,
            )
            return
        path = interpolate_joint_path(current, joints, chunk_deg)
        self.log.info(
            "%s continuous_path points=%d remaining_deg=%.3f max_step_deg=%.3f",
            target,
            len(path),
            remaining,
            chunk_deg,
        )
        self.bridge.move_path(
            path,
            speed_scale=self.config["speed_scale"],
            max_speeds_deg_s=self.config["joint_max_speeds_deg_s"],
            min_time_s=motion["min_time_s"],
            timeout_s=motion["timeout_s"],
            target_tolerance_deg=final_tolerance,
            source=f"fixed_pick_place:{target}:continuous",
        )
        tcp_position = getattr(self.bridge, "latest_tcp_position_m", None)
        tcp_euler = getattr(self.bridge, "latest_tcp_euler_rad", None)
        if tcp_position is not None and tcp_euler is not None:
            self.log.info(
                "%s tcp_pose=%s",
                target,
                ",".join(
                    f"{value:.9f}"
                    for value in [*tcp_position, *tcp_euler]
                ),
            )

    def run(self) -> None:
        failed = True
        self.log.info("STATE IDLE mode=%s", self.mode)
        try:
            current = self.bridge.connect()
            self.log.info(
                "connected current_joints_deg=%s",
                ", ".join(f"{value:.3f}" for value in current),
            )
            sequence = action_sequence_for(self.config)
            if self.resume_at_adaptive_a:
                current = getattr(self.bridge, "latest_joints_deg", None)
                target_a = self.config["waypoints"]["pre_pick"]
                if current is None or max(
                    abs(actual - target)
                    for actual, target in zip(current, target_a)
                ) > 1.0:
                    raise ConfigurationError(
                        "--resume-at-adaptive-a requires the arm to be at A "
                        "within 1 degree"
                    )
                start_index = next(
                    index
                    for index, action in enumerate(sequence)
                    if action[0] == "ADAPTIVE_GRASP_A"
                )
                sequence = sequence[start_index:]
                self.log.info("resuming sequence at ADAPTIVE_GRASP_A")
            elif self.resume_at_adaptive_b:
                current = getattr(self.bridge, "latest_joints_deg", None)
                target_b = self.config["waypoints"]["place"]
                if current is None or max(
                    abs(actual - target)
                    for actual, target in zip(current, target_b)
                ) > 1.0:
                    raise ConfigurationError(
                        "--resume-at-adaptive-b requires the arm to be at B "
                        "within 1 degree"
                    )
                start_index = next(
                    index
                    for index, action in enumerate(sequence)
                    if action[0] == "ADAPTIVE_GRASP_B"
                )
                sequence = sequence[start_index:]
                self.log.info("resuming sequence at ADAPTIVE_GRASP_B")
            cycles = (
                1
                if (self.resume_at_adaptive_a or self.resume_at_adaptive_b)
                else self.config.get("demo", {}).get("cycles", 1)
            )
            first_move = True
            for cycle_index in range(1, cycles + 1):
                self.log.info("CYCLE %d/%d START", cycle_index, cycles)
                for state, kind, target in sequence:
                    self.log.info("STATE %s", state)
                    self._confirm_step(f"CYCLE_{cycle_index}_{state}")
                    if kind == "move":
                        joints = self.config["waypoints"][target]
                        assert joints is not None
                        max_segment_delta = self.config["motion"].get(
                            "max_segment_delta_deg"
                        )
                        current = getattr(self.bridge, "latest_joints_deg", None)
                        if (
                            max_segment_delta is not None
                            and current is not None
                            and (self.mode == "real" or not first_move)
                        ):
                            deltas = [
                                abs(goal - actual)
                                for goal, actual in zip(joints, current)
                            ]
                            violations = [
                                f"J{index + 1}={delta:.3f}>{limit:.3f}"
                                for index, (delta, limit) in enumerate(
                                    zip(deltas, max_segment_delta)
                                )
                                if delta > limit
                            ]
                            if violations:
                                raise ConfigurationError(
                                    "segment jump rejected: " + ", ".join(violations)
                                )
                        self.log.info(
                            "%s target=%s speed_scale=%.4f",
                            target,
                            ", ".join(f"{value:.3f}" for value in joints),
                            self.config["speed_scale"],
                        )
                        self._move_closed_loop(target, joints)
                        first_move = False
                        time.sleep(self.config["motion"]["settle_s"])
                    elif kind == "gripper":
                        position = self.config["gripper"][f"{target}_position"]
                        self.log.info("gripper %s target=%.3f", target, position)
                        self.bridge.set_gripper(
                            position,
                            self.config["gripper"]["timeout_s"],
                            kp=(
                                self.config["gripper"].get("open_kp", 8.0)
                                if target == "open"
                                else None
                            ),
                        )
                    else:
                        if self.motion_only:
                            self.log.info(
                                "adaptive grasp skipped for empty trajectory validation"
                            )
                            continue
                        adaptive = self.config["adaptive_grasp"]
                        self.bridge.adaptive_grasp(
                            self.config["gripper"]["timeout_s"],
                            preload_position=adaptive["preload_position"],
                            min_contact_position=adaptive["min_contact_position"],
                            kp=adaptive["kp"],
                            kd=adaptive["kd"],
                        )
                self.log.info("CYCLE %d/%d COMPLETE", cycle_index, cycles)
            self.log.info("STATE COMPLETE")
            failed = False
        finally:
            self.bridge.close(failed=failed)


def configure_logging(root: Path) -> tuple[logging.Logger, Path]:
    log_dir = root / "logs" / "fixed_pick_place"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / time.strftime("run-%Y%m%d-%H%M%S.log")
    logger = logging.getLogger("fixed_pick_place")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)
    return logger, log_path


def build_parser(root: Path) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=root / "configs" / "tasks" / "fixed_pick_place.yaml",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--simulate", action="store_true")
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--real", action="store_true")
    parser.add_argument("--speed-scale", type=float)
    parser.add_argument("--confirm-each-step", action="store_true")
    parser.add_argument(
        "--motion-only",
        action="store_true",
        help="skip adaptive grasps for supervised empty-trajectory validation",
    )
    parser.add_argument(
        "--resume-at-adaptive-a",
        action="store_true",
        help="resume a supervised run with the arm already positioned at A",
    )
    parser.add_argument(
        "--resume-at-adaptive-b",
        action="store_true",
        help="resume a supervised run with the arm already positioned at B",
    )
    return parser


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    args = build_parser(root).parse_args()
    mode = "real" if args.real else "dry-run" if args.dry_run else "simulate"
    logger, log_path = configure_logging(root)
    bridge: BridgeClient | None = None
    try:
        config = load_config(args.config)
        if args.speed_scale is not None:
            if not 0 < args.speed_scale <= 1:
                raise ConfigurationError("--speed-scale must be in (0, 1]")
            config["speed_scale"] = args.speed_scale
        if mode == "real":
            if config["speed_scale"] > 0.20:
                raise ConfigurationError("real-arm speed scale must not exceed 0.20")
            if (
                not args.confirm_each_step
                and (
                    config["demo"]["validated_real_cycles"] < 3
                    or config["demo"]["require_step_confirmation"]
                )
            ):
                raise ConfigurationError(
                    "real mode requires --confirm-each-step until three "
                    "validated real cycles are recorded"
                )
        bridge = BridgeClient(
            root / "web-control" / "server" / "startouch_bridge.py",
            mode,
            logger,
        )
        runner = FixedPickPlaceRunner(
            bridge,
            config,
            mode,
            logger,
            confirm_each_step=args.confirm_each_step,
            motion_only=args.motion_only,
            resume_at_adaptive_a=args.resume_at_adaptive_a,
            resume_at_adaptive_b=args.resume_at_adaptive_b,
        )

        def handle_interrupt(_signum, _frame):
            raise KeyboardInterrupt

        signal.signal(signal.SIGINT, handle_interrupt)
        bridge.start()
        runner.run()
        logger.info("run log: %s", log_path)
        return 0
    except KeyboardInterrupt:
        logger.error("operator interrupt received; stopping sequence")
        return 130
    except PickPlaceError as exc:
        logger.error("%s", exc)
        return 1
    finally:
        if bridge is not None and bridge.process is not None:
            bridge.close(failed=True)
        logger.info("final log: %s", log_path)


if __name__ == "__main__":
    raise SystemExit(main())
