from __future__ import annotations

import numpy as np
import pytest

from thirdhand_vision.core.errors import ModelContractError
from thirdhand_vision.features.dino import (
    mask_to_patch_coverage,
    pool_patch_descriptor,
    prepare_model_input,
)


def test_pool_patch_descriptor_is_normalized() -> None:
    features = np.array([[[3.0, 0.0], [0.0, 4.0]]])
    coverage = np.array([[1.0, 0.5]])
    descriptor = pool_patch_descriptor(features, coverage, min_patch_coverage=0.1)
    expected = np.array([2.0, 4.0 / 3.0])
    expected /= np.linalg.norm(expected)
    np.testing.assert_allclose(descriptor, expected)
    assert not descriptor.flags.writeable


def test_mask_coverage_uses_area_fraction() -> None:
    mask = np.zeros((4, 4), dtype=bool)
    mask[:2, :2] = True
    coverage = mask_to_patch_coverage(mask, (2, 2))
    np.testing.assert_allclose(coverage, [[1.0, 0.0], [0.0, 0.0]])


def test_prepare_model_input_pads_to_patch_grid() -> None:
    image = np.zeros((5, 7, 3), dtype=np.uint8)
    mask = np.ones((5, 7), dtype=bool)
    prepared, masks = prepare_model_input(image, [mask], patch_size=4, max_long_side=16)
    assert prepared.shape == (8, 8, 3)
    assert masks[0].shape == (8, 8)
    assert masks[0][:5, :7].all()
    assert not masks[0][5:, :].any()


def test_pooling_refuses_mask_without_usable_patches() -> None:
    with pytest.raises(ModelContractError, match="no usable"):
        pool_patch_descriptor(
            np.ones((2, 2, 3)),
            np.zeros((2, 2)),
            min_patch_coverage=0.1,
        )
