from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from vision_models.calibration_capture import CalibrationCaptureError
from vision_models.dual_camera_candidate import (
    build_refit_candidate_payload,
    load_dual_camera_candidate,
)

ROOT = Path(__file__).resolve().parents[2]
SEED_PATH = ROOT / "configs/vision/calibration/legacy_dual_camera_candidate.json"


def _generated_payload() -> dict[str, object]:
    seed = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    transform = np.asarray(seed["T_lumos_from_d435"], dtype=float)
    return build_refit_candidate_payload(
        seed_payload=seed,
        transform=transform,
        fit_dataset_id="sha256:" + "1" * 64,
        metrics={
            "samples": 12,
            "corners": 960,
            "median_px": 0.3,
            "p95_px": 0.8,
            "baseline_m": float(np.linalg.norm(transform[:3, 3])),
            "rotation_deg": 15.0,
            "nfev": 21,
        },
    )


def test_loads_legacy_and_content_addressed_refit_candidates(tmp_path: Path) -> None:
    legacy = load_dual_camera_candidate(SEED_PATH)
    assert legacy.provenance == "legacy_seed"
    assert legacy.executable is False

    payload = _generated_payload()
    path = tmp_path / "candidate.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    loaded = load_dual_camera_candidate(path)

    assert loaded.candidate_id == payload["candidate_id"]
    assert loaded.provenance == "charuco_fixed_intrinsics_refit"
    assert loaded.executable is False
    assert np.allclose(loaded.t_lumos_from_d435, payload["T_lumos_from_d435"])
    assert loaded.t_lumos_from_d435.flags.writeable is False


def test_rejects_tampered_refit_candidate(tmp_path: Path) -> None:
    payload = _generated_payload()
    payload["T_lumos_from_d435"][0][3] += 0.01  # type: ignore[index]
    path = tmp_path / "candidate.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(CalibrationCaptureError, match="integrity"):
        load_dual_camera_candidate(path)


def test_refit_candidate_does_not_copy_runtime_authority() -> None:
    seed = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    seed["robot_execution_enabled"] = True
    payload = build_refit_candidate_payload(
        seed_payload=seed,
        transform=seed["T_lumos_from_d435"],
        fit_dataset_id="sha256:" + "2" * 64,
        metrics={
            "samples": 12,
            "corners": 900,
            "median_px": 0.2,
            "p95_px": 0.7,
            "baseline_m": 0.14,
            "rotation_deg": 10.0,
            "nfev": 18,
        },
    )

    serialized = json.dumps(payload, sort_keys=True)
    assert payload["status"] == "candidate_only"
    assert payload["executable"] is False
    assert "robot_execution_enabled" not in serialized


def test_rejects_symlink_candidate(tmp_path: Path) -> None:
    real = tmp_path / "real.json"
    real.write_text(json.dumps(_generated_payload()), encoding="utf-8")
    link = tmp_path / "candidate.json"
    link.symlink_to(real)

    with pytest.raises(CalibrationCaptureError, match="symlink"):
        load_dual_camera_candidate(link)
