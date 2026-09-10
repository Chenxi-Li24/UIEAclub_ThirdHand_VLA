"""Convert a requested gripper TCP pose into the Startouch flange pose."""

from __future__ import annotations

import math
from collections.abc import Sequence


def parse_offset_m(raw: str) -> tuple[float, float, float]:
    """Parse a finite three-value, comma-separated tool offset in metres."""
    values = raw.split(",")
    if len(values) != 3:
        raise ValueError("TCP offset must contain exactly three comma-separated values")
    try:
        parsed = tuple(float(value.strip()) for value in values)
    except ValueError as error:
        raise ValueError("TCP offset contains a non-numeric value") from error
    if not all(math.isfinite(value) for value in parsed):
        raise ValueError("TCP offset contains a non-finite value")
    return parsed


def tcp_position_to_flange(
    tcp_position_m: Sequence[float],
    flange_euler_rad: Sequence[float],
    tcp_offset_flange_m: Sequence[float],
) -> list[float]:
    """Return flange position for a TCP target using SDK Rz*Ry*Rx Euler order."""
    if not all(len(values) == 3 for values in (
        tcp_position_m,
        flange_euler_rad,
        tcp_offset_flange_m,
    )):
        raise ValueError("TCP conversion requires three-element vectors")
    x, y, z = (float(value) for value in tcp_position_m)
    roll, pitch, yaw = (float(value) for value in flange_euler_rad)
    ox, oy, oz = (float(value) for value in tcp_offset_flange_m)
    values = (x, y, z, roll, pitch, yaw, ox, oy, oz)
    if not all(math.isfinite(value) for value in values):
        raise ValueError("TCP conversion contains a non-finite value")

    cr, sr = math.cos(roll), math.sin(roll)
    cp, sp = math.cos(pitch), math.sin(pitch)
    cy, sy = math.cos(yaw), math.sin(yaw)
    rotated_offset = (
        (cy * cp) * ox + (cy * sp * sr - sy * cr) * oy
        + (cy * sp * cr + sy * sr) * oz,
        (sy * cp) * ox + (sy * sp * sr + cy * cr) * oy
        + (sy * sp * cr - cy * sr) * oz,
        (-sp) * ox + (cp * sr) * oy + (cp * cr) * oz,
    )
    return [
        x - rotated_offset[0],
        y - rotated_offset[1],
        z - rotated_offset[2],
    ]
