from __future__ import annotations

import numpy as np
import pytest

from vision_models.contracts import ModelContractError
from vision_models.dino import (
    mask_to_patch_coverage,
    pool_patch_descriptor,
    prepare_model_input,
)


def test_pool_patch_descriptor_averages_only_covered_patches():
    features = np.array(
        [
            [[1.0, 0.0], [0.0, 1.0]],
            [[1.0, 0.0], [0.0, 1.0]],
        ]
    )
    coverage = np.array([[1.0, 0.0], [1.0, 0.0]])
    descriptor = pool_patch_descriptor(features, coverage, min_patch_coverage=0.5)
    np.testing.assert_allclose(descriptor, [1.0, 0.0])
    assert not descriptor.flags.writeable


def test_pool_patch_descriptor_uses_area_weights_before_normalizing():
    features = np.array([[[1.0, 0.0], [0.0, 1.0]]])
    coverage = np.array([[1.0, 0.5]])
    descriptor = pool_patch_descriptor(features, coverage, min_patch_coverage=0.1)
    np.testing.assert_allclose(descriptor, np.array([1.0, 0.5]) / np.sqrt(1.25))


def test_native_mask_is_resized_to_patch_area_coverage():
    mask = np.zeros((4, 4), dtype=bool)
    mask[:2, :2] = True
    coverage = mask_to_patch_coverage(mask, (2, 2))
    np.testing.assert_allclose(coverage, [[1.0, 0.0], [0.0, 0.0]])


def test_model_input_is_downscaled_and_padded_to_patch_multiple_without_stretching_mask():
    image = np.zeros((8, 4, 3), dtype=np.uint8)
    image[:4] = 200
    mask = np.zeros((8, 4), dtype=bool)
    mask[:4] = True
    prepared_image, prepared_masks = prepare_model_input(
        image,
        [mask],
        patch_size=3,
        max_long_side=4,
    )
    assert prepared_image.shape == (6, 3, 3)
    assert prepared_masks[0].shape == (6, 3)
    assert prepared_masks[0][:2, :2].all()
    assert not prepared_masks[0][2:].any()


@pytest.mark.parametrize(
    "features,coverage",
    [
        (np.ones((2, 2, 2)), np.zeros((2, 2))),
        (np.zeros((2, 2, 2)), np.ones((2, 2))),
        (np.ones((2, 2, 2)), np.ones((3, 3))),
        (np.full((2, 2, 2), np.nan), np.ones((2, 2))),
    ],
)
def test_pooling_rejects_empty_zero_mismatched_or_nonfinite_data(features, coverage):
    with pytest.raises(ModelContractError):
        pool_patch_descriptor(features, coverage)


def test_mask_coverage_rejects_nonboolean_or_invalid_grid():
    with pytest.raises(ModelContractError):
        mask_to_patch_coverage(np.ones((4, 4), dtype=np.uint8), (2, 2))
    with pytest.raises(ModelContractError):
        mask_to_patch_coverage(np.ones((4, 4), dtype=bool), (0, 2))
