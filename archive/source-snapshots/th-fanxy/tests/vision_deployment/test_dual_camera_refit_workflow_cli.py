from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from vision.geometry import make_transform
from vision_models.calibration_targets import load_calibration_target
from vision_models.dual_camera_refit_capture import (
    DualCameraFitObservation,
    append_fit_observation,
)

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/vision/dual_camera_refit_workflow.py"
SEED = ROOT / "configs/vision/calibration/legacy_dual_camera_candidate.json"
TARGET_PATH = ROOT / "configs/vision/calibration/charuco_12x9.yaml"
SEED_ID = json.loads(SEED.read_text(encoding="utf-8"))["candidate_id"]


def _load_script_namespace() -> dict[str, object]:
    namespace: dict[str, object] = {
        "__name__": "dual_camera_refit_workflow_test",
        "__file__": str(SCRIPT),
    }
    exec(compile(SCRIPT.read_text(encoding="utf-8"), SCRIPT, "exec"), namespace)
    return namespace


def _fit_observation(x_m: float) -> DualCameraFitObservation:
    count = 24
    objects = np.column_stack(
        (
            np.linspace(0.0, 0.15, count),
            np.linspace(0.0, 0.10, count),
            np.zeros(count),
        )
    )
    return DualCameraFitObservation(
        point_ids=tuple(range(count)),
        object_points_m=objects,
        d435_image_points_px=np.column_stack(
            (np.linspace(100, 500, count), np.linspace(100, 400, count))
        ),
        lumos_image_points_px=np.column_stack(
            (np.linspace(200, 1000, count), np.linspace(200, 1050, count))
        ),
        t_d435_from_board=make_transform(np.eye(3), [x_m, 0.0, 0.65]),
        d435_reprojection_rmse_px=0.3,
        old_candidate_lumos_p95_px=100.0,
    )


def _status(namespace: dict[str, object], root: Path) -> dict[str, object]:
    return namespace["workflow_status"](
        fit_output=root / "fit",
        validation_output=root / "validation",
        candidate_output=root / "candidate.json",
        seed_path=SEED,
        target_path=TARGET_PATH,
        action="status",
    )


def test_status_transitions_from_fit_collect_to_fit_ready(tmp_path: Path) -> None:
    namespace = _load_script_namespace()
    initial = _status(namespace, tmp_path)
    assert initial["phase"] == "fit_collect"
    assert initial["progress"] == {"current": 0, "required": 12, "purpose": "fit"}
    assert initial["safety"] == {
        "motion_or_robot_access": False,
        "executable": False,
    }

    target = load_calibration_target(TARGET_PATH)
    for index in range(12):
        append_fit_observation(
            tmp_path / "fit",
            sample_id=f"fit-{index + 1:02d}",
            seed_candidate_id=SEED_ID,
            lumos_jpeg=f"lumos-{index}".encode(),
            d435_jpeg=f"d435-{index}".encode(),
            result=_fit_observation(index * 0.015),
            target=target,
            capture_skew_ms=10.0,
        )

    ready = _status(namespace, tmp_path)
    assert ready["phase"] == "fit_ready"
    assert ready["progress"] == {"current": 12, "required": 12, "purpose": "fit"}
    assert ready["sample"]["id"] == "fit-12"


def test_status_cli_is_bounded_and_motion_free(tmp_path: Path) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--action",
            "status",
            "--fit-output",
            str(tmp_path / "fit"),
            "--validation-output",
            str(tmp_path / "validation"),
            "--candidate-output",
            str(tmp_path / "candidate.json"),
            "--seed",
            str(SEED),
            "--target",
            str(TARGET_PATH),
            "--json",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr
    report = json.loads(completed.stdout)
    assert report["ok"] is True
    assert report["action"] == "status"
    assert report["phase"] == "fit_collect"
    assert report["safety"]["motion_or_robot_access"] is False
    assert str(tmp_path) not in completed.stdout
    source = SCRIPT.read_text(encoding="utf-8").lower()
    for forbidden in (
        "startouch",
        "pyrealsense2",
        "move_joint",
        "move_l(",
        "can.interface",
    ):
        assert forbidden not in source


def test_workflow_error_classification_is_stable() -> None:
    namespace = _load_script_namespace()
    classify = namespace["classify_workflow_error"]

    assert classify(ValueError("fit solver requires exactly 12 samples")) == "fit_not_ready"
    assert classify(ValueError("sample failed the pixel gate")) == "validation_pixel_gate_failed"
    assert classify(ValueError("capture skew exceeds 100 ms")) == "capture_skew_failed"
    assert classify(ValueError("ChArUco target was not detected")) == "target_not_visible"
