from __future__ import annotations

import numpy as np

from vision.active_view_types import (
    CoarseTargetEstimate,
    DepthQuality,
    ObservationMoveProposal,
    ObservationPose,
    TablePlane,
)
from vision.types import InvalidDataError
from vision.types import FrameStamp


EVIDENCE_ID = "sha256:" + "a" * 64


def test_coarse_proposal_copies_and_freezes_joint_target() -> None:
    joints = np.arange(6, dtype=float)

    proposal = ObservationMoveProposal.coarse(
        identity_id=4,
        source_stamp=FrameStamp("lumos_rgb", 7, 100),
        expires_ns=200,
        target_pose_id="table_left",
        joints_deg=joints,
        evidence_ids=(EVIDENCE_ID,),
    )
    joints[:] = 99.0

    assert proposal.kind == "coarse_pose"
    assert proposal.joints_deg is not None
    assert proposal.joints_deg.tolist() == [0.0, 1.0, 2.0, 3.0, 4.0, 5.0]
    assert proposal.joints_deg.flags.writeable is False
    assert proposal.delta_base_m is None
    assert proposal.reasons == ()


def test_table_plane_normal_is_normalized_copied_and_frozen() -> None:
    normal = np.array([0.0, 0.0, 2.0])

    table = TablePlane(
        normal_base=normal,
        offset_m=-0.02,
        position_rmse_m=0.004,
        calibration_id=EVIDENCE_ID,
        validated=True,
    )
    normal[:] = 7.0

    np.testing.assert_allclose(table.normal_base, [0.0, 0.0, 1.0])
    assert table.normal_base.flags.writeable is False
    assert table.offset_m == -0.01
    assert table.position_rmse_m == 0.004


def test_coarse_target_estimate_owns_immutable_uncertainty_arrays() -> None:
    center = np.array([0.2, -0.1])
    covariance = np.diag([0.001, 0.002])
    samples = np.array([[0.19, -0.1], [0.2, -0.11], [0.21, -0.09]])

    estimate = CoarseTargetEstimate(
        identity_id=7,
        center_xy_m=center,
        covariance_xy_m2=covariance,
        samples_xy_m=samples,
        source_stamp=FrameStamp("lumos_rgb", 8, 1_000),
        calibration_id=EVIDENCE_ID,
    )
    center[:] = 9.0
    covariance[:] = 9.0
    samples[:] = 9.0

    np.testing.assert_allclose(estimate.center_xy_m, [0.2, -0.1])
    np.testing.assert_allclose(estimate.covariance_xy_m2, np.diag([0.001, 0.002]))
    assert estimate.samples_xy_m.shape == (3, 2)
    assert estimate.center_xy_m.flags.writeable is False
    assert estimate.covariance_xy_m2.flags.writeable is False
    assert estimate.samples_xy_m.flags.writeable is False


def test_observation_pose_freezes_validated_catalog_geometry() -> None:
    joints = np.arange(6, dtype=float)
    transform = np.eye(4)
    polygon = np.array([[-0.2, -0.1], [0.2, -0.1], [0.2, 0.1], [-0.2, 0.1]])

    pose = ObservationPose(
        pose_id="table_center",
        joints_deg=joints,
        t_base_from_flange=transform,
        coverage_polygon_xy_m=polygon,
        allowed_start_pose_ids=("home",),
        path_validation_id=EVIDENCE_ID,
        calibration_id=EVIDENCE_ID,
    )
    joints[:] = 9.0
    transform[:] = 9.0
    polygon[:] = 9.0

    assert pose.joints_deg.tolist() == list(range(6))
    np.testing.assert_allclose(pose.t_base_from_flange, np.eye(4))
    assert pose.coverage_polygon_xy_m.shape == (4, 2)
    assert pose.joints_deg.flags.writeable is False
    assert pose.t_base_from_flange.flags.writeable is False
    assert pose.coverage_polygon_xy_m.flags.writeable is False


def test_observation_pose_rejects_non_convex_coverage() -> None:
    with np.testing.assert_raises_regex(InvalidDataError, "convex"):
        ObservationPose(
            pose_id="unsafe",
            joints_deg=np.zeros(6),
            t_base_from_flange=np.eye(4),
            coverage_polygon_xy_m=np.array(
                [[0.0, 0.0], [1.0, 0.0], [0.2, 0.2], [1.0, 1.0], [0.0, 1.0]]
            ),
            allowed_start_pose_ids=("home",),
            path_validation_id=EVIDENCE_ID,
            calibration_id=EVIDENCE_ID,
        )


def test_depth_quality_copies_centers_and_keeps_reasons_consistent() -> None:
    center_d435 = np.array([0.01, -0.02, 0.4])
    center_base = np.array([0.2, 0.1, 0.03])
    mad = np.array([0.001, 0.002, 0.003])

    quality = DepthQuality(
        valid_points=100,
        central_fraction=0.8,
        center_d435_m=center_d435,
        center_base_m=center_base,
        mad_m=mad,
        acceptable=True,
        reasons=(),
    )
    center_d435[:] = 9.0
    center_base[:] = 9.0
    mad[:] = 9.0

    np.testing.assert_allclose(quality.center_d435_m, [0.01, -0.02, 0.4])
    np.testing.assert_allclose(quality.center_base_m, [0.2, 0.1, 0.03])
    np.testing.assert_allclose(quality.mad_m, [0.001, 0.002, 0.003])
    assert quality.center_d435_m.flags.writeable is False
    assert quality.acceptable is True
    assert quality.reasons == ()


def test_rejected_and_refinement_proposals_have_disjoint_payloads() -> None:
    stamp = FrameStamp("lumos_rgb", 9, 1_000)
    rejected = ObservationMoveProposal.rejected(
        identity_id=3,
        source_stamp=stamp,
        reasons=("target_not_covered",),
        evidence_ids=(),
    )
    delta = np.array([0.01, -0.02, 0.0])
    rotation = np.zeros(3)
    refined = ObservationMoveProposal.refine(
        identity_id=3,
        source_stamp=stamp,
        expires_ns=2_000,
        delta_base_m=delta,
        rotation_delta_rad=rotation,
        evidence_ids=(EVIDENCE_ID,),
    )
    delta[:] = 9.0
    rotation[:] = 9.0

    assert rejected.kind == "none"
    assert rejected.joints_deg is None
    assert rejected.reasons == ("target_not_covered",)
    assert refined.kind == "refine_delta"
    np.testing.assert_allclose(refined.delta_base_m, [0.01, -0.02, 0.0])
    np.testing.assert_allclose(refined.rotation_delta_rad, np.zeros(3))
    assert refined.delta_base_m.flags.writeable is False
    assert refined.joints_deg is None
    assert refined.target_pose_id is None


def test_active_view_contracts_are_public_vision_interfaces() -> None:
    import vision

    expected = {
        "CoarseTargetEstimate",
        "DepthQuality",
        "ObservationMoveProposal",
        "ObservationPose",
        "TablePlane",
    }
    assert expected <= set(vision.__all__)
    assert vision.TablePlane is TablePlane
