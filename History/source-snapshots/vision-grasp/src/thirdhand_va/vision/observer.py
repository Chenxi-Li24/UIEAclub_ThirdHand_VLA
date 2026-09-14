"""Pure observation helpers for supervised bottle-pick diagnostics."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
import time
from typing import Any, Mapping, Sequence

import cv2
import numpy as np

from thirdhand_va.common.config import VisionConfig
from thirdhand_va.common.contracts import MaskCandidate, RgbdFrame
from thirdhand_va.vision.geometry.pointcloud import erode_mask, robust_mask_points


_ROTATION_ONLY_BLOCKERS = {
    "bottle_aspect_out_of_range",
    "container_type_not_bottle",
}


def wait_for_pose_covering_frame(
    read_pose: Callable[[], Mapping[str, Any]],
    *,
    capture_wall_ms: int,
    captured_monotonic_ns: int,
    max_wait_ms: int = 100,
    max_frame_age_ms: int = 250,
    poll_interval_ms: int = 5,
    monotonic_ns: Callable[[], int] = time.monotonic_ns,
    sleep: Callable[[float], None] = time.sleep,
) -> Mapping[str, Any]:
    """Wait briefly for a real stationary pose sample newer than one camera frame.

    Motion, an old inflight frame captured before the current stationary interval,
    invalid pose data, and already-stale frames return immediately.  Returned
    timestamps always come directly from ``read_pose``.
    """

    pose = read_pose()
    if not _pose_can_advance_to_cover_capture(pose, capture_wall_ms):
        return pose
    started_ns = int(monotonic_ns())
    wait_deadline_ns = started_ns + int(max_wait_ms) * 1_000_000
    frame_deadline_ns = int(captured_monotonic_ns) + int(max_frame_age_ms) * 1_000_000
    deadline_ns = min(wait_deadline_ns, frame_deadline_ns)
    while True:
        now_ns = int(monotonic_ns())
        remaining_ns = deadline_ns - now_ns
        if remaining_ns <= 0:
            return pose
        sleep(min(int(poll_interval_ms) * 1_000_000, remaining_ns) / 1_000_000_000)
        pose = read_pose()
        if not _pose_can_advance_to_cover_capture(pose, capture_wall_ms):
            return pose


def _pose_can_advance_to_cover_capture(
    pose: Mapping[str, Any], capture_wall_ms: int
) -> bool:
    if not isinstance(pose, Mapping):
        return False
    pose_ts = pose.get("ts")
    stationary_since_ms = pose.get("stationary_since_ms")
    if (
        pose.get("pose_frame") != "sdk_tool"
        or pose.get("stationary") is not True
        or not isinstance(pose_ts, int)
        or isinstance(pose_ts, bool)
        or not isinstance(stationary_since_ms, int)
        or isinstance(stationary_since_ms, bool)
        or stationary_since_ms > capture_wall_ms
        or not 0 <= capture_wall_ms - pose_ts <= 500
    ):
        return False
    try:
        position = np.asarray(pose["tcp_position_m"], dtype=np.float64)
        euler = np.asarray(pose["tcp_euler_rad"], dtype=np.float64)
    except (KeyError, TypeError, ValueError):
        return False
    return (
        pose_ts < capture_wall_ms
        and position.shape == (3,)
        and euler.shape == (3,)
        and np.isfinite(position).all()
        and np.isfinite(euler).all()
    )


def apply_rotated_mask_aspect_gate(
    candidate: MaskCandidate,
    config: VisionConfig,
) -> tuple[MaskCandidate, float | None, bool]:
    """Recover only axis-aligned aspect failures using an oriented rectangle."""

    ys, xs = np.nonzero(candidate.mask)
    if len(xs) < 3:
        return candidate, None, False
    points = np.column_stack((xs, ys)).astype(np.float32)
    _center, (width, height), _angle = cv2.minAreaRect(points)
    short = min(float(width), float(height))
    long = max(float(width), float(height))
    ratio = None if short <= 1e-6 else long / short
    blockers = set(candidate.reasons)
    recoverable = (
        not candidate.authorized
        and blockers == _ROTATION_ONLY_BLOCKERS
        and ratio is not None
        and config.min_bottle_aspect_ratio <= ratio <= config.max_bottle_aspect_ratio
    )
    if not recoverable:
        return candidate, ratio, False
    return replace(candidate, authorized=True, reasons=()), ratio, True


def robust_transverse_width_m(
    body_points_camera_m: np.ndarray,
    silhouette_points_camera_m: np.ndarray,
    *,
    upright_direction_camera: np.ndarray,
) -> float | None:
    """Reuse the grasp solver's near-surface transverse percentile width."""

    body = np.asarray(body_points_camera_m, dtype=np.float64)
    silhouette = np.asarray(silhouette_points_camera_m, dtype=np.float64)
    axis = np.asarray(upright_direction_camera, dtype=np.float64)
    if (
        body.ndim != 2
        or body.shape[1:] != (3,)
        or silhouette.ndim != 2
        or silhouette.shape[1:] != (3,)
        or len(body) < 3
        or len(silhouette) < 3
        or axis.shape != (3,)
        or not np.isfinite(axis).all()
    ):
        return None
    body = body[np.isfinite(body).all(axis=1)]
    silhouette = silhouette[np.isfinite(silhouette).all(axis=1)]
    if len(body) < 3 or len(silhouette) < 3:
        return None
    body_low, body_high = np.quantile(body[:, 2], (0.05, 0.45))
    body_surface = body[
        (body[:, 2] >= body_low - 1e-6) & (body[:, 2] <= body_high + 1e-6)
    ]
    silhouette_low, silhouette_high = np.quantile(silhouette[:, 2], (0.05, 0.45))
    silhouette_surface = silhouette[
        (silhouette[:, 2] >= silhouette_low - 1e-6)
        & (silhouette[:, 2] <= silhouette_high + 1e-6)
    ]
    if len(body_surface) < 3 or len(silhouette_surface) < 3:
        return None
    projected_axis = np.array(axis[:2], copy=True)
    projected_norm = float(np.linalg.norm(projected_axis))
    if projected_norm <= 1e-9:
        return None
    projected_axis /= projected_norm
    transverse = np.asarray([-projected_axis[1], projected_axis[0], 0.0])
    center = np.median(body_surface, axis=0)
    positions = (silhouette_surface - center) @ transverse
    width = float(np.quantile(positions, 0.99) - np.quantile(positions, 0.01))
    return width if np.isfinite(width) and width > 0 else None


