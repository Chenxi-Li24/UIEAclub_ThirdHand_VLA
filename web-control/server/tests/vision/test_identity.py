from __future__ import annotations

import numpy as np
import pytest

from vision.identity import (
    IdentityObservation,
    IdentityStatus,
    PersistentIdentityConfig,
    PersistentIdentityMemory,
)
from vision.types import FrameStamp, InvalidDataError, PoseEstimate


CALIBRATION_ID = "sha256:identity-test"


def config(**overrides):
    values = {
        "max_cosine_distance": 0.40,
        "ambiguity_margin": 0.03,
        "appearance_weight": 0.80,
        "position_weight": 0.20,
        "max_position_distance_m": 0.20,
        "position_gate_max_age_ns": 500_000_000,
        "occluded_after_ns": 200_000_000,
        "inactive_after_ns": 1_000_000_000,
        "min_confirmed_hits": 2,
        "min_memory_confidence": 0.80,
        "min_memory_visibility": 0.50,
        "work_bank_size": 2,
        "stable_bank_size": 2,
        "max_identities": 8,
    }
    values.update(overrides)
    return PersistentIdentityConfig(**values)


def pose(xyz, timestamp_ns, calibration_id=CALIBRATION_ID):
    return PoseEstimate(
        xyz_m=np.asarray(xyz, dtype=float),
        covariance_m2=np.eye(3) * 1e-4,
        frame="robot_base",
        stamp=FrameStamp("lumos+d435", timestamp_ns // 10_000_000, timestamp_ns),
        calibration_id=calibration_id,
    )


def observation(
    observation_id,
    descriptor,
    timestamp_ns,
    *,
    label="cup",
    confidence=0.95,
    visibility=0.90,
    xyz=None,
    calibration_id=CALIBRATION_ID,
):
    return IdentityObservation(
        observation_id=observation_id,
        label=label,
        confidence=confidence,
        visibility=visibility,
        descriptor=np.asarray(descriptor, dtype=float),
        stamp=FrameStamp("lumos", timestamp_ns // 10_000_000, timestamp_ns),
        pose=None if xyz is None else pose(xyz, timestamp_ns, calibration_id),
    )


def test_identity_reappears_with_same_id_after_inactive_gap():
    memory = PersistentIdentityMemory(config(min_confirmed_hits=1))
    first = memory.update([observation(1, [1, 0, 0], 0)], 0)
    assert first.assignments[0].identity_id == 1
    missing = memory.update([], 1_200_000_000)
    assert missing.snapshots[0].status is IdentityStatus.INACTIVE

    returned = memory.update(
        [observation(2, [0.99, 0.01, 0], 1_500_000_000)],
        1_500_000_000,
    )
    assert returned.assignments[0].identity_id == 1
    assert returned.assignments[0].status is IdentityStatus.CONFIRMED


def test_equal_candidates_are_ambiguous_without_forced_id_or_memory_mutation():
    memory = PersistentIdentityMemory(config(min_confirmed_hits=1))
    seeded = memory.update(
        [observation(1, [1, 0, 0], 0), observation(2, [0, 1, 0], 0)],
        0,
    )
    before = {
        item.identity_id: (item.hits, item.work_prototype_count, item.stable_prototype_count)
        for item in seeded.snapshots
    }

    result = memory.update([observation(3, [1, 1, 0], 100_000_000)], 100_000_000)

    assignment = result.assignments[0]
    assert assignment.identity_id is None
    assert assignment.status is IdentityStatus.AMBIGUOUS
    assert assignment.reason == "appearance_candidates_within_margin"
    after = {
        item.identity_id: (item.hits, item.work_prototype_count, item.stable_prototype_count)
        for item in result.snapshots
    }
    assert after == before


def test_global_assignment_keeps_two_similar_instances_one_to_one():
    memory = PersistentIdentityMemory(config(min_confirmed_hits=1))
    memory.update(
        [observation(1, [1.0, 0.0, 0.0], 0), observation(2, [0.0, 1.0, 0.0], 0)],
        0,
    )
    result = memory.update(
        [
            observation(3, [0.05, 0.95, 0.0], 100_000_000),
            observation(4, [0.95, 0.05, 0.0], 100_000_000),
        ],
        100_000_000,
    )
    by_observation = {item.observation_id: item.identity_id for item in result.assignments}
    assert by_observation == {3: 2, 4: 1}


def test_class_gate_never_reuses_identity_across_labels():
    memory = PersistentIdentityMemory(config(min_confirmed_hits=1))
    memory.update([observation(1, [1, 0, 0], 0, label="cup")], 0)
    result = memory.update(
        [observation(2, [1, 0, 0], 100_000_000, label="bottle")],
        100_000_000,
    )
    assert result.assignments[0].identity_id == 2
    assert {item.label for item in result.snapshots} == {"cup", "bottle"}


def test_short_gap_3d_jump_is_rejected_and_creates_a_new_identity():
    memory = PersistentIdentityMemory(config(min_confirmed_hits=1))
    memory.update([observation(1, [1, 0, 0], 0, xyz=[0.0, 0.0, 0.5])], 0)
    result = memory.update(
        [observation(2, [1, 0, 0], 100_000_000, xyz=[0.5, 0.0, 0.5])],
        100_000_000,
    )
    assert result.assignments[0].identity_id == 2


def test_long_gap_match_is_appearance_led_even_when_object_moved():
    memory = PersistentIdentityMemory(config(min_confirmed_hits=1))
    memory.update([observation(1, [1, 0, 0], 0, xyz=[0.0, 0.0, 0.5])], 0)
    result = memory.update(
        [observation(2, [1, 0.01, 0], 600_000_000, xyz=[0.5, 0.0, 0.5])],
        600_000_000,
    )
    assert result.assignments[0].identity_id == 1


def test_missing_pose_preserves_identity_but_snapshot_is_not_actionable():
    memory = PersistentIdentityMemory(config(min_confirmed_hits=1))
    memory.update([observation(1, [1, 0, 0], 0, xyz=[0.0, 0.0, 0.5])], 0)
    result = memory.update([observation(2, [1, 0.01, 0], 100_000_000)], 100_000_000)
    assert result.assignments[0].identity_id == 1
    assert result.snapshots[0].pose is None
    assert not result.snapshots[0].actionable


def test_low_quality_match_does_not_update_prototype_banks():
    memory = PersistentIdentityMemory(config(min_confirmed_hits=1))
    seeded = memory.update([observation(1, [1, 0, 0], 0)], 0).snapshots[0]
    result = memory.update(
        [observation(2, [0.99, 0.01, 0], 100_000_000, confidence=0.50)],
        100_000_000,
    ).snapshots[0]
    assert result.hits == seeded.hits + 1
    assert result.work_prototype_count == seeded.work_prototype_count
    assert result.stable_prototype_count == seeded.stable_prototype_count


def test_prototype_banks_are_bounded_after_many_views():
    memory = PersistentIdentityMemory(config(min_confirmed_hits=1, work_bank_size=2, stable_bank_size=2))
    descriptors = ([1.0, 0.0, 0.0], [0.99, 0.1, 0.0], [0.98, 0.2, 0.0], [0.97, 0.25, 0.0])
    for index, descriptor in enumerate(descriptors):
        memory.update(
            [observation(index + 1, descriptor, index * 100_000_000)],
            index * 100_000_000,
        )
    snapshot = memory.snapshots(400_000_000)[0]
    assert snapshot.work_prototype_count == 2
    assert snapshot.stable_prototype_count == 2


def test_capacity_evicts_oldest_inactive_identity_first():
    memory = PersistentIdentityMemory(
        config(
            min_confirmed_hits=1,
            occluded_after_ns=25,
            inactive_after_ns=50,
            max_identities=2,
        )
    )
    memory.update([observation(1, [1, 0, 0], 0)], 0)
    memory.update([observation(2, [0, 1, 0], 10, label="bottle")], 10)
    result = memory.update([observation(3, [0, 0, 1], 100, label="box")], 100)
    assert [item.identity_id for item in result.snapshots] == [2, 3]


def test_calibration_change_drops_robot_pose_but_keeps_appearance_identity():
    memory = PersistentIdentityMemory(config(min_confirmed_hits=1))
    memory.update([observation(1, [1, 0, 0], 0, xyz=[0.0, 0.0, 0.5])], 0)
    memory.set_calibration("sha256:new-calibration")
    snapshot = memory.snapshots(0)[0]
    assert snapshot.pose is None
    result = memory.update(
        [
            observation(
                2,
                [0.99, 0.01, 0],
                100_000_000,
                xyz=[0.2, 0.0, 0.5],
                calibration_id="sha256:new-calibration",
            )
        ],
        100_000_000,
    )
    assert result.assignments[0].identity_id == 1


def test_observation_normalizes_and_freezes_descriptor():
    item = observation(1, [3, 4, 0], 0)
    np.testing.assert_allclose(item.descriptor, [0.6, 0.8, 0.0])
    assert not item.descriptor.flags.writeable


@pytest.mark.parametrize(
    "descriptor",
    [[], [0, 0, 0], [1, np.nan, 0], [[1, 0], [0, 1]]],
)
def test_observation_rejects_invalid_descriptors(descriptor):
    with pytest.raises(InvalidDataError):
        observation(1, descriptor, 0)


def test_update_rejects_dimension_change_duplicate_ids_future_stamps_and_time_regression():
    memory = PersistentIdentityMemory(config())
    memory.update([observation(1, [1, 0, 0], 0)], 0)
    with pytest.raises(InvalidDataError):
        memory.update([observation(2, [1, 0], 10)], 10)
    duplicate = observation(3, [1, 0, 0], 20)
    with pytest.raises(InvalidDataError):
        memory.update([duplicate, duplicate], 20)
    with pytest.raises(InvalidDataError):
        memory.update([observation(4, [1, 0, 0], 31)], 30)
    memory.update([], 40)
    with pytest.raises(InvalidDataError):
        memory.update([], 39)


@pytest.mark.parametrize(
    "overrides",
    [
        {"max_cosine_distance": 0.0},
        {"ambiguity_margin": -0.1},
        {"appearance_weight": 0.0, "position_weight": 0.0},
        {"max_position_distance_m": 0.0},
        {"position_gate_max_age_ns": -1},
        {"inactive_after_ns": 10, "occluded_after_ns": 11},
        {"min_confirmed_hits": 0},
        {"min_memory_confidence": 1.1},
        {"work_bank_size": 0},
        {"stable_bank_size": 0},
        {"max_identities": 0},
    ],
)
def test_identity_config_rejects_unsafe_values(overrides):
    with pytest.raises(InvalidDataError):
        config(**overrides)
