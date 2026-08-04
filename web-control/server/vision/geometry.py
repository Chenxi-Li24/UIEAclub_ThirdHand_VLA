"""Explicit rigid-body geometry with the robot SDK's RPY convention."""

from __future__ import annotations

from typing import Any

import numpy as np

from .types import InvalidDataError


def _finite_array(value: Any, shape: tuple[int, ...], name: str) -> np.ndarray:
    array = np.asarray(value, dtype=float)
    if array.shape != shape:
        raise InvalidDataError(f"{name} must have shape {shape}, got {array.shape}")
    if not np.isfinite(array).all():
        raise InvalidDataError(f"{name} must contain only finite values")
    return array


def rotation_x(angle_rad: float) -> np.ndarray:
    angle = float(angle_rad)
    if not np.isfinite(angle):
        raise InvalidDataError("rotation angle must be finite")
    cosine, sine = np.cos(angle), np.sin(angle)
    return np.array([[1.0, 0.0, 0.0], [0.0, cosine, -sine], [0.0, sine, cosine]])


def rotation_y(angle_rad: float) -> np.ndarray:
    angle = float(angle_rad)
    if not np.isfinite(angle):
        raise InvalidDataError("rotation angle must be finite")
    cosine, sine = np.cos(angle), np.sin(angle)
    return np.array([[cosine, 0.0, sine], [0.0, 1.0, 0.0], [-sine, 0.0, cosine]])


def rotation_z(angle_rad: float) -> np.ndarray:
    angle = float(angle_rad)
    if not np.isfinite(angle):
        raise InvalidDataError("rotation angle must be finite")
    cosine, sine = np.cos(angle), np.sin(angle)
    return np.array([[cosine, -sine, 0.0], [sine, cosine, 0.0], [0.0, 0.0, 1.0]])


def rpy_xyz_to_matrix(rpy_rad: Any) -> np.ndarray:
    """Convert `(roll, pitch, yaw)` to `Rz(yaw) @ Ry(pitch) @ Rx(roll)`."""

    roll, pitch, yaw = _finite_array(rpy_rad, (3,), "rpy_rad")
    return rotation_z(yaw) @ rotation_y(pitch) @ rotation_x(roll)


def validate_transform(transform: Any) -> np.ndarray:
    """Return a validated copy of a proper homogeneous rigid transform."""

    result = np.array(transform, dtype=float, copy=True)
    if result.shape != (4, 4):
        raise InvalidDataError(f"transform must have shape (4, 4), got {result.shape}")
    if not np.isfinite(result).all():
        raise InvalidDataError("transform must contain only finite values")
    if not np.allclose(result[3], [0.0, 0.0, 0.0, 1.0], atol=1e-12):
        raise InvalidDataError("transform last row must be [0, 0, 0, 1]")
    rotation = result[:3, :3]
    if not np.allclose(rotation.T @ rotation, np.eye(3), atol=1e-8):
        raise InvalidDataError("transform rotation must be orthonormal")
    if not np.isclose(np.linalg.det(rotation), 1.0, atol=1e-8):
        raise InvalidDataError("transform rotation determinant must be +1")
    return result


def make_transform(rotation: Any, translation_m: Any) -> np.ndarray:
    rotation_array = _finite_array(rotation, (3, 3), "rotation")
    translation_array = _finite_array(translation_m, (3,), "translation_m")
    transform = np.eye(4)
    transform[:3, :3] = rotation_array
    transform[:3, 3] = translation_array
    return validate_transform(transform)


def invert_transform(transform: Any) -> np.ndarray:
    source = validate_transform(transform)
    result = np.eye(4)
    result[:3, :3] = source[:3, :3].T
    result[:3, 3] = -source[:3, :3].T @ source[:3, 3]
    return result


def transform_points(transform: Any, points_m: Any) -> np.ndarray:
    source = validate_transform(transform)
    points = np.asarray(points_m, dtype=float)
    single = points.ndim == 1
    if single:
        if points.shape != (3,):
            raise InvalidDataError(f"point must have shape (3,), got {points.shape}")
        batch = points.reshape(1, 3)
    else:
        if points.ndim != 2 or points.shape[1] != 3:
            raise InvalidDataError(f"points must have shape (N, 3), got {points.shape}")
        batch = points
    if not np.isfinite(batch).all():
        raise InvalidDataError("points must contain only finite values")
    transformed = batch @ source[:3, :3].T + source[:3, 3]
    return transformed[0] if single else transformed

