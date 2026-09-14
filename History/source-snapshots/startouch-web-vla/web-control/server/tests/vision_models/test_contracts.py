from __future__ import annotations

import numpy as np
import pytest

from vision_models.contracts import InstanceDetection, ModelContractError


def detection(**overrides):
    values = {
        "detection_id": 3,
        "label": "cup",
        "score": 0.9,
        "bbox_xyxy": np.array([1.0, 2.0, 4.0, 5.0]),
        "mask": np.ones((8, 8), dtype=bool),
    }
    values.update(overrides)
    return InstanceDetection(**values)


def test_instance_detection_owns_normalized_immutable_arrays():
    item = detection()
    np.testing.assert_allclose(item.bbox_xyxy, [1.0, 2.0, 4.0, 5.0])
    assert item.mask.dtype == np.bool_
    assert not item.bbox_xyxy.flags.writeable
    assert not item.mask.flags.writeable


@pytest.mark.parametrize(
    "overrides",
    [
        {"detection_id": -1},
        {"label": ""},
        {"score": -0.1},
        {"score": 1.1},
        {"bbox_xyxy": [1, 2, 1, 5]},
        {"bbox_xyxy": [1, 2, np.nan, 5]},
        {"bbox_xyxy": [1, 2, 3]},
        {"mask": np.ones((8, 8), dtype=np.uint8)},
        {"mask": np.ones((8, 8, 1), dtype=bool)},
        {"mask": np.zeros((8, 8), dtype=bool)},
        {"bbox_xyxy": [-1, 2, 4, 5]},
        {"bbox_xyxy": [1, 2, 9, 5]},
    ],
)
def test_instance_detection_rejects_malformed_or_out_of_image_data(overrides):
    with pytest.raises(ModelContractError):
        detection(**overrides)
