"""Robust robot-base position estimates from registered instance-mask depth."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy.ndimage import binary_erosion

from .depth_registration import RegisteredDepth
from .geometry import transform_points
from .types import FrameStamp, InvalidDataError, PoseEstimate


@dataclass(frozen=True)
class InstancePoseConfig:
    min_points: int
    erosion_px: int
    mad_scale: float
    noise_floor_m: float

    def __post_init__(self) -> None:
        if not isinstance(self.min_points, int) or self.min_points < 1:
            raise InvalidDataError("min_points must be a positive integer")
        if not isinstance(self.erosion_px, int) or self.erosion_px < 0:
            raise InvalidDataError("erosion_px must be a non-negative integer")
        if not np.isfinite(self.mad_scale) or self.mad_scale <= 0.0:
            raise InvalidDataError("mad_scale must be finite and positive")
        if not np.isfinite(self.noise_floor_m) or self.noise_floor_m <= 0.0:
            raise InvalidDataError("noise_floor_m must be finite and positive")


def _validated_mask(mask: Any, shape: tuple[int, int]) -> np.ndarray:
    result = np.asarray(mask)
    if result.dtype != np.bool_:
        raise InvalidDataError("instance mask must be a boolean array")
    if result.shape != shape:
        raise InvalidDataError("instance mask must have a shape matching registered depth")
    return result


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
    registered: RegisteredDepth,
    mask: Any,
    t_base_from_lumos: Any,
    stamp: FrameStamp,
    calibration_id: str,
    config: InstancePoseConfig,
) -> PoseEstimate:
    """Estimate a conservative robot-base center from an instance depth mask."""

    mask_array = _validated_mask(mask, registered.valid.shape)
    if config.erosion_px:
        usable_mask = binary_erosion(
            mask_array,
            iterations=config.erosion_px,
            border_value=0,
        )
    else:
        usable_mask = np.array(mask_array, copy=True)
    selected = usable_mask & registered.valid
    points_lumos = np.asarray(registered.points_lumos_m[selected], dtype=float)
    if len(points_lumos) < config.min_points:
        raise InvalidDataError("insufficient valid depth points inside instance mask")

    inliers_lumos = _robust_inliers(points_lumos, config)
    if len(inliers_lumos) < config.min_points:
        raise InvalidDataError("insufficient valid depth points after outlier rejection")

    points_base = transform_points(t_base_from_lumos, inliers_lumos)
    center_base = np.median(points_base, axis=0)
    if len(points_base) > 1:
        covariance = np.asarray(np.cov(points_base, rowvar=False, ddof=1), dtype=float)
    else:
        covariance = np.zeros((3, 3), dtype=float)
    covariance = covariance + np.eye(3) * config.noise_floor_m**2
    covariance = (covariance + covariance.T) * 0.5

    return PoseEstimate(
        xyz_m=center_base,
        covariance_m2=covariance,
        frame="robot_base",
        stamp=stamp,
        calibration_id=calibration_id,
    )
