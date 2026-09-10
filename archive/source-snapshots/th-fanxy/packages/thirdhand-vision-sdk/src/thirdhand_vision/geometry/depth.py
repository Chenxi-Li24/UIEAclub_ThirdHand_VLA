"""Register metric pinhole depth into native Lumos SEUCM pixels."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from thirdhand_vision.core.camera import PinholeCamera, SeucmCamera
from thirdhand_vision.core.errors import InputValidationError
from thirdhand_vision.core.transforms import transform_points, validate_transform


def _readonly(value: Any, shape: tuple[int, ...], name: str, dtype: Any = float) -> np.ndarray:
    array = np.asarray(value, dtype=dtype)
    if array.shape != shape:
        raise InputValidationError(f"{name} must have shape {shape}")
    result = np.array(array, copy=True)
    result.setflags(write=False)
    return result


@dataclass(frozen=True)
class RegisteredDepth:
    z_m: np.ndarray = field(compare=False, repr=False)
    range_m: np.ndarray = field(compare=False, repr=False)
    valid: np.ndarray = field(compare=False, repr=False)
    source_count: np.ndarray = field(compare=False, repr=False)
    points_lumos_m: np.ndarray = field(compare=False, repr=False)

    def __post_init__(self) -> None:
        valid = np.asarray(self.valid)
        if valid.ndim != 2 or valid.dtype != np.bool_:
            raise InputValidationError("registered valid mask must be boolean 2D")
        shape = valid.shape
        z_m = _readonly(self.z_m, shape, "z_m")
        range_m = _readonly(self.range_m, shape, "range_m")
        source_count = _readonly(self.source_count, shape, "source_count", np.int32)
        points = _readonly(self.points_lumos_m, (*shape, 3), "points_lumos_m")
        if np.any(source_count < 0):
            raise InputValidationError("source_count cannot be negative")
        if np.any(valid & (~np.isfinite(z_m) | (z_m <= 0.0))):
            raise InputValidationError("valid registered depth must be finite and positive")
        if np.any(valid & ~np.isfinite(points).all(axis=2)):
            raise InputValidationError("valid registered points must be finite")
        valid_copy = np.array(valid, copy=True)
        valid_copy.setflags(write=False)
        object.__setattr__(self, "z_m", z_m)
        object.__setattr__(self, "range_m", range_m)
        object.__setattr__(self, "valid", valid_copy)
        object.__setattr__(self, "source_count", source_count)
        object.__setattr__(self, "points_lumos_m", points)

    @classmethod
    def empty(cls, image_shape: tuple[int, int]) -> "RegisteredDepth":
        height, width = image_shape
        return cls(
            z_m=np.full((height, width), np.nan),
            range_m=np.full((height, width), np.nan),
            valid=np.zeros((height, width), dtype=bool),
            source_count=np.zeros((height, width), dtype=np.int32),
            points_lumos_m=np.full((height, width, 3), np.nan),
        )


def rasterize_lumos_points(
    uv_px: Any,
    points_lumos_m: Any,
    image_shape: tuple[int, int],
) -> RegisteredDepth:
    pixels = np.asarray(uv_px, dtype=float)
    points = np.asarray(points_lumos_m, dtype=float)
    if pixels.ndim != 2 or pixels.shape[1] != 2:
        raise InputValidationError("uv_px must have shape (N, 2)")
    if points.shape != (len(pixels), 3):
        raise InputValidationError("points_lumos_m must have shape (N, 3)")
    if len(image_shape) != 2 or any(not isinstance(value, int) or value <= 0 for value in image_shape):
        raise InputValidationError("image_shape must contain positive dimensions")
    height, width = image_shape
    if not len(pixels):
        return RegisteredDepth.empty(image_shape)
    finite = np.isfinite(pixels).all(axis=1) & np.isfinite(points).all(axis=1)
    finite &= points[:, 2] > 0.0
    rounded = np.zeros_like(pixels, dtype=np.int64)
    rounded[finite] = np.rint(pixels[finite]).astype(np.int64)
    cols, rows = rounded[:, 0], rounded[:, 1]
    usable = finite & (cols >= 0) & (cols < width) & (rows >= 0) & (rows < height)
    if not usable.any():
        return RegisteredDepth.empty(image_shape)
    cols = cols[usable]
    rows = rows[usable]
    points = points[usable]
    pixel_index = rows * width + cols
    source_count = np.zeros((height, width), dtype=np.int32)
    np.add.at(source_count, (rows, cols), 1)
    original_order = np.arange(len(points))
    order = np.lexsort((original_order, points[:, 2], pixel_index))
    sorted_pixels = pixel_index[order]
    first_per_pixel = np.concatenate(([True], sorted_pixels[1:] != sorted_pixels[:-1]))
    winners = order[first_per_pixel]
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


def register_depth(
    depth_z_m: Any,
    *,
    d435: PinholeCamera,
    t_lumos_from_d435: Any,
    lumos: SeucmCamera,
    min_depth_m: float,
    max_depth_m: float,
) -> RegisteredDepth:
    depth = np.asarray(depth_z_m, dtype=float)
    if depth.shape != (d435.height, d435.width):
        raise InputValidationError("depth image does not match D435 dimensions")
    lower, upper = float(min_depth_m), float(max_depth_m)
    if not np.isfinite([lower, upper]).all() or lower <= 0.0 or upper <= lower:
        raise InputValidationError("depth limits must satisfy 0 < min < max")
    transform = validate_transform(t_lumos_from_d435)
    usable = np.isfinite(depth) & (depth >= lower) & (depth <= upper)
    rows, cols = np.nonzero(usable)
    if not len(rows):
        return RegisteredDepth.empty((lumos.height, lumos.width))
    pixels = np.column_stack((cols, rows)).astype(float)
    points_d435 = d435.deproject_z(pixels, depth[rows, cols])
    points_lumos = transform_points(transform, points_d435)
    projected_pixels, projected = lumos.project(points_lumos)
    return rasterize_lumos_points(
        projected_pixels[projected],
        points_lumos[projected],
        (lumos.height, lumos.width),
    )

