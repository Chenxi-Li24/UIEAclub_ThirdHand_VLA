from __future__ import annotations

import pytest

from thirdhand_va.vision.camera.coverage import RegisteredDepthCoverage


def test_registered_depth_coverage_preserves_calibrated_hardware_fov() -> None:
    coverage = RegisteredDepthCoverage(
        camera_serial="250801DR48FP25002738",
        reference_size=(640, 480),
        roi_xyxy=(203, 149, 428, 319),
    )

    assert coverage.roi_for_size(640, 480) == (203, 149, 428, 319)
    assert coverage.roi_for_size(320, 240) == (101, 74, 214, 159)


def test_registered_depth_coverage_rejects_invalid_calibration_geometry() -> None:
    with pytest.raises(ValueError, match="reference_size"):
        RegisteredDepthCoverage(
            camera_serial="camera",
            reference_size=(0, 480),
            roi_xyxy=(203, 149, 428, 319),
        )

    coverage = RegisteredDepthCoverage(
        camera_serial="camera",
        reference_size=(640, 480),
        roi_xyxy=(203, 149, 428, 319),
    )
    with pytest.raises(ValueError, match="target size"):
        coverage.roi_for_size(0, 480)