def select_base_height_band(
    body_points_camera_m: np.ndarray,
    silhouette_points_camera_m: np.ndarray,
    *,
    t_base_camera: np.ndarray,
    upright_direction_camera: np.ndarray,
    target_base_z_m: float,
    half_band_m: float = 0.005,
    min_points: int = 20,
) -> dict[str, Any] | None:
    """Select a supported bottle-surface band at one explicit base height."""

    body = np.asarray(body_points_camera_m, dtype=np.float64)
    silhouette = np.asarray(silhouette_points_camera_m, dtype=np.float64)
    transform = np.asarray(t_base_camera, dtype=np.float64)
    axis = np.asarray(upright_direction_camera, dtype=np.float64)
    try:
        target_z = float(target_base_z_m)
        half_band = float(half_band_m)
    except (TypeError, ValueError):
        return None
    if (
        body.ndim != 2
        or body.shape[1:] != (3,)
        or silhouette.ndim != 2
        or silhouette.shape[1:] != (3,)
        or transform.shape != (4, 4)
        or axis.shape != (3,)
        or not np.isfinite(transform).all()
        or not np.isfinite(axis).all()
        or not np.isfinite(target_z)
        or not np.isfinite(half_band)
        or half_band <= 0
        or min_points < 3
    ):
        return None
    body = body[np.isfinite(body).all(axis=1)]
    silhouette = silhouette[np.isfinite(silhouette).all(axis=1)]
    if len(body) < min_points or len(silhouette) < min_points:
        return None

    body_low, body_high = np.quantile(body[:, 2], (0.05, 0.45))
    silhouette_low, silhouette_high = np.quantile(silhouette[:, 2], (0.05, 0.45))
    body_surface = body[
        (body[:, 2] >= body_low - 1e-6) & (body[:, 2] <= body_high + 1e-6)
    ]
    silhouette_surface = silhouette[
        (silhouette[:, 2] >= silhouette_low - 1e-6)
        & (silhouette[:, 2] <= silhouette_high + 1e-6)
    ]

    rotation = transform[:3, :3]
    translation = transform[:3, 3]
    body_base = (rotation @ body_surface.T).T + translation
    silhouette_base = (rotation @ silhouette_surface.T).T + translation
    body_keep = np.abs(body_base[:, 2] - target_z) <= half_band
    silhouette_keep = np.abs(silhouette_base[:, 2] - target_z) <= half_band
    body_band_camera = body_surface[body_keep]
    body_band_base = body_base[body_keep]
    silhouette_band_camera = silhouette_surface[silhouette_keep]
    if len(body_band_base) < min_points or len(silhouette_band_camera) < min_points:
        return None

    projected_axis = np.array(axis[:2], copy=True)
    projected_norm = float(np.linalg.norm(projected_axis))
    if projected_norm <= 1e-9:
        return None
    projected_axis /= projected_norm
    transverse_camera = np.asarray(
        [-projected_axis[1], projected_axis[0], 0.0], dtype=np.float64
    )
    median_base = np.median(body_band_base, axis=0)
    median_camera = rotation.T @ (median_base - translation)
    positions = (silhouette_band_camera - median_camera) @ transverse_camera
    width = float(np.quantile(positions, 0.99) - np.quantile(positions, 0.01))
    if not np.isfinite(width) or width <= 0:
        return None
    return {
        "median_base_xyz_m": [float(value) for value in median_base],
        "median_camera_xyz_m": [float(value) for value in median_camera],
        "width_m": width,
        "body_points": int(len(body_band_base)),
        "silhouette_points": int(len(silhouette_band_camera)),
        "body_surface_depth_range_m": [float(body_low), float(body_high)],
    }


