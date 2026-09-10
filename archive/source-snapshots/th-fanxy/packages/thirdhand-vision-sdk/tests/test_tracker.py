from __future__ import annotations

import numpy as np

from thirdhand_vision.core.types import FrameStamp, PoseEstimate
from thirdhand_vision.identity.tracker import (
    MultiObjectTracker,
    TrackObservation,
    TrackerConfig,
)


def tracked_pose(x: float, timestamp: int, frame_id: int) -> PoseEstimate:
    return PoseEstimate(
        xyz_m=np.array([x, 0.0, 0.5]),
        covariance_m2=np.eye(3) * 1e-4,
        frame="robot_base",
        stamp=FrameStamp("fusion", frame_id, timestamp),
        calibration_id="sha256:cal",
    )


def test_tracker_uses_constant_velocity_prediction() -> None:
    tracker = MultiObjectTracker(TrackerConfig(0.2, 2_000_000_000, 2))
    first = tracker.update([TrackObservation("bottle", tracked_pose(0.0, 0, 1))], 0)
    second = tracker.update(
        [TrackObservation("bottle", tracked_pose(0.1, 1_000_000_000, 2))],
        1_000_000_000,
    )
    third = tracker.update(
        [TrackObservation("bottle", tracked_pose(0.2, 2_000_000_000, 3))],
        2_000_000_000,
    )
    assert first[0].track_id == second[0].track_id == third[0].track_id
    np.testing.assert_allclose(third[0].velocity_mps, [0.1, 0.0, 0.0])
    assert third[0].confirmed


def test_tracker_never_reuses_ids_after_reset() -> None:
    tracker = MultiObjectTracker(TrackerConfig(0.2, 100, 1))
    first = tracker.update([TrackObservation("bottle", tracked_pose(0.0, 1, 1))], 1)
    tracker.reset()
    second = tracker.update([TrackObservation("bottle", tracked_pose(0.0, 2, 2))], 2)
    assert second[0].track_id > first[0].track_id
