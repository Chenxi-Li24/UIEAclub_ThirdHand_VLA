from dataclasses import replace

import numpy as np

from thirdhand_va.common.config import VisionConfig
from thirdhand_va.common.contracts import MaskCandidate
from thirdhand_va.vision.tracking.norfair_adapter import NorfairTrackerAdapter


def candidate(detection_id: int, center_x: int, color_bin: int) -> MaskCandidate:
    mask = np.zeros((80, 140), dtype=bool)
    mask[10:70, center_x - 7:center_x + 7] = True
    descriptor = np.zeros(4, dtype=np.float32)
    descriptor[color_bin] = 1.0
    return MaskCandidate(
        detection_id=detection_id,
        label="bottle",
        score=0.95,
        bbox_xyxy=(center_x - 7, 10, center_x + 7, 70),
        mask=mask,
        authorized=True,
        descriptor=descriptor,
    )


def test_norfair_adapter_keeps_backend_identity_when_detector_ids_reset() -> None:
    config = VisionConfig.from_yaml("configs/vision.yaml")
    adapter = NorfairTrackerAdapter.from_config(config)
    left = candidate(10, 35, 0)
    right = candidate(20, 105, 1)

    first = adapter.update((left, right))
    second = adapter.update((replace(right, detection_id=1), replace(left, detection_id=2)))

    first_by_color = {
        int(np.argmax(row.candidate.descriptor)): row.backend_track_id for row in first
    }
    second_by_color = {
        int(np.argmax(row.candidate.descriptor)): row.backend_track_id for row in second
    }
    assert first_by_color == second_by_color


def test_camera_motion_rejects_descriptor_and_world_point_conflict() -> None:
    config = VisionConfig.from_yaml("configs/vision.yaml")
    adapter = NorfairTrackerAdapter.from_config(config)
    original = candidate(10, 40, 0)
    first = adapter.update((original,), world_points={10: (0.1, 0.0, 0.5)})

    conflict = replace(candidate(11, 41, 2), detection_id=11)
    second = adapter.update(
        (conflict,),
        camera_moving=True,
        world_points={11: (0.4, 0.0, 0.5)},
    )

    assert first[0].backend_track_id != second[0].backend_track_id
