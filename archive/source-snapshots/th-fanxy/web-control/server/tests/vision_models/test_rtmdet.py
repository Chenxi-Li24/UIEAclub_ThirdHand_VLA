from __future__ import annotations

import numpy as np
import pytest

from vision_models.contracts import ModelContractError
from vision_models.rtmdet import detections_from_mmdet, validate_model_labels


class FakeTensor:
    def __init__(self, value):
        self.value = np.asarray(value)

    def detach(self):
        return self

    def cpu(self):
        return self

    def numpy(self):
        return np.array(self.value, copy=True)


class FakePredInstances:
    def __init__(self, *, bboxes, scores, labels, masks=None):
        self.bboxes = FakeTensor(bboxes)
        self.scores = FakeTensor(scores)
        self.labels = FakeTensor(labels)
        if masks is not None:
            self.masks = FakeTensor(masks)


def test_mmdet_conversion_requires_masks_filters_scores_and_sorts_deterministically():
    masks = np.zeros((3, 6, 8), dtype=bool)
    masks[0, 1:4, 1:4] = True
    masks[1, 2:5, 2:6] = True
    masks[2, 1:3, 5:7] = True
    instances = FakePredInstances(
        bboxes=[[1, 1, 4, 4], [2, 2, 6, 5], [5, 1, 7, 3]],
        scores=[0.85, 0.95, 0.20],
        labels=[0, 1, 0],
        masks=masks,
    )

    detections = detections_from_mmdet(
        instances,
        labels=("cup", "bottle"),
        image_shape=(6, 8),
        min_score=0.80,
    )

    assert [(item.detection_id, item.label, item.score) for item in detections] == [
        (1, "bottle", 0.95),
        (0, "cup", 0.85),
    ]
    assert detections[0].mask.sum() == 12


def test_mmdet_conversion_fails_closed_without_instance_masks():
    instances = FakePredInstances(
        bboxes=[[1, 1, 4, 4]],
        scores=[0.9],
        labels=[0],
    )
    with pytest.raises(ModelContractError, match="instance masks"):
        detections_from_mmdet(instances, ("cup",), (6, 8), 0.5)


def test_model_labels_must_exactly_match_checkpoint_metadata():
    assert validate_model_labels(
        ("cup", "bottle"),
        {"classes": ("cup", "bottle")},
    ) == ("cup", "bottle")
    with pytest.raises(ModelContractError, match="dataset metadata"):
        validate_model_labels(("cup",), {})
    with pytest.raises(ModelContractError, match="do not match"):
        validate_model_labels(
            ("cup", "bottle"),
            {"classes": ("bottle", "cup")},
        )
    with pytest.raises(ModelContractError, match="valid class names"):
        validate_model_labels(("cup",), {"classes": None})
    with pytest.raises(ModelContractError, match="valid class names"):
        validate_model_labels(("cup",), {"classes": ("",)})


def test_mmdet_conversion_rejects_length_shape_and_label_mismatches():
    mask = np.ones((1, 6, 8), dtype=bool)
    with pytest.raises(ModelContractError):
        detections_from_mmdet(
            FakePredInstances(
                bboxes=[[1, 1, 4, 4]],
                scores=[0.9, 0.8],
                labels=[0],
                masks=mask,
            ),
            ("cup",),
            (6, 8),
            0.5,
        )
    with pytest.raises(ModelContractError):
        detections_from_mmdet(
            FakePredInstances(
                bboxes=[[1, 1, 4, 4]],
                scores=[0.9],
                labels=[4],
                masks=mask,
            ),
            ("cup",),
            (6, 8),
            0.5,
        )
    with pytest.raises(ModelContractError):
        detections_from_mmdet(
            FakePredInstances(
                bboxes=[[1, 1, 4, 4]],
                scores=[0.9],
                labels=[0],
                masks=np.ones((1, 5, 8), dtype=bool),
            ),
            ("cup",),
            (6, 8),
            0.5,
        )


@pytest.mark.parametrize("min_score", [-0.1, 1.1, np.nan])
def test_mmdet_conversion_validates_score_threshold(min_score):
    instances = FakePredInstances(
        bboxes=[[1, 1, 4, 4]],
        scores=[0.9],
        labels=[0],
        masks=np.ones((1, 6, 8), dtype=bool),
    )
    with pytest.raises(ModelContractError):
        detections_from_mmdet(instances, ("cup",), (6, 8), min_score)
