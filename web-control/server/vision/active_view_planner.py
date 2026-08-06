"""Deterministic, hardware-independent active-view decisions."""

from __future__ import annotations

from typing import Any, Protocol

import numpy as np

from .active_view_geometry import contains_estimate
from .active_view_types import (
    CoarseTargetEstimate,
    DepthQuality,
    ObservationMoveProposal,
    ObservationPose,
    TablePlane,
    validated_evidence_ids,
)
from .camera_models import PinholeCamera
from .depth_registration import RegisteredDepth
from .geometry import transform_points, validate_transform
from .types import FrameStamp, InvalidDataError


class ActiveViewPlanningConfig(Protocol):
    """Narrow structural interface consumed by the pure observation selector."""

    table_plane: TablePlane
    coverage_margin_m: float
    inner_roi_fraction: float
    min_depth_points: int
    min_central_fraction: float
    max_translation_m: float
    max_refinement_steps: int
    proposal_ttl_ns: int


def _current_joints(value: Any) -> np.ndarray:
    joints = np.asarray(value, dtype=float)
    if joints.shape != (6,) or not np.isfinite(joints).all():
        raise InvalidDataError("current joints must be a finite six-vector")
    return joints


def _catalog(poses: Any) -> tuple[ObservationPose, ...]:
    try:
        result = tuple(poses)
    except TypeError as exc:
        raise InvalidDataError("observation catalog must be a sequence") from exc
    if any(not isinstance(pose, ObservationPose) for pose in result):
        raise InvalidDataError("observation catalog contains an invalid pose")
    pose_ids = tuple(pose.pose_id for pose in result)
    if len(set(pose_ids)) != len(pose_ids):
        raise InvalidDataError("observation catalog contains duplicate pose IDs")
    return result


def match_observation_pose(current_joints_deg: Any, poses: Any) -> str | None:
    """Match current joints to a taught pose using its own validated tolerance."""

    current = _current_joints(current_joints_deg)
    catalog = _catalog(poses)
    matches: list[tuple[float, float, str]] = []
    for pose in catalog:
        delta = np.abs(pose.joints_deg - current)
        if np.all(delta <= pose.joint_tolerance_deg):
            matches.append((float(np.max(delta)), float(np.linalg.norm(delta)), pose.pose_id))
    if not matches:
        return None
    return min(matches)[2]


def _rejected(
    identity_id: int,
    source_stamp: FrameStamp,
    reason: str,
    evidence_ids: tuple[str, ...] = (),
) -> ObservationMoveProposal:
    return ObservationMoveProposal.rejected(
        identity_id=identity_id,
        source_stamp=source_stamp,
        reasons=(reason,),
        evidence_ids=evidence_ids,
    )


