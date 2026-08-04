from __future__ import annotations

import numpy as np
import pytest

from vision.tracking import MultiObjectTracker, TrackerConfig
from vision.types import FrameStamp, InvalidDataError, PoseEstimate, TrackObservation


def observation(xyz, timestamp_ns, label="cup", confidence=0.9, variance=1e-4):
    return TrackObservation(
        label=label,
        confidence=confidence,
        pose=PoseEstimate(
            xyz_m=np.asarray(xyz, dtype=float),
            covariance_m2=np.eye(3) * variance,
            frame="robot_base",
            stamp=FrameStamp("lumos+d435", timestamp_ns // 10_000_000, timestamp_ns),
            calibration_id="sha256:tracking-test",
        ),
    )


def config(min_hits=2):
    return TrackerConfig(
        max_distance_m=0.20,
        max_age_ns=500_000_000,
        min_confirmed_hits=min_hits,
    )


def test_confirmed_track_survives_one_empty_detection_frame():
    tracker = MultiObjectTracker(config())
    first = tracker.update([observation([0.0, 0.0, 1.0], 0)], 0)
    second = tracker.update(
        [observation([0.01, 0.0, 1.0], 100_000_000)], 100_000_000
    )
    third = tracker.update([], 200_000_000)
    assert not first[0].confirmed
    assert second[0].confirmed
    assert third[0].track_id == first[0].track_id
    assert third[0].misses == 1
    np.testing.assert_allclose(third[0].velocity_mps, [0.1, 0.0, 0.0])


def test_track_expires_only_after_configured_age():
    tracker = MultiObjectTracker(config(min_hits=1))
    tracker.update([observation([0.0, 0.0, 1.0], 0)], 0)
    assert len(tracker.update([], 500_000_000)) == 1
    assert tracker.update([], 500_000_001) == ()


def test_hungarian_assignment_is_global_and_ids_do_not_swap():
    tracker = MultiObjectTracker(config(min_hits=1))
    initial = tracker.update(
        [observation([0.00, 0.0, 1.0], 0), observation([0.11, 0.0, 1.0], 0)],
        0,
    )
    assert [track.track_id for track in initial] == [1, 2]
    updated = tracker.update(
        [
            observation([0.10, 0.0, 1.0], 100_000_000),
            observation([0.20, 0.0, 1.0], 100_000_000),
        ],
        100_000_000,
    )
    by_id = {track.track_id: track for track in updated}
    np.testing.assert_allclose(by_id[1].pose.xyz_m, [0.10, 0.0, 1.0])
    np.testing.assert_allclose(by_id[2].pose.xyz_m, [0.20, 0.0, 1.0])


def test_class_gate_creates_new_track_instead_of_cross_class_match():
    tracker = MultiObjectTracker(config(min_hits=1))
    tracker.update([observation([0.0, 0.0, 1.0], 0, label="cup")], 0)
    tracks = tracker.update(
        [observation([0.01, 0.0, 1.0], 100_000_000, label="bottle")],
        100_000_000,
    )
    assert [(track.track_id, track.label) for track in tracks] == [(1, "cup"), (2, "bottle")]
    assert tracks[0].misses == 1


def test_distance_gate_creates_new_track_for_large_jump():
    tracker = MultiObjectTracker(config(min_hits=1))
    tracker.update([observation([0.0, 0.0, 1.0], 0)], 0)
    tracks = tracker.update(
        [observation([0.5, 0.0, 1.0], 100_000_000)], 100_000_000
    )
    assert len(tracks) == 2
    assert tracks[0].misses == 1
    assert tracks[1].hits == 1


def test_update_rejects_time_regression_future_observation_and_mixed_frames():
    tracker = MultiObjectTracker(config())
    tracker.update([], 10)
    with pytest.raises(InvalidDataError):
        tracker.update([], 9)
    with pytest.raises(InvalidDataError):
        tracker.update([observation([0.0, 0.0, 1.0], 20)], 19)
    bad_pose = PoseEstimate(
        xyz_m=np.array([0.0, 0.0, 1.0]),
        covariance_m2=np.eye(3),
        frame="lumos",
        stamp=FrameStamp("lumos", 3, 30),
        calibration_id="sha256:tracking-test",
    )
    with pytest.raises(InvalidDataError):
        tracker.update([TrackObservation("cup", 0.9, bad_pose)], 30)


def test_tracker_rejects_calibration_change_until_reset():
    tracker = MultiObjectTracker(config())
    tracker.update([observation([0.0, 0.0, 1.0], 0)], 0)
    changed = TrackObservation(
        "cup",
        0.9,
        PoseEstimate(
            np.array([0.01, 0.0, 1.0]),
            np.eye(3) * 1e-4,
            "robot_base",
            FrameStamp("lumos+d435", 10, 100_000_000),
            "sha256:changed",
        ),
    )
    with pytest.raises(InvalidDataError):
        tracker.update([changed], 100_000_000)
    tracker.reset()
    tracks = tracker.update([changed], 100_000_000)
    assert tracks[0].track_id == 2


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_distance_m": 0.0, "max_age_ns": 1, "min_confirmed_hits": 1},
        {"max_distance_m": 0.1, "max_age_ns": -1, "min_confirmed_hits": 1},
        {"max_distance_m": 0.1, "max_age_ns": 1, "min_confirmed_hits": 0},
    ],
)
def test_tracker_config_is_validated(kwargs):
    with pytest.raises(InvalidDataError):
        TrackerConfig(**kwargs)
