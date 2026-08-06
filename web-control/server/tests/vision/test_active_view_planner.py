from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from vision.active_view_planner import (
    evaluate_depth_quality,
    match_observation_pose,
    propose_refinement,
    select_observation_pose,
)
from vision.active_view_types import CoarseTargetEstimate, ObservationPose, TablePlane
from vision.camera_models import PinholeCamera
from vision.depth_registration import RegisteredDepth
from vision.types import FrameStamp, InvalidDataError
from vision_models.active_view_online import load_active_view_config_dict


CALIBRATION_ID = "sha256:" + "d" * 64
PATH_ID = "sha256:" + "e" * 64


def estimate() -> CoarseTargetEstimate:
    return CoarseTargetEstimate(
        identity_id=9,
        center_xy_m=np.array([0.0, 0.0]),
        covariance_xy_m2=np.eye(2) * 0.0001,
        samples_xy_m=np.array([[-0.01, 0.0], [0.0, -0.01], [0.01, 0.01]]),
        source_stamp=FrameStamp("lumos_rgb", 5, 1_000),
        calibration_id=CALIBRATION_ID,
    )


def pose(
    pose_id: str,
    joints: list[float],
    polygon: list[list[float]],
    *,
    allowed: tuple[str, ...] = ("home",),
    calibration_id: str = CALIBRATION_ID,
) -> ObservationPose:
    return ObservationPose(
        pose_id=pose_id,
        joints_deg=np.array(joints, dtype=float),
        t_base_from_flange=np.eye(4),
        coverage_polygon_xy_m=np.array(polygon, dtype=float),
        allowed_start_pose_ids=allowed,
        path_validation_id=PATH_ID,
        calibration_id=calibration_id,
        joint_tolerance_deg=0.25,
    )


def home_pose(*, covers_target: bool = False) -> ObservationPose:
    polygon = (
        [[-0.1, -0.1], [0.1, -0.1], [0.1, 0.1], [-0.1, 0.1]]
        if covers_target
        else [[1.0, 1.0], [1.2, 1.0], [1.2, 1.2], [1.0, 1.2]]
    )
    return pose("home", [0, 0, 0, 0, 0, 0], polygon, allowed=("home",))


def covering_pose(
    pose_id: str,
    joint_value: float,
    *,
    allowed: tuple[str, ...] = ("home",),
    calibration_id: str = CALIBRATION_ID,
) -> ObservationPose:
    return pose(
        pose_id,
        [joint_value] * 6,
        [[-0.1, -0.1], [0.1, -0.1], [0.1, 0.1], [-0.1, 0.1]],
        allowed=allowed,
        calibration_id=calibration_id,
    )


def config():
    raw = {
        "schema_version": 1,
        "dry_run_enabled": True,
        "active_view_execution_enabled": False,
        "table_plane": {
            "normal_base": [0.0, 0.0, 1.0],
            "offset_m": 0.0,
            "position_rmse_m": 0.004,
            "calibration_id": CALIBRATION_ID,
            "validated": True,
        },
        "quality": {
            "inner_roi_fraction": 0.60,
            "coverage_margin_m": 0.005,
            "min_depth_points": 80,
            "min_central_fraction": 0.60,
            "stable_sample_count": 5,
            "max_center_deviation_m": 0.010,
            "max_axis_mad_m": 0.005,
        },
        "motion_proposals": {
            "max_translation_m": 0.020,
            "max_rotation_deg": 5.0,
            "max_refinement_steps": 3,
            "proposal_ttl_ms": 200,
        },
        "observation_poses": [],
    }
    return load_active_view_config_dict(raw)


def test_selector_prefers_covering_pose_with_lower_joint_travel() -> None:
    proposal = select_observation_pose(
        estimate=estimate(),
        poses=(home_pose(), covering_pose("far", 10.0), covering_pose("near", 2.0)),
        current_joints_deg=np.zeros(6),
        required_calibration_id=CALIBRATION_ID,
        now_ns=1_000,
        config=config(),
    )

    assert proposal.kind == "coarse_pose"
    assert proposal.target_pose_id == "near"
    assert proposal.expires_ns == 200_001_000
    assert proposal.reasons == ()
    assert proposal.joints_deg is not None
    assert proposal.joints_deg.tolist() == [2.0] * 6
    assert PATH_ID in proposal.evidence_ids


def test_match_observation_pose_uses_per_pose_joint_tolerance() -> None:
    home = home_pose()

    assert match_observation_pose(np.full(6, 0.20), (home,)) == "home"
    assert match_observation_pose(np.full(6, 0.26), (home,)) is None
    with pytest.raises(InvalidDataError, match="current joints"):
        match_observation_pose(np.array([0.0, np.nan, 0.0, 0.0, 0.0, 0.0]), (home,))


