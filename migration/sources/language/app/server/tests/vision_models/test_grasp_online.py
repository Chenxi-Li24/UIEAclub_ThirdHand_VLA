from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
from vision.active_view_types import TablePlane
from vision.calibration_gate import audit_handeye_calibration
from vision.camera_models import PinholeCamera, SeucmCamera
from vision.depth_registration import RegisteredDepth
from vision.d435_instance_verifier import D435InstanceVerification
from vision.dual_camera import (
    DualCameraCalibrationBundle,
    DualCameraFusionContext,
    DualCameraTarget,
)
from vision.grasp_geometry import GraspGeometryConfig
from vision.identity import IdentityStatus
from vision.types import FrameStamp
from vision_models.contracts import InstanceDetection
from vision_models.grasp_online import OnlineGraspPreviewAdapter, load_grasp_preview_config

ROOT = Path(__file__).parents[4]


def calibration_bundle() -> DualCameraCalibrationBundle:
    def audit(key: str):
        return audit_handeye_calibration(
            {
                key: np.eye(4).tolist(),
                "validation": {"reprojection_rmse_px": 0.3, "position_rmse_m": 0.004},
            },
            key,
        )

    return DualCameraCalibrationBundle.from_audits(
        d435=PinholeCamera(100.0, 100.0, 50.0, 50.0, 100, 100),
        lumos=SeucmCamera(100.0, 100.0, 50.0, 50.0, 0.5, 1.0, 100, 100),
        d435_to_lumos_audit=audit("T_lumos_from_d435"),
        lumos_to_flange_audit=audit("T_flange_from_lumos"),
    )


def geometry_config() -> GraspGeometryConfig:
    return GraspGeometryConfig(
        min_points=80,
        erosion_px=0,
        mad_scale=4.0,
        noise_floor_m=0.001,
        inner_roi_fraction=0.60,
        min_central_fraction=0.80,
        max_axis_mad_m=0.005,
        min_object_height_m=0.010,
        max_object_height_m=0.250,
        min_gripper_width_m=0.010,
        max_gripper_width_m=0.085,
        grasp_width_margin_m=0.006,
        pregrasp_clearance_m=0.080,
        retreat_clearance_m=0.100,
        workspace_min_m=np.array([0.10, -0.40, 0.01]),
        workspace_max_m=np.array([0.70, 0.40, 0.45]),
        stable_sample_count=5,
        max_center_deviation_m=0.010,
        max_temporal_axis_mad_m=0.005,
    )


def registered_cloud() -> tuple[RegisteredDepth, np.ndarray, np.ndarray]:
    valid = np.zeros((100, 100), dtype=bool)
    mask = np.zeros((100, 100), dtype=bool)
    points = np.full((100, 100, 3), np.nan)
    rows, cols = np.mgrid[40:60, 40:60]
    points[rows, cols, 0] = np.linspace(-0.03, 0.03, cols.size).reshape(20, 20)
    points[rows, cols, 1] = np.tile(np.linspace(-0.015, 0.015, 20), (20, 1))
    points[rows, cols, 2] = np.linspace(0.46, 0.48, cols.size).reshape(20, 20)
    valid[rows, cols] = True
    mask[38:62, 38:62] = True
    z_image = np.full((100, 100), np.nan)
    range_image = np.full((100, 100), np.nan)
    z_image[valid] = points[valid, 2]
    range_image[valid] = np.linalg.norm(points[valid], axis=1)
    counts = np.zeros((100, 100), dtype=np.int32)
    counts[valid] = 1
    transform = np.eye(4)
    transform[:3, 3] = [0.4, 0.0, -0.41]
    return RegisteredDepth(z_image, range_image, valid, counts, points), mask, transform


def inputs():
    calibration = calibration_bundle()
    registered, mask, t_base_from_lumos = registered_cloud()
    context = DualCameraFusionContext(
        registered=registered,
        t_d435_from_lumos=np.eye(4),
        t_base_from_lumos=t_base_from_lumos,
        source_stamp=FrameStamp("lumos_rgb+d435_depth", 1, 100),
        calibration_id=calibration.calibration.calibration_id,
        evidence_ids=(calibration.calibration.calibration_id, *calibration.source_audit_ids),
    )
    target = DualCameraTarget(
        detection_id=3,
        label="bottle",
        score=0.95,
        identity_id=7,
        identity_status=IdentityStatus.CONFIRMED,
        pose=None,
        registered_depth_points=400,
        actionable=True,
        reasons=(),
    )
    detection = InstanceDetection(
        detection_id=3,
        label="bottle",
        score=0.95,
        bbox_xyxy=np.array([38.0, 38.0, 62.0, 62.0]),
        mask=mask,
    )
    table = TablePlane(
        normal_base=[0.0, 0.0, 1.0],
        offset_m=0.0,
        position_rmse_m=0.003,
        calibration_id=calibration.calibration.calibration_id,
        validated=True,
    )
    return calibration, context, target, detection, table


