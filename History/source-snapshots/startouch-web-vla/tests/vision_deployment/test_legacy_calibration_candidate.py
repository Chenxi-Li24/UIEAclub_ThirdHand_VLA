from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from vision_models.legacy_calibration import (
    LegacyCalibrationError,
    audit_legacy_calibration_directory,
)


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _legacy_directory(tmp_path: Path) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    lumos = np.eye(4)
    lumos[:3, 3] = [0.10, -0.02, -0.08]
    d435 = np.eye(4)
    d435[:3, 3] = [-0.02, 0.01, 0.18]
    table = np.eye(4)
    table[:3, :3] = [[0.0, 0.0, 1.0], [0.0, 1.0, 0.0], [-1.0, 0.0, 0.0]]
    _write_json(
        tmp_path / "handeye_result.json",
        {"T_flange_camera": lumos.tolist(), "pairs": 14},
    )
    _write_json(
        tmp_path / "d435_handeye_result.json",
        {
            "T_flange_d435cam": d435.tolist(),
            "pairs": 13,
            "method": "OpenCV calibrateHandEye TSAI",
        },
    )
    _write_json(tmp_path / "desk_ref.json", {"T_base_board": table.tolist()})
    (tmp_path / "handeye_calib.py").write_text(
        "# SEUCM intrinsics\n"
        "cv2.solvePnP(obj_pts, img_pts, K, DIST)\n"
        "cv2.Rodrigues(np.array(euler, dtype=np.float64))\n",
        encoding="utf-8",
    )
    (tmp_path / "d435_calibrate.py").write_text(
        "cv2.Rodrigues(np.array(euler, dtype=np.float64))\n"
        "T_cam_flange = handeye_tsai(R_flange, t_flange, R_board, t_board)\n"
        "R_flange_cam = R_cam_flange.T\n",
        encoding="utf-8",
    )
    return tmp_path


def test_legacy_files_become_content_addressed_non_executable_candidates(tmp_path: Path) -> None:
    report = audit_legacy_calibration_directory(_legacy_directory(tmp_path))

    assert report["candidate_id"].startswith("sha256:")
    assert report["status"] == "candidate_only"
    assert report["validated"] is False
    assert report["executable"] is False
    assert report["sources"]["lumos_handeye"]["samples"] == 14
    assert report["sources"]["d435_handeye"]["samples"] == 13
    geometry = report["candidate_geometry"]
    assert geometry["seed_hypothesis"] == "d435_extra_inversion_corrected"
    assert geometry["seed_only"] is True
    assert geometry["hypotheses"]["as_labeled"]["baseline_m"] == pytest.approx(
        0.287924, abs=1e-6
    )
    assert geometry["hypotheses"]["d435_extra_inversion_corrected"][
        "baseline_m"
    ] == pytest.approx(0.128452, abs=1e-6)
    assert np.allclose(
        geometry["seed_T_lumos_from_d435"],
        np.linalg.inv(np.array(report["sources"]["lumos_handeye"]["transform"]))
        @ np.linalg.inv(np.array(report["sources"]["d435_handeye"]["transform"])),
    )
    assert set(report["reasons"]) >= {
        "independent_validation_missing",
        "legacy_euler_rpy_passed_to_rodrigues",
        "legacy_d435_transform_direction_ambiguous",
        "legacy_lumos_seucm_processed_as_pinhole",
        "legacy_table_normal_implausible",
    }


def test_candidate_id_changes_when_any_legacy_source_changes(tmp_path: Path) -> None:
    root = _legacy_directory(tmp_path)
    first = audit_legacy_calibration_directory(root)
    payload = json.loads((root / "handeye_result.json").read_text(encoding="utf-8"))
    payload["T_flange_camera"][0][3] += 0.001
    _write_json(root / "handeye_result.json", payload)

    second = audit_legacy_calibration_directory(root)

    assert second["candidate_id"] != first["candidate_id"]


def test_invalid_legacy_table_rotation_is_reported_instead_of_repaired(tmp_path: Path) -> None:
    root = _legacy_directory(tmp_path)
    payload = json.loads((root / "desk_ref.json").read_text(encoding="utf-8"))
    payload["T_base_board"][0][0] += 0.001
    _write_json(root / "desk_ref.json", payload)

    report = audit_legacy_calibration_directory(root)

    assert "legacy_table_transform_invalid" in report["reasons"]
    assert report["validated"] is False
    assert report["executable"] is False
    assert report["sources"]["table_reference"]["transform"] == payload["T_base_board"]


def test_legacy_auditor_rejects_missing_files_and_symlink_sources(tmp_path: Path) -> None:
    with pytest.raises(LegacyCalibrationError, match="missing"):
        audit_legacy_calibration_directory(tmp_path)

    root = _legacy_directory(tmp_path)
    original = root / "handeye_result.json"
    moved = root / "handeye_result.backup.json"
    original.rename(moved)
    original.symlink_to(moved)
    with pytest.raises(LegacyCalibrationError, match="symlink"):
        audit_legacy_calibration_directory(root)


def test_report_contains_no_runtime_or_motion_authorization_fields(tmp_path: Path) -> None:
    report = audit_legacy_calibration_directory(_legacy_directory(tmp_path))
    serialized = json.dumps(report, sort_keys=True)

    assert "joints_deg" not in serialized
    assert "robot_execution_enabled" not in serialized
    assert "active_view_execution_enabled" not in serialized
    assert "operator_acknowledged" not in serialized


def test_cli_writes_audit_atomically_without_hardware_access(tmp_path: Path) -> None:
    root = _legacy_directory(tmp_path / "legacy")
    output = tmp_path / "artifacts" / "legacy-candidate-audit.json"
    script = Path(__file__).parents[2] / "scripts/vision/audit_legacy_calibration.py"

    completed = subprocess.run(
        [
            sys.executable,
            str(script),
            "--legacy-dir",
            str(root),
            "--output",
            str(output),
        ],
        check=False,
        capture_output=True,
        text=True,
        env={"PYTHONPATH": str(Path(__file__).parents[2] / "web-control/server")},
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(output.read_text(encoding="utf-8"))["executable"] is False
    assert list(output.parent.glob("*.tmp")) == []
    source = script.read_text(encoding="utf-8")
    assert "startouch" not in source.lower()
    assert "pyrealsense" not in source.lower()
    assert "move_" not in source