@pytest.mark.parametrize(
    ("poses", "current", "reason"),
    [
        ((), np.zeros(6), "observation_catalog_empty"),
        ((home_pose(),), np.ones(6) * 20.0, "current_pose_unvalidated"),
        (
            (
                home_pose(),
                pose(
                    "uncovered",
                    [2, 2, 2, 2, 2, 2],
                    [[1.0, 1.0], [1.2, 1.0], [1.2, 1.2], [1.0, 1.2]],
                ),
            ),
            np.zeros(6),
            "target_not_covered",
        ),
        (
            (home_pose(), covering_pose("blocked", 2.0, allowed=("other",))),
            np.zeros(6),
            "start_pose_not_allowed",
        ),
        (
            (
                home_pose(),
                covering_pose("old_calibration", 2.0, calibration_id="sha256:" + "f" * 64),
            ),
            np.zeros(6),
            "observation_calibration_mismatch",
        ),
    ],
)
def test_selector_returns_ordered_fail_closed_reason(
    poses: tuple[ObservationPose, ...],
    current: np.ndarray,
    reason: str,
) -> None:
    proposal = select_observation_pose(
        estimate=estimate(),
        poses=poses,
        current_joints_deg=current,
        required_calibration_id=CALIBRATION_ID,
        now_ns=1_000,
        config=config(),
    )

    assert proposal.kind == "none"
    assert proposal.reasons == (reason,)


def test_selector_skips_motion_when_current_pose_already_covers_target() -> None:
    proposal = select_observation_pose(
        estimate=estimate(),
        poses=(home_pose(covers_target=True), covering_pose("other", 2.0)),
        current_joints_deg=np.zeros(6),
        required_calibration_id=CALIBRATION_ID,
        now_ns=1_000,
        config=config(),
    )

    assert proposal.kind == "none"
    assert proposal.reasons == ("observation_already_sufficient",)


def test_selector_breaks_equal_travel_ties_by_pose_id() -> None:
    proposal = select_observation_pose(
        estimate=estimate(),
        poses=(
            home_pose(),
            covering_pose("z_pose", 2.0),
            covering_pose("a_pose", -2.0),
        ),
        current_joints_deg=np.zeros(6),
        required_calibration_id=CALIBRATION_ID,
        now_ns=1_000,
        config=config(),
    )

    assert proposal.target_pose_id == "a_pose"


def test_selector_rejects_table_calibration_change() -> None:
    changed_table = TablePlane(
        normal_base=[0, 0, 1],
        offset_m=0.0,
        position_rmse_m=0.004,
        calibration_id="sha256:" + "1" * 64,
        validated=True,
    )

    proposal = select_observation_pose(
        estimate=estimate(),
        poses=(home_pose(), covering_pose("target", 2.0)),
        current_joints_deg=np.zeros(6),
        required_calibration_id=CALIBRATION_ID,
        now_ns=1_000,
        config=replace(config(), table_plane=changed_table),
    )

    assert proposal.kind == "none"
    assert proposal.reasons == ("table_calibration_mismatch",)


def test_observation_selector_is_a_public_pure_vision_interface() -> None:
    import vision

    assert "evaluate_depth_quality" in vision.__all__
    assert "match_observation_pose" in vision.__all__
    assert "propose_refinement" in vision.__all__
    assert "select_observation_pose" in vision.__all__
    assert vision.evaluate_depth_quality is evaluate_depth_quality
    assert vision.select_observation_pose is select_observation_pose


def d435() -> PinholeCamera:
    return PinholeCamera(100.0, 100.0, 50.0, 50.0, 100, 100)


def registered_cloud(points: np.ndarray) -> RegisteredDepth:
    points = np.asarray(points, dtype=float)
    height, width, _ = points.shape
    valid = np.isfinite(points).all(axis=2)
    z_m = np.full((height, width), np.nan)
    range_m = np.full((height, width), np.nan)
    z_m[valid] = points[..., 2][valid]
    range_m[valid] = np.linalg.norm(points[valid], axis=1)
    frozen_points = np.full((height, width, 3), np.nan)
    frozen_points[valid] = points[valid]
    return RegisteredDepth(
        z_m=z_m,
        range_m=range_m,
        valid=valid,
        source_count=valid.astype(np.int32),
        points_lumos_m=frozen_points,
    )


def point_grid(*, center_x: float = 0.0, size: int = 10) -> np.ndarray:
    offsets = np.linspace(-0.01, 0.01, size)
    xx, yy = np.meshgrid(offsets + center_x, offsets)
    return np.stack((xx, yy, np.ones_like(xx)), axis=2)


