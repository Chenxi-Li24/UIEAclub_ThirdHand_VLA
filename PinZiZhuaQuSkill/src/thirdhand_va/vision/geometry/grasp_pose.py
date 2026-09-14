"""Compatibility wrapper for the highest-quality upright bottle grasp."""

from __future__ import annotations

from thirdhand_va.common.config import VisionConfig
from thirdhand_va.common.contracts import GraspPoseCamera, MaskCandidate, RgbdFrame

from .grasp_candidates import GeometryRejected, estimate_grasp_candidates
from .pointcloud import erode_mask, robust_mask_points


def has_grasp_depth_support(
    frame: RgbdFrame,
    candidate: MaskCandidate,
    config: VisionConfig,
) -> bool:
    if not candidate.authorized or candidate.mask.shape != frame.depth_m.shape:
        return False
    points, valid_ratio = robust_mask_points(
        frame.xyz_camera_m,
        erode_mask(candidate.mask, radius=config.mask_erosion_px),
        min_depth_m=config.min_depth_m,
        max_depth_m=config.max_depth_m,
        mad_scale=3.5,
    )
    return bool(
        len(points) >= config.min_depth_points
        and valid_ratio >= config.min_depth_ratio
    )


def estimate_grasp_pose(
    frame: RgbdFrame,
    candidate: MaskCandidate,
    config: VisionConfig,
) -> GraspPoseCamera:
    return estimate_grasp_candidates(frame, candidate, config)[0].pose


__all__ = ["GeometryRejected", "estimate_grasp_pose", "has_grasp_depth_support"]
