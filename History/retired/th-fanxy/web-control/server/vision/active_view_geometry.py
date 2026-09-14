"""Pure Lumos-to-table geometry for active observation planning."""

from __future__ import annotations

from typing import Any

import numpy as np

from .active_view_types import (
    CoarseTargetEstimate,
    TablePlane,
    validated_coverage_polygon,
)
from .camera_models import SeucmCamera
from .geometry import validate_transform
from .types import FrameStamp, InvalidDataError


def _lower_boundary_pixels(mask: np.ndarray, maximum_bins: int = 16) -> np.ndarray:
    rows, columns = np.nonzero(mask)
    unique_columns = np.unique(columns)
    column_groups = np.array_split(unique_columns, min(maximum_bins, len(unique_columns)))
    pixels: list[tuple[float, float]] = []
    for group in column_groups:
        in_group = np.isin(columns, group)
        bottom_row = int(np.max(rows[in_group]))
        bottom_columns = columns[in_group & (rows == bottom_row)]
        pixels.append((float(np.median(bottom_columns)), float(bottom_row)))
    return np.asarray(pixels, dtype=float)


def estimate_table_target(
    identity_id: int,
    mask: Any,
    lumos: SeucmCamera,
    t_base_from_lumos: Any,
    table: TablePlane,
    source_stamp: FrameStamp,
) -> CoarseTargetEstimate:
    """Estimate coarse table XY from the lower edge of a Lumos instance mask.

    The result is observation-planning evidence only. It deliberately contains
    no Z coordinate and cannot be passed to the grasp pose API.
    """

    if not isinstance(lumos, SeucmCamera):
        raise InvalidDataError("table target estimation requires a Lumos SEUCM camera")
    mask_array = np.asarray(mask)
    expected_shape = (lumos.height, lumos.width)
    if mask_array.dtype != np.bool_ or mask_array.shape != expected_shape:
        raise InvalidDataError(f"instance mask must be boolean with shape {expected_shape}")
    if not mask_array.any():
        raise InvalidDataError("instance mask cannot be empty")
    if not isinstance(table, TablePlane) or not table.validated:
        raise InvalidDataError("table target estimation requires a validated table")
    if not isinstance(source_stamp, FrameStamp):
        raise InvalidDataError("table target estimation requires frame provenance")

    transform = validate_transform(t_base_from_lumos)
    pixels = _lower_boundary_pixels(mask_array)
    if len(pixels) < 3:
        raise InvalidDataError("table intersection requires at least three mask-edge rays")
    rays_lumos, unprojected = lumos.unproject(pixels)
    origin_base = transform[:3, 3]
    rays_base = rays_lumos @ transform[:3, :3].T
    denominator = rays_base @ table.normal_base
    numerator = -(float(table.normal_base @ origin_base) + table.offset_m)
    with np.errstate(divide="ignore", invalid="ignore"):
        distance = numerator / denominator
    valid = (
        unprojected
        & np.isfinite(rays_base).all(axis=1)
        & np.isfinite(distance)
        & (np.abs(denominator) > 1e-12)
        & (distance > 0.0)
    )
    if np.count_nonzero(valid) < 3:
        raise InvalidDataError("table intersection produced fewer than three forward rays")

    intersections = origin_base + distance[valid, None] * rays_base[valid]
    samples_xy_m = intersections[:, :2]
    center_xy_m = np.median(samples_xy_m, axis=0)
    covariance_xy_m2 = np.asarray(np.cov(samples_xy_m, rowvar=False, ddof=1), dtype=float)
    covariance_xy_m2 += np.eye(2) * table.position_rmse_m**2

    return CoarseTargetEstimate(
        identity_id=identity_id,
        center_xy_m=center_xy_m,
        covariance_xy_m2=covariance_xy_m2,
        samples_xy_m=samples_xy_m,
        source_stamp=source_stamp,
        calibration_id=table.calibration_id,
    )


def contains_estimate(
    polygon_xy_m: Any,
    estimate: CoarseTargetEstimate,
    minimum_edge_margin_m: float,
) -> bool:
    """Return whether all coarse target samples fit inside a convex polygon."""

    if not isinstance(estimate, CoarseTargetEstimate):
        raise InvalidDataError("coverage check requires a coarse target estimate")
    if isinstance(minimum_edge_margin_m, bool):
        raise InvalidDataError("coverage edge margin must be finite and non-negative")
    try:
        margin = float(minimum_edge_margin_m)
    except (TypeError, ValueError) as exc:
        raise InvalidDataError("coverage edge margin must be finite and non-negative") from exc
    if not np.isfinite(margin) or margin < 0.0:
        raise InvalidDataError("coverage edge margin must be finite and non-negative")

    polygon = validated_coverage_polygon(polygon_xy_m)
    signed_area = 0.5 * np.sum(
        polygon[:, 0] * np.roll(polygon[:, 1], -1)
        - polygon[:, 1] * np.roll(polygon[:, 0], -1)
    )
    orientation = 1.0 if signed_area > 0.0 else -1.0
    points = np.vstack((estimate.samples_xy_m, estimate.center_xy_m[None, :]))
    for start, end in zip(polygon, np.roll(polygon, -1, axis=0)):
        edge = end - start
        inward = orientation * np.array([-edge[1], edge[0]]) / np.linalg.norm(edge)
        distances = (points - start) @ inward
        if float(np.min(distances)) < margin - 1e-12:
            return False
    return True


__all__ = ["contains_estimate", "estimate_table_target"]
