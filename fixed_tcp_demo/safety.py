from __future__ import annotations

import math
import os
import socket
from typing import Iterable


JOINT_LIMITS_RAD = [
    (-math.radians(162), math.radians(162)),
    (-math.radians(12), math.radians(201)),
    (-math.radians(183), 0.0),
    (-math.radians(98), math.radians(98)),
    (-math.radians(98), math.radians(98)),
    (-math.radians(164), math.radians(164)),
]

WORKSPACE_LIMITS_M = ((0.15, 0.66), (-0.65, 0.45), (0.04, 0.65))


class SafetyError(RuntimeError):
    """Raised when a target is unsafe or not solvable."""


def finite_vector(values: Iterable[float], count: int, label: str) -> list[float]:
    result = [float(value) for value in values]
    if len(result) != count or not all(math.isfinite(value) for value in result):
        raise SafetyError(f"{label} must contain {count} finite values")
    return result


def assert_workspace_position(position: Iterable[float]) -> list[float]:
    pos = finite_vector(position, 3, "TCP position")
    for index, (value, (lower, upper)) in enumerate(zip(pos, WORKSPACE_LIMITS_M), start=1):
        if value < lower or value > upper:
            raise SafetyError(
                f"target XYZ axis {index}={value:.4f}m is outside "
                f"[{lower:.3f}, {upper:.3f}]m"
            )
    return pos


def assert_joint_limits(joints: Iterable[float]) -> list[float]:
    q = finite_vector(joints, 6, "joint target")
    for index, (value, (lower, upper)) in enumerate(zip(q, JOINT_LIMITS_RAD), start=1):
        if value < lower or value > upper:
            raise SafetyError(
                f"IK target J{index}={math.degrees(value):.2f}deg is outside "
                f"[{math.degrees(lower):.1f}, {math.degrees(upper):.1f}]deg"
            )
    return q


def assert_known_collision_zones(joints: Iterable[float]) -> list[float]:
    q = assert_joint_limits(joints)
    j3 = q[2]
    j4 = q[3]
    j5 = q[4]
    j6 = q[5]

    if abs(j5) > math.radians(58):
        raise SafetyError("wrist risk zone: J5 is too close to the SDK documented +/-90deg case")

    if abs(j4) > math.radians(90):
        raise SafetyError("J4 risk zone: keep at least 8deg away from the mechanical limit")

    if abs(j3 - -0.7685) < math.radians(10) and j4 > math.radians(75):
        raise SafetyError("J3/J4 foldback risk zone from SDK self-collision examples")

    if abs(j3 - -0.37) < math.radians(10) and j4 > math.radians(58):
        raise SafetyError("J3/J4 foldback risk zone near link56/link1")

    if abs(j3 - -0.543) < math.radians(10) and j4 > math.radians(58) and abs(j6) > math.radians(70):
        raise SafetyError("J3/J4/J6 foldback risk zone from SDK self-collision examples")

    elbow_distance = math.hypot(j3 - -2.912226, j4 - -0.267559)
    if elbow_distance < math.radians(16):
        raise SafetyError("elbow singularity risk zone from SDK singularity examples")

    return q


def assert_step_size(current: Iterable[float], target: Iterable[float], max_delta_rad: float) -> None:
    before = finite_vector(current, 6, "current joints")
    after = finite_vector(target, 6, "target joints")
    delta = max(abs(a - b) for a, b in zip(after, before))
    if delta > max_delta_rad:
        raise SafetyError(
            f"joint step {math.degrees(delta):.2f}deg exceeds "
            f"{math.degrees(max_delta_rad):.2f}deg"
        )


def assert_joint_acceleration(
    previous: Iterable[float],
    current: Iterable[float],
    target: Iterable[float],
    max_delta_rad: float,
) -> None:
    before = finite_vector(previous, 6, "previous joints")
    middle = finite_vector(current, 6, "current joints")
    after = finite_vector(target, 6, "target joints")
    delta = max(abs(a - 2.0 * b + c) for a, b, c in zip(after, middle, before))
    if delta > max_delta_rad:
        raise SafetyError(
            f"joint acceleration step {math.degrees(delta):.2f}deg exceeds "
            f"{math.degrees(max_delta_rad):.2f}deg"
        )


def assert_orientation_delta(
    center_rpy: Iterable[float],
    target_rpy: Iterable[float],
    max_delta_rad: float,
) -> list[float]:
    center = finite_vector(center_rpy, 3, "center RPY")
    target = finite_vector(target_rpy, 3, "target RPY")
    delta = max(abs(a - b) for a, b in zip(target, center))
    if delta > max_delta_rad:
        raise SafetyError(
            f"RPY delta {math.degrees(delta):.2f}deg exceeds "
            f"{math.degrees(max_delta_rad):.2f}deg"
        )
    return target


def euler_to_quaternion_wxyz(euler: Iterable[float]) -> list[float]:
    roll, pitch, yaw = finite_vector(euler, 3, "Euler angles")
    cr = math.cos(roll * 0.5)
    sr = math.sin(roll * 0.5)
    cp = math.cos(pitch * 0.5)
    sp = math.sin(pitch * 0.5)
    cy = math.cos(yaw * 0.5)
    sy = math.sin(yaw * 0.5)
    return [
        cr * cp * cy + sr * sp * sy,
        sr * cp * cy - cr * sp * sy,
        cr * sp * cy + sr * cp * sy,
        cr * cp * sy - sr * sp * cy,
    ]


def require_can_interface(name: str) -> None:
    path = os.path.join("/sys/class/net", name)
    if not os.path.isdir(path):
        raise SafetyError(f"CAN interface {name} does not exist")
    flags_path = os.path.join(path, "flags")
    try:
        flags = int(open(flags_path, "r", encoding="ascii").read().strip(), 16)
    except OSError as exc:
        raise SafetyError(f"cannot read {name} state: {exc}") from exc
    if not (flags & 0x1):
        raise SafetyError(f"CAN interface {name} is not UP")
    sock = socket.socket(socket.PF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
    try:
        sock.bind((name,))
    finally:
        sock.close()
