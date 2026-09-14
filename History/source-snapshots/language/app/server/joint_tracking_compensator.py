"""Bounded outer-loop compensation for static joint tracking residuals.

This module has no perception or task knowledge.  It only converts measured
joint tracking error into a small accumulated command bias, with fail-closed
limits that are independent of the vendor SDK controller.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable, Sequence

import numpy as np


class JointTrackingCompensationError(RuntimeError):
    """Raised when measured tracking error cannot be compensated safely."""


@dataclass(frozen=True)
class JointTrackingCompensation:
    target_joints_rad: tuple[float, ...]
    max_increment_rad: float
    max_total_bias_rad: float


def _finite_six(values: Iterable[float], name: str) -> np.ndarray:
    try:
        result = np.asarray(tuple(values), dtype=float).reshape(-1)
    except (TypeError, ValueError) as error:
        raise JointTrackingCompensationError(
            f"{name} must contain six finite values"
        ) from error
    if result.shape != (6,) or not np.isfinite(result).all():
        raise JointTrackingCompensationError(f"{name} must contain six finite values")
    return result


class BoundedJointTrackingCompensator:
    """Accumulate a limited command bias from measured static tracking error."""

    def __init__(
        self,
        *,
        gain: float = 0.75,
        max_total_bias_rad: float = math.radians(1.5),
        max_increment_rad: float = math.radians(1.0),
    ) -> None:
        if not math.isfinite(gain) or not 0.0 < gain <= 1.0:
            raise JointTrackingCompensationError("gain must be within (0, 1]")
        if not math.isfinite(max_total_bias_rad) or not 0.0 < max_total_bias_rad <= math.radians(2.0):
            raise JointTrackingCompensationError("total bias limit must be within 2 degrees")
        if not math.isfinite(max_increment_rad) or not 0.0 < max_increment_rad <= math.radians(1.0):
            raise JointTrackingCompensationError("increment limit must be within 1 degree")
        self.gain = float(gain)
        self.max_total_bias_rad = float(max_total_bias_rad)
        self.max_increment_rad = float(max_increment_rad)

    def next_target(
        self,
        *,
        desired_joints_rad: Iterable[float],
        previous_command_rad: Iterable[float],
        actual_joints_rad: Iterable[float],
        joint_limits_rad: Sequence[Sequence[float]],
    ) -> JointTrackingCompensation:
        desired = _finite_six(desired_joints_rad, "desired joints")
        previous = _finite_six(previous_command_rad, "previous command")
        actual = _finite_six(actual_joints_rad, "actual joints")
        limits = np.asarray(joint_limits_rad, dtype=float)
        if limits.shape != (6, 2) or not np.isfinite(limits).all() or np.any(limits[:, 0] >= limits[:, 1]):
            raise JointTrackingCompensationError("joint limits are invalid")

        increment = self.gain * (desired - actual)
        max_increment = float(np.max(np.abs(increment)))
        if max_increment > self.max_increment_rad + 1e-12:
            raise JointTrackingCompensationError("tracking compensation increment exceeds limit")
        target = previous + increment
        total_bias = target - desired
        max_total_bias = float(np.max(np.abs(total_bias)))
        if max_total_bias > self.max_total_bias_rad + 1e-12:
            raise JointTrackingCompensationError("tracking compensation total bias exceeds limit")
        if np.any(target < limits[:, 0]) or np.any(target > limits[:, 1]):
            raise JointTrackingCompensationError("tracking compensation exceeds joint limits")
        return JointTrackingCompensation(
            target_joints_rad=tuple(float(value) for value in target),
            max_increment_rad=max_increment,
            max_total_bias_rad=max_total_bias,
        )
