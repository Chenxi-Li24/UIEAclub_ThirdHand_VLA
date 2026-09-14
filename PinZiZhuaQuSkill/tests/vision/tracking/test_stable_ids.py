from dataclasses import replace

import numpy as np

from thirdhand_va.common.config import VisionConfig
from thirdhand_va.common.contracts import MaskCandidate
from thirdhand_va.vision.tracking.stable_ids import StableTrackManager


def candidate(detection_id: int, center_x: int, physical_id: int) -> MaskCandidate:
    mask = np.zeros((80, 160), dtype=bool)
    mask[10:70, center_x - 7:center_x + 7] = True
    descriptor = np.zeros(6, dtype=np.float32)
    descriptor[physical_id] = 1.0
    return MaskCandidate(
        detection_id=detection_id,
        label="bottle",
        score=0.95,
        bbox_xyxy=(center_x - 7, 10, center_x + 7, 70),
        mask=mask,
        authorized=True,
        descriptor=descriptor,
    )


def confirmed(manager: StableTrackManager, items, *, start_ns: int = 1):
    result = ()
    for offset in range(3):
        result = manager.update(
            tuple(replace(item, detection_id=item.detection_id + offset * 100) for item in items),
            now_ns=start_ns + offset,
            camera_moving=False,
        )
    return result


def physical_to_stable(tracks):
    return {
        int(np.argmax(track.candidate.descriptor)): track.stable_id
        for track in tracks
        if track.stable_id is not None
    }


def test_stable_ids_survive_reorder_and_backend_detection_reseed() -> None:
    manager = StableTrackManager.from_config(VisionConfig.from_yaml("configs/vision.yaml"))
    items = (candidate(10, 30, 0), candidate(20, 80, 1), candidate(30, 130, 2))
    first = confirmed(manager, items)

    second = manager.update(
        tuple(replace(item, detection_id=900 + index) for index, item in enumerate(reversed(items))),
        now_ns=10,
        camera_moving=False,
    )

    assert physical_to_stable(first) == physical_to_stable(second)
    assert set(physical_to_stable(second).values()) == {1, 2, 3}


def test_track_is_tentative_until_three_hits() -> None:
    manager = StableTrackManager.from_config(VisionConfig.from_yaml("configs/vision.yaml"))
    item = candidate(10, 60, 0)

    first = manager.update((item,), now_ns=1, camera_moving=False)
    second = manager.update((replace(item, detection_id=11),), now_ns=2, camera_moving=False)
    third = manager.update((replace(item, detection_id=12),), now_ns=3, camera_moving=False)

    assert first[0].state == "tentative" and first[0].stable_id is None
    assert second[0].state == "tentative" and second[0].stable_id is None
    assert third[0].state == "confirmed" and third[0].stable_id == 1


def test_reserved_id_is_not_recycled_until_request_finishes() -> None:
    manager = StableTrackManager.from_config(VisionConfig.from_yaml("configs/vision.yaml"))
    tracks = confirmed(manager, (candidate(10, 60, 0),))
    stable_id = tracks[0].stable_id
    assert stable_id == 1
    assert manager.reserve(stable_id, "req-1") is True

    lost = manager.update((), now_ns=3_000_000_100, camera_moving=False)

    assert lost[0].stable_id == 1
    assert 1 not in manager.available_ids
    manager.release("req-1")
    assert 1 in manager.available_ids


def test_sixth_confirmed_track_is_visible_but_unnumbered() -> None:
    manager = StableTrackManager.from_config(VisionConfig.from_yaml("configs/vision.yaml"))
    items = tuple(candidate(index, 15 + index * 23, index) for index in range(6))

    tracks = confirmed(manager, items)

    assert len(tracks) == 6
    unnumbered = [track for track in tracks if track.stable_id is None]
    assert len(unnumbered) == 1
    assert unnumbered[0].blockers == ("unnumbered_capacity_exceeded",)
