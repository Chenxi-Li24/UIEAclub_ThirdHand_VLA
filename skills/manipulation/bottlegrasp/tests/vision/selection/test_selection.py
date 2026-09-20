from dataclasses import replace

import numpy as np
import pytest

from thirdhand_va.common.contracts import GraspPoseCamera, MaskCandidate
from thirdhand_va.vision.selection import (
    SelectionRequest,
    SpatialBottleSelector,
    TargetLock,
)


def candidate(detection_id: int, center_x: int, *, width: int = 12) -> MaskCandidate:
    mask = np.zeros((80, 120), dtype=bool)
    left = center_x - width // 2
    mask[10:70, left : left + width] = True
    return MaskCandidate(
        detection_id=detection_id,
        label="bottle",
        score=0.9,
        bbox_xyxy=(left, 10, left + width, 70),
        mask=mask,
        authorized=True,
    )


def pose(x: float) -> GraspPoseCamera:
    return GraspPoseCamera(
        point_m=(x, 0.0, 0.5),
        axis=(0.0, 1.0, 0.0),
        approach=(0.0, 0.0, 1.0),
        width_m=0.06,
        position_std_m=(0.001, 0.001, 0.001),
        valid_points=500,
        depth_valid_ratio=0.9,
    )


def test_three_bottles_left_two_and_right_two_are_middle() -> None:
    items = (candidate(10, 20), candidate(20, 60), candidate(30, 100))
    selector = SpatialBottleSelector(min_horizontal_gap_px=8.0)

    left = selector.select(items, SelectionRequest("left", 2))
    right = selector.select(items, SelectionRequest("right", 2))

    assert left.selected is not None and left.selected.detection_id == 20
    assert right.selected is not None and right.selected.detection_id == 20
    assert [(r.detection_id, r.left_ordinal, r.right_ordinal) for r in left.ranks] == [
        (10, 1, 3), (20, 2, 2), (30, 3, 1)
    ]


def test_four_bottles_left_two_and_right_two_differ() -> None:
    items = tuple(candidate(i, x) for i, x in zip((10, 20, 30, 40), (15, 45, 75, 105)))
    selector = SpatialBottleSelector(min_horizontal_gap_px=8.0)

    left = selector.select(items, SelectionRequest("left", 2))
    right = selector.select(items, SelectionRequest("right", 2))

    assert left.selected is not None and left.selected.detection_id == 20
    assert right.selected is not None and right.selected.detection_id == 30


def test_rejects_invalid_or_out_of_range_ordinal() -> None:
    selector = SpatialBottleSelector(min_horizontal_gap_px=8.0)
    with pytest.raises(ValueError, match="positive"):
        SelectionRequest("left", 0)
    result = selector.select((candidate(1, 30),), SelectionRequest("right", 2))
    assert result.selected is None
    assert result.reasons == ("ordinal_out_of_range",)


def test_rejects_ambiguous_horizontal_order() -> None:
    selector = SpatialBottleSelector(min_horizontal_gap_px=8.0)
    result = selector.select(
        (candidate(1, 50, width=4), candidate(2, 55, width=4)),
        SelectionRequest("left", 1),
    )
    assert result.selected is None
    assert result.reasons == ("horizontal_order_ambiguous",)


def test_lock_follows_target_without_resorting_after_motion() -> None:
    selected = candidate(20, 60)
    lock = TargetLock(
        min_mask_iou=0.15,
        max_center_distance_px=70.0,
        ambiguity_margin=0.05,
        max_point_distance_m=0.05,
    )
    lock.acquire(selected)
    # The locked bottle moves left of its neighbour and receives a new detection id.
    moved_target = replace(candidate(202, 45), mask=np.roll(selected.mask, -15, axis=1))
    neighbour = candidate(303, 90)

    result = lock.match((neighbour, moved_target))

    assert result.selected is not None
    assert result.selected.detection_id == 202
    assert result.ranks == ()


def test_lock_rejects_loss_ambiguity_and_3d_jump() -> None:
    selected = candidate(20, 60)
    lock = TargetLock(0.2, 25.0, 0.05, 0.05)
    lock.acquire(selected)
    assert lock.match((candidate(9, 12),)).reasons == ("target_track_lost",)

    lock.acquire(selected)
    twins = (candidate(1, 55), candidate(2, 65))
    assert lock.match(twins).reasons == ("target_lock_ambiguous",)

    lock.acquire(selected, pose(0.0))
    ok, reasons = lock.confirm_pose(pose(0.20))
    assert ok is False
    assert reasons == ("target_3d_jump",)
