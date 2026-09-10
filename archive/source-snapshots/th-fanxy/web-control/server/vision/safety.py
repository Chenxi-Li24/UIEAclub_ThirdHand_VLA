"""Deterministic, fail-closed safety checks for offline target proposals."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .types import CalibrationRef, InvalidDataError, SafetyDecision, TrackState


def _readonly_vector(value: Any, name: str) -> np.ndarray:
    array = np.array(value, dtype=float, copy=True)
    if array.shape != (3,) or not np.isfinite(array).all():
        raise InvalidDataError(f"{name} must be a finite three-vector")
    array.setflags(write=False)
    return array


@dataclass(frozen=True)
class SafetyConfig:
    workspace_min_m: np.ndarray = field(compare=False)
    workspace_max_m: np.ndarray = field(compare=False)
    max_target_age_ns: int
    max_position_std_m: float
    min_cloud_points: int
    min_gripper_width_m: float
    max_gripper_width_m: float
    grasp_width_margin_m: float
    pregrasp_clearance_m: float
    retreat_clearance_m: float
    table_clearance_m: float
    clearance_weight: float
    uncertainty_weight: float
    travel_weight: float
    nominal_pose_m: np.ndarray = field(compare=False)

    def __post_init__(self) -> None:
        lower = _readonly_vector(self.workspace_min_m, "workspace_min_m")
        upper = _readonly_vector(self.workspace_max_m, "workspace_max_m")
        nominal = _readonly_vector(self.nominal_pose_m, "nominal_pose_m")
        if not np.all(lower < upper):
            raise InvalidDataError("workspace_min_m must be below workspace_max_m on every axis")
        if self.max_target_age_ns < 0:
            raise InvalidDataError("max_target_age_ns must be non-negative")
        if self.min_cloud_points < 1:
            raise InvalidDataError("min_cloud_points must be at least one")
        positive = np.asarray(
            [
                self.max_position_std_m,
                self.min_gripper_width_m,
                self.max_gripper_width_m,
                self.grasp_width_margin_m,
                self.pregrasp_clearance_m,
                self.retreat_clearance_m,
                self.table_clearance_m,
            ],
            dtype=float,
        )
        if not np.isfinite(positive).all() or np.any(positive <= 0.0):
            raise InvalidDataError("safety distances and widths must be finite and positive")
        if self.min_gripper_width_m > self.max_gripper_width_m:
            raise InvalidDataError("minimum gripper width cannot exceed maximum width")
        weights = np.asarray(
            [self.clearance_weight, self.uncertainty_weight, self.travel_weight],
            dtype=float,
        )
        if not np.isfinite(weights).all() or np.any(weights < 0.0):
            raise InvalidDataError("score weights must be finite and non-negative")
        object.__setattr__(self, "workspace_min_m", lower)
        object.__setattr__(self, "workspace_max_m", upper)
        object.__setattr__(self, "nominal_pose_m", nominal)


def _validated_cloud(target_cloud_m: Any) -> np.ndarray:
    cloud = np.asarray(target_cloud_m, dtype=float)
    if cloud.ndim != 2 or cloud.shape[1] != 3:
        raise InvalidDataError(f"target_cloud_m must have shape (N, 3), got {cloud.shape}")
    return cloud


def evaluate_target_safety(
    target: TrackState,
    target_cloud_m: Any,
    calibration: CalibrationRef,
    now_ns: int,
    config: SafetyConfig,
    reachable: bool,
) -> SafetyDecision:
    if not isinstance(now_ns, int) or now_ns < target.last_seen_ns:
        raise InvalidDataError("now_ns cannot precede the target observation")
    if not isinstance(reachable, (bool, np.bool_)):
        raise InvalidDataError("reachable must be an explicit boolean result")
    cloud = _validated_cloud(target_cloud_m)
    finite_cloud_points = int(np.isfinite(cloud).all(axis=1).sum())
    position_std_m = float(
        np.sqrt(max(0.0, np.max(np.linalg.eigvalsh(target.pose.covariance_m2))))
    )
    reasons = []
    if not calibration.validated:
        reasons.append("calibration_not_validated")
    if target.pose.calibration_id != calibration.calibration_id:
        reasons.append("calibration_mismatch")
    if now_ns - target.last_seen_ns > config.max_target_age_ns:
        reasons.append("target_stale")
    if position_std_m > config.max_position_std_m:
        reasons.append("uncertainty_too_high")
    if finite_cloud_points < config.min_cloud_points:
        reasons.append("target_cloud_too_small")
    if not (
        np.all(config.workspace_min_m <= target.pose.xyz_m)
        and np.all(target.pose.xyz_m <= config.workspace_max_m)
    ):
        reasons.append("outside_workspace")
    if not reachable:
        reasons.append("target_not_reachable")
    return SafetyDecision(approved=not reasons, reasons=tuple(reasons))
