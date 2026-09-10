"""Robust median/MAD instance position and covariance estimation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy.ndimage import binary_erosion

from thirdhand_vision.core.errors import InputValidationError
from thirdhand_vision.core.transforms import transform_points
from thirdhand_vision.core.types import FrameStamp, PoseEstimate

from .depth import RegisteredDepth


@dataclass(frozen=True)
class InstancePoseConfig:
    min_points: int
    erosion_px: int
    mad_scale: float
    noise_floor_m: float

    def __post_init__(self) -> None:
        if isinstance(self.min_points, bool) or not isinstance(self.min_points, int) or self.min_points < 1:
            raise InputValidationError("min_points must be a positive integer")
        if isinstance(self.erosion_px, bool) or not isinstance(self.erosion_px, int) or self.erosion_px < 0:
            raise InputValidationError("erosion_px must be a non-negative integer")
        if not np.isfinite(self.mad_scale) or self.mad_scale <= 0.0:
            raise InputValidationError("mad_scale must be positive")
        if not np.isfinite(self.noise_floor_m) or self.noise_floor_m <= 0.0:
            raise InputValidationError("noise_floor_m must be positive")


def _robust_inliers(points: np.ndarray, config: InstancePoseConfig) -> np.ndarray:
    center = np.median(points, axis=0)
    deviation = np.abs(points - center)
    median_absolute_deviation = np.median(deviation, axis=0)
    limits = np.maximum(
        config.mad_scale * 1.4826 * median_absolute_deviation,
        config.noise_floor_m,
    )
    return points[np.all(deviation <= limits, axis=1)]


def estimate_instance_pose(
    *,
    registered: RegisteredDepth,
    mask: Any,
    t_output_from_lumos: Any,
    stamp: FrameStamp,
    calibration_id: str,
    config: InstancePoseConfig,
) -> PoseEstimate:
    if not isinstance(registered, RegisteredDepth):
        raise InputValidationError("registered must be a RegisteredDepth")
    mask_array = np.asarray(mask)
    if mask_array.dtype != np.bool_ or mask_array.shape != registered.valid.shape:
        raise InputValidationError("instance mask must match registered depth")
    usable_mask = (
        binary_erosion(mask_array, iterations=config.erosion_px, border_value=0)
        if config.erosion_px
        else np.array(mask_array, copy=True)
    )
    points_lumos = np.asarray(
        registered.points_lumos_m[usable_mask & registered.valid],
        dtype=float,
    )
    if len(points_lumos) < config.min_points:
        raise InputValidationError("insufficient valid depth points inside instance mask")
    inliers_lumos = _robust_inliers(points_lumos, config)
    if len(inliers_lumos) < config.min_points:
        raise InputValidationError("insufficient valid depth points after outlier rejection")
    points_output = transform_points(t_output_from_lumos, inliers_lumos)
    center = np.median(points_output, axis=0)
    covariance = (
        np.asarray(np.cov(points_output, rowvar=False, ddof=1), dtype=float)
        if len(points_output) > 1
        else np.zeros((3, 3), dtype=float)
    )
    covariance += np.eye(3) * config.noise_floor_m**2
    covariance = (covariance + covariance.T) * 0.5
    return PoseEstimate(
        xyz_m=center,
        covariance_m2=covariance,
        frame="robot_base",
        stamp=stamp,
        calibration_id=calibration_id,
    )
