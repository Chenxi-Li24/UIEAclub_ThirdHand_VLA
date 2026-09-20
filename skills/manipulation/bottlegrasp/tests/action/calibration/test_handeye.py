import json
from dataclasses import replace

import numpy as np
import pytest

from thirdhand_va.common.contracts import (
    GraspPoseCamera,
    MaskCandidate,
    VisionDecision,
)
from thirdhand_va.action.calibration.handeye import (
    ArmState,
    HandEyeCalibration,
    build_base_grasp_preview,
    rpy_xyz_transform,
)


def _decision() -> VisionDecision:
    mask = np.ones((4, 4), dtype=bool)
    target = MaskCandidate(4, "bottle", 0.9, (0, 0, 4, 4), mask, True)
    pose = GraspPoseCamera(
        point_m=(0.1, 0.0, 0.5),
        axis=(0.0, 1.0, 0.0),
        approach=(1.0, 0.0, 0.0),
        width_m=0.06,
        position_std_m=(0.001, 0.001, 0.001),
        valid_points=100,
        depth_valid_ratio=0.9,
        height_m=0.20,
    )
    return VisionDecision("ready", 7, target, pose, stable_hits=5, candidates=(target,))


def _calibration(*, physically_validated: bool = False) -> HandEyeCalibration:
    return HandEyeCalibration(
        t_flange_camera=np.eye(4),
        content_id="sha256:" + "a" * 64,
        camera_serial="camera",
        registration_id="registration",
        camera_mount_id="mount-1",
        robot_state_semantics="T_base_flange",
        extrinsic_semantics="T_flange_camera",
        pose_semantics_compatible=True,
        numerically_validated=True,
        physically_validated=physically_validated,
        approved_for_bottle_grasp=physically_validated,
    )


def _evidence_kwargs() -> dict:
    return {
        "vision_config_id": "sha256:" + "b" * 64,
        "model_provenance": {
            "grounding_revision": "a" * 40,
            "grounding_weights_sha256": "sha256:" + "c" * 64,
            "sam_revision": "b" * 40,
            "sam_weights_sha256": "sha256:" + "d" * 64,
        },
    }


def test_startouch_rpy_uses_rz_ry_rx_order() -> None:
    transform = rpy_xyz_transform([1, 2, 3], [0, 0, np.pi / 2])

    assert np.allclose(transform @ [1, 0, 0, 1], [1, 3, 3, 1])


def test_preview_transforms_camera_point_and_fails_closed_before_physical_gate() -> None:
    state = ArmState((0.4, 0.1, 0.2), (0, 0, 0), True, 1_000_000_000)

    preview = build_base_grasp_preview(
        _decision(), _calibration(), state,
        observed_at_ms=1234, now_monotonic_ns=1_100_000_000,
        **_evidence_kwargs(),
    )

    assert preview is not None
    assert np.allclose(preview["surface_xyz_m"], [0.5, 0.1, 0.7])
    assert np.allclose(preview["grasp_xyz_m"], [0.53, 0.1, 0.7])
    assert np.allclose(preview["pregrasp_xyz_m"], [0.43, 0.1, 0.7])
    assert preview["approach_base"] == [1.0, 0.0, 0.0]
    assert preview["center_advance_m"] == 0.03
    assert preview["allowed"] is False
    assert "handeye_physical_validation_pending" in preview["blockers"]
    assert preview["preview_id"].startswith("sha256:")
    assert preview["object_height_m"] == 0.20
    assert preview["grasp_lumos_px"] == [1.5, 1.5]


def test_preview_can_only_allow_fresh_stationary_state_and_activated_calibration() -> None:
    state = ArmState((0, 0, 0), (0, 0, 0), True, 2_000_000_000)

    preview = build_base_grasp_preview(
        _decision(), _calibration(physically_validated=True), state,
        observed_at_ms=1234, now_monotonic_ns=2_050_000_000,
        **_evidence_kwargs(),
    )

    assert preview is not None
    assert preview["allowed"] is True
    assert preview["blockers"] == []


def test_preview_rejects_geometry_checked_on_a_different_insertion_axis() -> None:
    decision = _decision()
    decision = replace(
        decision,
        pose=replace(decision.pose, approach=(0.0, 0.0, 1.0)),
    )
    state = ArmState((0, 0, 0), (0, 0, 0), True, 2_000_000_000)

    preview = build_base_grasp_preview(
        decision, _calibration(physically_validated=True), state,
        observed_at_ms=1234, now_monotonic_ns=2_050_000_000,
        **_evidence_kwargs(),
    )

    assert preview is not None and preview["allowed"] is False
    assert "approach_corridor_axis_mismatch" in preview["blockers"]