def _nearest_height_band_pixel(
    frame: RgbdFrame,
    mask: np.ndarray,
    *,
    t_base_camera: np.ndarray,
    target_base_z_m: float,
    half_band_m: float,
    body_surface_depth_range_m: Sequence[float],
    median_base_xyz_m: Sequence[float],
) -> tuple[list[float], list[float], list[float]] | None:
    ys, xs = np.nonzero(mask)
    if not len(xs):
        return None
    points = np.asarray(frame.xyz_camera_m[ys, xs], dtype=np.float64)
    transform = np.asarray(t_base_camera, dtype=np.float64)
    low, high = (float(value) for value in body_surface_depth_range_m)
    finite = (
        np.isfinite(points).all(axis=1)
        & (points[:, 2] >= low - 1e-6)
        & (points[:, 2] <= high + 1e-6)
    )
    points = points[finite]
    xs = xs[finite]
    ys = ys[finite]
    if not len(points):
        return None
    points_base = (transform[:3, :3] @ points.T).T + transform[:3, 3]
    in_band = np.abs(points_base[:, 2] - float(target_base_z_m)) <= float(half_band_m)
    points = points[in_band]
    points_base = points_base[in_band]
    xs = xs[in_band]
    ys = ys[in_band]
    if not len(points):
        return None
    median_base = np.asarray(median_base_xyz_m, dtype=np.float64)
    selected = int(np.argmin(np.linalg.norm(points_base - median_base, axis=1)))
    return (
        [float(xs[selected]), float(ys[selected])],
        [float(value) for value in points[selected]],
        [float(value) for value in points_base[selected]],
    )


def estimate_base_center_from_surface(
    *,
    surface_xyz_m: Sequence[float],
    camera_origin_xyz_m: Sequence[float],
    width_m: float,
) -> list[float] | None:
    """Advance half a measured width along the base-horizontal viewing ray."""

    surface = np.asarray(surface_xyz_m, dtype=np.float64)
    origin = np.asarray(camera_origin_xyz_m, dtype=np.float64)
    try:
        width = float(width_m)
    except (TypeError, ValueError):
        return None
    if (
        surface.shape != (3,)
        or origin.shape != (3,)
        or not np.isfinite(surface).all()
        or not np.isfinite(origin).all()
        or not np.isfinite(width)
        or width <= 0
    ):
        return None
    direction = surface - origin
    direction[2] = 0.0
    norm = float(np.linalg.norm(direction))
    if norm <= 1e-9:
        return None
    center = surface + direction / norm * (width * 0.5)
    return [float(value) for value in center]


