from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from vision.active_view_types import ObservationPose, TablePlane
from vision.calibration_gate import audit_handeye_calibration
from vision.camera_models import PinholeCamera, SeucmCamera
from vision.dual_camera import (
    DualCameraCalibrationBundle,
    DualCameraTarget,
    StampedRobotPose,
)
from vision.identity import IdentityStatus
from vision.types import FrameStamp
from vision.types import InvalidDataError
from vision_models.contracts import InstanceDetection
from vision_models.active_view_online import (
    ActiveViewDryRunAdapter,
    load_active_view_config,
    load_active_view_config_dict,
)


PROJECT_ROOT = Path(__file__).parents[4]
EVIDENCE_ID = "sha256:" + "b" * 64


def test_checked_in_active_view_config_is_execution_locked_and_empty() -> None:
    config = load_active_view_config(PROJECT_ROOT / "configs/vision/active_view.yaml")

    assert config.dry_run_enabled is True
    assert config.execution_enabled is False
    assert config.table_plane.validated is False
    assert config.observation_poses == ()
    assert config.inner_roi_fraction == pytest.approx(0.60)
    assert config.min_depth_points == 80
    assert config.stable_sample_count == 5
    assert config.max_refinement_steps == 3
    assert config.proposal_ttl_ns == 200_000_000


def test_config_dict_rejects_any_execution_permission() -> None:
    with pytest.raises(InvalidDataError, match="execution"):
        load_active_view_config_dict(
            {
                "schema_version": 1,
                "dry_run_enabled": True,
                "active_view_execution_enabled": True,
            }
        )


def test_config_loader_builds_an_immutable_observation_catalog() -> None:
    raw = _valid_config_dict()
    raw["observation_poses"] = [
        {
            "pose_id": "table_center",
            "joints_deg": [0, 1, 2, 3, 4, 5],
            "t_base_from_flange": np.eye(4).tolist(),
            "coverage_polygon_xy_m": [
                [-0.2, -0.1],
                [0.2, -0.1],
                [0.2, 0.1],
                [-0.2, 0.1],
            ],
            "allowed_start_pose_ids": ["home"],
            "path_validation_id": EVIDENCE_ID,
            "calibration_id": EVIDENCE_ID,
            "joint_tolerance_deg": 0.5,
        }
    ]

    config = load_active_view_config_dict(raw)

    assert len(config.observation_poses) == 1
    assert config.observation_poses[0].pose_id == "table_center"
    assert config.observation_poses[0].joints_deg.flags.writeable is False
    assert config.observation_poses[0].joint_tolerance_deg == 0.5


def test_config_loader_rejects_duplicate_pose_ids_and_long_ttl() -> None:
    raw = _valid_config_dict()
    pose = {
        "pose_id": "duplicate",
        "joints_deg": [0, 1, 2, 3, 4, 5],
        "t_base_from_flange": np.eye(4).tolist(),
        "coverage_polygon_xy_m": [[0, 0], [1, 0], [0, 1]],
        "allowed_start_pose_ids": ["home"],
        "path_validation_id": EVIDENCE_ID,
        "calibration_id": EVIDENCE_ID,
    }
    raw["observation_poses"] = [pose, dict(pose)]
    with pytest.raises(InvalidDataError, match="duplicate"):
        load_active_view_config_dict(raw)

    raw = _valid_config_dict()
    raw["motion_proposals"]["proposal_ttl_ms"] = 1_001
    with pytest.raises(InvalidDataError, match="TTL"):
        load_active_view_config_dict(raw)


def test_config_contract_cannot_be_replaced_with_unsafe_motion_limits() -> None:
    config = load_active_view_config_dict(_valid_config_dict())

    with pytest.raises(InvalidDataError, match="translation"):
        replace(config, max_translation_m=0.021)
    with pytest.raises(InvalidDataError, match="rotation"):
        replace(config, max_rotation_rad=np.deg2rad(5.1))
    with pytest.raises(InvalidDataError, match="refinement"):
        replace(config, max_refinement_steps=4)
    with pytest.raises(InvalidDataError, match="TTL"):
        replace(config, proposal_ttl_ns=1_000_000_001)


