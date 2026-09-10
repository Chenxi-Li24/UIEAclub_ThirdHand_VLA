from __future__ import annotations

import numpy as np

from thirdhand_vision.core.types import CameraCalibrationRef, FrameStamp, PoseEstimate
from thirdhand_vision.identity.memory import (
    IdentityConfig,
    IdentityObservation,
    IdentityStatus,
    PersistentIdentityMemory,
)


def config(**changes) -> IdentityConfig:
    values = {
        "max_cosine_distance": 0.4,
        "ambiguity_margin": 0.03,
        "appearance_weight": 0.8,
        "position_weight": 0.2,
        "max_position_distance_m": 0.2,
        "position_gate_max_age_ns": 500,
        "occluded_after_ns": 300,
        "inactive_after_ns": 1500,
        "min_confirmed_hits": 2,
        "min_memory_confidence": 0.8,
        "min_memory_visibility": 0.5,
        "work_bank_size": 2,
        "stable_bank_size": 2,
        "max_identities": 8,
        "reacquire_confirmed_hits": 2,
        "max_actionable_position_std_m": 0.025,
        "max_actionable_pose_age_ns": 200,
        "min_actionable_pose_hits": 2,
    }
    values.update(changes)
    return IdentityConfig(**values)


def observation(
    observation_id: int,
    descriptor,
    timestamp: int,
    *,
    label: str = "bottle",
    confidence: float = 0.9,
    visibility: float = 0.9,
    x: float | None = None,
) -> IdentityObservation:
    pose = None
    if x is not None:
        pose = PoseEstimate(
            xyz_m=np.array([x, 0.0, 0.5]),
            covariance_m2=np.eye(3) * 1e-6,
            frame="robot_base",
            stamp=FrameStamp("fusion", observation_id, timestamp),
            calibration_id="sha256:cal",
        )
    return IdentityObservation(
        observation_id=observation_id,
        label=label,
        confidence=confidence,
        visibility=visibility,
        descriptor=np.asarray(descriptor, dtype=float),
        stamp=FrameStamp("fusion", observation_id, timestamp),
        pose=pose,
    )


def test_identity_requires_two_hits_before_confirmation_and_action() -> None:
    memory = PersistentIdentityMemory(config())
    memory.set_calibration(CameraCalibrationRef("sha256:cal", True, 0.4))
    first = memory.update([observation(1, [1.0, 0.0], 100, x=0.1)], now_ns=100)
    assert first.assignments[0].status is IdentityStatus.TENTATIVE
    second = memory.update([observation(2, [0.99, 0.01], 150, x=0.101)], now_ns=150)
    assert second.assignments[0].identity_id == first.assignments[0].identity_id
    assert second.assignments[0].status is IdentityStatus.CONFIRMED
    assert second.snapshots[0].actionable


def test_rgb_only_updates_do_not_break_a_recent_rgbd_pose_chain() -> None:
    memory = PersistentIdentityMemory(config(min_confirmed_hits=1))
    memory.set_calibration(CameraCalibrationRef("sha256:cal", True, 0.4))
    first_depth = memory.update([observation(1, [1.0, 0.0], 100, x=0.1)], 100)
    assert not first_depth.snapshots[0].actionable

    rgb_only = memory.update([observation(2, [0.99, 0.01], 125)], 125)
    assert not rgb_only.snapshots[0].actionable

    second_depth = memory.update([observation(3, [0.99, 0.01], 150, x=0.101)], 150)
    assert second_depth.snapshots[0].actionable


def test_category_gate_prevents_cross_class_identity_reuse() -> None:
    memory = PersistentIdentityMemory(config(min_confirmed_hits=1))
    bottle = memory.update([observation(1, [1.0, 0.0], 100)], 100)
    cup = memory.update([observation(2, [1.0, 0.0], 110, label="cup")], 110)
    assert bottle.assignments[0].identity_id != cup.assignments[0].identity_id


def test_ambiguous_identity_is_not_forced() -> None:
    memory = PersistentIdentityMemory(config(min_confirmed_hits=1, ambiguity_margin=0.05))
    seeded = memory.update(
        [
            observation(1, [1.0, 0.0], 100),
            observation(2, [0.98, 0.2], 100),
        ],
        100,
    )
    assert len({item.identity_id for item in seeded.assignments}) == 2
    update = memory.update([observation(3, [0.995, 0.1], 200)], 200)
    assert update.assignments[0].identity_id is None
    assert update.assignments[0].status is IdentityStatus.AMBIGUOUS


def test_low_quality_match_does_not_update_prototype_banks() -> None:
    memory = PersistentIdentityMemory(config(min_confirmed_hits=1))
    initial = memory.update([observation(1, [1.0, 0.0], 100)], 100)
    before = initial.snapshots[0]
    update = memory.update(
        [observation(2, [0.99, 0.01], 150, confidence=0.4)],
        150,
    )
    after = update.snapshots[0]
    assert update.assignments[0].reason == "low_quality_association"
    assert after.work_prototype_count == before.work_prototype_count
    assert after.stable_prototype_count == before.stable_prototype_count


def test_inactive_identity_requires_two_pose_hits_to_reacquire() -> None:
    memory = PersistentIdentityMemory(
        config(
            min_confirmed_hits=1,
            occluded_after_ns=50,
            inactive_after_ns=100,
            reacquire_confirmed_hits=2,
        )
    )
    memory.set_calibration(CameraCalibrationRef("sha256:cal", True, 0.4))
    first = memory.update([observation(1, [1.0, 0.0], 100, x=0.1)], 100)
    identity_id = first.assignments[0].identity_id
    one = memory.update([observation(2, [1.0, 0.0], 250, x=0.1)], 250)
    assert one.assignments[0].identity_id == identity_id
    assert one.assignments[0].status is IdentityStatus.TENTATIVE
    two = memory.update([observation(3, [1.0, 0.0], 275, x=0.1)], 275)
    assert two.assignments[0].status is IdentityStatus.CONFIRMED
