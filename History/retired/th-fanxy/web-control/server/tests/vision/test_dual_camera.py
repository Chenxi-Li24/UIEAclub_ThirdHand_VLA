from __future__ import annotations

import numpy as np
import pytest
from types import SimpleNamespace

from vision.camera_models import PinholeCamera, SeucmCamera
from vision.dual_camera import (
    DualCameraCalibrationBundle,
    DualCameraConfig,
    DualCameraPerception,
    StampedRobotPose,
)
from vision.calibration_gate import audit_handeye_calibration
from vision.identity import PersistentIdentityConfig, PersistentIdentityMemory
from vision.instance_pose import InstancePoseConfig
from vision.online_frames import CameraRoleMap
from vision.types import FrameStamp, InvalidDataError
from vision_models.contracts import InstanceDetection


def identity_config() -> PersistentIdentityConfig:
    return PersistentIdentityConfig(
        max_cosine_distance=0.40,
        ambiguity_margin=0.03,
        appearance_weight=0.80,
        position_weight=0.20,
        max_position_distance_m=0.20,
        position_gate_max_age_ns=500_000_000,
        occluded_after_ns=300_000_000,
        inactive_after_ns=1_500_000_000,
        min_confirmed_hits=2,
        min_memory_confidence=0.80,
        min_memory_visibility=0.50,
        work_bank_size=4,
        stable_bank_size=4,
        max_identities=8,
        reacquire_confirmed_hits=2,
        max_actionable_position_std_m=0.025,
        max_actionable_pose_age_ns=200_000_000,
        min_actionable_pose_hits=2,
    )


def pipeline() -> DualCameraPerception:
    return DualCameraPerception(
        PersistentIdentityMemory(identity_config()),
        DualCameraConfig(
            max_frame_skew_ns=40_000_000,
            max_frame_age_ns=200_000_000,
            max_robot_pose_skew_ns=40_000_000,
            min_depth_m=0.10,
            max_depth_m=2.0,
            pose=InstancePoseConfig(
                min_points=4,
                erosion_px=0,
                mad_scale=3.5,
                noise_floor_m=0.002,
            ),
            roles=CameraRoleMap(
                "lumos_rgb",
                "d435_depth",
                "d435_rgb",
                "cross_camera",
            ),
        ),
    )


def cameras() -> tuple[PinholeCamera, SeucmCamera]:
    return (
        PinholeCamera(40.0, 40.0, 2.0, 2.0, 5, 5),
        SeucmCamera(40.0, 40.0, 2.0, 2.0, 0.5, 1.0, 5, 5),
    )


def detection(score: float = 0.95) -> InstanceDetection:
    mask = np.zeros((5, 5), dtype=bool)
    mask[1:4, 1:4] = True
    return InstanceDetection(
        detection_id=7,
        label="bottle",
        score=score,
        bbox_xyxy=np.array([1.0, 1.0, 4.0, 4.0]),
        mask=mask,
    )


def calibration_bundle(validated: bool = True) -> DualCameraCalibrationBundle:
    d435, lumos = cameras()
    validation = (
        {"reprojection_rmse_px": 0.3, "position_rmse_m": 0.004}
        if validated
        else None
    )
    def audit(key: str):
        payload = {key: np.eye(4).tolist(), "pairs": 20}
        if validation is not None:
            payload["validation"] = validation
        return audit_handeye_calibration(payload, key)

    return DualCameraCalibrationBundle.from_audits(
        d435=d435,
        lumos=lumos,
        d435_to_lumos_audit=audit("T_lumos_from_d435"),
        lumos_to_flange_audit=audit("T_flange_from_lumos"),
    )


