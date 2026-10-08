from __future__ import annotations

import math
from dataclasses import dataclass


def euler_to_matrix(euler: list[float]) -> list[list[float]]:
    roll, pitch, yaw = euler
    cr = math.cos(roll)
    sr = math.sin(roll)
    cp = math.cos(pitch)
    sp = math.sin(pitch)
    cy = math.cos(yaw)
    sy = math.sin(yaw)
    return [
        [cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr],
        [sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr],
        [-sp, cp * sr, cp * cr],
    ]


def matrix_to_euler(matrix: list[list[float]]) -> list[float]:
    sy = -matrix[2][0]
    sy = max(-1.0, min(1.0, sy))
    pitch = math.asin(sy)
    cp = math.cos(pitch)
    if abs(cp) > 1e-9:
        roll = math.atan2(matrix[2][1], matrix[2][2])
        yaw = math.atan2(matrix[1][0], matrix[0][0])
    else:
        roll = 0.0
        yaw = math.atan2(-matrix[0][1], matrix[1][1])
    return [roll, pitch, yaw]


def _cross(a: list[float], b: list[float]) -> list[float]:
    return [
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    ]


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def _normalize(v: list[float]) -> list[float]:
    norm = math.sqrt(_dot(v, v))
    if norm < 1e-12:
        raise ValueError("cannot normalize a zero-length vector")
    return [value / norm for value in v]


def _smoothstep(value: float) -> float:
    value = max(0.0, min(1.0, value))
    return value * value * (3.0 - 2.0 * value)


@dataclass(frozen=True)
class FixedTcpTrajectory:
    center_rpy: list[float]
    max_roll_rad: float
    max_pitch_rad: float
    max_yaw_rad: float
    period_sec: float

    def sample(self, elapsed_sec: float) -> list[float]:
        phase = 2.0 * math.pi * ((elapsed_sec % self.period_sec) / self.period_sec)
        # The gripper-tip TCP stays fixed while the local tool ray sweeps around
        # it. Pitch/yaw carry the large visual direction changes; roll is kept
        # lower as a continuous bias so the wrist looks alive without asking the
        # IK for the risky fully twisted poses.
        roll = self.center_rpy[0] + 0.40 * self.max_roll_rad * math.sin(phase)
        pitch = self.center_rpy[1] + self.max_pitch_rad * math.sin(2.0 * phase)
        yaw = self.center_rpy[2] + self.max_yaw_rad * math.sin(phase)
        return [roll, pitch, yaw]


@dataclass(frozen=True)
class RCMConeOrbitTrajectory:
    center_rpy: list[float]
    cone_angle_rad: float
    period_sec: float
    duration_sec: float | None = None
    ramp_sec: float = 4.0
    tool_roll_rad: float = 0.0
    cone_pulse_fraction: float = 0.22
    phase_wobble_rad: float = 0.22
    path_style: str = "orbit"
    phase_direction: float = 1.0

    def sample(self, elapsed_sec: float) -> list[float]:
        base_phase = self.phase_direction * 2.0 * math.pi * ((elapsed_sec % self.period_sec) / self.period_sec)
        phase = base_phase + self.phase_wobble_rad * math.sin(3.0 * base_phase)
        cone_scale = self._cone_scale(elapsed_sec)
        pulse = 1.0 - max(0.0, min(0.5, self.cone_pulse_fraction)) * (
            0.5 + 0.5 * math.sin(2.0 * base_phase + math.pi / 5.0)
        )
        cone_angle = self.cone_angle_rad * cone_scale * pulse
        center_matrix = euler_to_matrix(self.center_rpy)
        center_x = _normalize([row[0] for row in center_matrix])
        center_y = _normalize([row[1] for row in center_matrix])
        center_z = _normalize([row[2] for row in center_matrix])

        cone_radius = math.sin(cone_angle)
        axis_weight = math.cos(cone_angle)
        sweep_y, sweep_z = self._sweep_direction(phase)
        tool_x = _normalize([
            axis_weight * center_x[index]
            + cone_radius * sweep_y * center_y[index]
            + cone_radius * sweep_z * center_z[index]
            for index in range(3)
        ])

        roll_reference = [
            math.cos(self.tool_roll_rad) * center_y[index]
            + math.sin(self.tool_roll_rad) * center_z[index]
            for index in range(3)
        ]
        tool_z = _cross(tool_x, roll_reference)
        if math.sqrt(_dot(tool_z, tool_z)) < 1e-9:
            tool_z = _cross(tool_x, center_z)
        tool_z = _normalize(tool_z)
        tool_y = _normalize(_cross(tool_z, tool_x))
        return matrix_to_euler([
            [tool_x[0], tool_y[0], tool_z[0]],
            [tool_x[1], tool_y[1], tool_z[1]],
            [tool_x[2], tool_y[2], tool_z[2]],
        ])

    def _cone_scale(self, elapsed_sec: float) -> float:
        if self.ramp_sec <= 0.0:
            return 1.0
        scale = _smoothstep(elapsed_sec / self.ramp_sec)
        if self.duration_sec is not None:
            scale = min(scale, _smoothstep((self.duration_sec - elapsed_sec) / self.ramp_sec))
        return scale

    def _sweep_direction(self, phase: float) -> tuple[float, float]:
        if self.path_style == "orbit":
            return math.cos(phase), math.sin(phase)
        if self.path_style == "lissajous":
            y = math.cos(phase + 0.35 * math.sin(2.0 * phase))
            z = math.sin(phase + 0.35 * math.sin(3.0 * phase))
            length = math.hypot(y, z)
            if length < 1e-9:
                return 1.0, 0.0
            return y / length, z / length
        if self.path_style == "nod_shake":
            half = (phase % (2.0 * math.pi)) < math.pi
            local_phase = (phase * 2.0) % (2.0 * math.pi)
            if half:
                return 0.0, math.sin(local_phase)
            return math.sin(local_phase), 0.0
        if self.path_style == "cardinal_cross":
            y = math.sin(phase)
            z = math.cos(phase)
            length = math.hypot(y, z)
            if length > 1.0:
                y /= length
                z /= length
            return y, z
        if self.path_style == "spiral_breathe":
            breath = 0.35 + 0.65 * (0.5 + 0.5 * math.sin(phase - math.pi / 2.0))
            return breath * math.cos(phase), breath * math.sin(phase)
        if self.path_style == "irregular_shell":
            y = (
                1.04 * math.cos(phase)
                + 0.14 * math.cos(2.0 * phase + 0.7)
                + 0.16 * math.sin(3.0 * phase - 0.4)
            )
            z = (
                0.92 * math.sin(phase + 0.35)
                - 0.18 * math.sin(2.0 * phase - 0.2)
                + 0.12 * math.cos(3.0 * phase + 0.5)
            )
            length = math.hypot(y, z)
            if length > 1.0:
                y /= length
                z /= length
            breath = 0.78 + 0.22 * (0.5 + 0.5 * math.sin(2.0 * phase - 0.8))
            y *= breath
            z *= breath
            return y, z
        raise ValueError(f"unknown RCM path style: {self.path_style}")
