from __future__ import annotations

import numpy as np
import pytest

import thirdhand_vision.active_view as active_view
from thirdhand_vision.active_view import (
    ActiveViewConfig,
    CoarseTargetEstimate,
    ObservationPose,
    evaluate_depth_quality,
    propose_refinement,
    select_observation_pose,
)
from thirdhand_vision.core.camera import PinholeCamera
from thirdhand_vision.core.types import FrameStamp
from thirdhand_vision.geometry.depth import RegisteredDepth


def config() -> ActiveViewConfig:
    return ActiveViewConfig(
        inner_roi_fraction=0.6,
        min_depth_points=4,
        min_central_fraction=0.6,
        max_axis_mad_m=0.01,
        max_translation_m=0.02,
        proposal_ttl_ns=200_000_000,
    )


def registered_fixture() -> RegisteredDepth:
    points = np.full((5, 5, 3), np.nan)
    valid = np.zeros((5, 5), dtype=bool)
    samples = {
        (1, 1): [-0.01, -0.01, 0.5],
        (1, 2): [0.00, -0.01, 0.5],
        (2, 1): [-0.01, 0.00, 0.5],
        (2, 2): [0.00, 0.00, 0.5],
        (3, 3): [0.02, 0.02, 0.5],
    }
    for (row, col), point in samples.items():
        points[row, col] = point
        valid[row, col] = True
    return RegisteredDepth(
        z_m=points[..., 2],
        range_m=np.linalg.norm(points, axis=2),
        valid=valid,
        source_count=valid.astype(np.int32),
        points_lumos_m=points,
    )


def test_depth_quality_reports_count_central_fraction_and_mad() -> None:
    quality = evaluate_depth_quality(
        registered=registered_fixture(),
        mask=np.ones((5, 5), dtype=bool),
        d435=PinholeCamera(50.0, 50.0, 2.0, 2.0, 5, 5),
        t_d435_from_lumos=np.eye(4),
        t_output_from_lumos=np.eye(4),
        config=config(),
    )
    assert quality.valid_points == 5
    assert quality.central_fraction == pytest.approx(0.8)
    assert quality.acceptable
    np.testing.assert_allclose(quality.center_output_m, [0.0, 0.0, 0.5])


def test_observation_selector_uses_nearest_valid_catalog_pose() -> None:
    target = CoarseTargetEstimate(
        center_xy_m=np.array([0.1, 0.1]),
        covariance_xy_m2=np.eye(2) * 1e-4,
        stamp=FrameStamp("lumos_rgb", 8, 1_000),
        calibration_id="sha256:test",
    )
    poses = (
        ObservationPose("far", np.full(6, 10.0), [0.0, 0.0], [0.2, 0.2], True),
        ObservationPose("near", np.full(6, 2.0), [0.0, 0.0], [0.2, 0.2], True),
        ObservationPose("invalid", np.zeros(6), [0.0, 0.0], [0.2, 0.2], False),
    )
    proposal = select_observation_pose(
        target,
        current_joints_deg=np.zeros(6),
        poses=poses,
        now_ns=1_100,
        config=config(),
    )
    assert proposal.kind == "catalog"
    assert proposal.target_pose_id == "near"
    assert proposal.expires_ns == 200_001_100


def test_refinement_clamps_lateral_correction() -> None:
    proposal = propose_refinement(
        identity_id=4,
        offset_xy_m=np.array([0.03, 0.04]),
        source_stamp=FrameStamp("fusion", 3, 10),
        now_ns=20,
        config=config(),
    )
    assert proposal.kind == "refinement"
    assert np.linalg.norm(proposal.delta_output_m[:2]) == pytest.approx(0.02)
    assert proposal.delta_output_m[2] == 0.0


def test_active_view_module_has_no_execution_api() -> None:
    assert not hasattr(active_view, "execute")
    assert not hasattr(active_view, "move_robot")
