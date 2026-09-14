"""Pure pose-separation gates shared by calibration capture modules."""

from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Any

import numpy as np
from vision.geometry import validate_transform

from vision_models.calibration_capture import CalibrationCaptureError


def _rotation_delta(first: np.ndarray, second: np.ndarray) -> float:
    relative = first[:3, :3].T @ second[:3, :3]
    return math.acos(float(np.clip((np.trace(relative) - 1.0) / 2.0, -1.0, 1.0)))


def transform_is_distinct(
    candidate: Any,
    previous: Iterable[Any],
    *,
    translation_m: float,
    rotation_deg: float,
) -> bool:
    """Require translation or rotation separation from every previous transform."""

    current = validate_transform(candidate)
    history = tuple(validate_transform(item) for item in previous)
    thresholds = np.asarray([translation_m, rotation_deg], dtype=float)
    if not np.isfinite(thresholds).all() or np.any(thresholds <= 0.0):
        raise CalibrationCaptureError("pose diversity thresholds are invalid")
    rotation_rad = math.radians(rotation_deg)
    return all(
        np.linalg.norm(current[:3, 3] - item[:3, 3]) >= translation_m - 1e-12
        or _rotation_delta(current, item) >= rotation_rad - 1e-12
        for item in history
    )


__all__ = ["transform_is_distinct"]
