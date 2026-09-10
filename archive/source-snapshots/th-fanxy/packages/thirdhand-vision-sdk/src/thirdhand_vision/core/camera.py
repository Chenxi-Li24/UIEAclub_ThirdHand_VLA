"""Pinhole and SEUCM projection models with explicit depth semantics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from .errors import InputValidationError


def _matrix(value: Any, columns: int, name: str) -> np.ndarray:
    result = np.asarray(value, dtype=float)
    if result.ndim != 2 or result.shape[1] != columns:
        raise InputValidationError(f"{name} must have shape (N, {columns})")
    return result


def _validate_camera(
    fx: float,
    fy: float,
    cx: float,
    cy: float,
    width: int,
    height: int,
) -> None:
    if not np.isfinite([fx, fy, cx, cy]).all() or fx <= 0.0 or fy <= 0.0:
        raise InputValidationError("camera focal lengths must be finite and positive")
    if (
        isinstance(width, bool)
        or isinstance(height, bool)
        or not isinstance(width, int)
        or not isinstance(height, int)
        or width <= 0
        or height <= 0
    ):
        raise InputValidationError("camera dimensions must be positive integers")


@dataclass(frozen=True)
class PinholeCamera:
    fx: float
    fy: float
    cx: float
    cy: float
    width: int
    height: int

    def __post_init__(self) -> None:
        _validate_camera(self.fx, self.fy, self.cx, self.cy, self.width, self.height)

    def project(self, points_camera_m: Any) -> tuple[np.ndarray, np.ndarray]:
        points = _matrix(points_camera_m, 3, "points_camera_m")
        z = points[:, 2]
        valid = np.isfinite(points).all(axis=1) & (z > 1e-12)
        with np.errstate(divide="ignore", invalid="ignore"):
            u = self.fx * points[:, 0] / z + self.cx
            v = self.fy * points[:, 1] / z + self.cy
        valid &= (u >= 0.0) & (u < self.width) & (v >= 0.0) & (v < self.height)
        pixels = np.full((len(points), 2), np.nan)
        pixels[valid] = np.column_stack((u, v))[valid]
        return pixels, valid

    def deproject_z(self, uv_px: Any, z_m: Any) -> np.ndarray:
        pixels = _matrix(uv_px, 2, "uv_px")
        depth = np.asarray(z_m, dtype=float)
        if depth.shape != (len(pixels),):
            raise InputValidationError("z_m must contain one axial depth per pixel")
        if not np.isfinite(pixels).all() or not np.isfinite(depth).all() or np.any(depth <= 0.0):
            raise InputValidationError("pixels and axial depth must be finite and positive")
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
        _validate_camera(self.fx, self.fy, self.cx, self.cy, self.width, self.height)
        if not np.isfinite(self.alpha) or not 0.0 < self.alpha < 1.0:
            raise InputValidationError("SEUCM alpha must be within (0, 1)")
        if not np.isfinite(self.beta) or self.beta <= 0.0:
            raise InputValidationError("SEUCM beta must be positive")

    def project(self, points_camera_m: Any) -> tuple[np.ndarray, np.ndarray]:
        points = _matrix(points_camera_m, 3, "points_camera_m")
        x, y, z = points.T
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
        valid = np.isfinite(points).all(axis=1)
        valid &= (distance > 1e-15) & (z > -domain_weight * distance)
        valid &= denominator > 1e-15
        valid &= (u >= 0.0) & (u < self.width) & (v >= 0.0) & (v < self.height)
        pixels = np.full((len(points), 2), np.nan)
        pixels[valid] = np.column_stack((u, v))[valid]
        return pixels, valid

    def unproject(self, uv_px: Any) -> tuple[np.ndarray, np.ndarray]:
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
        safe_argument = np.where(valid, sqrt_argument, 0.0)
        denominator = self.alpha * np.sqrt(safe_argument) + 1.0 - self.alpha
        with np.errstate(invalid="ignore", divide="ignore"):
            mz = (1.0 - self.beta * self.alpha * self.alpha * radius_squared) / denominator
        valid &= np.isfinite(mz) & (np.abs(denominator) > 1e-15)
        vectors = np.column_stack((mx, my, mz))
        norms = np.linalg.norm(vectors, axis=1)
        valid &= np.isfinite(norms) & (norms > 1e-15)
        rays = np.full((len(pixels), 3), np.nan)
        rays[valid] = vectors[valid] / norms[valid, None]
        return rays, valid