def _valid_config_dict() -> dict:
    return {
        "schema_version": 1,
        "dry_run_enabled": True,
        "active_view_execution_enabled": False,
        "table_plane": {
            "normal_base": [0.0, 0.0, 1.0],
            "offset_m": 0.0,
            "position_rmse_m": 0.010,
            "calibration_id": EVIDENCE_ID,
            "validated": False,
        },
        "quality": {
            "inner_roi_fraction": 0.60,
            "coverage_margin_m": 0.010,
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


def _detection(detection_id: int = 7) -> InstanceDetection:
    mask = np.zeros((9, 9), dtype=bool)
    mask[2:8, 3:6] = True
    return InstanceDetection(
        detection_id=detection_id,
        label="bottle",
        score=0.9,
        bbox_xyxy=np.array([3.0, 2.0, 6.0, 8.0]),
        mask=mask,
    )


def _target(detection_id: int = 7) -> DualCameraTarget:
    return DualCameraTarget(
        detection_id=detection_id,
        label="bottle",
        score=0.9,
        identity_id=3,
        identity_status=IdentityStatus.CONFIRMED,
        pose=None,
        registered_depth_points=0,
        actionable=False,
        reasons=("calibration_unavailable",),
    )


def test_checked_in_adapter_reports_blockers_without_motion_payload() -> None:
    adapter = ActiveViewDryRunAdapter(
        load_active_view_config(PROJECT_ROOT / "configs/vision/active_view.yaml")
    )

    reports = adapter.evaluate(
        detections=(_detection(),),
        targets=(_target(),),
        rgb_stamp=FrameStamp("lumos_rgb", 1, 1_000),
        robot_pose=None,
        calibration=None,
        arm_stationary=True,
        now_ns=1_000,
    )

    assert len(reports) == 1
    report = reports[0].to_dict()
    assert report["identity_id"] == 3
    assert report["active_view_execution_enabled"] is False
    assert report["kind"] == "none"
    assert report["stable_samples"] == 0
    assert report["remaining_refinements"] == 3
    assert "table_unvalidated" in report["reasons"]
    assert "observation_catalog_empty" in report["reasons"]
    assert "calibration_unavailable" in report["reasons"]
    assert "robot_pose_unavailable" in report["reasons"]
    encoded = str(report).lower()
    for forbidden in ("move_l", "move_joint", "trajectory", "gripper", "can"):
        assert forbidden not in encoded


def test_adapter_matches_by_detection_id_and_bounds_reports() -> None:
    adapter = ActiveViewDryRunAdapter(
        load_active_view_config(PROJECT_ROOT / "configs/vision/active_view.yaml")
    )
    detections = tuple(_detection(index) for index in range(300))

    reports = adapter.evaluate(
        detections=detections,
        targets=(_target(299),),
        rgb_stamp=FrameStamp("lumos_rgb", 1, 1_000),
        robot_pose=None,
        calibration=None,
        arm_stationary=False,
        now_ns=1_000,
    )

    assert len(reports) == 256
    assert reports[0].detection_id == 0
    assert reports[-1].detection_id == 255
    assert all(report.identity_id is None for report in reports)
    assert all("target_result_missing" in report.reasons for report in reports)


def test_active_view_adapter_is_a_public_model_boundary() -> None:
    import vision_models

    expected = {
        "ActiveViewConfig",
        "ActiveViewDryRunAdapter",
        "ActiveViewEvaluationBatch",
        "ActiveViewTargetReport",
        "load_active_view_config",
    }
    assert expected <= set(vision_models.__all__)
    assert vision_models.ActiveViewDryRunAdapter is ActiveViewDryRunAdapter


def test_adapter_keeps_trusted_motion_proposal_out_of_presentation_report() -> None:
    d435 = PinholeCamera(20.0, 20.0, 4.0, 4.0, 9, 9)
    lumos = SeucmCamera(20.0, 20.0, 4.0, 4.0, 0.5, 1.0, 9, 9)

    def audit(key: str):
        return audit_handeye_calibration(
            {
                key: np.eye(4).tolist(),
                "validation": {"reprojection_rmse_px": 0.4, "position_rmse_m": 0.004},
            },
            key,
        )

    calibration = DualCameraCalibrationBundle.from_audits(
        d435=d435,
        lumos=lumos,
        d435_to_lumos_audit=audit("T_lumos_from_d435"),
        lumos_to_flange_audit=audit("T_flange_from_lumos"),
    )
    calibration_id = calibration.calibration.calibration_id
    table = TablePlane([0, 0, 1], 0.0, 0.004, calibration_id, True)
    transform = np.eye(4)
    transform[:3, :3] = np.diag([1.0, -1.0, -1.0])
    transform[2, 3] = 1.0
    home_observation = ObservationPose(
        pose_id="home",
        joints_deg=[1, 20, -40, 0, 10, 0],
        t_base_from_flange=transform,
        coverage_polygon_xy_m=[[2, 2], [3, 2], [3, 3], [2, 3]],
        allowed_start_pose_ids=("home",),
        path_validation_id="sha256:" + "c" * 64,
        calibration_id=calibration_id,
    )
    observation = ObservationPose(
        pose_id="table_center",
        joints_deg=[2, 20, -40, 0, 10, 0],
        t_base_from_flange=transform,
        coverage_polygon_xy_m=[[-1, -1], [1, -1], [1, 1], [-1, 1]],
        allowed_start_pose_ids=("home",),
        path_validation_id=EVIDENCE_ID,
        calibration_id=calibration_id,
    )
    active_config = replace(
        load_active_view_config_dict(_valid_config_dict()),
        table_plane=table,
        observation_poses=(home_observation, observation),
    )
    adapter = ActiveViewDryRunAdapter(active_config)

    batch = adapter.evaluate_with_proposals(
        detections=(_detection(),),
        targets=(_target(),),
        rgb_stamp=FrameStamp("lumos_rgb", 1, 1_000),
        robot_pose=StampedRobotPose(FrameStamp("robot_flange_pose", 1, 1_000), transform),
        calibration=calibration,
        arm_stationary=True,
        current_joints_deg=np.array([1, 20, -40, 0, 10, 0]),
        now_ns=1_001,
    )

    assert len(batch.proposals) == 1
    assert batch.proposals[0].kind == "coarse_pose"
    assert batch.reports[0].kind == "coarse_pose"
    assert batch.reports[0].target_pose_id == "table_center"
    serialized = batch.reports[0].to_dict()
    assert "joints_deg" not in serialized
    assert "delta_base_m" not in serialized
