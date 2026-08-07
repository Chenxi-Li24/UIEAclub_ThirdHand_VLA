from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from vision.types import InvalidDataError
from vision_models.active_view_catalog import (
    ActiveViewEvidenceError,
    ActiveViewEvidenceGuard,
    load_active_view_evidence,
    load_active_view_foundation,
)


def content_id(payload: dict) -> str:
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def addressed(payload: dict) -> dict:
    result = dict(payload)
    result["content_id"] = content_id(payload)
    return result


def write_evidence(directory: Path) -> tuple[Path, Path, Path]:
    directory.mkdir()
    camera_payload = {
        "schema_version": 1,
        "robot_model_id": "startouch-fasttouch-v3",
        "d435": {"fx": 400.0, "fy": 400.0, "cx": 320.0, "cy": 240.0, "width": 640, "height": 480},
        "lumos": {
            "fx": 300.0,
            "fy": 300.0,
            "cx": 320.0,
            "cy": 240.0,
            "alpha": 0.5,
            "beta": 1.0,
            "width": 640,
            "height": 480,
        },
        "audits": {
            "d435_to_lumos": {
                "transform_key": "T_lumos_from_d435",
                "payload": {
                    "T_lumos_from_d435": np.eye(4).tolist(),
                    "validation": {"reprojection_rmse_px": 0.8, "position_rmse_m": 0.004},
                },
            },
            "lumos_to_flange": {
                "transform_key": "T_flange_from_lumos",
                "payload": {
                    "T_flange_from_lumos": np.eye(4).tolist(),
                    "validation": {"reprojection_rmse_px": 0.7, "position_rmse_m": 0.005},
                },
            },
        },
        "validation": {
            "lumos_median_px": 0.8,
            "lumos_p95_px": 2.0,
            "lumos_edge_p95_px": 3.5,
            "d435_to_lumos_target_p95_px": 3.0,
            "desktop_plane_p95_m": 0.006,
            "full_chain_static_p95_m": 0.008,
        },
    }
    camera = addressed(camera_payload)
    camera_path = directory / "camera.json"
    camera_path.write_text(json.dumps(camera), encoding="utf-8")

    # The domain calibration ID is derived from the two audited transforms and cameras.
    temporary_table = addressed({
        "schema_version": 1,
        "normal_base": [0.0, 0.0, 1.0],
        "offset_m": 0.0,
        "position_rmse_m": 0.004,
        "calibration_id": "sha256:" + "0" * 64,
        "validated": True,
    })
    temporary_path = directory / "temporary-table.json"
    temporary_path.write_text(json.dumps(temporary_table), encoding="utf-8")
    with pytest.raises(ActiveViewEvidenceError):
        load_active_view_foundation(camera_path, temporary_path, evidence_dir=directory)

    from vision.calibration_gate import audit_handeye_calibration
    from vision.camera_models import PinholeCamera, SeucmCamera
    from vision.dual_camera import DualCameraCalibrationBundle

    audits = camera_payload["audits"]
    bundle = DualCameraCalibrationBundle.from_audits(
        d435=PinholeCamera(**camera_payload["d435"]),
        lumos=SeucmCamera(**camera_payload["lumos"]),
        d435_to_lumos_audit=audit_handeye_calibration(
            audits["d435_to_lumos"]["payload"],
            "T_lumos_from_d435",
            max_reprojection_rmse_px=4.0,
            max_position_rmse_m=0.008,
        ),
        lumos_to_flange_audit=audit_handeye_calibration(
            audits["lumos_to_flange"]["payload"],
            "T_flange_from_lumos",
            max_reprojection_rmse_px=4.0,
            max_position_rmse_m=0.010,
        ),
    )
    calibration_id = bundle.calibration.calibration_id
    temporary_path.unlink()

    table_path = directory / "table.json"
    table_path.write_text(
        json.dumps(addressed({
            "schema_version": 1,
            "normal_base": [0.0, 0.0, 1.0],
            "offset_m": 0.0,
            "position_rmse_m": 0.004,
            "calibration_id": calibration_id,
            "validated": True,
        })),
        encoding="utf-8",
    )
    path_validation = {
        "tested_at": "2026-08-06T08:00:00Z",
        "max_joint_error_deg": 0.4,
        "speed_scale": 0.05,
        "operator_acknowledged": True,
    }
    catalog_path = directory / "catalog.json"
    catalog_path.write_text(
        json.dumps(addressed({
            "schema_version": 1,
            "robot_model_id": "startouch-fasttouch-v3",
            "calibration_id": calibration_id,
            "validated": True,
            "poses": [{
                "pose_id": "table_left",
                "joints_deg": [1, 20, -40, 0, 10, 0],
                "t_base_from_flange": np.eye(4).tolist(),
                "coverage_polygon_xy_m": [[-0.3, -0.2], [0.0, -0.2], [0.0, 0.2], [-0.3, 0.2]],
                "allowed_start_pose_ids": ["home"],
                "joint_tolerance_deg": 1.0,
                "path_validation": path_validation,
                "path_validation_id": content_id(path_validation),
            }],
        })),
        encoding="utf-8",
    )
    return camera_path, table_path, catalog_path