def attach_supervised_base_candidate(
    observation: Mapping[str, Any],
    *,
    t_base_camera: np.ndarray | None,
    pose_blockers: Sequence[str],
    bottle_diameter_m: float | None = None,
) -> dict[str, Any]:
    """Attach Base geometry only for a fully valid stationary height-band row."""

    result = dict(observation)
    result.update({
        "camera_origin_base_m": None,
        "base_surface_xyz_m": None,
        "base_center_estimate_xyz_m": None,
        "base_xyz_m": None,
        "base_xyz_semantics": None,
        "supervised_base_candidate_valid": False,
        "base_transform_approved": False,
    })
    if (
        result.get("geometry_valid") is not True
        or pose_blockers
        or t_base_camera is None
        or result.get("camera_xyz_m") is None
    ):
        return result
    transform = np.asarray(t_base_camera, dtype=np.float64)
    point_camera = np.asarray(result["camera_xyz_m"], dtype=np.float64)
    if (
        transform.shape != (4, 4)
        or point_camera.shape != (3,)
        or not np.isfinite(transform).all()
        or not np.isfinite(point_camera).all()
    ):
        return result
    surface_base = (transform @ np.asarray([*point_camera, 1.0]))[:3]
    camera_origin_base = transform[:3, 3]
    diameter = result.get("width_m") if bottle_diameter_m is None else bottle_diameter_m
    if bottle_diameter_m is not None and (
        not np.isfinite(bottle_diameter_m) or not 0 < bottle_diameter_m <= 0.072
    ):
        return result
    center_base = estimate_base_center_from_surface(
        surface_xyz_m=surface_base,
        camera_origin_xyz_m=camera_origin_base,
        width_m=diameter,
    )
    if center_base is None:
        return result
    result.update({
        "camera_origin_base_m": [float(value) for value in camera_origin_base],
        "base_surface_xyz_m": [float(value) for value in surface_base],
        "base_center_estimate_xyz_m": center_base,
        "base_xyz_m": center_base,
        "base_xyz_semantics": "rule_based_bottle_center_estimate",
        "center_diameter_m": diameter,
        "center_diameter_source": (
            "operator_measured_bottle" if bottle_diameter_m is not None
            else "observed_transverse_width"
        ),
        "supervised_base_candidate_valid": True,
    })
    return result


