"""Shared loopback-only camera and stable robot-state readers for calibration."""

from __future__ import annotations

import json
import math
import time
from urllib.parse import urlparse

import numpy as np
from websockets.sync.client import connect

from vision_models.calibration_capture import (
    CalibrationCaptureError,
    ReadOnlyRobotState,
    parse_robot_state,
)


def loopback_url(value: str, schemes: set[str], name: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in schemes or not parsed.hostname:
        raise CalibrationCaptureError(f"{name} has an invalid URL")
    if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise CalibrationCaptureError(f"{name} must be loopback")
    return value


def _rotation_delta_rad(first: np.ndarray, second: np.ndarray) -> float:
    relative = first[:3, :3].T @ second[:3, :3]
    return math.acos(float(np.clip((np.trace(relative) - 1.0) / 2.0, -1.0, 1.0)))


def read_stable_robot_state(url: str, timeout_s: float = 5.0) -> ReadOnlyRobotState:
    """Request only status and require three mutually consistent stationary readings."""

    loopback_url(url, {"ws", "wss"}, "robot state")
    deadline = time.monotonic() + timeout_s
    stable: list[ReadOnlyRobotState] = []
    with connect(url, open_timeout=timeout_s, close_timeout=1.0, max_size=1024 * 1024) as socket:
        socket.send(json.dumps({"cmd": "status"}, separators=(",", ":")))
        while time.monotonic() < deadline:
            try:
                payload = json.loads(socket.recv(timeout=max(0.05, deadline - time.monotonic())))
                state = parse_robot_state(payload)
            except (json.JSONDecodeError, CalibrationCaptureError, TimeoutError):
                continue
            if stable:
                position_delta = float(
                    np.linalg.norm(
                        state.t_base_from_flange[:3, 3]
                        - stable[-1].t_base_from_flange[:3, 3]
                    )
                )
                rotation_delta = _rotation_delta_rad(
                    stable[-1].t_base_from_flange,
                    state.t_base_from_flange,
                )
                joint_delta = max(
                    abs(first - second)
                    for first, second in zip(
                        state.joints_deg, stable[-1].joints_deg, strict=True
                    )
                )
                if (
                    position_delta > 0.001
                    or rotation_delta > math.radians(0.5)
                    or joint_delta > 0.2
                ):
                    stable.clear()
            stable.append(state)
            if len(stable) >= 3:
                return stable[-1]
    raise CalibrationCaptureError("three stable robot-state readings were not available")


__all__ = ["loopback_url", "read_stable_robot_state"]
