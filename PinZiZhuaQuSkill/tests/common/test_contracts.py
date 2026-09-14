from dataclasses import FrozenInstanceError

import numpy as np
import pytest

from thirdhand_va.common.contracts import (
    GraspPoseCamera,
    MaskCandidate,
    RgbdFrame,
    TrackedBottle,
    VisionDecision,
)


def test_rgbd_frame_validates_shapes_and_freezes_arrays() -> None:
    rgb = np.zeros((3, 4, 3), dtype=np.uint8)
    depth = np.full((3, 4), 0.5, dtype=np.float32)
    xyz = np.zeros((3, 4, 3), dtype=np.float32)

    frame = RgbdFrame(
        sequence=7,
        monotonic_ns=123,
        camera_serial="250801DR48FP25002738",
        rgb=rgb,
        depth_m=depth,
        xyz_camera_m=xyz,
    )

    assert frame.rgb.shape == (3, 4, 3)
    assert frame.depth_m.shape == (3, 4)
    assert frame.xyz_camera_m.shape == (3, 4, 3)
    assert not frame.rgb.flags.writeable
    assert not frame.depth_m.flags.writeable
    assert not frame.xyz_camera_m.flags.writeable
    with pytest.raises(ValueError):
        frame.depth_m[0, 0] = 1.0
    with pytest.raises(FrozenInstanceError):
        frame.sequence = 8


def test_rgbd_frame_rejects_misaligned_depth() -> None:
    with pytest.raises(ValueError, match="aligned"):
        RgbdFrame(
            sequence=1,
            monotonic_ns=1,
            camera_serial="camera",
            rgb=np.zeros((3, 4, 3), dtype=np.uint8),
            depth_m=np.zeros((2, 4), dtype=np.float32),
            xyz_camera_m=np.zeros((3, 4, 3), dtype=np.float32),
        )


def test_decision_requires_pose_and_target_for_ready_status() -> None:
    candidate = MaskCandidate(
        detection_id=3,
        label="coca-cola bottle",
        score=0.93,
        bbox_xyxy=(1.0, 2.0, 8.0, 9.0),
        mask=np.ones((10, 10), dtype=bool),
        authorized=True,
        reasons=(),
    )
    pose = GraspPoseCamera(
        point_m=(0.1, 0.0, 0.4),
        axis=(0.0, 1.0, 0.0),
        approach=(0.0, 0.0, 1.0),
        width_m=0.06,
        position_std_m=(0.002, 0.002, 0.004),
        valid_points=500,
        depth_valid_ratio=0.8,
    )

    ready = VisionDecision(
        status="ready",
        frame_id=8,
        target=candidate,
        pose=pose,
        reasons=(),
        stable_hits=4,
        window_size=5,
    )
    assert ready.pose is not None
    assert ready.pose.frame == "xvisio_color"

    with pytest.raises(ValueError, match="pose"):
        VisionDecision(
            status="ready",
            frame_id=9,
            target=candidate,
            pose=None,
            reasons=("missing pose",),
            stable_hits=4,
            window_size=5,
        )

    with pytest.raises(ValueError, match="target"):
        VisionDecision(
            status="ready",
            frame_id=10,
            target=None,
            pose=pose,
            reasons=("missing target",),
            stable_hits=4,
            window_size=5,
        )


def test_tracked_bottle_separates_backend_and_user_identity() -> None:
    candidate = MaskCandidate(
        detection_id=17,
        label="bottle",
        score=0.91,
        bbox_xyxy=(1.0, 2.0, 8.0, 9.0),
        mask=np.ones((10, 10), dtype=bool),
        authorized=True,
        descriptor=np.asarray([0.2, 0.8], dtype=np.float32),
    )

    track = TrackedBottle(
        stable_id=2,
        backend_track_id=91,
        state="confirmed",
        candidate=candidate,
        centroid_xy=(4.5, 5.5),
        depth_supported=True,
        blockers=(),
    )

    assert track.stable_id == 2
    assert track.backend_track_id == 91
    assert track.candidate.descriptor is not None
    assert track.candidate.descriptor.flags.writeable is False


def test_decision_carries_request_motion_and_evidence_identity() -> None:
    decision = VisionDecision(
        status="searching",
        frame_id=3,
        target=None,
        pose=None,
        request_id="req-2",
        selected_stable_id=2,
        captured_monotonic_ns=123,
        camera_serial="250801DR48FP25002738",
        registration_id="xvisio-sdk:250801DR48FP25002738",
        motion_epoch=4,
        evidence_id="sha256:abc",
    )

    assert decision.request_id == "req-2"
    assert decision.selected_stable_id == 2
    assert decision.motion_epoch == 4


@pytest.mark.parametrize(
    "status",
    ["searching", "rejected", "uncertain", "unstable"],
)
def test_decision_accepts_closed_status_vocabulary(status: str) -> None:
    decision = VisionDecision(
        status=status,
        frame_id=1,
        target=None,
        pose=None,
        reasons=("not ready",),
        stable_hits=0,
        window_size=5,
    )
    assert decision.status == status