def build_candidate_observations(
    frame: RgbdFrame,
    candidates: Sequence[MaskCandidate],
    config: VisionConfig,
    *,
    now_monotonic_ns: int,
    upright_direction_camera: np.ndarray | None = None,
    t_base_camera: np.ndarray | None = None,
    grasp_height_base_m: float | None = None,
    grasp_height_half_band_m: float = 0.005,
) -> tuple[dict[str, Any], ...]:
    """Return left-ordered, fail-closed camera-frame bottle observations."""

    age_ms = (int(now_monotonic_ns) - frame.monotonic_ns) / 1_000_000
    rows: list[dict[str, Any]] = []
    for candidate in candidates:
        reasons = list(candidate.reasons)
        mask = np.asarray(candidate.mask, dtype=bool)
        if mask.shape != frame.depth_m.shape or not mask.any():
            reasons.append("mask_missing_or_misaligned")
            pixel_uv = None
            mask_pixels = 0
            points = np.empty((0, 3), dtype=np.float64)
            depth_ratio = 0.0
        else:
            ys, xs = np.nonzero(mask)
            pixel_uv = [float(xs.mean()), float(ys.mean())]
            mask_pixels = int(mask.sum())
            points, depth_ratio = robust_mask_points(
                frame.xyz_camera_m,
                erode_mask(mask, radius=config.mask_erosion_px),
                min_depth_m=config.min_depth_m,
                max_depth_m=config.max_depth_m,
                mad_scale=3.5,
            )
        if not candidate.authorized:
            reasons.append("candidate_not_authorized")
        if mask_pixels < config.min_mask_pixels:
            reasons.append("mask_too_small")
        if len(points) < config.min_depth_points:
            reasons.append("depth_points_insufficient")
        if depth_ratio < config.min_depth_ratio:
            reasons.append("depth_ratio_insufficient")
        if age_ms < 0 or age_ms > config.max_frame_age_ms:
            reasons.append("frame_stale")
        camera_reasons = list(dict.fromkeys(reasons))
        camera_observation_valid = not camera_reasons
        camera_xyz = (
            None
            if not len(points)
            else [float(value) for value in np.median(points, axis=0)]
        )
        camera_xyz_semantics = "robust_mask_median_tracking_only"
        pixel_uv_semantics = "mask_centroid_tracking_only"
        geometry_reasons: list[str] = []
        silhouette_points, _silhouette_ratio = robust_mask_points(
            frame.xyz_camera_m,
            mask,
            min_depth_m=config.min_depth_m,
            max_depth_m=config.max_depth_m,
            mad_scale=3.5,
        )
        height_band = None
        if grasp_height_base_m is not None:
            if upright_direction_camera is None or t_base_camera is None:
                geometry_reasons.append("grasp_height_transform_unavailable")
            else:
                height_band = select_base_height_band(
                    points,
                    silhouette_points,
                    t_base_camera=t_base_camera,
                    upright_direction_camera=upright_direction_camera,
                    target_base_z_m=grasp_height_base_m,
                    half_band_m=grasp_height_half_band_m,
                    min_points=max(20, config.min_depth_points // 12),
                )
                if height_band is None:
                    geometry_reasons.append("grasp_height_band_insufficient")
        width_m = (
            height_band["width_m"]
            if height_band is not None
            else (
                None
                if upright_direction_camera is None or grasp_height_base_m is not None
                else robust_transverse_width_m(
                    points,
                    silhouette_points,
                    upright_direction_camera=upright_direction_camera,
                )
            )
        )
        base_surface_xyz = None
        if height_band is not None:
            band_pixel = _nearest_height_band_pixel(
                frame,
                erode_mask(mask, radius=config.mask_erosion_px),
                t_base_camera=np.asarray(t_base_camera, dtype=np.float64),
                target_base_z_m=float(grasp_height_base_m),
                half_band_m=grasp_height_half_band_m,
                body_surface_depth_range_m=height_band["body_surface_depth_range_m"],
                median_base_xyz_m=height_band["median_base_xyz_m"],
            )
            if band_pixel is None:
                geometry_reasons.append("grasp_height_band_pixel_unavailable")
            else:
                pixel_uv, camera_xyz, base_surface_xyz = band_pixel
                camera_xyz_semantics = "height_band_surface_sample"
                pixel_uv_semantics = "height_band_surface_sample"
        if width_m is None:
            if grasp_height_base_m is None:
                geometry_reasons.append("width_orientation_unavailable")
        elif not config.min_grasp_width_m <= width_m <= config.max_grasp_width_m:
            geometry_reasons.append("transverse_width_out_of_range")
        all_reasons = camera_reasons + geometry_reasons
        geometry_valid = camera_observation_valid and not geometry_reasons
        if grasp_height_base_m is None and geometry_valid:
            camera_xyz_semantics = "robust_mask_median_axis_estimate"
            pixel_uv_semantics = "mask_centroid_axis_estimate"
        rows.append({
            "detection_id": int(candidate.detection_id),
            "target_id": f"detection:{candidate.detection_id}",
            "score": float(candidate.score),
            "bbox": [float(value) for value in candidate.bbox_xyxy],
            "pixel_uv": pixel_uv,
            "pixel_uv_semantics": pixel_uv_semantics,
            "camera_xyz_m": camera_xyz,
            "camera_xyz_semantics": camera_xyz_semantics,
            "width_m": width_m,
            "width_method": "near_surface_transverse_q01_q99",
            "width_is_gripper_command": False,
            "grasp_height_base_m": grasp_height_base_m,
            "grasp_height_half_band_m": (
                grasp_height_half_band_m if grasp_height_base_m is not None else None
            ),
            "height_band_body_points": (
                None if height_band is None else height_band["body_points"]
            ),
            "height_band_silhouette_points": (
                None if height_band is None else height_band["silhouette_points"]
            ),
            "height_band_median_base_xyz_m": (
                None if height_band is None else height_band["median_base_xyz_m"]
            ),
            "base_surface_xyz_m": base_surface_xyz,
            "mask_pixels": mask_pixels,
            "depth_points": int(len(points)),
            "depth_valid_ratio": float(depth_ratio),
            "frame_age_ms": float(age_ms),
            "camera_observation_valid": camera_observation_valid,
            "camera_reasons": camera_reasons,
            "geometry_valid": geometry_valid,
            "geometry_reasons": geometry_reasons,
            "valid": geometry_valid,
            "reason": None if not all_reasons else all_reasons[0],
            "reasons": all_reasons,
        })

    rows.sort(key=lambda row: float("inf") if row["pixel_uv"] is None else row["pixel_uv"][0])
    for ordinal, row in enumerate(rows, start=1):
        row["left_ordinal"] = ordinal
        row["right_ordinal"] = len(rows) - ordinal + 1
    return tuple(rows)


def find_locked_observation(
    observations: Sequence[dict[str, Any]], *, detection_id: int
) -> dict[str, Any] | None:
    """Find only the previously locked backend ID; never select a replacement."""

    return next(
        (row for row in observations if row.get("detection_id") == detection_id),
        None,
    )


def require_flange_pose(
    pose: Mapping[str, Any],
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    """Require explicit flange semantics before applying T_flange_camera."""

    if "flange_position_m" not in pose or "flange_euler_rad" not in pose:
        if "tcp_position_m" in pose or "tcp_euler_rad" in pose:
            raise ValueError("flange_pose_required_tcp_pose_rejected")
        raise ValueError("flange_pose_required")
    position = tuple(float(value) for value in pose["flange_position_m"])
    euler = tuple(float(value) for value in pose["flange_euler_rad"])
    if (
        len(position) != 3
        or len(euler) != 3
        or not np.isfinite(position).all()
        or not np.isfinite(euler).all()
    ):
        raise ValueError("flange_pose_invalid")
    return position, euler


def capture_wall_time_ms(
    *,
    captured_monotonic_ns: int,
    now_monotonic_ns: int,
    now_wall_ms: int,
) -> int:
    """Estimate capture wall time without relabelling an old frame as current."""

    age_ms = (int(now_monotonic_ns) - int(captured_monotonic_ns)) / 1_000_000
    return int(round(int(now_wall_ms) - age_ms))


def finalize_observation_freshness(
    observation: Mapping[str, Any],
    *,
    captured_monotonic_ns: int,
    now_monotonic_ns: int,
    max_frame_age_ms: int,
) -> dict[str, Any]:
    """Recheck age after every output-side operation has completed."""

    result = dict(observation)
    age_ms = (int(now_monotonic_ns) - int(captured_monotonic_ns)) / 1_000_000
    result["final_frame_age_ms"] = float(age_ms)
    if age_ms < 0 or age_ms > max_frame_age_ms:
        reasons = list(result.get("reasons", []))
        if "frame_stale_after_postprocessing" not in reasons:
            reasons.append("frame_stale_after_postprocessing")
        result["reasons"] = reasons
        result["reason"] = "frame_stale_after_postprocessing"
        result["valid"] = False
        result["camera_observation_valid"] = False
        result["geometry_valid"] = False
    return result


__all__ = [
    "apply_rotated_mask_aspect_gate",
    "attach_supervised_base_candidate",
    "build_candidate_observations",
    "capture_wall_time_ms",
    "finalize_observation_freshness",
    "estimate_base_center_from_surface",
    "find_locked_observation",
    "require_flange_pose",
    "robust_transverse_width_m",
    "select_base_height_band",
]
