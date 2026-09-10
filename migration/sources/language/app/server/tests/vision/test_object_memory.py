from __future__ import annotations

import numpy as np
import pytest

from vision.object_memory import ObjectMemory, ObjectMemoryConfig
from vision.types import FrameStamp, InvalidDataError, PoseEstimate, TrackState


def track(
    track_id,
    *,
    label="cup",
    timestamp_ns=100,
    variance=1e-4,
    hits=3,
    confirmed=True,
    calibration_id="sha256:a",
    frame="robot_base",
):
    pose = PoseEstimate(
        xyz_m=np.array([track_id * 0.01, 0.0, 0.4]),
        covariance_m2=np.eye(3) * variance,
        frame=frame,
        stamp=FrameStamp("lumos+d435", track_id, timestamp_ns),
        calibration_id=calibration_id,
    )
    return TrackState(
        track_id=track_id,
        label=label,
        pose=pose,
        velocity_mps=np.zeros(3),
        hits=hits,
        misses=0,
        confirmed=confirmed,
        last_seen_ns=timestamp_ns,
    )


def config(max_objects=128):
    return ObjectMemoryConfig(
        max_age_ns=300_000_000,
        max_position_std_m=0.025,
        min_hits=3,
        max_objects=max_objects,
    )


def test_stable_selection_excludes_stale_uncertain_tentative_and_low_hit_tracks():
    memory = ObjectMemory(config())
    memory.ingest(
        [
            track(2),
            track(3, variance=0.04**2),
            track(4, confirmed=False),
            track(5, hits=2),
        ],
        now_ns=100,
    )
    assert [item.track_id for item in memory.select_stable("cup", 200)] == [2]
    assert memory.select_stable("cup", 300_000_101) == ()


def test_stable_selection_is_sorted_by_uncertainty_then_track_id():
    memory = ObjectMemory(config())
    memory.ingest(
        [track(7, variance=2e-4), track(3, variance=1e-4), track(2, variance=1e-4)],
        now_ns=100,
    )
    assert [item.track_id for item in memory.select_stable("cup", 101)] == [2, 3, 7]


def test_get_returns_fresh_track_and_none_after_expiry():
    memory = ObjectMemory(config())
    memory.ingest([track(2)], now_ns=100)
    assert memory.get(999, 100) is None
    assert memory.get(2, 300_000_100).track_id == 2
    assert memory.get(2, 300_000_101) is None


def test_calibration_change_invalidates_robot_space_memory():
    memory = ObjectMemory(config())
    memory.ingest([track(2, calibration_id="sha256:a")], now_ns=100)
    memory.set_calibration("sha256:b")
    assert memory.get(2, 101) is None
    memory.ingest([track(3, calibration_id="sha256:b")], now_ns=101)
    assert memory.get(3, 101).track_id == 3


def test_ingest_rejects_wrong_frame_future_stamp_and_implicit_calibration_change():
    memory = ObjectMemory(config())
    with pytest.raises(InvalidDataError):
        memory.ingest([track(1, frame="lumos")], now_ns=100)
    with pytest.raises(InvalidDataError):
        memory.ingest([track(1, timestamp_ns=101)], now_ns=100)
    memory.ingest([track(1, calibration_id="sha256:a")], now_ns=100)
    with pytest.raises(InvalidDataError):
        memory.ingest([track(2, calibration_id="sha256:b")], now_ns=101)


def test_memory_is_bounded_by_newest_timestamp_then_track_id():
    memory = ObjectMemory(config(max_objects=2))
    memory.ingest(
        [
            track(1, timestamp_ns=100),
            track(2, timestamp_ns=200),
            track(3, timestamp_ns=200),
        ],
        now_ns=200,
    )
    assert memory.get(1, 200) is None
    assert memory.get(2, 200).track_id == 2
    assert memory.get(3, 200).track_id == 3


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_age_ns": -1, "max_position_std_m": 0.1, "min_hits": 1},
        {"max_age_ns": 1, "max_position_std_m": 0.0, "min_hits": 1},
        {"max_age_ns": 1, "max_position_std_m": 0.1, "min_hits": 0},
        {"max_age_ns": 1, "max_position_std_m": 0.1, "min_hits": 1, "max_objects": 0},
    ],
)
def test_memory_config_is_validated(kwargs):
    with pytest.raises(InvalidDataError):
        ObjectMemoryConfig(**kwargs)
