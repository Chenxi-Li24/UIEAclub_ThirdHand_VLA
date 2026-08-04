"""Generate auditable grasp geometry without any execution transport."""

from __future__ import annotations

from typing import Any

import numpy as np

from .safety import SafetyConfig, _validated_cloud, evaluate_target_safety
from .types import CalibrationRef, DryRunReport, GraspCandidate, InvalidDataError, TrackState


def generate_top_down_candidates(
    target_cloud_m: Any,
    table_plane_z_m: float,
    config: SafetyConfig,
) -> tuple[GraspCandidate, ...]:
    cloud = _validated_cloud(target_cloud_m)
    table_z = float(table_plane_z_m)
    if not np.isfinite(table_z):
        raise InvalidDataError("table_plane_z_m must be finite")
    cloud = cloud[np.isfinite(cloud).all(axis=1)]
    if len(cloud) < config.min_cloud_points:
        return ()

    lower = np.quantile(cloud, 0.05, axis=0)
    upper = np.quantile(cloud, 0.95, axis=0)
    center = np.median(cloud, axis=0)
    planar_extents = upper[:2] - lower[:2]
    required_width = float(np.min(planar_extents) + config.grasp_width_margin_m)
    if not config.min_gripper_width_m <= required_width <= config.max_gripper_width_m:
        return ()

    grasp_z = max(float(center[2]), table_z + config.table_clearance_m)
    grasp = np.array([center[0], center[1], grasp_z])
    pregrasp = grasp + np.array([0.0, 0.0, config.pregrasp_clearance_m])
    retreat = grasp + np.array([0.0, 0.0, config.retreat_clearance_m])
    all_points = np.vstack((grasp, pregrasp, retreat))
    if not (
        np.all(config.workspace_min_m <= all_points)
        and np.all(all_points <= config.workspace_max_m)
    ):
        return ()

    clearance = grasp_z - table_z
    travel = float(np.linalg.norm(pregrasp - config.nominal_pose_m))
    score = config.clearance_weight * clearance - config.travel_weight * travel
    return (
        GraspCandidate(
            pregrasp_xyz_m=pregrasp,
            grasp_xyz_m=grasp,
            retreat_xyz_m=retreat,
            width_m=required_width,
            score=score,
        ),
    )


def build_dry_run_report(
    target: TrackState,
    target_cloud_m: Any,
    calibration: CalibrationRef,
    now_ns: int,
    config: SafetyConfig,
    table_plane_z_m: float,
    reachable: bool,
    collision_free: bool,
) -> DryRunReport:
    if not isinstance(collision_free, (bool, np.bool_)):
        raise InvalidDataError("collision_free must be an explicit boolean result")
    decision = evaluate_target_safety(
        target,
        target_cloud_m,
        calibration,
        now_ns,
        config,
        reachable,
    )
    reasons = list(decision.reasons)
    candidates: tuple[GraspCandidate, ...] = ()
    if not collision_free:
        reasons.append("no_collision_free_candidate")
    elif not reasons:
        candidates = generate_top_down_candidates(target_cloud_m, table_plane_z_m, config)
        if not candidates:
            reasons.append("no_collision_free_candidate")

    if reasons:
        return DryRunReport(
            approved=False,
            reasons=tuple(dict.fromkeys(reasons)),
            candidate_xyz_m=None,
            score=None,
            target_track_id=target.track_id,
            calibration_id=target.pose.calibration_id,
        )
    best = max(candidates, key=lambda item: (item.score, -item.width_m))
    return DryRunReport(
        approved=True,
        reasons=(),
        candidate_xyz_m=best.grasp_xyz_m,
        score=best.score,
        target_track_id=target.track_id,
        calibration_id=target.pose.calibration_id,
    )