def test_preview_rejects_frame_captured_before_arm_settled() -> None:
    state = ArmState(
        (0, 0, 0), (0, 0, 0), True, 2_000_000_000, 1_900_000_000
    )

    stale_frame = build_base_grasp_preview(
        _decision(), _calibration(physically_validated=True), state,
        observed_at_ms=1234,
        now_monotonic_ns=2_050_000_000,
        frame_monotonic_ns=2_100_000_000,
        **_evidence_kwargs(),
    )
    fresh_frame = build_base_grasp_preview(
        _decision(), _calibration(physically_validated=True), state,
        observed_at_ms=1235,
        now_monotonic_ns=2_050_000_000,
        frame_monotonic_ns=2_250_000_000,
        **_evidence_kwargs(),
    )

    assert stale_frame is not None and stale_frame["allowed"] is False
    assert "frame_precedes_stationary_settle" in stale_frame["blockers"]
    assert fresh_frame is not None and fresh_frame["allowed"] is True


def test_calibration_loader_honors_all_activation_gates(tmp_path) -> None:
    payload = {
        "schema": "thirdhand-handeye-calibration-v3",
        "robot_state_semantics": "T_base_flange",
        "extrinsic_semantics": "T_flange_camera",
        "T_flange_camera": {"matrix_4x4": np.eye(4).tolist()},
        "camera": {
            "camera_serial": "serial",
            "registration_id": "registration",
            "camera_mount_id": "mount-1",
        },
        "numerically_validated": True,
        "camera_mount_id_activation": False,
        "activated_camera_mount_id": None,
        "approved_for_bottle_grasp": False,
        "physical_validation": {
            "status": "pending", "measured_error_m": None,
            "required_3d_point_or_grasp_error_m_max": 0.01,
        },
    }
    path = tmp_path / "calibration.json"
    path.write_text(json.dumps(payload))

    calibration = HandEyeCalibration.load(path)

    assert calibration.numerically_validated is True
    assert calibration.pose_semantics_compatible is True
    assert calibration.physically_validated is False
    assert calibration.approved_for_bottle_grasp is False


def test_loader_rejects_unknown_schema_or_policy_relaxed_artifacts(tmp_path) -> None:
    payload = {
        "T_flange_camera": {"matrix_4x4": np.eye(4).tolist()},
        "camera": {"camera_serial": "serial"},
        "numerically_validated": True,
        "camera_mount_id_activation": False,
        "approved_for_bottle_grasp": False,
        "physical_validation": {"status": "pending"},
    }
    path = tmp_path / "legacy.json"
    path.write_text(json.dumps(payload))

    with pytest.raises(Exception, match="schema"):
        HandEyeCalibration.load(path)

    payload = {
        "schema": "thirdhand-handeye-calibration-v3",
        "robot_state_semantics": "T_base_flange",
        "extrinsic_semantics": "T_flange_camera",
        "T_flange_camera": {"matrix_4x4": np.eye(4).tolist()},
        "camera": {
            "camera_serial": "serial",
            "registration_id": "registration",
            "camera_mount_id": "mount-1",
        },
        "numerically_validated": True,
        "camera_mount_id_activation": True,
        "activated_camera_mount_id": "mount-1",
        "approved_for_bottle_grasp": True,
        "physical_validation": {
            "status": "passed",
            "measured_error_m": 0.5,
            "required_3d_point_or_grasp_error_m_max": 1.0,
        },
    }
    path.write_text(json.dumps(payload))

    calibration = HandEyeCalibration.load(path)
    assert calibration.physically_validated is False
    assert calibration.approved_for_bottle_grasp is False


def test_v2_tool_tcp_artifact_is_diagnostic_only(tmp_path) -> None:
    payload = {
        "schema": "thirdhand-handeye-calibration-v2",
        "T_tool_camera": {"matrix_4x4": np.eye(4).tolist()},
        "camera": {
            "camera_serial": "serial",
            "registration_id": "registration",
            "camera_mount_id": "mount-1",
        },
        "tcp_semantics": "configured_tool_tcp",
        "numerically_validated": True,
        "camera_mount_id_activation": True,
        "activated_camera_mount_id": "mount-1",
        "approved_for_bottle_grasp": True,
        "physical_validation": {
            "status": "passed",
            "measured_error_m": 0.001,
            "required_3d_point_or_grasp_error_m_max": 0.01,
        },
    }
    path = tmp_path / "legacy-v2.json"
    path.write_text(json.dumps(payload))

    calibration = HandEyeCalibration.load(path)

    assert calibration.pose_semantics_compatible is False
    assert calibration.approved_for_bottle_grasp is False


def test_known_flange_camera_chain_uses_explicit_matrix_order() -> None:
    t_flange_camera = np.eye(4)
    t_flange_camera[:3, 3] = [0.1, 0.0, 0.0]
    calibration = replace(_calibration(physically_validated=True), t_flange_camera=t_flange_camera)
    state = ArmState((1.0, 2.0, 3.0), (0.0, 0.0, np.pi / 2), True, 1_000)

    preview = build_base_grasp_preview(
        _decision(), calibration, state,
        observed_at_ms=1234, now_monotonic_ns=1_000,
        **_evidence_kwargs(),
    )

    assert preview is not None
    # T_base_camera = T_base_flange @ T_flange_camera.  The flange +X offset
    # rotates into base +Y at yaw=90 degrees.
    assert np.allclose(preview["surface_xyz_m"], [1.0, 2.2, 3.5])
