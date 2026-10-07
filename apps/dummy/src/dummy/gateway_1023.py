from __future__ import annotations

from dataclasses import dataclass


JOINT_LIMITS_DEG = [
    [-162, 162],
    [-12, 201],
    [-183, 0],
    [-98, 98],
    [-98, 98],
    [-164, 164],
]


@dataclass
class PolicyResult:
    ok: bool
    message: dict | None = None
    code: str | None = None
    reason: str | None = None


class Gateway1023Policy:
    """Safety filter for the 31023 debug gateway."""

    def __init__(
        self,
        *,
        max_delta_deg=None,
        min_interval_s=0.0,
        min_time_sec=0.5,
        joint_limits=None,
    ):
        self.max_delta_deg = None if max_delta_deg is None else float(max_delta_deg)
        self.min_interval_s = float(min_interval_s)
        self.min_time_sec = float(min_time_sec)
        self.joint_limits = joint_limits or JOINT_LIMITS_DEG
        self.last_motion_at = None

    def validate(self, message, current_joints, *, now):
        command = message.get("cmd") if isinstance(message, dict) else None
        if command in {"connect", "disconnect", "ping", "status", "get_state", "software_stop"}:
            return PolicyResult(True, _with_request_id(message, {"cmd": command}))
        if command == "preset" and message.get("name") in {"home", "zero"}:
            return PolicyResult(True, _with_request_id(message, {"cmd": "preset", "name": message.get("name")}))
        if command not in {"move_joint", "servo"}:
            return PolicyResult(False, code="command_blocked", reason="only connect/disconnect/home/zero/move_joint/servo/status/software_stop are allowed")

        joint_field = "joints" if command == "servo" else "joints_deg"
        joints = message.get(joint_field)
        if not _finite_vector(joints, 6):
            return PolicyResult(False, code="joint_target_invalid", reason=f"{joint_field} must contain six finite values")
        if not _finite_vector(current_joints, 6):
            return PolicyResult(False, code="robot_state_unavailable", reason="fresh robot joints are required")

        for index, (value, limits) in enumerate(zip(joints, self.joint_limits), start=1):
            lo, hi = float(limits[0]), float(limits[1])
            if float(value) < lo or float(value) > hi:
                return PolicyResult(False, code="joint_limit", reason=f"J{index} outside [{lo}, {hi}] deg")

        requested_joints = [float(value) for value in joints]
        max_delta = max(abs(float(dst) - float(src)) for dst, src in zip(requested_joints, current_joints))
        if command == "servo" and self.max_delta_deg is not None and max_delta > self.max_delta_deg:
            requested_joints = [
                float(src) + _clamp(float(dst) - float(src), -self.max_delta_deg, self.max_delta_deg)
                for dst, src in zip(requested_joints, current_joints)
            ]
            max_delta = self.max_delta_deg
        if self.max_delta_deg is not None and max_delta > self.max_delta_deg:
            return PolicyResult(False, code="relative_step_limit", reason=f"relative move {max_delta:.3f} deg exceeds {self.max_delta_deg:.3f} deg")

        if self.min_interval_s > 0.0 and self.last_motion_at is not None and float(now) - self.last_motion_at < self.min_interval_s:
            return PolicyResult(False, code="rate_limited", reason="motion commands are arriving too quickly")

        self.last_motion_at = float(now)
        if command == "servo":
            filtered = {
                "cmd": "servo",
                "joints": requested_joints,
            }
        else:
            filtered = {
                "cmd": "move_joint",
                "joints_deg": requested_joints,
                "time_sec": max(self.min_time_sec, float(message.get("time_sec", self.min_time_sec) or self.min_time_sec)),
                "source": "dummy_1023_gateway",
            }
        return PolicyResult(True, _with_request_id(message, filtered))


def _finite_vector(value, length):
    if not isinstance(value, list) or len(value) != length:
        return False
    try:
        return all(_is_finite(float(item)) for item in value)
    except (TypeError, ValueError):
        return False


def _is_finite(value):
    return value == value and value not in (float("inf"), float("-inf"))


def _clamp(value, lo, hi):
    return min(max(value, lo), hi)


def _with_request_id(source, message):
    request_id = source.get("request_id") if isinstance(source, dict) else None
    if isinstance(request_id, str) and request_id:
        message["request_id"] = request_id
    return message
