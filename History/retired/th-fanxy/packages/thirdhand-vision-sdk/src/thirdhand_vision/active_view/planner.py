"""Pure advisory viewpoint selection and depth-quality evaluation."""

from __future__ import annotations

from typing import Any, Iterable

import numpy as np

from thirdhand_vision.core.camera import PinholeCamera
from thirdhand_vision.core.errors import InputValidationError
from thirdhand_vision.core.transforms import transform_points
from thirdhand_vision.core.types import FrameStamp
from thirdhand_vision.geometry.depth import RegisteredDepth

from .types import (
    ActiveViewConfig,
    CoarseTargetEstimate,
    DepthQuality,
    ObservationPose,
    ObservationProposal,
)


def evaluate_depth_quality(
    *,
    registered: RegisteredDepth,
    mask: Any,
    d435: PinholeCamera,
    t_d435_from_lumos: Any,
    t_output_from_lumos: Any,
    config: ActiveViewConfig,
) -> DepthQuality:
    mask_array = np.asarray(mask)
    if mask_array.dtype != np.bool_ or mask_array.shape != registered.valid.shape:
        raise InputValidationError("active-view mask must match registered depth")
    points_lumos = registered.points_lumos_m[registered.valid & mask_array]
    if len(points_lumos):
        points_d435 = transform_points(t_d435_from_lumos, points_lumos)
        pixels, projected = d435.project(points_d435)
        points_d435 = points_d435[projected]
        points_output = transform_points(t_output_from_lumos, points_lumos[projected])
        pixels = pixels[projected]
    else:
        points_d435 = np.empty((0, 3))
        points_output = np.empty((0, 3))
        pixels = np.empty((0, 2))
    valid_points = len(points_d435)
    if valid_points:
        margin_x = d435.width * (1.0 - config.inner_roi_fraction) * 0.5
        margin_y = d435.height * (1.0 - config.inner_roi_fraction) * 0.5
        central = (
            (pixels[:, 0] >= margin_x)
            & (pixels[:, 0] < d435.width - margin_x)
            & (pixels[:, 1] >= margin_y)
            & (pixels[:, 1] < d435.height - margin_y)
        )
        central_fraction = float(np.count_nonzero(central) / valid_points)
        center_d435 = np.median(points_d435, axis=0)
        center_output = np.median(points_output, axis=0)
        mad_output = np.median(np.abs(points_output - center_output), axis=0)
    else:
        central_fraction = 0.0
        center_d435 = np.zeros(3)
        center_output = np.zeros(3)
        mad_output = np.zeros(3)
    reasons = []
    if valid_points < config.min_depth_points:
        reasons.append("insufficient_depth_points")
    if central_fraction < config.min_central_fraction:
        reasons.append("insufficient_central_coverage")
    if np.any(mad_output > config.max_axis_mad_m):
        reasons.append("depth_not_stable")
    return DepthQuality(
        valid_points=valid_points,
        central_fraction=central_fraction,
        center_d435_m=center_d435,
        center_output_m=center_output,
        mad_output_m=mad_output,
        acceptable=not reasons,
        reasons=tuple(reasons),
    )


def select_observation_pose(
    target: CoarseTargetEstimate,
    *,
    current_joints_deg: Any,
    poses: Iterable[ObservationPose],
    now_ns: int,
    config: ActiveViewConfig,
) -> ObservationProposal:
    if not isinstance(target, CoarseTargetEstimate):
        raise InputValidationError("coarse target estimate is required")
    joints = np.asarray(current_joints_deg, dtype=float)
    if joints.shape != (6,) or not np.isfinite(joints).all():
        raise InputValidationError("current joints must be a finite six-vector")
    if isinstance(now_ns, bool) or not isinstance(now_ns, int) or now_ns < target.stamp.monotonic_ns:
        raise InputValidationError("proposal time cannot precede its source frame")
    candidates = [pose for pose in poses if pose.covers(target.center_xy_m)]
    if not candidates:
        return ObservationProposal(
            proposal_id=f"none:{target.stamp.frame_id}:{now_ns}",
            kind="none",
            identity_id=None,
            target_pose_id=None,
            joints_deg=None,
            delta_output_m=np.zeros(3),
            source_frame_id=target.stamp.frame_id,
            expires_ns=now_ns + config.proposal_ttl_ns,
            reasons=("no_valid_observation_pose",),
        )
    selected = min(
        candidates,
        key=lambda pose: (float(np.linalg.norm(pose.joints_deg - joints)), pose.pose_id),
    )
    return ObservationProposal(
        proposal_id=f"catalog:{selected.pose_id}:{target.stamp.frame_id}:{now_ns}",
        kind="catalog",
        identity_id=None,
        target_pose_id=selected.pose_id,
        joints_deg=selected.joints_deg,
        delta_output_m=np.zeros(3),
        source_frame_id=target.stamp.frame_id,
        expires_ns=now_ns + config.proposal_ttl_ns,
    )


def propose_refinement(
    *,
    identity_id: int,
    offset_xy_m: Any,
    source_stamp: FrameStamp,
    now_ns: int,
    config: ActiveViewConfig,
) -> ObservationProposal:
    offset = np.asarray(offset_xy_m, dtype=float)
    if offset.shape != (2,) or not np.isfinite(offset).all():
        raise InputValidationError("refinement offset must be a finite two-vector")
    if isinstance(identity_id, bool) or not isinstance(identity_id, int) or identity_id < 0:
        raise InputValidationError("refinement identity ID is invalid")
    if not isinstance(source_stamp, FrameStamp):
        raise InputValidationError("refinement source stamp is invalid")
    if isinstance(now_ns, bool) or not isinstance(now_ns, int) or now_ns < source_stamp.monotonic_ns:
        raise InputValidationError("refinement time cannot precede source frame")
    norm = float(np.linalg.norm(offset))
    bounded = np.array(offset, copy=True)
    if norm > config.max_translation_m:
        bounded *= config.max_translation_m / norm
    return ObservationProposal(
        proposal_id=f"refinement:{identity_id}:{source_stamp.frame_id}:{now_ns}",
        kind="refinement",
        identity_id=identity_id,
        target_pose_id=None,
        joints_deg=None,
        delta_output_m=np.array([bounded[0], bounded[1], 0.0]),
        source_frame_id=source_stamp.frame_id,
        expires_ns=now_ns + config.proposal_ttl_ns,
    )
