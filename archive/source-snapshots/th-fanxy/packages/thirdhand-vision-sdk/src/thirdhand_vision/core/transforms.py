"""Validated right-handed SE(3) transform helpers."""

from __future__ import annotations

from typing import Any

import numpy as np

from .errors import InputValidationError


def validate_transform(transform: Any) -> np.ndarray:
    matrix = np.asarray(transform, dtype=float)
    if matrix.shape != (4, 4) or not np.isfinite(matrix).all():
        raise InputValidationError("transform must be a finite 4x4 matrix")
    if not np.allclose(matrix[3], [0.0, 0.0, 0.0, 1.0], atol=1e-12):
        raise InputValidationError("transform must have a homogeneous final row")
    rotation = matrix[:3, :3]
    if not np.allclose(rotation.T @ rotation, np.eye(3), atol=1e-8):
        raise InputValidationError("transform rotation must be orthonormal")
    if not np.isclose(np.linalg.det(rotation), 1.0, atol=1e-8):
        raise InputValidationError("transform must contain a proper rotation")
    result = np.array(matrix, copy=True)
    result.setflags(write=False)
    return result


def make_transform(rotation: Any, translation_m: Any) -> np.ndarray:
    rotation_array = np.asarray(rotation, dtype=float)
    translation = np.asarray(translation_m, dtype=float)
    if rotation_array.shape != (3, 3) or translation.shape != (3,):
        raise InputValidationError("rotation and translation must have shapes (3,3) and (3,)")
    transform = np.eye(4)
    transform[:3, :3] = rotation_array
    transform[:3, 3] = translation
    return validate_transform(transform)


def invert_transform(transform: Any) -> np.ndarray:
    matrix = validate_transform(transform)
    rotation = matrix[:3, :3]
    translation = matrix[:3, 3]
    return make_transform(rotation.T, -rotation.T @ translation)


def transform_points(transform: Any, points_m: Any) -> np.ndarray:
    matrix = validate_transform(transform)
    points = np.asarray(points_m, dtype=float)
    if points.ndim != 2 or points.shape[1] != 3 or not np.isfinite(points).all():
        raise InputValidationError("points_m must be a finite Nx3 array")
    return points @ matrix[:3, :3].T + matrix[:3, 3]

