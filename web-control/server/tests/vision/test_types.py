from __future__ import annotations

import json

import numpy as np
import pytest

from vision.types import (
    CalibrationRef,
    DryRunReport,
    FrameStamp,
    InvalidDataError,
    PoseEstimate,
    SafetyDecision,
    TrackObservation,
    TrackState,
)


def make_pose() -> PoseEstimate:
    return PoseEstimate(
        xyz_m=np.array([0.1, 0.2, 0.3]),
        covariance_m2=np.eye(3) * 1e-4,
        frame="robot_base",
        stamp=FrameStamp("lumos+d435", 7, 100),
        calibration_id="sha256:abc",
    )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"source": "", "frame_id": 0, "monotonic_ns": 0},
        {"source": "lumos", "frame_id": -1, "monotonic_ns": 0},
        {"source": "lumos", "frame_id": 0, "monotonic_ns": -1},
    ],
)
def test_frame_stamp_rejects_invalid_provenance(kwargs):
    with pytest.raises(InvalidDataError):
        FrameStamp(**kwargs)


def test_pose_estimate_copies_and_freezes_arrays():
    xyz = np.array([0.1, 0.2, 0.3])
    covariance = np.eye(3) * 1e-4
    pose = PoseEstimate(
        xyz_m=xyz,
        covariance_m2=covariance,
        frame="robot_base",
        stamp=FrameStamp("lumos+d435", 7, 100),
        calibration_id="sha256:abc",
    )
    xyz[0] = 99.0
    covariance[0, 0] = 99.0
    np.testing.assert_allclose(pose.xyz_m, [0.1, 0.2, 0.3])
    np.testing.assert_allclose(np.diag(pose.covariance_m2), [1e-4] * 3)
    assert not pose.xyz_m.flags.writeable
    assert not pose.covariance_m2.flags.writeable


@pytest.mark.parametrize(
    "xyz,covariance",
    [
        ([0.0, 0.0], np.eye(3)),
        ([0.0, np.nan, 0.0], np.eye(3)),
        ([0.0, 0.0, 0.0], np.eye(2)),
        ([0.0, 0.0, 0.0], np.diag([1.0, -1.0, 1.0])),
        ([0.0, 0.0, 0.0], np.array([[1.0, 0.2, 0.0], [0.1, 1.0, 0.0], [0.0, 0.0, 1.0]])),
    ],
)
def test_pose_rejects_bad_xyz_or_covariance(xyz, covariance):
    with pytest.raises(InvalidDataError):
        PoseEstimate(
            xyz_m=np.asarray(xyz),
            covariance_m2=np.asarray(covariance),
            frame="robot_base",
            stamp=FrameStamp("lumos+d435", 7, 100),
            calibration_id="sha256:abc",
        )


def test_calibration_ref_requires_content_address_and_validation_metrics():
    valid = CalibrationRef(
        calibration_id="sha256:012345",
        validated=True,
        reprojection_rmse_px=0.42,
        validation_notes=("independent holdout",),
    )
    assert valid.validated
    with pytest.raises(InvalidDataError):
        CalibrationRef("calibration-latest", True, 0.42)
    with pytest.raises(InvalidDataError):
        CalibrationRef("sha256:012345", True, None)


def test_track_contracts_reject_bad_confidence_and_time():
    with pytest.raises(InvalidDataError):
        TrackObservation("cup", 1.1, make_pose())
    with pytest.raises(InvalidDataError):
        TrackState(
            track_id=1,
            label="cup",
            pose=make_pose(),
            velocity_mps=np.zeros(3),
            hits=1,
            misses=0,
            confirmed=False,
            last_seen_ns=99,
        )


def test_safety_and_dry_run_reports_are_json_serializable():
    decision = SafetyDecision(False, ("target_stale",))
    report = DryRunReport(
        approved=decision.approved,
        reasons=decision.reasons,
        candidate_xyz_m=None,
        score=None,
        target_track_id=8,
        calibration_id="sha256:abc",
    )
    encoded = json.dumps(report.to_dict(), sort_keys=True)
    assert '"approved": false' in encoded
    assert "target_stale" in encoded
