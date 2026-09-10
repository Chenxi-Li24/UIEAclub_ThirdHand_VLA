from __future__ import annotations

import numpy as np
import pytest
from dataclasses import replace

from vision.calibration_gate import audit_handeye_calibration, sdk_pose_transform
from vision.types import InvalidDataError


def test_sdk_pose_uses_rz_ry_rx_rpy_convention():
    transform = sdk_pose_transform([0.1, 0.2, 0.3], [0.2, -0.3, 0.4])
    roll, pitch, yaw = 0.2, -0.3, 0.4
    rx = np.array(
        [[1, 0, 0], [0, np.cos(roll), -np.sin(roll)], [0, np.sin(roll), np.cos(roll)]]
    )
    ry = np.array(
        [[np.cos(pitch), 0, np.sin(pitch)], [0, 1, 0], [-np.sin(pitch), 0, np.cos(pitch)]]
    )
    rz = np.array(
        [[np.cos(yaw), -np.sin(yaw), 0], [np.sin(yaw), np.cos(yaw), 0], [0, 0, 1]]
    )
    np.testing.assert_allclose(transform[:3, :3], rz @ ry @ rx)
    np.testing.assert_allclose(transform[:3, 3], [0.1, 0.2, 0.3])


def test_handeye_without_independent_validation_is_rejected():
    payload = {
        "T_flange_d435cam": np.eye(4).tolist(),
        "pairs": 13,
        "method": "OpenCV calibrateHandEye TSAI",
    }
    audit = audit_handeye_calibration(payload, "T_flange_d435cam")

    assert not audit.calibration.validated
    assert "independent_validation_missing" in audit.reasons
    assert audit.calibration.calibration_id.startswith("sha256:")


def test_implausible_camera_offset_is_rejected_even_with_metrics():
    transform = np.eye(4)
    transform[:3, 3] = [0.0, 0.0, 0.39]
    payload = {
        "T_flange_d435cam": transform.tolist(),
        "pairs": 20,
        "validation": {"reprojection_rmse_px": 0.4, "position_rmse_m": 0.004},
    }
    audit = audit_handeye_calibration(payload, "T_flange_d435cam")

    assert not audit.calibration.validated
    assert "camera_offset_implausible" in audit.reasons


def test_negative_or_nonfinite_validation_metrics_are_rejected():
    for metrics in (
        {"reprojection_rmse_px": -0.1, "position_rmse_m": 0.004},
        {"reprojection_rmse_px": 0.4, "position_rmse_m": -0.001},
    ):
        audit = audit_handeye_calibration(
            {
                "T_flange_d435cam": np.eye(4).tolist(),
                "validation": metrics,
            },
            "T_flange_d435cam",
        )
        assert not audit.calibration.validated
        assert "independent_validation_invalid" in audit.reasons

    with pytest.raises(InvalidDataError, match="canonical JSON"):
        audit_handeye_calibration(
            {
                "T_flange_d435cam": np.eye(4).tolist(),
                "validation": {
                    "reprojection_rmse_px": 0.4,
                    "position_rmse_m": float("inf"),
                },
            },
            "T_flange_d435cam",
        )


def test_calibration_audit_cannot_replace_transform_without_reauditing_payload():
    audit = audit_handeye_calibration(
        {
            "T_flange_d435cam": np.eye(4).tolist(),
            "validation": {"reprojection_rmse_px": 0.3, "position_rmse_m": 0.004},
        },
        "T_flange_d435cam",
    )

    with pytest.raises(TypeError):
        replace(audit, transform=np.eye(4))