def process_frame(
    perception: DualCameraPerception,
    timestamp_ns: int,
    *,
    frame_skew_ns: int = 5_000_000,
    arm_stationary: bool = True,
    validated: bool = True,
    depth: np.ndarray | None = None,
    score: float = 0.95,
    now_lag_ns: int = 0,
    robot_pose_skew_ns: int = 2_000_000,
    robot_pose_override=None,
    calibration_override=None,
):
    depth_image = np.ones((5, 5), dtype=float) if depth is None else depth
    d435_timestamp_ns = timestamp_ns + frame_skew_ns
    robot_timestamp_ns = timestamp_ns + robot_pose_skew_ns
    fusion_timestamp_ns = max(timestamp_ns, d435_timestamp_ns)
    return perception.process(
        rgb_stamp=FrameStamp("lumos_rgb", timestamp_ns // 10_000_000, timestamp_ns),
        depth_stamp=FrameStamp(
            "d435_depth",
            timestamp_ns // 10_000_000,
            d435_timestamp_ns,
        ),
        robot_pose=robot_pose_override or StampedRobotPose(
            stamp=FrameStamp(
                "robot_flange_pose",
                timestamp_ns // 10_000_000,
                robot_timestamp_ns,
            ),
            t_base_from_flange=np.eye(4),
        ),
        detections=(detection(score),),
        descriptors=(np.array([1.0, 0.0, 0.0]),),
        visibilities=(0.95,),
        depth_z_m=depth_image,
        calibration=calibration_override or calibration_bundle(validated),
        arm_stationary=arm_stationary,
        now_ns=max(fusion_timestamp_ns, robot_timestamp_ns) + now_lag_ns,
    )


def test_roles_are_explicit_and_valid_second_observation_becomes_actionable():
    perception = pipeline()
    first = process_frame(perception, 100_000_000)
    second = process_frame(perception, 200_000_000)

    assert first.canonical_rgb_source == "lumos_rgb"
    assert first.metric_depth_source == "d435_depth"
    assert not first.targets[0].actionable
    assert "identity_not_actionable" in first.targets[0].reasons
    assert second.targets[0].identity_id == first.targets[0].identity_id == 1
    assert second.targets[0].pose is not None
    assert second.targets[0].registered_depth_points == 9
    assert second.targets[0].actionable
    assert second.targets[0].reasons == ()
    assert second.fusion_context is not None
    assert second.fusion_context.registered.valid.shape == (5, 5)
    assert second.fusion_context.source_stamp.monotonic_ns == 205_000_000
    assert second.fusion_context.calibration_id == calibration_bundle().calibration.calibration_id


def test_missing_geometry_keeps_lumos_identity_but_never_becomes_actionable():
    perception = pipeline()
    timestamp_ns = 100_000_000
    result = perception.process(
        rgb_stamp=FrameStamp("lumos_rgb", 10, timestamp_ns),
        depth_stamp=None,
        robot_pose=None,
        detections=(detection(),),
        descriptors=(np.array([1.0, 0.0, 0.0]),),
        visibilities=(0.95,),
        depth_z_m=None,
        calibration=None,
        arm_stationary=True,
        now_ns=timestamp_ns,
    )

    target = result.targets[0]
    assert result.canonical_rgb_source == "lumos_rgb"
    assert result.metric_depth_source == "d435_depth"
    assert result.frame_skew_ns is None
    assert target.identity_id == 1
    assert target.pose is None
    assert target.actionable is False
    assert target.reasons == (
        "calibration_unavailable",
        "depth_unavailable",
        "robot_pose_unavailable",
        "identity_not_actionable",
    )
    assert result.fusion_context is None


def test_configured_roles_reject_frames_from_a_different_rgb_source():
    perception = pipeline()
    with pytest.raises(InvalidDataError, match="canonical RGB source"):
        perception.process(
            rgb_stamp=FrameStamp("d435_rgb", 10, 100_000_000),
            depth_stamp=None,
            robot_pose=None,
            detections=(detection(),),
            descriptors=(np.array([1.0, 0.0, 0.0]),),
            visibilities=(0.95,),
            depth_z_m=None,
            calibration=None,
            arm_stationary=True,
            now_ns=100_000_000,
        )


def test_unvalidated_calibration_preserves_appearance_identity_but_never_pose():
    perception = pipeline()
    result = process_frame(perception, 100_000_000, validated=False)

    target = result.targets[0]
    assert target.identity_id == 1
    assert target.pose is None
    assert not target.actionable
    assert "calibration_not_validated" in target.reasons


def test_frame_skew_and_arm_motion_fail_closed_before_depth_fusion():
    perception = pipeline()
    skewed = process_frame(perception, 100_000_000, frame_skew_ns=50_000_000)
    moving = process_frame(perception, 200_000_000, arm_stationary=False)

    assert "frame_skew_exceeded" in skewed.targets[0].reasons
    assert skewed.targets[0].pose is None
    assert "arm_not_stationary" in moving.targets[0].reasons
    assert moving.targets[0].pose is None


def test_stale_camera_frames_and_robot_pose_skew_are_not_actionable():
    perception = pipeline()
    process_frame(perception, 100_000_000)
    stale = process_frame(perception, 200_000_000, now_lag_ns=500_000_000)
    pose_skewed = process_frame(
        pipeline(),
        100_000_000,
        robot_pose_skew_ns=50_000_000,
    )

    assert not stale.targets[0].actionable
    assert stale.targets[0].identity_id == 1
    assert "camera_frames_stale" in stale.targets[0].reasons
    assert stale.targets[0].pose is None
    assert not pose_skewed.targets[0].actionable
    assert "robot_pose_skew_exceeded" in pose_skewed.targets[0].reasons
    assert pose_skewed.targets[0].pose is None


def test_mask_with_too_little_registered_depth_is_not_actionable():
    depth = np.zeros((5, 5), dtype=float)
    depth[2, 2] = 1.0
    result = process_frame(pipeline(), 100_000_000, depth=depth)

    target = result.targets[0]
    assert target.registered_depth_points == 1
    assert target.pose is None
    assert not target.actionable
    assert "insufficient_mask_depth" in target.reasons


def test_low_confidence_detection_cannot_seed_a_physical_identity():
    result = process_frame(pipeline(), 100_000_000, score=0.22)

    target = result.targets[0]
    assert target.identity_id is None
    assert not target.actionable
    assert "observation_below_memory_quality" in target.reasons


def test_calibration_id_is_bound_to_models_and_both_fixed_transforms():
    bundle = calibration_bundle()

    assert bundle.calibration.validated
    assert bundle.calibration.calibration_id not in bundle.source_audit_ids
    assert all(
        audit_id in " ".join(bundle.calibration.validation_notes)
        for audit_id in bundle.source_audit_ids
    )
    with pytest.raises(TypeError):
        DualCameraCalibrationBundle()


def test_robot_transform_and_timestamp_are_one_immutable_sample():
    with pytest.raises(InvalidDataError, match="robot pose source"):
        StampedRobotPose(
            stamp=FrameStamp("untrusted", 1, 100),
            t_base_from_flange=np.eye(4),
        )


def test_fusion_calibration_requires_the_audited_bundle_runtime_type():
    with pytest.raises(InvalidDataError, match="DualCameraCalibrationBundle"):
        process_frame(
            pipeline(),
            100_000_000,
            calibration_override=SimpleNamespace(
                calibration=SimpleNamespace(validated=True),
            ),
        )

    perception = pipeline()
    with pytest.raises(InvalidDataError, match="StampedRobotPose"):
        process_frame(
            perception,
            100_000_000,
            robot_pose_override=SimpleNamespace(
                stamp=FrameStamp("untrusted", 1, 102_000_000),
                t_base_from_flange=np.eye(4),
            ),
        )


def test_calibration_audits_cannot_be_swapped_between_transform_directions():
    d435, lumos = cameras()
    first = audit_handeye_calibration(
        {
            "T_lumos_from_d435": np.eye(4).tolist(),
            "validation": {"reprojection_rmse_px": 0.3, "position_rmse_m": 0.004},
        },
        "T_lumos_from_d435",
    )
    second = audit_handeye_calibration(
        {
            "T_flange_from_lumos": np.eye(4).tolist(),
            "validation": {"reprojection_rmse_px": 0.3, "position_rmse_m": 0.004},
        },
        "T_flange_from_lumos",
    )

    with pytest.raises(InvalidDataError, match="directions"):
        DualCameraCalibrationBundle.from_audits(
            d435=d435,
            lumos=lumos,
            d435_to_lumos_audit=second,
            lumos_to_flange_audit=first,
        )
