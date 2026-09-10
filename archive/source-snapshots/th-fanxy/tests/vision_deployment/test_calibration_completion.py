from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
from vision_models.active_view_catalog import load_active_view_foundation
from vision_models.calibration_capture import CalibrationCaptureError
from vision_models.calibration_completion import (
    ValidatedHandEyeResult,
    load_handeye_capture_input,
)
from vision_models.dual_camera_candidate import load_dual_camera_candidate
from vision_models.foundation_evidence import (
    ValidatedTableResult,
    build_foundation_payloads,
    foundation_calibration_id,
    load_validated_table_result,
    write_foundation_payloads,
)
from vision_models.relative_validation_evidence import (
    RelativeValidationEvidence,
    load_relative_validation_evidence,
)


def _canonical(payload: dict) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")


def _refit_candidate(path: Path) -> Path:
    payload = {
        "schema_version": 2,
        "status": "candidate_only",
        "executable": False,
        "provenance": "charuco_fixed_intrinsics_refit",
        "source_fit_dataset_id": "sha256:" + "1" * 64,
        "solver": {
            "name": "scipy.optimize.least_squares",
            "method": "trf",
            "loss": "soft_l1",
            "f_scale": 2.0,
            "x_scale": "jac",
            "optimized_parameters": "T_lumos_from_d435_6dof",
            "fixed_intrinsics": True,
        },
        "metrics": {
            "samples": 12,
            "corners": 900,
            "median_px": 0.5,
            "p95_px": 2.0,
            "baseline_m": 0.057,
            "rotation_deg": 1.7,
            "nfev": 5,
        },
        "T_lumos_from_d435": [
            [1.0, 0.0, 0.0, -0.032],
            [0.0, 1.0, 0.0, -0.047],
            [0.0, 0.0, 1.0, -0.010],
            [0.0, 0.0, 0.0, 1.0],
        ],
        "lumos": {
            "serial": "lumos-1",
            "model": "eucm",
            "width": 1280,
            "height": 1280,
            "fx": 392.6,
            "fy": 392.4,
            "cx": 637.4,
            "cy": 641.8,
            "alpha": 0.68,
            "beta": 0.75,
            "source_id": "sha256:" + "2" * 64,
        },
        "d435": {
            "serial": "d435-1",
            "firmware": "5.17.3.10",
            "model": "pinhole",
            "distortion_model": "none",
            "width": 640,
            "height": 480,
            "fx": 606.6,
            "fy": 606.1,
            "cx": 329.0,
            "cy": 243.0,
        },
    }
    payload["candidate_id"] = "sha256:" + hashlib.sha256(_canonical(payload)).hexdigest()
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_refit_candidate_becomes_minimal_handeye_capture_input(tmp_path: Path) -> None:
    candidate_path = _refit_candidate(tmp_path / "candidate.json")
    payload = json.loads(candidate_path.read_text(encoding="utf-8"))

    capture_input = load_handeye_capture_input(candidate_path)

    assert capture_input.source_id == payload["candidate_id"]
    assert capture_input.d435.fx == pytest.approx(606.6)
    assert capture_input.d435.height == 480
    assert capture_input.distortion_coeffs == ()


def test_handeye_capture_input_rejects_legacy_or_tampered_candidate(tmp_path: Path) -> None:
    candidate_path = _refit_candidate(tmp_path / "candidate.json")
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    candidate["provenance"] = "legacy_seed"
    candidate_path.write_text(json.dumps(candidate), encoding="utf-8")

    with pytest.raises(CalibrationCaptureError, match="integrity|refit"):
        load_handeye_capture_input(candidate_path)


def _completion_inputs(tmp_path: Path):
    candidate = load_dual_camera_candidate(_refit_candidate(tmp_path / "candidate.json"))
    relative = RelativeValidationEvidence(
        validation_id="sha256:" + "3" * 64,
        candidate_id=candidate.candidate_id,
        samples=10,
        edge_points=64,
        d435_reprojection_rmse_px=0.4,
        lumos_reprojection_rmse_px=0.8,
        lumos_median_px=0.5,
        lumos_p95_px=1.8,
        lumos_edge_p95_px=2.2,
        relative_position_rmse_m=0.001,
    )
    handeye_payload = {
        "schema_version": 1,
        "dataset_id": "sha256:" + "4" * 64,
        "solver": "opencv_calibrateHandEye_park",
        "T_flange_from_d435": np.eye(4).tolist(),
        "validation": {"reprojection_rmse_px": 0.6, "position_rmse_m": 0.003},
    }
    handeye = ValidatedHandEyeResult(
        t_flange_from_d435=np.eye(4),
        result_id="sha256:" + "5" * 64,
        dataset_id="sha256:" + "4" * 64,
        position_rmse_m=0.003,
        position_p95_m=0.006,
        reprojection_rmse_px=0.6,
        audit_payload=handeye_payload,
    )
    return candidate, relative, handeye