def select_observation_pose(
    *,
    estimate: CoarseTargetEstimate,
    poses: Any,
    current_joints_deg: Any,
    required_calibration_id: str,
    now_ns: int,
    config: ActiveViewPlanningConfig,
) -> ObservationMoveProposal:
    """Select a pre-taught observation pose without synthesizing robot motion."""

    if not isinstance(estimate, CoarseTargetEstimate):
        raise InvalidDataError("observation selection requires a coarse target estimate")
    required_calibration_id = validated_evidence_ids((required_calibration_id,))[0]
    if isinstance(now_ns, bool) or not isinstance(now_ns, int):
        raise InvalidDataError("observation selection time must be an integer")
    if now_ns < estimate.source_stamp.monotonic_ns:
        raise InvalidDataError("observation selection time cannot precede its source frame")
    table = getattr(config, "table_plane", None)
    if not isinstance(table, TablePlane):
        raise InvalidDataError("observation selection requires a table-plane config")
    if not table.validated:
        return _rejected(estimate.identity_id, estimate.source_stamp, "table_unvalidated")
    if table.calibration_id != estimate.calibration_id:
        return _rejected(
            estimate.identity_id,
            estimate.source_stamp,
            "table_calibration_mismatch",
        )
    try:
        margin = float(config.coverage_margin_m)
        ttl_ns = config.proposal_ttl_ns
    except (AttributeError, TypeError, ValueError) as exc:
        raise InvalidDataError("observation planning config is incomplete") from exc
    if not np.isfinite(margin) or margin < 0.0:
        raise InvalidDataError("observation coverage margin must be finite and non-negative")
    if (
        isinstance(ttl_ns, bool)
        or not isinstance(ttl_ns, int)
        or ttl_ns <= 0
        or ttl_ns > 1_000_000_000
    ):
        raise InvalidDataError("observation proposal TTL must be within one second")

    catalog = _catalog(poses)
    if not catalog:
        return _rejected(
            estimate.identity_id,
            estimate.source_stamp,
            "observation_catalog_empty",
        )
    current = _current_joints(current_joints_deg)
    current_pose_id = match_observation_pose(current, catalog)
    if current_pose_id is None:
        return _rejected(
            estimate.identity_id,
            estimate.source_stamp,
            "current_pose_unvalidated",
        )
    current_pose = next(pose for pose in catalog if pose.pose_id == current_pose_id)
    if current_pose.calibration_id != required_calibration_id:
        return _rejected(
            estimate.identity_id,
            estimate.source_stamp,
            "current_pose_calibration_mismatch",
        )
    if contains_estimate(current_pose.coverage_polygon_xy_m, estimate, margin):
        evidence = tuple(
            dict.fromkeys(
                (
                    estimate.calibration_id,
                    required_calibration_id,
                    current_pose.path_validation_id,
                )
            )
        )
        return _rejected(
            estimate.identity_id,
            estimate.source_stamp,
            "observation_already_sufficient",
            evidence,
        )

    alternatives = tuple(pose for pose in catalog if pose.pose_id != current_pose_id)
    if not alternatives:
        return _rejected(estimate.identity_id, estimate.source_stamp, "target_not_covered")
    calibrated = tuple(
        pose for pose in alternatives if pose.calibration_id == required_calibration_id
    )
    if not calibrated:
        return _rejected(
            estimate.identity_id,
            estimate.source_stamp,
            "observation_calibration_mismatch",
        )
    reachable = tuple(
        pose for pose in calibrated if current_pose_id in pose.allowed_start_pose_ids
    )
    if not reachable:
        return _rejected(
            estimate.identity_id,
            estimate.source_stamp,
            "start_pose_not_allowed",
        )
    covering = tuple(
        pose
        for pose in reachable
        if contains_estimate(pose.coverage_polygon_xy_m, estimate, margin)
    )
    if not covering:
        return _rejected(estimate.identity_id, estimate.source_stamp, "target_not_covered")

    selected = min(
        covering,
        key=lambda pose: (
            float(np.max(np.abs(pose.joints_deg - current))),
            float(np.linalg.norm(pose.joints_deg - current)),
            pose.pose_id,
        ),
    )
    evidence_ids = tuple(
        dict.fromkeys(
            (
                estimate.calibration_id,
                required_calibration_id,
                selected.path_validation_id,
            )
        )
    )
    return ObservationMoveProposal.coarse(
        identity_id=estimate.identity_id,
        source_stamp=estimate.source_stamp,
        expires_ns=now_ns + ttl_ns,
        target_pose_id=selected.pose_id,
        joints_deg=selected.joints_deg,
        evidence_ids=evidence_ids,
    )


def evaluate_depth_quality(
    registered: RegisteredDepth,
    target_mask: Any,
    d435: PinholeCamera,
    t_d435_from_lumos: Any,
    t_base_from_lumos: Any,
    config: ActiveViewPlanningConfig,
) -> DepthQuality:
    """Measure target depth count and central D435 coverage without planning motion."""

    if not isinstance(registered, RegisteredDepth):
        raise InvalidDataError("depth quality requires registered D435 depth")
    mask = np.asarray(target_mask)
    if mask.dtype != np.bool_ or mask.shape != registered.valid.shape:
        raise InvalidDataError("target mask must be boolean and match registered depth")
    if not isinstance(d435, PinholeCamera):
        raise InvalidDataError("depth quality requires a D435 pinhole camera")
    t_d435 = validate_transform(t_d435_from_lumos)
    t_base = validate_transform(t_base_from_lumos)
    try:
        roi_fraction = float(config.inner_roi_fraction)
        min_points = config.min_depth_points
        min_central_fraction = float(config.min_central_fraction)
    except (AttributeError, TypeError, ValueError) as exc:
        raise InvalidDataError("depth quality config is incomplete") from exc
    if not np.isfinite(roi_fraction) or not 0.0 < roi_fraction <= 1.0:
        raise InvalidDataError("inner ROI fraction must be within (0, 1]")
    if isinstance(min_points, bool) or not isinstance(min_points, int) or min_points <= 0:
        raise InvalidDataError("minimum depth points must be a positive integer")
    if not np.isfinite(min_central_fraction) or not 0.0 < min_central_fraction <= 1.0:
        raise InvalidDataError("minimum central fraction must be within (0, 1]")

    selected_lumos = registered.points_lumos_m[registered.valid & mask]
    if len(selected_lumos):
        selected_d435 = transform_points(t_d435, selected_lumos)
        uv_d435, projected = d435.project(selected_d435)
    else:
        selected_d435 = np.empty((0, 3), dtype=float)
        uv_d435 = np.empty((0, 2), dtype=float)
        projected = np.zeros(0, dtype=bool)

    valid_points = int(np.count_nonzero(projected))
    if valid_points:
        points_d435 = selected_d435[projected]
        points_base = transform_points(t_base, selected_lumos[projected])
        pixels = uv_d435[projected]
        horizontal_margin = d435.width * (1.0 - roi_fraction) * 0.5
        vertical_margin = d435.height * (1.0 - roi_fraction) * 0.5
        central = (
            (pixels[:, 0] >= horizontal_margin)
            & (pixels[:, 0] < d435.width - horizontal_margin)
            & (pixels[:, 1] >= vertical_margin)
            & (pixels[:, 1] < d435.height - vertical_margin)
        )
        central_fraction = float(np.count_nonzero(central) / valid_points)
        center_d435_m = np.median(points_d435, axis=0)
        center_base_m = np.median(points_base, axis=0)
        mad_m = np.median(np.abs(points_base - center_base_m), axis=0)
    else:
        central_fraction = 0.0
        center_d435_m = center_base_m = mad_m = None

    reasons: list[str] = []
    if valid_points == 0:
        reasons.append("no_projectable_depth_points")
    if valid_points < min_points:
        reasons.append("insufficient_depth_points")
    if central_fraction < min_central_fraction:
        reasons.append("insufficient_central_coverage")
    return DepthQuality(
        valid_points=valid_points,
        central_fraction=central_fraction,
        center_d435_m=center_d435_m,
        center_base_m=center_base_m,
        mad_m=mad_m,
        acceptable=not reasons,
        reasons=tuple(reasons),
    )


