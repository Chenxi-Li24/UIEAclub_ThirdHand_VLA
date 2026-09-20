"""Mask-safe point selection and robust depth outlier removal."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray


@dataclass(frozen=True, slots=True)
class TablePlane:
    normal: NDArray[np.float64]
    offset: float
    inlier_ratio: float
    inlier_count: int

    def __post_init__(self) -> None:
        normal = np.array(self.normal, dtype=np.float64, copy=True)
        if normal.shape != (3,) or not np.isfinite(normal).all():
            raise ValueError("table normal must contain three finite values")
        norm = float(np.linalg.norm(normal))
        if norm <= 1e-12:
            raise ValueError("table normal must be non-zero")
        normal /= norm
        normal.setflags(write=False)
        object.__setattr__(self, "normal", normal)

    def signed_distance(self, points: NDArray[np.floating]) -> NDArray[np.float64]:
        values = np.asarray(points, dtype=np.float64)
        return values @ self.normal + self.offset


def erode_mask(
    mask: NDArray[np.bool_],
    *,
    radius: int,
) -> NDArray[np.bool_]:
    source = np.asarray(mask, dtype=bool)
    if source.ndim != 2 or radius < 0:
        raise ValueError("mask must be 2-D and radius must be non-negative")
    if radius == 0:
        return source.copy()
    height, width = source.shape
    padded = np.pad(source, radius, mode="constant", constant_values=False)
    result = np.ones_like(source)
    diameter = radius * 2 + 1
    for dy in range(diameter):
        for dx in range(diameter):
            result &= padded[dy : dy + height, dx : dx + width]
    return result


def robust_mask_points(
    xyz_camera_m: NDArray[np.float32],
    mask: NDArray[np.bool_],
    *,
    min_depth_m: float,
    max_depth_m: float,
    mad_scale: float,
) -> tuple[NDArray[np.float64], float]:
    xyz = np.asarray(xyz_camera_m)
    selected = np.asarray(mask, dtype=bool)
    if xyz.ndim != 3 or xyz.shape[2] != 3 or xyz.shape[:2] != selected.shape:
        raise ValueError("XYZ and mask must share one pixel grid")
    selected_count = int(selected.sum())
    if selected_count == 0:
        return np.empty((0, 3), dtype=np.float64), 0.0
    points = np.asarray(xyz[selected], dtype=np.float64)
    valid = (
        np.isfinite(points).all(axis=1)
        & (points[:, 2] >= min_depth_m)
        & (points[:, 2] <= max_depth_m)
    )
    points = points[valid]
    if points.size == 0:
        return points.reshape(0, 3), 0.0
    median_z = float(np.median(points[:, 2]))
    absolute = np.abs(points[:, 2] - median_z)
    mad = float(np.median(absolute))
    if mad <= 1e-9:
        keep = absolute <= 1e-6
    else:
        robust_sigma = 1.4826 * mad
        keep = absolute <= mad_scale * robust_sigma
    points = points[keep]
    return points, len(points) / selected_count


def fit_table_plane(
    xyz_camera_m: NDArray[np.float32],
    object_mask: NDArray[np.bool_],
    *,
    distance_m: float,
    normal_hint: NDArray[np.floating] | None = None,
    max_normal_angle_deg: float = 15.0,
    seed: int = 17,
    max_iterations: int = 256,
) -> TablePlane:
    """Fit a deterministic RANSAC plane to finite points outside the object."""
    xyz = np.asarray(xyz_camera_m)
    mask = np.asarray(object_mask, dtype=bool)
    if xyz.ndim != 3 or xyz.shape[2] != 3 or xyz.shape[:2] != mask.shape:
        raise ValueError("XYZ and object mask must share one pixel grid")
    if distance_m <= 0 or max_iterations <= 0:
        raise ValueError("plane fit thresholds must be positive")
    hint = None
    minimum_alignment = -1.0
    if normal_hint is not None:
        hint = np.asarray(normal_hint, dtype=np.float64)
        if hint.shape != (3,) or not np.isfinite(hint).all():
            raise ValueError("table_normal_hint_invalid")
        hint_norm = float(np.linalg.norm(hint))
        if hint_norm <= 1e-12 or not 0 < max_normal_angle_deg < 90:
            raise ValueError("table_normal_hint_invalid")
        hint = hint / hint_norm
        minimum_alignment = float(np.cos(np.deg2rad(max_normal_angle_deg)))
    excluded = _dilate_mask(mask, radius=2)
    points = np.asarray(xyz[~excluded], dtype=np.float64)
    points = points[np.isfinite(points).all(axis=1)]
    if len(points) < 30:
        raise ValueError("table_plane_points_insufficient")

    rng = np.random.default_rng(seed)
    best_inliers: NDArray[np.bool_] | None = None
    best_error = float("inf")
    for _ in range(min(max_iterations, max(32, len(points) * 2))):
        sample = points[rng.choice(len(points), size=3, replace=False)]
        normal = np.cross(sample[1] - sample[0], sample[2] - sample[0])
        norm = float(np.linalg.norm(normal))
        if norm <= 1e-10:
            continue
        normal /= norm
        if hint is not None and abs(float(np.dot(normal, hint))) < minimum_alignment:
            continue
        offset = -float(np.dot(normal, sample[0]))
        distances = np.abs(points @ normal + offset)
        inliers = distances <= distance_m
        count = int(inliers.sum())
        if count < 3:
            continue
        error = float(np.median(distances[inliers]))
        if (
            best_inliers is None
            or count > int(best_inliers.sum())
            or (count == int(best_inliers.sum()) and error < best_error)
        ):
            best_inliers = inliers
            best_error = error
    if best_inliers is None or int(best_inliers.sum()) < 30:
        raise ValueError("table_plane_ransac_failed")

    inlier_points = points[best_inliers]
    center = np.mean(inlier_points, axis=0)
    _u, _s, vh = np.linalg.svd(inlier_points - center, full_matrices=False)
    normal = vh[-1]
    if hint is not None:
        if abs(float(np.dot(normal, hint))) < minimum_alignment:
            raise ValueError("table_plane_normal_mismatch")
        if float(np.dot(normal, hint)) < 0:
            normal = -normal
    elif float(np.dot(normal, -center)) < 0:
        normal = -normal
    normal /= np.linalg.norm(normal)
    offset = -float(np.dot(normal, center))
    distances = np.abs(points @ normal + offset)
    refined_inliers = distances <= distance_m
    return TablePlane(
        normal=normal,
        offset=offset,
        inlier_ratio=float(refined_inliers.mean()),
        inlier_count=int(refined_inliers.sum()),
    )


def _dilate_mask(mask: NDArray[np.bool_], *, radius: int) -> NDArray[np.bool_]:
    if radius <= 0:
        return np.array(mask, dtype=bool, copy=True)
    source = np.asarray(mask, dtype=bool)
    height, width = source.shape
    padded = np.pad(source, radius, mode="constant", constant_values=False)
    result = np.zeros_like(source)
    diameter = radius * 2 + 1
    for dy in range(diameter):
        for dx in range(diameter):
            result |= padded[dy:dy + height, dx:dx + width]
    return result
