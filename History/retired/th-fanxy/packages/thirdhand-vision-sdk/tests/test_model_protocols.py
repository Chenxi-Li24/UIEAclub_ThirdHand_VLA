from __future__ import annotations

import numpy as np
import pytest

from thirdhand_vision.core.errors import ModelContractError
from thirdhand_vision.detection.base import InstanceSegmenter
from thirdhand_vision.features.base import FeatureEncoder, normalized_descriptor


class SmallSegmenter:
    def predict(self, image_rgb: np.ndarray):
        return ()


class SmallEncoder:
    model_id = "fixture"

    def encode(self, image_rgb: np.ndarray, masks):
        return ()


def test_structural_model_protocols_accept_small_adapters() -> None:
    assert isinstance(SmallSegmenter(), InstanceSegmenter)
    assert isinstance(SmallEncoder(), FeatureEncoder)


def test_descriptor_is_normalized_and_read_only() -> None:
    value = normalized_descriptor([3.0, 4.0])
    np.testing.assert_allclose(value, [0.6, 0.8])
    assert not value.flags.writeable


def test_descriptor_rejects_zero_vector() -> None:
    with pytest.raises(ModelContractError, match="norm"):
        normalized_descriptor([0.0, 0.0])