def test_foundation_payloads_round_trip_with_derived_transform(tmp_path: Path) -> None:
    candidate, relative, handeye = _completion_inputs(tmp_path)
    calibration_id = foundation_calibration_id(candidate, relative, handeye)
    table = ValidatedTableResult(
        result_id="sha256:" + "6" * 64,
        candidate_source_id=candidate.candidate_id,
        handeye_result_id=handeye.result_id,
        calibration_id=calibration_id,
        normal_base=(0.0, 0.0, 1.0),
        offset_m=-0.12,
        fit_rmse_m=0.002,
        validation_p95_m=0.004,
    )

    camera_payload, table_payload = build_foundation_payloads(
        candidate,
        relative,
        handeye,
        table,
        robot_model_id="startouch-fasttouch-v3",
    )

    expected_lumos = handeye.t_flange_from_d435 @ np.linalg.inv(
        candidate.t_lumos_from_d435
    )
    assert np.allclose(
        camera_payload["audits"]["lumos_to_flange"]["payload"][
            "T_flange_from_lumos"
        ],
        expected_lumos,
    )
    assert camera_payload["validation"]["lumos_edge_p95_px"] == pytest.approx(2.2)
    assert table_payload["calibration_id"] == calibration_id
    assert camera_payload["content_id"].startswith("sha256:")
    assert table_payload["content_id"].startswith("sha256:")

    evidence = tmp_path / "evidence"
    evidence.mkdir()
    camera_path = evidence / "camera.json"
    table_path = evidence / "table.json"
    camera_path.write_text(json.dumps(camera_payload), encoding="utf-8")
    table_path.write_text(json.dumps(table_payload), encoding="utf-8")
    foundation = load_active_view_foundation(
        camera_path,
        table_path,
        evidence_dir=evidence,
    )
    assert foundation.camera.calibration.calibration_id == calibration_id
    assert foundation.table.validated is True


def test_foundation_rejects_changed_sources_and_unvalidated_metrics(tmp_path: Path) -> None:
    candidate, relative, handeye = _completion_inputs(tmp_path)
    with pytest.raises(CalibrationCaptureError, match="edge|relative"):
        RelativeValidationEvidence(
            validation_id=relative.validation_id,
            candidate_id=relative.candidate_id,
            samples=10,
            edge_points=2,
            d435_reprojection_rmse_px=0.4,
            lumos_reprojection_rmse_px=0.8,
            lumos_median_px=0.5,
            lumos_p95_px=1.8,
            lumos_edge_p95_px=2.2,
            relative_position_rmse_m=0.001,
        )

    calibration_id = foundation_calibration_id(candidate, relative, handeye)
    changed_table = ValidatedTableResult(
        result_id="sha256:" + "6" * 64,
        candidate_source_id="sha256:" + "7" * 64,
        handeye_result_id=handeye.result_id,
        calibration_id=calibration_id,
        normal_base=(0.0, 0.0, 1.0),
        offset_m=-0.12,
        fit_rmse_m=0.002,
        validation_p95_m=0.004,
    )
    with pytest.raises(CalibrationCaptureError, match="source"):
        build_foundation_payloads(candidate, relative, handeye, changed_table)


def _relative_manifest(path: Path, candidate_id: str) -> Path:
    observations = []
    for index in range(10):
        sample_id = f"pose-{index + 1:02d}"
        lumos = f"lumos-{index}".encode()
        d435 = f"d435-{index}".encode()
        lumos_path = path / "images" / "lumos" / f"{sample_id}.jpg"
        d435_path = path / "images" / "d435" / f"{sample_id}.jpg"
        lumos_path.parent.mkdir(parents=True, exist_ok=True)
        d435_path.parent.mkdir(parents=True, exist_ok=True)
        lumos_path.write_bytes(lumos)
        d435_path.write_bytes(d435)
        observations.append(
            {
                "sample_id": sample_id,
                "lumos_image": f"images/lumos/{sample_id}.jpg",
                "lumos_image_sha256": hashlib.sha256(lumos).hexdigest(),
                "d435_image": f"images/d435/{sample_id}.jpg",
                "d435_image_sha256": hashlib.sha256(d435).hexdigest(),
                "capture_skew_ms": 10.0,
                "metrics": {
                    "common_points": 24,
                    "d435_reprojection_rmse_px": 0.4,
                    "lumos_reprojection_median_px": 0.5,
                    "lumos_reprojection_p95_px": 1.8,
                    "passes_pixel_gate": True,
                    "lumos_errors_px": [0.5] * 24,
                    "T_d435_from_board": np.eye(4).tolist(),
                },
            }
        )
    summary = {
        "schema_version": 1,
        "candidate_id": candidate_id,
        "samples": 10,
        "required_samples": 10,
        "passing_pairs": 10,
        "distinct_poses": 10,
        "pose_separation_translation_m": 0.015,
        "pose_separation_rotation_deg": 3.0,
        "common_points_min": 24,
        "d435_reprojection_rmse_px": 0.4,
        "lumos_reprojection_median_px": 0.5,
        "lumos_reprojection_p95_px": 1.8,
        "relative_extrinsic_validated": True,
        "executable": False,
        "remaining_blockers": [
            "handeye_validation_missing",
            "table_validation_missing",
        ],
    }
    summary["content_id"] = "sha256:" + hashlib.sha256(_canonical(summary)).hexdigest()
    payload = {
        "schema_version": 1,
        "candidate_id": candidate_id,
        "target": {
            "family": "charuco",
            "rows": 9,
            "columns": 12,
            "square_size_m": 0.015,
            "marker_size_m": 0.01125,
            "dictionary": "DICT_5X5_100",
        },
        "motion_or_robot_access": False,
        "observations": observations,
        "summary": summary,
    }
    payload["content_id"] = "sha256:" + hashlib.sha256(_canonical(payload)).hexdigest()
    manifest = path / "validation.json"
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    return manifest


