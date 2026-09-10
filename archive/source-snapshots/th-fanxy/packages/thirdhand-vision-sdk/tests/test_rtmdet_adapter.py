from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from thirdhand_vision.core.errors import ModelContractError
from thirdhand_vision.detection.rtmdet import detections_from_mmdet, validate_model_labels


def prediction_fixture(*, include_masks: bool = True):
    values = {
        "bboxes": np.array([[1.0, 2.0, 5.0, 6.0], [0.0, 0.0, 2.0, 2.0]]),
        "scores": np.array([0.9, 0.2]),
        "labels": np.array([1, 0]),
    }
    if include_masks:
        values["masks"] = np.stack(
            [np.ones((8, 9), dtype=bool), np.zeros((8, 9), dtype=bool)]
        )
    return SimpleNamespace(**values)


def test_rtmdet_conversion_requires_masks_and_filters_scores() -> None:
    detections = detections_from_mmdet(
        prediction_fixture(),
        labels=("cup", "bottle"),
        image_shape=(8, 9),
        min_score=0.35,
    )
    assert len(detections) == 1
    assert detections[0].label == "bottle"
    assert detections[0].image_shape == (8, 9)
    assert detections[0].mask.all()


def test_rtmdet_conversion_refuses_box_only_output() -> None:
    with pytest.raises(ModelContractError, match="instance masks"):
        detections_from_mmdet(
            prediction_fixture(include_masks=False),
            labels=("cup", "bottle"),
            image_shape=(8, 9),
            min_score=0.35,
        )


def test_rtmdet_labels_must_equal_checkpoint_metadata() -> None:
    with pytest.raises(ModelContractError, match="do not match"):
        validate_model_labels(("bottle",), {"classes": ("cup",)})

