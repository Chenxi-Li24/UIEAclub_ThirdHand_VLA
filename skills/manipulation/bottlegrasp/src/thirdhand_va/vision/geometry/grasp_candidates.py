"""Rank side-grasp candidates for an upright bottle above a fitted table."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from thirdhand_va.common.config import VisionConfig
from thirdhand_va.common.contracts import GraspPoseCamera, MaskCandidate, RgbdFrame

from .pointcloud import erode_mask, fit_table_plane, robust_mask_points


class GeometryRejected(RuntimeError):
    """Depth or geometry quality is insufficient to authorize a grasp pose."""


@dataclass(frozen=True, slots=True)
class GraspCandidate3D:
    pose: GraspPoseCamera
    quality: float
    height_fraction: float
    clearance_m: float
    neighbor_clearance_m: float | None = None
    blockers: tuple[str, ...] = ()
    quality_components: tuple[tuple[str, float], ...] = ()


def estimate_grasp_candidates(
    frame: RgbdFrame,
    candidate: MaskCandidate,
    config: VisionConfig,
    *,
    scene_exclusion_mask: np.ndarray | None = None,
    approach_direction_camera: np.ndarray | None = None,
    upright_direction_camera: np.ndarray | None = None,
) -> tuple[GraspCandidate3D, ...]:
    if not candidate.authorized:
        raise GeometryRejected("target_not_authorized")
    if candidate.mask.shape != frame.depth_m.shape:
        raise GeometryRejected("mask_frame_misaligned")
    fixed_approach = None
    if approach_direction_camera is not None:
        fixed_approach = np.asarray(approach_direction_camera, dtype=np.float64)
        if fixed_approach.shape != (3,) or not np.isfinite(fixed_approach).all():
            raise GeometryRejected("approach_direction_camera_invalid")
        fixed_norm = float(np.linalg.norm(fixed_approach))
        if fixed_norm <= 1e-9:
            raise GeometryRejected("approach_direction_camera_invalid")
        fixed_approach = fixed_approach / fixed_norm
    upright_hint = None
    if upright_direction_camera is not None:
        upright_hint = np.asarray(upright_direction_camera, dtype=np.float64)
        if upright_hint.shape != (3,) or not np.isfinite(upright_hint).all():
            raise GeometryRejected("upright_direction_camera_invalid")
        upright_norm = float(np.linalg.norm(upright_hint))
        if upright_norm <= 1e-9:
            raise GeometryRejected("upright_direction_camera_invalid")
        upright_hint = upright_hint / upright_norm
    eroded = erode_mask(candidate.mask, radius=config.mask_erosion_px)
    points, valid_ratio = robust_mask_points(
        frame.xyz_camera_m,
        eroded,
        min_depth_m=config.min_depth_m,
        max_depth_m=config.max_depth_m,
        mad_scale=3.5,
    )
    if len(points) < config.min_depth_points or valid_ratio < config.min_depth_ratio:
        raise GeometryRejected(
            f"depth_insufficient: points={len(points)}, ratio={valid_ratio:.3f}"
        )

    axial_depth = points[:, 2]
    near_low, near_high = np.quantile(axial_depth, (0.05, 0.45))
    surface = points[
        (axial_depth >= near_low - 1e-6) & (axial_depth <= near_high + 1e-6)
    ]
    if len(surface) < max(80, config.min_depth_points // 4):
        raise GeometryRejected("bottle_surface_depth_cluster_insufficient")

    silhouette_points, _silhouette_ratio = robust_mask_points(
        frame.xyz_camera_m,
        candidate.mask,
        min_depth_m=config.min_depth_m,
        max_depth_m=config.max_depth_m,
        mad_scale=3.5,
    )
    silhouette_depth = silhouette_points[:, 2]
    silhouette_low, silhouette_high = np.quantile(silhouette_depth, (0.05, 0.45))
    silhouette_surface = silhouette_points[
        (silhouette_depth >= silhouette_low - 1e-6)
        & (silhouette_depth <= silhouette_high + 1e-6)
    ]

    table_exclusion = candidate.mask
    neighbor_points = np.empty((0, 3), dtype=np.float64)
    if scene_exclusion_mask is not None:
        table_exclusion = np.asarray(scene_exclusion_mask, dtype=bool)
        if table_exclusion.shape != candidate.mask.shape:
            raise GeometryRejected("scene_exclusion_mask_misaligned")
        table_exclusion = np.logical_or(table_exclusion, candidate.mask)
        neighbor_mask = np.logical_and(table_exclusion, np.logical_not(candidate.mask))
        neighbor_points = np.asarray(frame.xyz_camera_m[neighbor_mask], dtype=np.float64)
        neighbor_points = neighbor_points[
            np.isfinite(neighbor_points).all(axis=1)
            & (neighbor_points[:, 2] >= config.min_depth_m)
            & (neighbor_points[:, 2] <= config.max_depth_m)
        ]
    try:
        table = fit_table_plane(
            frame.xyz_camera_m,
            table_exclusion,
            distance_m=config.table_plane_distance_m,
            normal_hint=upright_hint,
            max_normal_angle_deg=config.upright_axis_max_angle_deg,
        )
    except ValueError as error:
        raise GeometryRejected(str(error)) from error

    cloud_center = np.median(surface, axis=0)
    centered = surface - cloud_center
    # The deployed task explicitly admits only bottles placed upright on the
    # fitted table.  A wrist fisheye sees only the near cylindrical skin, so
    # the largest PCA eigenvector is strongly biased by partial depth and can
    # jump tens of degrees between frames.  Reuse the robust RANSAC table
    # normal as the task-constrained bottle axis; the height/width check below
    # still rejects an object lying sideways.
    axis = np.array(
        table.normal if upright_hint is None else upright_hint,
        dtype=np.float64,
        copy=True,
    )
    if float(np.dot(axis, table.normal)) < 0:
        axis = -axis

    projections = centered @ axis
    low, high = np.quantile(projections, (0.05, 0.95))
    height_m = float(high - low)
    projected_axis = np.array(axis[:2], copy=True)
    projected_norm = float(np.linalg.norm(projected_axis))
    if projected_norm <= 1e-9:
        raise GeometryRejected("bottle_axis_projection_unreliable")
    projected_axis /= projected_norm
    transverse = np.asarray([-projected_axis[1], projected_axis[0], 0.0])
    transverse_positions = (silhouette_surface - cloud_center) @ transverse
    width_m = float(
        np.quantile(transverse_positions, 0.99)
        - np.quantile(transverse_positions, 0.01)
    )
    if not np.isfinite(width_m) or width_m <= 0.005:
        raise GeometryRejected("bottle_width_unreliable")
    if width_m > config.max_grasp_width_m:
        raise GeometryRejected(f"grasp_width_exceeded: width_m={width_m:.4f}")
    if width_m < config.min_grasp_width_m:
        raise GeometryRejected(f"grasp_width_below_minimum: width_m={width_m:.4f}")
    if not np.isfinite(height_m) or height_m <= width_m:
        raise GeometryRejected("bottle_height_unreliable")

    candidates: list[GraspCandidate3D] = []
    neighbor_blocked = False
    half_band = max(height_m * 0.08, 0.004)
    for fraction in config.grasp_band_fractions:
        target_projection = low + fraction * height_m
        safe = surface[np.abs(projections - target_projection) <= half_band]
        if len(safe) < max(20, config.min_depth_points // 12):
            continue
        point = np.median(safe, axis=0)
        clearance_m = float(abs(table.signed_distance(point[None, :])[0]))
        if clearance_m < config.min_grasp_clearance_m:
            continue
        if fixed_approach is None:
            approach = point - axis * float(np.dot(point, axis))
            approach_norm = float(np.linalg.norm(approach))
            if approach_norm <= 1e-9:
                continue
            approach /= approach_norm
        else:
            approach = fixed_approach
        neighbor_clearance_m = None
        if len(neighbor_points):
            segment_start = point - approach * config.approach_corridor_length_m
            segment = point - segment_start
            segment_norm_sq = float(np.dot(segment, segment))
            relative = neighbor_points - segment_start
            parameters = np.clip((relative @ segment) / segment_norm_sq, 0.0, 1.0)
            closest = segment_start + parameters[:, None] * segment
            neighbor_clearance_m = float(
                np.min(np.linalg.norm(neighbor_points - closest, axis=1))
            )
            required_clearance = (
                config.approach_corridor_radius_m + config.min_neighbor_clearance_m
            )
            if neighbor_clearance_m < required_clearance:
                neighbor_blocked = True
                continue

        safe_median = np.median(safe, axis=0)
        safe_mad = np.median(np.abs(safe - safe_median), axis=0)
        position_std = 1.4826 * safe_mad / np.sqrt(len(safe))
        depth_score = float(np.clip(valid_ratio, 0.0, 1.0))
        point_score = float(np.clip(len(surface) / (2 * config.min_depth_points), 0.0, 1.0))
        covariance_score = float(1.0 / (1.0 + np.linalg.norm(position_std) / 0.005))
        width_score = float(np.clip(
            (config.max_grasp_width_m - width_m)
            / (config.max_grasp_width_m - config.min_grasp_width_m),
            0.0,
            1.0,
        ))
        clearance_score = float(np.clip(
            clearance_m / max(config.min_grasp_clearance_m * 3.0, 1e-6),
            0.0,
            1.0,
        ))
        centered_body_score = float(np.clip(
            1.0 - abs(fraction - 0.5) / 0.15,
            0.0,
            1.0,
        ))
        quality_components = (
            ("depth_ratio", depth_score),
            ("point_support", point_score),
            ("position_covariance", covariance_score),
            ("width_margin", width_score),
            ("table_clearance", clearance_score),
            ("centered_body", centered_body_score),
        )
        quality = (
            0.25 * depth_score
            + 0.15 * point_score
            + 0.20 * covariance_score
            + 0.10 * width_score
            + 0.15 * clearance_score
            + 0.15 * centered_body_score
        )
        pose = GraspPoseCamera(
            point_m=tuple(float(value) for value in point),
            axis=tuple(float(value) for value in axis),
            approach=tuple(float(value) for value in approach),
            width_m=width_m,
            position_std_m=tuple(float(value) for value in position_std),
            valid_points=len(surface),
            depth_valid_ratio=float(valid_ratio),
            height_m=height_m,
        )
        candidates.append(GraspCandidate3D(
            pose=pose,
            quality=float(quality),
            height_fraction=float(fraction),
            clearance_m=clearance_m,
            neighbor_clearance_m=neighbor_clearance_m,
            quality_components=quality_components,
        ))
    if not candidates:
        if neighbor_blocked:
            raise GeometryRejected("neighbor_approach_clearance_insufficient")
        raise GeometryRejected("safe_grasp_band_insufficient")
    return tuple(sorted(candidates, key=lambda item: item.quality, reverse=True))


__all__ = ["GeometryRejected", "GraspCandidate3D", "estimate_grasp_candidates"]
