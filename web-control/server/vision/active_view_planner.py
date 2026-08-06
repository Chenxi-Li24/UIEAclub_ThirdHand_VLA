"""Deterministic, hardware-independent active-view decisions."""

from __future__ import annotations

from typing import Any, Protocol

import numpy as np

from .active_view_geometry import contains_estimate
from .active_view_types import (
    CoarseTargetEstimate,
    ObservationMoveProposal,
    ObservationPose,
    TablePlane,
    validated_evidence_ids,
)
from .types import InvalidDataError


class ActiveViewPlanningConfig(Protocol):
    """Narrow structural interface consumed by the pure observation selector."""

    table_plane: TablePlane
    coverage_margin_m: float
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
    estimate: CoarseTargetEstimate,
    reason: str,
    evidence_ids: tuple[str, ...] = (),
) -> ObservationMoveProposal:
    return ObservationMoveProposal.rejected(
        identity_id=estimate.identity_id,
        source_stamp=estimate.source_stamp,
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
        return _rejected(estimate, "table_unvalidated")
    if table.calibration_id != estimate.calibration_id:
        return _rejected(estimate, "table_calibration_mismatch")
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
        return _rejected(estimate, "observation_catalog_empty")
    current = _current_joints(current_joints_deg)
    current_pose_id = match_observation_pose(current, catalog)
    if current_pose_id is None:
        return _rejected(estimate, "current_pose_unvalidated")
    current_pose = next(pose for pose in catalog if pose.pose_id == current_pose_id)
    if current_pose.calibration_id != required_calibration_id:
        return _rejected(estimate, "current_pose_calibration_mismatch")
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
        return _rejected(estimate, "observation_already_sufficient", evidence)

    alternatives = tuple(pose for pose in catalog if pose.pose_id != current_pose_id)
    if not alternatives:
        return _rejected(estimate, "target_not_covered")
    calibrated = tuple(
        pose for pose in alternatives if pose.calibration_id == required_calibration_id
    )
    if not calibrated:
        return _rejected(estimate, "observation_calibration_mismatch")
    reachable = tuple(
        pose for pose in calibrated if current_pose_id in pose.allowed_start_pose_ids
    )
    if not reachable:
        return _rejected(estimate, "start_pose_not_allowed")
    covering = tuple(
        pose
        for pose in reachable
        if contains_estimate(pose.coverage_polygon_xy_m, estimate, margin)
    )
    if not covering:
        return _rejected(estimate, "target_not_covered")

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


__all__ = ["ActiveViewPlanningConfig", "match_observation_pose", "select_observation_pose"]