def test_adapter_binds_preview_to_identity_detection_and_foundation_evidence():
    calibration, context, target, detection, table = inputs()
    table_source_id = "sha256:" + "e" * 64
    adapter = OnlineGraspPreviewAdapter(
        table=table,
        config=geometry_config(),
        foundation_evidence_ids=(table_source_id,),
    )

    for frame_id in range(1, 6):
        stamp = FrameStamp("lumos_rgb+d435_depth", frame_id, frame_id * 100)
        statuses = adapter.evaluate(
            detections=(detection,),
            targets=(target,),
            fusion_context=replace(context, source_stamp=stamp),
            calibration=calibration,
            robot_pose=None,
            arm_stationary=True,
            now_ns=frame_id * 100,
        )

    assert len(statuses) == 1
    status = statuses[0]
    assert status.identity_id == 7
    assert status.candidate.detection_id == 3
    assert status.allowed is True
    assert status.stable_samples == 5
    assert table_source_id in status.candidate.evidence_ids


def test_adapter_fails_closed_without_fusion_or_stationarity():
    calibration, context, target, detection, table = inputs()
    adapter = OnlineGraspPreviewAdapter(
        table=table,
        config=geometry_config(),
        foundation_evidence_ids=("sha256:" + "e" * 64,),
    )

    assert adapter.evaluate(
        detections=(detection,),
        targets=(target,),
        fusion_context=None,
        calibration=calibration,
        robot_pose=None,
        arm_stationary=True,
        now_ns=100,
    ) == ()


def test_adapter_requires_and_uses_explicit_d435_same_instance_evidence():
    calibration, context, target, detection, table = inputs()
    adapter = OnlineGraspPreviewAdapter(
        table=table,
        config=geometry_config(),
        foundation_evidence_ids=("sha256:" + "e" * 64,),
    )
    unverified = D435InstanceVerification(
        3, None, "bottle", False, 400, 0, 0.0, None, None,
        ("d435_instance_unverified",),
    )
    d435_mask = np.zeros((100, 100), dtype=bool)
    d435_mask[:, :50] = True
    verified = D435InstanceVerification(
        3, 9, "bottle", True, 400, 200, 0.5,
        np.array([0.0, 0.0, 50.0, 100.0]), d435_mask, (),
    )

    blocked = adapter.evaluate(
        detections=(detection,), targets=(target,), fusion_context=context,
        calibration=calibration, robot_pose=None, arm_stationary=True, now_ns=100,
        d435_verifications={3: unverified},
    )
    accepted = adapter.evaluate(
        detections=(detection,), targets=(target,), fusion_context=context,
        calibration=calibration, robot_pose=None, arm_stationary=True, now_ns=100,
        d435_verifications={3: verified},
    )

    assert blocked == ()
    assert len(accepted) == 1
    assert accepted[0].candidate is not None
    assert accepted[0].candidate.valid_points < 400
    assert adapter.evaluate(
        detections=(detection,),
        targets=(target,),
        fusion_context=context,
        calibration=calibration,
        robot_pose=None,
        arm_stationary=False,
        now_ns=100,
    ) == ()


def test_grasp_preview_config_is_strict_and_uses_robot_base_workspace(tmp_path: Path):
    loaded = load_grasp_preview_config(ROOT / "configs/vision/grasp_preview.yaml")
    assert loaded.min_points == 80
    assert loaded.stable_sample_count == 5
    np.testing.assert_allclose(loaded.workspace_min_m, [-0.3, -0.4, 0.01])
    np.testing.assert_allclose(loaded.workspace_max_m, [0.5, 0.4, 0.4])

    invalid = tmp_path / "invalid.yaml"
    invalid.write_text("schema_version: 1\nunknown: true\n", encoding="utf-8")
    with np.testing.assert_raises_regex(ValueError, "keys"):
        load_grasp_preview_config(invalid)
