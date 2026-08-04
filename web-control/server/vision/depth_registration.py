"""Project D435 axial depth into Lumos SEUCM pixels with a z-buffer."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Tuple

import numpy as np

from .camera_models import PinholeCamera, SeucmCamera
from .geometry import transform_points, validate_transform
from .types import InvalidDataError


def _readonly(value: Any, name: str) -> np.ndarray:
    array = np.array(value, copy=True)
    if not np.isfinite(array).all() and array.dtype.kind not in "bui":
        # Floating result images intentionally use NaN for invalid pixels.
        finite_or_nan = np.isfinite(array) | np.isnan(array)
        if not finite_or_nan.all():
            raise InvalidDataError(f"{name} contains infinite values")
    array.setflags(write=False)
    return array


@dataclass(frozen=True)
class RegisteredDepth:
    z_m: np.ndarray = field(compare=False)
    range_m: np.ndarray = field(compare=False)
    valid: np.ndarray = field(compare=False)
    source_count: np.ndarray = field(compare=False)
    points_lumos_m: np.ndarray = field(compare=False)

    def __post_init__(self) -> None:
        z = np.asarray(self.z_m, dtype=float)
        range_image = np.asarray(self.range_m, dtype=float)
        valid = np.asarray(self.valid, dtype=bool)
        counts = np.asarray(self.source_count)
        points = np.asarray(self.points_lumos_m, dtype=float)
        if z.ndim != 2:
            raise InvalidDataError("registered depth must be a 2D image")
        shape = z.shape
        if range_image.shape != shape or valid.shape != shape or counts.shape != shape:
            raise InvalidDataError("registered depth planes must have matching shapes")
        if points.shape != shape + (3,):
            raise InvalidDataError("points_lumos_m must have shape (H, W, 3)")
        if np.any(counts < 0) or not np.issubdtype(counts.dtype, np.integer):
            raise InvalidDataError("source_count must contain non-negative integers")
        if not np.isfinite(z[valid]).all() or not np.isfinite(range_image[valid]).all():
            raise InvalidDataError("valid registered pixels must have finite depth")
        if not np.isfinite(points[valid]).all() or np.any(z[valid] <= 0.0):
            raise InvalidDataError("valid registered points must be finite and in front of Lumos")
        if not np.isnan(z[~valid]).all() or not np.isnan(range_image[~valid]).all():
            raise InvalidDataError("invalid depth pixels must be NaN")
        if not np.isnan(points[~valid]).all():
            raise InvalidDataError("invalid 3D pixels must be NaN")
        object.__setattr__(self, "z_m", _readonly(z, "z_m"))
        object.__setattr__(self, "range_m", _readonly(range_image, "range_m"))
        object.__setattr__(self, "valid", _readonly(valid, "valid"))
        object.__setattr__(self, "source_count", _readonly(counts.astype(np.int32), "source_count"))
        object.__setattr__(self, "points_lumos_m", _readonly(points, "points_lumos_m"))


def _empty_result(image_shape: Tuple[int, int]) -> RegisteredDepth:
    height, width = image_shape
    return RegisteredDepth(
        z_m=np.full((height, width), np.nan),
        range_m=np.full((height, width), np.nan),
        valid=np.zeros((height, width), dtype=bool),
        source_count=np.zeros((height, width), dtype=np.int32),
        points_lumos_m=np.full((height, width, 3), np.nan),
    )


def rasterize_lumos_points(
    uv_px: Any,
    points_lumos_m: Any,
    image_shape: Tuple[int, int],
) -> RegisteredDepth:
    pixels = np.asarray(uv_px, dtype=float)
    points = np.asarray(points_lumos_m, dtype=float)
    if pixels.ndim != 2 or pixels.shape[1] != 2:
        raise InvalidDataError(f"uv_px must have shape (N, 2), got {pixels.shape}")
    if points.shape != (len(pixels), 3):
        raise InvalidDataError(f"points_lumos_m must have shape ({len(pixels)}, 3)")
    if len(image_shape) != 2:
        raise InvalidDataError("image_shape must contain height and width")
    height, width = image_shape
    if not isinstance(height, int) or not isinstance(width, int) or height <= 0 or width <= 0:
        raise InvalidDataError("image dimensions must be positive integers")
    if len(pixels) == 0:
        return _empty_result((height, width))

    finite = np.isfinite(pixels).all(axis=1) & np.isfinite(points).all(axis=1)
    finite &= points[:, 2] > 0.0
    rounded = np.zeros_like(pixels, dtype=np.int64)
    rounded[finite] = np.rint(pixels[finite]).astype(np.int64)
    cols, rows = rounded[:, 0], rounded[:, 1]
    valid = finite & (cols >= 0) & (cols < width) & (rows >= 0) & (rows < height)
    if not valid.any():
        return _empty_result((height, width))

    cols = cols[valid]
    rows = rows[valid]
    points = points[valid]
    pixel_index = rows * width + cols
    source_count = np.zeros((height, width), dtype=np.int32)
    np.add.at(source_count, (rows, cols), 1)

    original_order = np.arange(len(points))
    order = np.lexsort((original_order, points[:, 2], pixel_index))
    sorted_pixels = pixel_index[order]
    first = np.concatenate(([True], sorted_pixels[1:] != sorted_pixels[:-1]))
    winners = order[first]
    winner_rows = rows[winners]
    winner_cols = cols[winners]
    winner_points = points[winners]

    z_image = np.full((height, width), np.nan)
    range_image = np.full((height, width), np.nan)
    point_image = np.full((height, width, 3), np.nan)
    valid_image = np.zeros((height, width), dtype=bool)
    z_image[winner_rows, winner_cols] = winner_points[:, 2]
    range_image[winner_rows, winner_cols] = np.linalg.norm(winner_points, axis=1)
    point_image[winner_rows, winner_cols] = winner_points
    valid_image[winner_rows, winner_cols] = True
    return RegisteredDepth(z_image, range_image, valid_image, source_count, point_image)


def register_depth_to_lumos(
    depth_z_m: Any,
    d435: PinholeCamera,
    t_lumos_from_d435: Any,
    lumos: SeucmCamera,
    min_depth_m: float,
    max_depth_m: float,
) -> RegisteredDepth:
    depth = np.asarray(depth_z_m, dtype=float)
    if depth.shape != (d435.height, d435.width):
        raise InvalidDataError(
            f"D435 depth shape must be {(d435.height, d435.width)}, got {depth.shape}"
        )
    lower, upper = float(min_depth_m), float(max_depth_m)
    if not np.isfinite([lower, upper]).all() or lower <= 0.0 or upper <= lower:
        raise InvalidDataError("depth limits must satisfy 0 < min_depth_m < max_depth_m")
    transform = validate_transform(t_lumos_from_d435)
    usable = np.isfinite(depth) & (depth >= lower) & (depth <= upper)
    rows, cols = np.nonzero(usable)
    if not len(rows):
        return _empty_result((lumos.height, lumos.width))
    uv_d435 = np.column_stack((cols, rows)).astype(float)
    points_d435 = d435.deproject_z(uv_d435, depth[rows, cols])
    points_lumos = transform_points(transform, points_d435)
    uv_lumos, projected = lumos.project(points_lumos)
    return rasterize_lumos_points(
        uv_lumos[projected],
        points_lumos[projected],
        (lumos.height, lumos.width),
    )


def select_masked_cloud(registered: RegisteredDepth, mask: Any) -> np.ndarray:
    mask_array = np.asarray(mask)
    if mask_array.shape != registered.valid.shape or mask_array.dtype != np.bool_:
        raise InvalidDataError("mask must be a boolean array matching the Lumos image")
    selected = registered.valid & mask_array
    return np.array(registered.points_lumos_m[selected], copy=True)

