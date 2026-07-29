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
    normalized: dict[str, list[float] | None] = {}
    for name in POINT_NAMES:
        value = waypoints.get(name)
        normalized[name] = (
            validate_waypoint(name, value, limits)
            if value is not None or require_all_points
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
    gripper_timeout = float(gripper.get("timeout_s", 5.0))
    open_position = float(gripper.get("open_position", 1.0))
    close_position = float(gripper.get("close_position", 0.0))
    if min_time <= 0 or timeout <= 0 or settle < 0 or gripper_timeout <= 0:
        raise ConfigurationError("motion/gripper timing values are invalid")
    if not 0 <= open_position <= 1 or not 0 <= close_position <= 1:
        raise ConfigurationError("gripper positions must be between 0 and 1")

    raw["joint_limits_deg"] = limits
    raw["joint_max_speeds_deg_s"] = max_speeds
    raw["waypoints"] = normalized
    raw["speed_scale"] = speed_scale
    raw["motion"] = {
        **motion,
        "min_time_s": min_time,
        "timeout_s": timeout,
        "settle_s": settle,
    }
    raw["gripper"] = {
        **gripper,
        "timeout_s": gripper_timeout,
        "open_position": open_position,
        "close_position": close_position,
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
        source: str,
    ) -> None:
        if self.latest_joints_deg is None:
            raise BridgeError("current joint state is unavailable")
        duration = max(
            min_time_s,
            max(
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
        self._send(
            {
                "cmd": "move_joint",
                "joints_rad": [math.radians(value) for value in target_deg],
                "time_sec": duration,
                "request_id": request_id,
                "source": source,
            }
        )
        self._wait_for(
            lambda item: (
                item.get("type") == "command_complete"
                and item.get("command") == "move_joint"
                and item.get("request_id") == request_id
            ),
            min(timeout_s, duration + 10.0),
        )
        self.latest_joints_deg = list(target_deg)

    def set_gripper(self, position: float, timeout_s: float) -> None:
        self._send({"cmd": "gripper", "position": position})
        event = self._wait_for(
            lambda item: (
                item.get("type") == "command_complete"
                and item.get("command") == "gripper"
            ),
            timeout_s,
        )
        if not event.get("reached", False):
            raise BridgeError(str(event.get("message", "gripper failed to reach target")))

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
        confirm: Callable[[str], str] = input,
    ):
        self.bridge = bridge
        self.config = config
        self.mode = mode
        self.log = logger
        self.confirm_each_step = confirm_each_step
        self.confirm = confirm

    def _confirm_step(self, state: str) -> None:
        if not self.confirm_each_step:
            return
        answer = self.confirm(
            f"[{state}] Press Enter to execute this step; type STOP to abort: "
        )
        if answer.strip().upper() == "STOP":
            raise UserAbort(f"operator aborted before {state}")

    def run(self) -> None:
        failed = True
        self.log.info("STATE IDLE mode=%s", self.mode)
        try:
            current = self.bridge.connect()
            self.log.info(
                "connected current_joints_deg=%s",
                ", ".join(f"{value:.3f}" for value in current),
            )
            for state, kind, target in ACTION_SEQUENCE:
                self.log.info("STATE %s", state)
                self._confirm_step(state)
                if kind == "move":
                    joints = self.config["waypoints"][target]
                    assert joints is not None
                    self.log.info(
                        "%s target=%s speed_scale=%.4f",
                        target,
                        ", ".join(f"{value:.3f}" for value in joints),
                        self.config["speed_scale"],
                    )
                    self.bridge.move(
                        joints,
                        speed_scale=self.config["speed_scale"],
                        max_speeds_deg_s=self.config["joint_max_speeds_deg_s"],
                        min_time_s=self.config["motion"]["min_time_s"],
                        timeout_s=self.config["motion"]["timeout_s"],
                        source=f"fixed_pick_place:{target}",
                    )
                    time.sleep(self.config["motion"]["settle_s"])
                else:
                    position = self.config["gripper"][f"{target}_position"]
                    self.log.info("gripper %s target=%.3f", target, position)
                    self.bridge.set_gripper(
                        position,
                        self.config["gripper"]["timeout_s"],
                    )
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
            if config["speed_scale"] > 0.05:
                raise ConfigurationError("real-arm speed scale must not exceed 0.05")
            if not args.confirm_each_step:
                raise ConfigurationError(
                    "real mode requires --confirm-each-step for the first safe run"
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
