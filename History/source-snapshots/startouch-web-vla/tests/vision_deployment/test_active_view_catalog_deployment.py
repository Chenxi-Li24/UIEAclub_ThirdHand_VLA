from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
from vision.active_view_types import ObservationPose, TablePlane
from vision.calibration_gate import audit_handeye_calibration
from vision.camera_models import PinholeCamera, SeucmCamera
from vision.dual_camera import DualCameraCalibrationBundle
from vision_models.active_view_catalog import ActiveViewFoundation

ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "scripts/vision/finalize_active_view_catalog.py"


def load_finalizer():
    spec = importlib.util.spec_from_file_location("active_view_catalog_finalizer", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def foundation() -> ActiveViewFoundation:
    d435 = PinholeCamera(400.0, 400.0, 320.0, 240.0, 640, 480)
    lumos = SeucmCamera(300.0, 300.0, 320.0, 240.0, 0.5, 1.0, 640, 480)

    def audit(key: str, position_rmse_m: float):
        return audit_handeye_calibration(
            {
                key: np.eye(4).tolist(),
                "validation": {
                    "reprojection_rmse_px": 0.5,
                    "position_rmse_m": position_rmse_m,
                },
            },
            key,
            max_reprojection_rmse_px=4.0,
            max_position_rmse_m=0.010,
        )

    camera = DualCameraCalibrationBundle.from_audits(
        d435=d435,
        lumos=lumos,
        d435_to_lumos_audit=audit("T_lumos_from_d435", 0.004),
        lumos_to_flange_audit=audit("T_flange_from_lumos", 0.005),
    )
    table = TablePlane(
        normal_base=[0.0, 0.0, 1.0],
        offset_m=0.0,
        position_rmse_m=0.004,
        calibration_id=camera.calibration.calibration_id,
        validated=True,
    )
    return ActiveViewFoundation(
        camera=camera,
        table=table,
        robot_model_id="startouch-fasttouch-v3",
        camera_source_id="sha256:" + "1" * 64,
        table_source_id="sha256:" + "2" * 64,
    )


def capture() -> dict:
    return {
        "name": "table_center",
        "joints_deg": [1, 20, -40, 0, 10, 0],
        "tcp_position_m": [0.0, 0.0, 1.0],
        "tcp_euler_rad": [float(np.pi), 0.0, 0.0],
        "allowed_start_pose_ids": ["home"],
        "joint_tolerance_deg": 1.0,
        "path_validation": {
            "tested_at": "2026-08-06T08:00:00Z",
            "max_joint_error_deg": 0.3,
            "speed_scale": 0.05,
            "operator_acknowledged": True,
        },
    }


def test_finalizer_projects_d435_inner_roi_and_writes_atomic_catalog(tmp_path: Path) -> None:
    output = tmp_path / "catalog.json"
    result = load_finalizer().finalize_catalog(
        {"schema_version": 1, "captures": [capture()]},
        foundation(),
        output,
    )

    assert result["validated"] is True
    assert result["content_id"].startswith("sha256:")
    assert output.exists()
    assert not output.with_suffix(".json.tmp").exists()
    saved = json.loads(output.read_text(encoding="utf-8"))
    pose = saved["poses"][0]
    assert pose["pose_id"] == "table_center"
    assert len(pose["coverage_polygon_xy_m"]) == 4
    assert pose["path_validation_id"].startswith("sha256:")
    ObservationPose(
        pose_id=pose["pose_id"],
        joints_deg=pose["joints_deg"],
        t_base_from_flange=pose["t_base_from_flange"],
        coverage_polygon_xy_m=pose["coverage_polygon_xy_m"],
        allowed_start_pose_ids=pose["allowed_start_pose_ids"],
        path_validation_id=pose["path_validation_id"],
        calibration_id=saved["calibration_id"],
        joint_tolerance_deg=pose["joint_tolerance_deg"],
    )


def test_finalizer_keeps_catalog_unvalidated_without_path_audit(tmp_path: Path) -> None:
    raw_capture = capture()
    raw_capture.pop("path_validation")
    output = tmp_path / "catalog.json"

    result = load_finalizer().finalize_catalog(
        {"schema_version": 1, "captures": [raw_capture]},
        foundation(),
        output,
    )

    assert result["validated"] is False
    assert result["poses"][0]["path_validation_id"] is None


def test_finalizer_rejects_path_validation_above_speed_gate(tmp_path: Path) -> None:
    raw_capture = capture()
    raw_capture["path_validation"]["speed_scale"] = 0.06

    with np.testing.assert_raises_regex(ValueError, "speed"):
        load_finalizer().finalize_catalog(
            {"schema_version": 1, "captures": [raw_capture]},
            foundation(),
            tmp_path / "catalog.json",
        )


def test_finalizer_rejects_duplicate_names_and_nonfinite_captures(tmp_path: Path) -> None:
    finalizer = load_finalizer()
    duplicate = capture()
    with np.testing.assert_raises_regex(ValueError, "duplicate"):
        finalizer.finalize_catalog(
            {"schema_version": 1, "captures": [capture(), duplicate]},
            foundation(),
            tmp_path / "duplicate.json",
        )
    invalid = capture()
    invalid["tcp_position_m"][0] = float("nan")
    with np.testing.assert_raises_regex(ValueError, "finite"):
        finalizer.finalize_catalog(
            {"schema_version": 1, "captures": [invalid]},
            foundation(),
            tmp_path / "invalid.json",
        )
