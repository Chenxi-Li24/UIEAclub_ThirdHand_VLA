from pathlib import Path

import numpy as np

from thirdhand_va.common.config import VisionConfig
from thirdhand_va.common.contracts import (
    GraspPoseCamera,
    MaskCandidate,
    RgbdFrame,
)
from thirdhand_va.vision.tracking.stability import StabilityWindow


def frame(sequence: int, *, stamp_ns: int | None = None) -> RgbdFrame:
    timestamp = sequence * 100_000_000 if stamp_ns is None else stamp_ns
    depth = np.full((10, 10), 0.45, dtype=np.float32)
    xyz = np.zeros((10, 10, 3), dtype=np.float32)
    xyz[..., 2] = depth
    return RgbdFrame(
        sequence=sequence,
        monotonic_ns=timestamp,
        camera_serial="250801DR48FP25002738",
        rgb=np.zeros((10, 10, 3), dtype=np.uint8),
        depth_m=depth,
        xyz_camera_m=xyz,
    )


def candidate(detection_id: int = 1, *, offset: int = 0) -> MaskCandidate:
    mask = np.zeros((10, 10), dtype=bool)
    mask[2:8, 2 + offset : 7 + offset] = True
    return MaskCandidate(
        detection_id=detection_id,
        label="coca-cola plastic bottle",
        score=0.9,
        bbox_xyxy=(2.0 + offset, 2.0, 7.0 + offset, 8.0),
        mask=mask,
        authorized=True,
        reasons=(),
    )


def pose(x: float = 0.08) -> GraspPoseCamera:
    return GraspPoseCamera(
        point_m=(x, 0.0, 0.45),
        axis=(0.0, 1.0, 0.0),
        approach=(0.2, 0.0, 0.98),
        width_m=0.06,
        position_std_m=(0.002, 0.002, 0.003),
        valid_points=500,
        depth_valid_ratio=0.8,
    )


def window() -> StabilityWindow:
    return StabilityWindow(VisionConfig.from_yaml(Path("configs/vision.yaml")))


def test_four_of_five_consistent_observations_become_ready() -> None:
    tracker = window()
    decisions = []
    for sequence in range(1, 5):
        current = frame(sequence)
        decisions.append(
            tracker.update(
                current,
                ((candidate(), pose(0.08 + sequence * 0.0005)),),
                now_ns=current.monotonic_ns + 1_000_000,
            )
        )

    assert [item.status for item in decisions[:3]] == ["uncertain"] * 3
    assert decisions[-1].status == "ready"
    assert decisions[-1].stable_hits == 4


def test_two_authorized_bottles_are_ambiguous() -> None:
    tracker = window()
    current = frame(1)

    decision = tracker.update(
        current,
        ((candidate(1), pose()), (candidate(2, offset=1), pose(0.10))),
        now_ns=current.monotonic_ns + 1_000_000,
    )

    assert decision.status == "uncertain"
    assert "multiple_authorized_targets" in decision.reasons


def test_stale_or_jumping_pose_never_becomes_ready() -> None:
    tracker = window()
    decisions = []
    for sequence, x in enumerate((0.08, 0.081, 0.14, 0.079, 0.08), start=1):
        current = frame(sequence)
        decisions.append(
            tracker.update(
                current,
                ((candidate(), pose(x)),),
                now_ns=current.monotonic_ns + 1_000_000,
            )
        )
    assert all(item.status != "ready" for item in decisions)
    assert "pose_spread_too_large" in decisions[-1].reasons

    stale_frame = frame(6)
    stale = tracker.update(
        stale_frame,
        ((candidate(), pose()),),
        now_ns=stale_frame.monotonic_ns + 2_000_000_000,
    )
    assert stale.status != "ready"
    assert "frame_stale" in stale.reasons


def test_non_monotonic_sequence_is_rejected() -> None:
    tracker = window()
    current = frame(2)
    tracker.update(
        current,
        ((candidate(), pose()),),
        now_ns=current.monotonic_ns,
    )

    decision = tracker.update(
        frame(2),
        ((candidate(), pose()),),
        now_ns=current.monotonic_ns,
    )

    assert decision.status == "rejected"
    assert "frame_not_monotonic" in decision.reasons