def propose_refinement(
    identity_id: int,
    quality: DepthQuality,
    t_base_from_d435: Any,
    source_stamp: FrameStamp,
    now_ns: int,
    step_index: int,
    config: ActiveViewPlanningConfig,
    evidence_ids: tuple[str, ...],
) -> ObservationMoveProposal:
    """Produce one bounded lateral correction proposal; never execute it."""

    if not isinstance(quality, DepthQuality):
        raise InvalidDataError("view refinement requires depth quality")
    transform = validate_transform(t_base_from_d435)
    if not isinstance(source_stamp, FrameStamp):
        raise InvalidDataError("view refinement requires frame provenance")
    if (
        isinstance(now_ns, bool)
        or not isinstance(now_ns, int)
        or now_ns < source_stamp.monotonic_ns
    ):
        raise InvalidDataError("view refinement time is invalid")
    if isinstance(step_index, bool) or not isinstance(step_index, int) or step_index < 0:
        raise InvalidDataError("view refinement step index must be non-negative")
    try:
        min_points = config.min_depth_points
        max_steps = config.max_refinement_steps
        max_translation_m = float(config.max_translation_m)
        ttl_ns = config.proposal_ttl_ns
    except (AttributeError, TypeError, ValueError) as exc:
        raise InvalidDataError("view refinement config is incomplete") from exc
    integer_limits = (min_points, max_steps, ttl_ns)
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value <= 0
        for value in integer_limits
    ):
        raise InvalidDataError("view refinement integer limits must be positive")
    if max_steps > 3:
        raise InvalidDataError("view refinement cannot exceed three steps")
    if ttl_ns > 1_000_000_000:
        raise InvalidDataError("view refinement TTL cannot exceed one second")
    if not np.isfinite(max_translation_m) or not 0.0 < max_translation_m <= 0.020:
        raise InvalidDataError("view refinement translation limit must be within 20 mm")

    evidence = validated_evidence_ids(evidence_ids)
    if quality.acceptable:
        return _rejected(identity_id, source_stamp, "depth_quality_sufficient", evidence)
    if step_index >= max_steps:
        return _rejected(identity_id, source_stamp, "view_refinement_exhausted", evidence)
    if quality.center_d435_m is None or quality.valid_points < min_points:
        return _rejected(identity_id, source_stamp, "depth_geometry_unavailable", evidence)

    lateral_d435 = np.array(
        [quality.center_d435_m[0], quality.center_d435_m[1], 0.0],
        dtype=float,
    )
    raw_delta_base = transform[:3, :3] @ lateral_d435
    norm = float(np.linalg.norm(raw_delta_base))
    if norm <= 1e-12:
        return _rejected(identity_id, source_stamp, "lateral_alignment_sufficient", evidence)
    delta_base = raw_delta_base * min(1.0, max_translation_m / norm)
    return ObservationMoveProposal.refine(
        identity_id=identity_id,
        source_stamp=source_stamp,
        expires_ns=now_ns + ttl_ns,
        delta_base_m=delta_base,
        rotation_delta_rad=np.zeros(3),
        evidence_ids=evidence,
    )


__all__ = [
    "ActiveViewPlanningConfig",
    "evaluate_depth_quality",
    "match_observation_pose",
    "propose_refinement",
    "select_observation_pose",
]