def test_catalog_is_bound_to_exact_calibration_and_validated_paths(tmp_path: Path) -> None:
    evidence_dir = tmp_path / "evidence"
    camera_path, table_path, catalog_path = write_evidence(evidence_dir)

    evidence = load_active_view_evidence(
        camera_path,
        table_path,
        catalog_path,
        evidence_dir=evidence_dir,
    )

    assert evidence.camera.calibration.validated is True
    assert evidence.table.validated is True
    assert evidence.poses[0].path_validation_id.startswith("sha256:")
    assert evidence.catalog_id.startswith("sha256:")
    assert evidence.evidence_id.startswith("sha256:")
    assert evidence.robot_model_id == "startouch-fasttouch-v3"


@pytest.mark.parametrize("field,value", [
    ("joints_deg", [2, 20, -40, 0, 10, 0]),
    ("coverage_polygon_xy_m", [[-0.4, -0.2], [0.0, -0.2], [0.0, 0.2], [-0.4, 0.2]]),
])
def test_catalog_content_change_without_new_hash_is_rejected(
    tmp_path: Path,
    field: str,
    value: list,
) -> None:
    evidence_dir = tmp_path / "evidence"
    camera_path, table_path, catalog_path = write_evidence(evidence_dir)
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    catalog["poses"][0][field] = value
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")

    with pytest.raises(ActiveViewEvidenceError, match="integrity"):
        load_active_view_evidence(
            camera_path,
            table_path,
            catalog_path,
            evidence_dir=evidence_dir,
        )


def test_readdressed_catalog_with_wrong_calibration_is_rejected(tmp_path: Path) -> None:
    evidence_dir = tmp_path / "evidence"
    camera_path, table_path, catalog_path = write_evidence(evidence_dir)
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    catalog.pop("content_id")
    catalog["calibration_id"] = "sha256:" + "9" * 64
    catalog_path.write_text(json.dumps(addressed(catalog)), encoding="utf-8")

    with pytest.raises(ActiveViewEvidenceError, match="calibration"):
        load_active_view_evidence(
            camera_path,
            table_path,
            catalog_path,
            evidence_dir=evidence_dir,
        )


def test_camera_gate_and_path_validation_gate_fail_closed(tmp_path: Path) -> None:
    evidence_dir = tmp_path / "evidence"
    camera_path, table_path, catalog_path = write_evidence(evidence_dir)
    camera = json.loads(camera_path.read_text(encoding="utf-8"))
    camera.pop("content_id")
    camera["validation"]["lumos_edge_p95_px"] = 4.1
    camera_path.write_text(json.dumps(addressed(camera)), encoding="utf-8")
    with pytest.raises(ActiveViewEvidenceError, match="Lumos edge"):
        load_active_view_evidence(
            camera_path, table_path, catalog_path, evidence_dir=evidence_dir
        )

    camera_path, table_path, catalog_path = write_evidence(tmp_path / "second")
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    catalog.pop("content_id")
    catalog["poses"][0]["path_validation"]["speed_scale"] = 0.06
    catalog["poses"][0]["path_validation_id"] = content_id(
        catalog["poses"][0]["path_validation"]
    )
    catalog_path.write_text(json.dumps(addressed(catalog)), encoding="utf-8")
    with pytest.raises(ActiveViewEvidenceError, match="speed"):
        load_active_view_evidence(
            camera_path,
            table_path,
            catalog_path,
            evidence_dir=tmp_path / "second",
        )


def test_loader_rejects_symlinks_and_paths_outside_evidence_root(tmp_path: Path) -> None:
    evidence_dir = tmp_path / "evidence"
    camera_path, table_path, catalog_path = write_evidence(evidence_dir)
    linked = evidence_dir / "linked-catalog.json"
    linked.symlink_to(catalog_path)

    with pytest.raises(ActiveViewEvidenceError, match="symlink"):
        load_active_view_evidence(
            camera_path, table_path, linked, evidence_dir=evidence_dir
        )
    with pytest.raises(ActiveViewEvidenceError, match="outside"):
        load_active_view_evidence(
            camera_path, table_path, catalog_path, evidence_dir=tmp_path / "other"
        )


def test_loader_rejects_invalid_numeric_camera_values(tmp_path: Path) -> None:
    evidence_dir = tmp_path / "evidence"
    camera_path, table_path, catalog_path = write_evidence(evidence_dir)
    camera = json.loads(camera_path.read_text(encoding="utf-8"))
    camera.pop("content_id")
    camera["d435"]["fx"] = True
    camera_path.write_text(json.dumps(addressed(camera)), encoding="utf-8")

    with pytest.raises((ActiveViewEvidenceError, InvalidDataError)):
        load_active_view_evidence(
            camera_path, table_path, catalog_path, evidence_dir=evidence_dir
        )


def test_loaded_evidence_guard_fails_closed_if_catalog_hash_changes(tmp_path: Path) -> None:
    evidence_dir = tmp_path / "evidence"
    camera_path, table_path, catalog_path = write_evidence(evidence_dir)
    guard = ActiveViewEvidenceGuard.load(
        camera_path,
        table_path,
        catalog_path,
        evidence_dir=evidence_dir,
    )
    original_id = guard.evidence.evidence_id
    assert guard.verify_unchanged() is True

    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    catalog.pop("content_id")
    catalog["poses"][0]["joint_tolerance_deg"] = 0.8
    catalog_path.write_text(json.dumps(addressed(catalog)), encoding="utf-8")

    assert guard.verify_unchanged() is False
    assert guard.evidence.evidence_id == original_id
