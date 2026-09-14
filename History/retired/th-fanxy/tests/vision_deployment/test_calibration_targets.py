from __future__ import annotations

from pathlib import Path

import numpy as np
from vision_models.calibration_targets import (
    AprilGridSpec,
    CharucoSpec,
    detect_target_corners,
    load_calibration_target,
)

ROOT = Path(__file__).parents[2]


def test_existing_charuco_definition_recovers_all_88_keyed_corners() -> None:
    target = load_calibration_target(
        ROOT / "configs/vision/calibration/charuco_12x9.yaml"
    )

    assert isinstance(target, CharucoSpec)
    assert (target.columns, target.rows) == (12, 9)
    assert target.square_size_m == 0.015
    assert target.marker_size_m == 0.01125
    assert target.dictionary == "DICT_5X5_100"
    image = target.board().generateImage((1200, 900), marginSize=40)
    detected = detect_target_corners(image, target)

    assert detected.point_ids == tuple(range(88))
    assert detected.object_points.shape == (88, 3)
    assert detected.image_points.shape == (88, 2)
    assert np.allclose(detected.object_points[:, 2], 0.0)


def test_existing_aprilgrid_config_remains_a_loadable_adapter() -> None:
    target = load_calibration_target(
        ROOT / "configs/vision/calibration/aprilgrid_6x6.yaml"
    )

    assert isinstance(target, AprilGridSpec)
    assert (target.columns, target.rows) == (6, 6)
    assert target.tag_size_m == 0.036
    assert target.spacing_ratio == 0.30
