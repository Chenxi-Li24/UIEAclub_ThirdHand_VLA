"""Vectorized pinhole and Extended Unified Camera Model geometry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Tuple

import numpy as np

from .types import InvalidDataError


def _matrix(value: Any, columns: int, name: str) -> np.ndarray:
    array = np.asarray(value, dtype=float)
    if array.ndim != 2 or array.shape[1] != columns:
        raise InvalidDataError(f"{name} must have shape (N, {columns}), got {array.shape}")
    return array


def normalize_rows(vectors: Any) -> np.ndarray:
    array = _matrix(vectors, 3, "vectors")
    if not np.isfinite(array).all():
        raise InvalidDataError("vectors must contain only finite values")
    norms = np.linalg.norm(array, axis=1)
    if np.any(norms <= 1e-15):
        raise InvalidDataError("cannot normalize a zero-length vector")
    return array / norms[:, None]


def _validate_common_camera(
    fx: float,
    fy: float,
    cx: float,
    cy: float,
    width: int,
    height: int,
) -> None:
    numeric = np.asarray([fx, fy, cx, cy], dtype=float)
    if not np.isfinite(numeric).all() or fx <= 0.0 or fy <= 0.0:
        raise InvalidDataError("camera focal lengths must be finite and positive")
    if not isinstance(width, int) or not isinstance(height, int) or width <= 0 or height <= 0:
        raise InvalidDataError("camera image dimensions must be positive integers")


@dataclass(frozen=True)
class PinholeCamera:
    fx: float
    fy: float
    cx: float
    cy: float
    width: int
    height: int

    def __post_init__(self) -> None:
        _validate_common_camera(self.fx, self.fy, self.cx, self.cy, self.width, self.height)

    def project(self, points_camera_m: Any) -> Tuple[np.ndarray, np.ndarray]:
        points = _matrix(points_camera_m, 3, "points_camera_m")
        finite = np.isfinite(points).all(axis=1)
        z = points[:, 2]
        valid = finite & (z > 1e-12)
        uv = np.full((len(points), 2), np.nan, dtype=float)
        with np.errstate(divide="ignore", invalid="ignore"):
            u = self.fx * points[:, 0] / z + self.cx
            v = self.fy * points[:, 1] / z + self.cy
        in_image = (u >= 0.0) & (u < self.width) & (v >= 0.0) & (v < self.height)
        valid &= in_image
        uv[valid] = np.column_stack((u, v))[valid]
        return uv, valid

    def deproject_z(self, uv_px: Any, z_m: Any) -> np.ndarray:
        pixels = _matrix(uv_px, 2, "uv_px")
        depth = np.asarray(z_m, dtype=float)
        if depth.shape != (len(pixels),):
            raise InvalidDataError(f"z_m must have shape ({len(pixels)},), got {depth.shape}")
        if not np.isfinite(pixels).all() or not np.isfinite(depth).all() or np.any(depth <= 0.0):
            raise InvalidDataError("pixels and Z-depth must be finite; depth must be positive")
        x = (pixels[:, 0] - self.cx) * depth / self.fx
        y = (pixels[:, 1] - self.cy) * depth / self.fy
        return np.column_stack((x, y, depth))


@dataclass(frozen=True)
class SeucmCamera:
    fx: float
    fy: float
    cx: float
    cy: float
    alpha: float
    beta: float
    width: int
    height: int

    def __post_init__(self) -> None:
        _validate_common_camera(self.fx, self.fy, self.cx, self.cy, self.width, self.height)
        if not np.isfinite(self.alpha) or not 0.0 < self.alpha < 1.0:
            raise InvalidDataError("SEUCM alpha must be finite and strictly between 0 and 1")
        if not np.isfinite(self.beta) or self.beta <= 0.0:
            raise InvalidDataError("SEUCM beta must be finite and positive")

    def project(self, points_camera_m: Any) -> Tuple[np.ndarray, np.ndarray]:
        points = _matrix(points_camera_m, 3, "points_camera_m")
        x, y, z = points.T
        finite = np.isfinite(points).all(axis=1)
        with np.errstate(invalid="ignore", divide="ignore"):
            distance = np.sqrt(self.beta * (x * x + y * y) + z * z)
            denominator = self.alpha * distance + (1.0 - self.alpha) * z
            u = self.fx * x / denominator + self.cx
            v = self.fy * y / denominator + self.cy
        domain_weight = (
            self.alpha / (1.0 - self.alpha)
            if self.alpha <= 0.5
            else (1.0 - self.alpha) / self.alpha
        )
        valid = finite & (distance > 1e-15) & (z > -domain_weight * distance)
        valid &= denominator > 1e-15
        valid &= (u >= 0.0) & (u < self.width) & (v >= 0.0) & (v < self.height)
        uv = np.full((len(points), 2), np.nan, dtype=float)
        uv[valid] = np.column_stack((u, v))[valid]
        return uv, valid

    def unproject(self, uv_px: Any) -> Tuple[np.ndarray, np.ndarray]:
        pixels = _matrix(uv_px, 2, "uv_px")
        finite = np.isfinite(pixels).all(axis=1)
        in_image = (
            (pixels[:, 0] >= 0.0)
            & (pixels[:, 0] < self.width)
            & (pixels[:, 1] >= 0.0)
            & (pixels[:, 1] < self.height)
        )
        mx = (pixels[:, 0] - self.cx) / self.fx
        my = (pixels[:, 1] - self.cy) / self.fy
        radius_squared = mx * mx + my * my
        sqrt_argument = 1.0 - (2.0 * self.alpha - 1.0) * self.beta * radius_squared
        valid = finite & in_image & (sqrt_argument >= 0.0)
        safe_sqrt_argument = np.where(valid, sqrt_argument, 0.0)
        denominator = self.alpha * np.sqrt(safe_sqrt_argument) + 1.0 - self.alpha
        with np.errstate(invalid="ignore", divide="ignore"):
            mz = (1.0 - self.beta * self.alpha * self.alpha * radius_squared) / denominator
        valid &= np.isfinite(mz) & (np.abs(denominator) > 1e-15)
        vectors = np.column_stack((mx, my, mz))
        norms = np.linalg.norm(vectors, axis=1)
        valid &= np.isfinite(norms) & (norms > 1e-15)
        rays = np.full((len(pixels), 3), np.nan, dtype=float)
        rays[valid] = vectors[valid] / norms[valid, None]
        return rays, valid

