from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from vision.active_view_planner import match_observation_pose, select_observation_pose
from vision.active_view_types import CoarseTargetEstimate, ObservationPose, TablePlane
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

    assert "match_observation_pose" in vision.__all__
    assert "select_observation_pose" in vision.__all__
    assert vision.select_observation_pose is select_observation_pose
