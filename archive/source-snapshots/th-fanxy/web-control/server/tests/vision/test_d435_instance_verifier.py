from __future__ import annotations

import numpy as np
import pytest

from vision.camera_models import PinholeCamera
from vision.d435_instance_verifier import (
    D435InstanceVerifier,
    D435InstanceVerifierConfig,
)
from vision.depth_registration import RegisteredDepth
from vision.types import InvalidDataError
from vision_models.contracts import InstanceDetection


def _registered() -> RegisteredDepth:
    valid = np.zeros((5, 5), dtype=bool)
    valid[1:4, 1:4] = True
    points = np.full((5, 5, 3), np.nan)
    rows, cols = np.nonzero(valid)
    points[rows, cols] = np.column_stack((cols, rows, np.ones(len(rows))))
    z = np.full((5, 5), np.nan)
    z[valid] = 1.0
    return RegisteredDepth(
        z_m=z,
        range_m=np.where(valid, np.linalg.norm(points, axis=2), np.nan),
        valid=valid,
        source_count=valid.astype(np.int32),
        points_lumos_m=points,
    )


def _detection(detection_id: int, label: str, mask: np.ndarray) -> InstanceDetection:
    rows, cols = np.nonzero(mask)
    return InstanceDetection(
        detection_id=detection_id,
        label=label,
        score=0.95,
        bbox_xyxy=np.array(
            [cols.min(), rows.min(), cols.max() + 1, rows.max() + 1], dtype=float
        ),
        mask=mask,
    )


def _verifier() -> D435InstanceVerifier:
    return D435InstanceVerifier(
        D435InstanceVerifierConfig(
            min_projected_points=4,
            min_support_fraction=0.70,
            ambiguity_margin=0.10,
        )
    )


def test_matching_d435_bottle_mask_verifies_the_same_instance() -> None:
    target_mask = np.zeros((5, 5), dtype=bool)
    target_mask[1:4, 1:4] = True
    d435_mask = target_mask.copy()

    result = _verifier().evaluate(
        lumos_detection=_detection(7, "bottle", target_mask),
        d435_detections=(_detection(3, "bottle", d435_mask),),
        registered=_registered(),
        d435=PinholeCamera(1.0, 1.0, 0.0, 0.0, 5, 5),
        t_d435_from_lumos=np.eye(4),
    )

    assert result.verified is True
    assert result.d435_detection_id == 3
    assert result.projected_points == 9
    assert result.support_points == 9
    assert result.support_fraction == 1.0
    assert np.array_equal(result.d435_mask, d435_mask)
    assert result.blockers == ()


def test_missing_or_nonoverlapping_d435_detection_fails_closed() -> None:
    target_mask = np.zeros((5, 5), dtype=bool)
    target_mask[1:4, 1:4] = True
    corner = np.zeros((5, 5), dtype=bool)
    corner[0, 0] = True

    result = _verifier().evaluate(
        lumos_detection=_detection(7, "bottle", target_mask),
        d435_detections=(_detection(9, "bottle", corner),),
        registered=_registered(),
        d435=PinholeCamera(1.0, 1.0, 0.0, 0.0, 5, 5),
        t_d435_from_lumos=np.eye(4),
    )

    assert result.verified is False
    assert result.d435_mask is None
    assert result.blockers == ("d435_instance_unverified",)


def test_wrong_label_and_ambiguous_matches_fail_closed() -> None:
    target_mask = np.zeros((5, 5), dtype=bool)
    target_mask[1:4, 1:4] = True
    first = target_mask.copy()
    second = target_mask.copy()
    first[1, 1] = False
    second[3, 3] = False
    camera = PinholeCamera(1.0, 1.0, 0.0, 0.0, 5, 5)

    wrong = _verifier().evaluate(
        lumos_detection=_detection(7, "bottle", target_mask),
        d435_detections=(_detection(1, "cup", target_mask),),
        registered=_registered(),
        d435=camera,
        t_d435_from_lumos=np.eye(4),
    )
    ambiguous = _verifier().evaluate(
        lumos_detection=_detection(7, "bottle", target_mask),
        d435_detections=(
            _detection(1, "bottle", first),
            _detection(2, "bottle", second),
        ),
        registered=_registered(),
        d435=camera,
        t_d435_from_lumos=np.eye(4),
    )

    assert wrong.blockers == ("d435_instance_unverified",)
    assert ambiguous.blockers == ("d435_instance_ambiguous",)


def test_verifier_rejects_d435_mask_with_wrong_native_shape() -> None:
    target_mask = np.zeros((5, 5), dtype=bool)
    target_mask[1:4, 1:4] = True
    wrong_shape = np.ones((4, 5), dtype=bool)

    with pytest.raises(InvalidDataError, match="native D435"):
        _verifier().evaluate(
            lumos_detection=_detection(7, "bottle", target_mask),
            d435_detections=(_detection(1, "bottle", wrong_shape),),
            registered=_registered(),
            d435=PinholeCamera(1.0, 1.0, 0.0, 0.0, 5, 5),
            t_d435_from_lumos=np.eye(4),
        )