def test_good_central_depth_requests_no_extra_motion() -> None:
    registered = registered_cloud(point_grid())
    quality = evaluate_depth_quality(
        registered=registered,
        target_mask=np.ones(registered.valid.shape, dtype=bool),
        d435=d435(),
        t_d435_from_lumos=np.eye(4),
        t_base_from_lumos=np.eye(4),
        config=config(),
    )

    assert quality.valid_points == 100
    assert quality.central_fraction == pytest.approx(1.0)
    assert quality.acceptable is True
    assert quality.reasons == ()
    proposal = propose_refinement(
        3,
        quality,
        np.eye(4),
        FrameStamp("lumos+d435", 2, 1_000),
        1_000,
        0,
        config(),
        (CALIBRATION_ID,),
    )
    assert proposal.kind == "none"
    assert proposal.reasons == ("depth_quality_sufficient",)


def test_off_center_depth_produces_clipped_lateral_only_refinement() -> None:
    registered = registered_cloud(point_grid(center_x=0.35))
    quality = evaluate_depth_quality(
        registered,
        np.ones(registered.valid.shape, dtype=bool),
        d435(),
        np.eye(4),
        np.eye(4),
        config(),
    )
    proposal = propose_refinement(
        3,
        quality,
        np.eye(4),
        FrameStamp("lumos+d435", 2, 1_000),
        1_000,
        0,
        config(),
        (CALIBRATION_ID,),
    )

    assert quality.valid_points == 100
    assert quality.central_fraction == pytest.approx(0.0)
    assert quality.reasons == ("insufficient_central_coverage",)
    assert proposal.kind == "refine_delta"
    assert proposal.delta_base_m is not None
    assert np.linalg.norm(proposal.delta_base_m) == pytest.approx(0.020)
    assert proposal.delta_base_m[2] == pytest.approx(0.0)
    np.testing.assert_allclose(proposal.rotation_delta_rad, np.zeros(3))


def test_depth_quality_reports_sparse_and_behind_camera_points() -> None:
    sparse = registered_cloud(point_grid(size=5))
    sparse_quality = evaluate_depth_quality(
        sparse,
        np.ones(sparse.valid.shape, dtype=bool),
        d435(),
        np.eye(4),
        np.eye(4),
        config(),
    )
    assert sparse_quality.valid_points == 25
    assert sparse_quality.reasons == ("insufficient_depth_points",)

    behind_transform = np.eye(4)
    behind_transform[:3, :3] = np.diag([1.0, -1.0, -1.0])
    behind_quality = evaluate_depth_quality(
        registered_cloud(point_grid()),
        np.ones((10, 10), dtype=bool),
        d435(),
        behind_transform,
        np.eye(4),
        config(),
    )
    assert behind_quality.valid_points == 0
    assert behind_quality.center_d435_m is None
    assert behind_quality.reasons == (
        "no_projectable_depth_points",
        "insufficient_depth_points",
        "insufficient_central_coverage",
    )


def test_refinement_limit_and_missing_depth_fail_closed() -> None:
    registered = registered_cloud(point_grid(center_x=0.35))
    quality = evaluate_depth_quality(
        registered,
        np.ones(registered.valid.shape, dtype=bool),
        d435(),
        np.eye(4),
        np.eye(4),
        config(),
    )
    exhausted = propose_refinement(
        3,
        quality,
        np.eye(4),
        FrameStamp("lumos+d435", 2, 1_000),
        1_000,
        3,
        config(),
        (CALIBRATION_ID,),
    )
    assert exhausted.kind == "none"
    assert exhausted.reasons == ("view_refinement_exhausted",)

    behind_transform = np.eye(4)
    behind_transform[:3, :3] = np.diag([1.0, -1.0, -1.0])
    missing_quality = evaluate_depth_quality(
        registered_cloud(point_grid()),
        np.ones((10, 10), dtype=bool),
        d435(),
        behind_transform,
        np.eye(4),
        config(),
    )
    missing = propose_refinement(
        3,
        missing_quality,
        np.eye(4),
        FrameStamp("lumos+d435", 2, 1_000),
        1_000,
        0,
        config(),
        (CALIBRATION_ID,),
    )
    assert missing.kind == "none"
    assert missing.reasons == ("depth_geometry_unavailable",)


def test_depth_quality_rejects_mask_and_transform_mismatch() -> None:
    registered = registered_cloud(point_grid())
    with pytest.raises(InvalidDataError, match="target mask"):
        evaluate_depth_quality(
            registered,
            np.ones(registered.valid.shape, dtype=np.uint8),
            d435(),
            np.eye(4),
            np.eye(4),
            config(),
        )
    bad_transform = np.eye(4)
    bad_transform[3, 3] = 2.0
    with pytest.raises(InvalidDataError, match="transform"):
        evaluate_depth_quality(
            registered,
            np.ones(registered.valid.shape, dtype=bool),
            d435(),
            bad_transform,
            np.eye(4),
            config(),
        )
