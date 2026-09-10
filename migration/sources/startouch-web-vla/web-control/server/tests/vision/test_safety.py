from __future__ import annotations

import numpy as np
import pytest

from vision.safety import SafetyConfig, evaluate_target_safety
from vision.types import (
    CalibrationRef,
    FrameStamp,
    InvalidDataError,
    PoseEstimate,
    TrackState,
)


def safety_config() -> SafetyConfig:
    return SafetyConfig(
        workspace_min_m=np.array([0.10, -0.50, 0.02]),
        workspace_max_m=np.array([0.80, 0.50, 0.80]),
        max_target_age_ns=300_000_000,
        max_position_std_m=0.025,
        min_cloud_points=20,
        min_gripper_width_m=0.01,
        max_gripper_width_m=0.12,
        grasp_width_margin_m=0.01,
        pregrasp_clearance_m=0.10,
        retreat_clearance_m=0.12,
        table_clearance_m=0.01,
        clearance_weight=1.0,
        uncertainty_weight=2.0,
        travel_weight=0.1,
        nominal_pose_m=np.array([0.35, 0.0, 0.35]),
    )


def target(
    *,
    xyz=(0.4, 0.0, 0.15),
    timestamp_ns=100,
    variance=1e-4,
    calibration_id="sha256:calibration-a",
) -> TrackState:
    pose = PoseEstimate(
        xyz_m=np.asarray(xyz, dtype=float),
        covariance_m2=np.eye(3) * variance,
        frame="robot_base",
        stamp=FrameStamp("lumos+d435", 1, timestamp_ns),
        calibration_id=calibration_id,
    )
    return TrackState(4, "cup", pose, np.zeros(3), 5, 0, True, timestamp_ns)


def cloud(count=40):
    x = np.linspace(0.36, 0.44, count)
    y = np.linspace(-0.03, 0.03, count)
    z = np.linspace(0.10, 0.20, count)
    return np.column_stack((x, y, z))


def calibration(*, validated=True, calibration_id="sha256:calibration-a"):
    return CalibrationRef(
        calibration_id=calibration_id,
        validated=validated,
        reprojection_rmse_px=0.42,
        validation_notes=("independent holdout",),
    )


def test_valid_target_passes_all_safety_gates():
    decision = evaluate_target_safety(
        target(), cloud(), calibration(), now_ns=200, config=safety_config(), reachable=True
    )
    assert decision.approved
    assert decision.reasons == ()


@pytest.mark.parametrize(
    "expected,track_value,cloud_value,calibration_value,now_ns,reachable",
    [
        ("calibration_not_validated", target(), cloud(), calibration(validated=False), 200, True),
        (
            "calibration_mismatch",
            target(),
            cloud(),
            calibration(calibration_id="sha256:calibration-b"),
            200,
            True,
        ),
        ("target_stale", target(timestamp_ns=0), cloud(), calibration(), 300_000_001, True),
        ("uncertainty_too_high", target(variance=0.04**2), cloud(), calibration(), 200, True),
        ("target_cloud_too_small", target(), cloud(count=10), calibration(), 200, True),
        ("outside_workspace", target(xyz=(0.9, 0.0, 0.15)), cloud(), calibration(), 200, True),
        ("target_not_reachable", target(), cloud(), calibration(), 200, False),
    ],
)
def test_each_safety_gate_fails_closed(
    expected, track_value, cloud_value, calibration_value, now_ns, reachable
):
    decision = evaluate_target_safety(
        track_value,
        cloud_value,
        calibration_value,
        now_ns=now_ns,
        config=safety_config(),
        reachable=reachable,
    )
    assert not decision.approved
    assert expected in decision.reasons


def test_multiple_failures_are_reported_in_stable_order():
    decision = evaluate_target_safety(
        target(xyz=(0.9, 0.0, 0.15), timestamp_ns=0, variance=0.04**2),
        cloud(count=1),
        calibration(validated=False),
        now_ns=300_000_001,
        config=safety_config(),
        reachable=False,
    )
    assert decision.reasons == (
        "calibration_not_validated",
        "target_stale",
        "uncertainty_too_high",
        "target_cloud_too_small",
        "outside_workspace",
        "target_not_reachable",
    )


def test_safety_rejects_invalid_time_cloud_and_config():
    with pytest.raises(InvalidDataError):
        evaluate_target_safety(
            target(), cloud(), calibration(), now_ns=99, config=safety_config(), reachable=True
        )
    with pytest.raises(InvalidDataError):
        evaluate_target_safety(
            target(), np.ones((3, 2)), calibration(), 200, safety_config(), True
        )
    with pytest.raises(InvalidDataError):
        SafetyConfig(
            workspace_min_m=np.zeros(3),
            workspace_max_m=np.zeros(3),
            max_target_age_ns=1,
            max_position_std_m=0.1,
            min_cloud_points=1,
            min_gripper_width_m=0.01,
            max_gripper_width_m=0.02,
            grasp_width_margin_m=0.001,
            pregrasp_clearance_m=0.1,
            retreat_clearance_m=0.1,
            table_clearance_m=0.01,
            clearance_weight=1.0,
            uncertainty_weight=1.0,
            travel_weight=1.0,
            nominal_pose_m=np.zeros(3),
        )
