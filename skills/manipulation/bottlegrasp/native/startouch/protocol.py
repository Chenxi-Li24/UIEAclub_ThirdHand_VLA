"""Strict, hardware-independent Startouch JSON-Lines protocol."""

from __future__ import annotations

from dataclasses import dataclass
import math
from types import MappingProxyType
from typing import Any, Mapping


PROTOCOL_SCHEMA = "thirdhand-startouch-bridge-v1"
LOW_LEVEL_PROTOCOL = "thirdhand-robot-lowlevel-v1"
COMMANDS = frozenset({
    "connect",
    "disconnect",
    "get_state",
    "gripper",
    "move_joint",
    "move_l",
    "software_stop",
})
POSE_FRAME = "robot_flange"
STATE_UNITS = MappingProxyType({
    "position": "m",
    "orientation": "rad",
    "joints": "deg",
    "joint_velocity": "deg/s",
    "gripper": "m",
})
SHA256_ID_PREFIX = "sha256:"


class ProtocolError(ValueError):
    """A command violates the low-level protocol contract."""


@dataclass(frozen=True, slots=True)
class RobotCommand:
    """Validated command with an immutable payload."""

    cmd: str
    request_id: str
    payload: Mapping[str, Any]


def _finite_vector(value: Any, length: int, reason: str) -> tuple[float, ...]:
    if (
        not isinstance(value, list)
        or len(value) != length
        or not all(isinstance(item, (int, float)) and math.isfinite(float(item))
                   for item in value)
    ):
        raise ProtocolError(reason)
    return tuple(float(item) for item in value)


def _finite_range(
    value: Any,
    minimum: float,
    maximum: float,
    reason: str,
) -> float:
    if (
        not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or not minimum <= float(value) <= maximum
    ):
        raise ProtocolError(reason)
    return float(value)


def _assert_keys(message: Mapping[str, Any], allowed: set[str]) -> None:
    if set(message) - allowed:
        raise ProtocolError("command_keys_invalid")


def validate_command(message: Mapping[str, Any]) -> RobotCommand:
    """Validate one untrusted bridge command without guessing units or fields."""
    if not isinstance(message, Mapping):
        raise ProtocolError("command_object_invalid")
    cmd = message.get("cmd")
    if not isinstance(cmd, str) or cmd not in COMMANDS:
        raise ProtocolError("command_unsupported")
    request_id = message.get("request_id")
    if (
        not isinstance(request_id, str)
        or not request_id.strip()
        or len(request_id) > 128
    ):
        raise ProtocolError("request_id_invalid")
    common = {"cmd", "request_id", "source"}
    source = message.get("source")
    if source is not None and (
        not isinstance(source, str) or not source or len(source) > 128
    ):
        raise ProtocolError("source_invalid")
    payload: dict[str, Any] = {}

    if cmd == "move_l":
        _assert_keys(message, common | {
            "flange_position_m",
            "flange_euler_rad",
            "duration_sec",
            "position_tolerance_m",
            "orientation_tolerance_rad",
        })
        payload["flange_position_m"] = _finite_vector(
            message.get("flange_position_m"), 3, "flange_position_m_invalid"
        )
        payload["flange_euler_rad"] = _finite_vector(
            message.get("flange_euler_rad"), 3, "flange_euler_rad_invalid"
        )
        payload["duration_sec"] = _finite_range(
            message.get("duration_sec"), 0.001, 30.0, "duration_sec_invalid"
        )
        payload["position_tolerance_m"] = _finite_range(
            message.get("position_tolerance_m", 0.005),
            0.0001,
            0.020,
            "position_tolerance_m_invalid",
        )
        payload["orientation_tolerance_rad"] = _finite_range(
            message.get("orientation_tolerance_rad", 0.035),
            0.001,
            0.20,
            "orientation_tolerance_rad_invalid",
        )
    elif cmd == "move_joint":
        _assert_keys(message, common | {"joints_rad", "duration_sec"})
        payload["joints_rad"] = _finite_vector(
            message.get("joints_rad"), 6, "joints_rad_invalid"
        )
        payload["duration_sec"] = _finite_range(
            message.get("duration_sec"), 0.001, 30.0, "duration_sec_invalid"
        )
    elif cmd == "gripper":
        _assert_keys(message, common | {"position"})
        payload["position"] = _finite_range(
            message.get("position"), 0.0, 1.0, "gripper_position_invalid"
        )
    elif cmd == "software_stop":
        _assert_keys(message, common | {"reason"})
        reason = message.get("reason")
        if reason is not None and (
            not isinstance(reason, str) or not reason or len(reason) > 128
        ):
            raise ProtocolError("stop_reason_invalid")
        if reason is not None:
            payload["reason"] = reason
    else:
        _assert_keys(message, common)

    if source is not None:
        payload["source"] = source
    return RobotCommand(cmd, request_id, MappingProxyType(payload))


def valid_content_id(value: Any) -> bool:
    """Return whether value is a canonical SHA-256 content ID."""
    if not isinstance(value, str) or not value.startswith(SHA256_ID_PREFIX):
        return False
    digest = value[len(SHA256_ID_PREFIX):]
    return len(digest) == 64 and all(character in "0123456789abcdef" for character in digest)


__all__ = [
    "COMMANDS",
    "LOW_LEVEL_PROTOCOL",
    "POSE_FRAME",
    "PROTOCOL_SCHEMA",
    "ProtocolError",
    "RobotCommand",
    "STATE_UNITS",
    "valid_content_id",
    "validate_command",
]
