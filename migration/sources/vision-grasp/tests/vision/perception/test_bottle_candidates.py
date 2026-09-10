from pathlib import Path

import numpy as np

from thirdhand_va.common.config import VisionConfig
from thirdhand_va.vision.perception.bottle_filter import (
    BottleCandidateFilter,
    evaluate_bottle_shape,
)
from thirdhand_va.vision.perception.interfaces import RawCandidate


def _bottle_mask() -> np.ndarray:
    mask = np.zeros((80, 100), dtype=bool)
    mask[5:25, 45:55] = True
    mask[25:75, 35:65] = True
    return mask


def test_accepts_generic_bottle_without_brand_or_descriptor() -> None:
    config = VisionConfig.from_yaml(Path("configs/vision.yaml"))
    raw = RawCandidate(
        detection_id=7,
        prompt_label="bottle",
        score=0.91,
        bbox_xyxy=(35, 5, 65, 75),
        mask=_bottle_mask(),
        descriptor=None,
    )

    result = BottleCandidateFilter(config).filter(
        np.zeros((80, 100, 3), dtype=np.uint8), (raw,)
    )

    assert len(result) == 1
    assert result[0].authorized is True
    assert result[0].label == "bottle"


def test_filter_preserves_masked_appearance_descriptor() -> None:
    config = VisionConfig.from_yaml(Path("configs/vision.yaml"))
    descriptor = np.asarray([0.1, 0.4, 0.9], dtype=np.float32)
    raw = RawCandidate(
        detection_id=12,
        prompt_label="bottle",
        score=0.91,
        bbox_xyxy=(35, 5, 65, 75),
        mask=_bottle_mask(),
        descriptor=descriptor,
    )

    result = BottleCandidateFilter(config).filter(
        np.zeros((80, 100, 3), dtype=np.uint8), (raw,)
    )

    np.testing.assert_array_equal(result[0].descriptor, descriptor)
    assert result[0].descriptor is not None
    assert result[0].descriptor.flags.writeable is False


def test_rejects_misaligned_mask_fail_closed() -> None:
    config = VisionConfig.from_yaml(Path("configs/vision.yaml"))
    raw = RawCandidate(
        detection_id=8,
        prompt_label="bottle",
        score=0.91,
        bbox_xyxy=(1, 1, 10, 10),
        mask=np.ones((2, 2), dtype=bool),
        descriptor=None,
    )

    result = BottleCandidateFilter(config).filter(
        np.zeros((80, 100, 3), dtype=np.uint8), (raw,)
    )

    assert result[0].authorized is False
    assert "mask_missing_or_misaligned" in result[0].reasons


def test_ignores_non_bottle_prompt() -> None:
    config = VisionConfig.from_yaml(Path("configs/vision.yaml"))
    raw = RawCandidate(
        detection_id=9,
        prompt_label="cup",
        score=0.99,
        bbox_xyxy=(1, 1, 10, 10),
        mask=np.ones((80, 100), dtype=bool),
        descriptor=None,
    )

    result = BottleCandidateFilter(config).filter(
        np.zeros((80, 100, 3), dtype=np.uint8), (raw,)
    )

    assert result == ()


def test_accepts_short_wide_experimental_bottle_seen_by_fisheye() -> None:
    config = VisionConfig.from_yaml(Path("configs/vision.yaml"))
    mask = np.zeros((100, 100), dtype=bool)
    mask[10:27, 45:55] = True
    mask[27:78, 33:67] = True
    raw = RawCandidate(
        detection_id=10,
        prompt_label="bottle",
        score=0.79,
        bbox_xyxy=(33, 10, 67, 78),
        mask=mask,
        descriptor=None,
    )

    result = BottleCandidateFilter(config).filter(
        np.zeros((100, 100, 3), dtype=np.uint8), (raw,)
    )

    assert result[0].authorized is True


def test_reports_edge_truncation_and_inverted_profile_without_loosening_gate() -> None:
    config = VisionConfig.from_yaml(Path("configs/vision.yaml"))
    mask = np.zeros((240, 320), dtype=bool)
    mask[2:50, 120:170] = True
    mask[50:190, 132:158] = True
    raw = RawCandidate(
        detection_id=11,
        prompt_label="bottle",
        score=0.73,
        bbox_xyxy=(120, 2, 170, 190),
        mask=mask,
        descriptor=None,
    )

    shape = evaluate_bottle_shape(mask, config)
    result = BottleCandidateFilter(config).filter(
        np.zeros((240, 320, 3), dtype=np.uint8), (raw,)
    )

    assert 3.7 < shape.aspect_ratio < 3.8
    assert shape.neck_body_ratio > 1.8
    assert shape.near_frame_edge is True
    assert shape.allowed is False
    assert shape.blockers == (
        "bottle_mask_truncated_at_frame_edge",
        "bottle_profile_inverted_or_occluded",
    )
    assert result[0].authorized is False
    assert result[0].reasons == (
        "bottle_mask_truncated_at_frame_edge",
        "bottle_profile_inverted_or_occluded",
        "container_type_not_bottle",
    )


def test_shape_evaluation_exposes_reusable_metrics_for_debugging() -> None:
    config = VisionConfig.from_yaml(Path("configs/vision.yaml"))

    shape = evaluate_bottle_shape(_bottle_mask(), config)

    assert shape.allowed is True
    assert shape.mask_bbox_xyxy == (35, 5, 65, 75)
    assert shape.height_px == 70
    assert shape.width_px == 30
    assert shape.aspect_ratio == 70 / 30
    assert shape.neck_median_width_px == 10.0
    assert shape.body_median_width_px == 30.0
    assert shape.neck_body_ratio == 1 / 3
    assert shape.near_frame_edge is False
    assert shape.blockers == ()


def test_near_edge_but_complete_normal_profile_remains_actionable() -> None:
    config = VisionConfig.from_yaml(Path("configs/vision.yaml"))
    mask = np.zeros((240, 320), dtype=bool)
    mask[2:50, 145:155] = True
    mask[50:190, 130:170] = True

    shape = evaluate_bottle_shape(mask, config)

    assert shape.near_frame_edge is True
    assert shape.neck_body_ratio == 0.25
    assert shape.allowed is True
    assert shape.blockers == ()