def test_relative_loader_checks_manifest_and_retained_image_hashes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate, relative, _handeye = _completion_inputs(tmp_path)
    manifest = _relative_manifest(tmp_path / "relative", candidate.candidate_id)
    stored = json.loads(manifest.read_text(encoding="utf-8"))
    expected = RelativeValidationEvidence(
        **{**relative.__dict__, "validation_id": stored["content_id"]}
    )
    monkeypatch.setattr(
        "vision_models.relative_validation_evidence._recompute_relative_validation",
        lambda _payload, _root, _candidate: expected,
    )

    assert load_relative_validation_evidence(manifest, candidate) == expected

    image = tmp_path / "relative" / "images" / "lumos" / "pose-01.jpg"
    image.write_bytes(b"tampered")
    with pytest.raises(CalibrationCaptureError, match="image|integrity"):
        load_relative_validation_evidence(manifest, candidate)


def test_table_result_loader_and_atomic_foundation_writer(tmp_path: Path) -> None:
    candidate, relative, handeye = _completion_inputs(tmp_path)
    calibration_id = foundation_calibration_id(candidate, relative, handeye)
    unsigned = {
        "schema_version": 1,
        "dataset_id": "sha256:" + "8" * 64,
        "candidate_source_id": candidate.candidate_id,
        "handeye_result_id": handeye.result_id,
        "calibration_id": calibration_id,
        "normal_base": [0.0, 0.0, 1.0],
        "offset_m": -0.12,
        "fit_samples": 6,
        "validation_samples": 2,
        "fit": {"rmse_m": 0.002},
        "validation": {"p95_m": 0.004},
        "validated": True,
        "reasons": [],
    }
    record = dict(unsigned)
    record["content_id"] = "sha256:" + hashlib.sha256(_canonical(unsigned)).hexdigest()
    source = tmp_path / "table-result.json"
    source.write_text(json.dumps(record), encoding="utf-8")

    table = load_validated_table_result(source)
    camera_payload, table_payload = build_foundation_payloads(
        candidate, relative, handeye, table
    )
    camera_path, table_path = write_foundation_payloads(
        tmp_path / "foundation", camera_payload, table_payload
    )
    assert json.loads(camera_path.read_text())["content_id"] == camera_payload["content_id"]
    assert json.loads(table_path.read_text())["content_id"] == table_payload["content_id"]

    record["validation"]["p95_m"] = 0.009
    source.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(CalibrationCaptureError, match="integrity|validated"):
        load_validated_table_result(source)


def test_table_result_loader_accepts_supplemental_fit_sample_count(
    tmp_path: Path,
) -> None:
    candidate, relative, handeye = _completion_inputs(tmp_path)
    unsigned = {
        "schema_version": 1,
        "dataset_id": "sha256:" + "8" * 64,
        "candidate_source_id": candidate.candidate_id,
        "handeye_result_id": handeye.result_id,
        "calibration_id": foundation_calibration_id(candidate, relative, handeye),
        "normal_base": [0.0, 0.0, 1.0],
        "offset_m": -0.12,
        "fit_samples": 7,
        "validation_samples": 2,
        "fit": {"rmse_m": 0.002},
        "validation": {"p95_m": 0.004},
        "validated": True,
        "reasons": [],
    }
    record = dict(unsigned)
    record["content_id"] = "sha256:" + hashlib.sha256(_canonical(unsigned)).hexdigest()
    source = tmp_path / "table-result-supplemental.json"
    source.write_text(json.dumps(record), encoding="utf-8")

    result = load_validated_table_result(source)

    assert result.fit_rmse_m == pytest.approx(0.002)
    assert result.validation_p95_m == pytest.approx(0.004)
