#!/usr/bin/env python3
"""Run the motion-free ChArUco dual-camera refit and held-out validation workflow."""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import cv2
import numpy as np

SCRIPT_ROOT = Path(__file__).resolve().parent
SERVER_ROOT = Path(__file__).resolve().parents[2] / "web-control" / "server"
for import_root in (SCRIPT_ROOT, SERVER_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from validate_legacy_dual_camera import (  # noqa: E402
    _validated_manifest as load_validation_manifest,
)
from validate_legacy_dual_camera import capture_one as capture_validation_one  # noqa: E402
from validate_legacy_dual_camera import public_validation_report  # noqa: E402
from vision.camera_models import PinholeCamera, SeucmCamera  # noqa: E402
from vision_models.calibration_capture import CalibrationCaptureError  # noqa: E402
from vision_models.calibration_targets import (  # noqa: E402
    CalibrationTargetSpec,
    detect_target_corners,
    load_calibration_target,
)
from vision_models.dual_camera_candidate import (  # noqa: E402
    DualCameraCandidate,
    load_dual_camera_candidate,
)
from vision_models.dual_camera_refit_capture import (  # noqa: E402
    FIT_MANIFEST_NAME,
    append_fit_observation,
    evaluate_fit_pair,
    fit_summary,
    load_fit_manifest,
)
from vision_models.dual_camera_refit_solver import (  # noqa: E402
    solve_dual_camera_refit,
    write_refit_candidate,
)
from vision_models.read_only_http import fetch_jpeg  # noqa: E402

_ERROR_MESSAGES = {
    "target_not_visible": "标定板未同时被两台相机识别",
    "pose_not_distinct": "请明显移动或倾斜标定板后重试",
    "insufficient_common_points": "两台相机共同识别的角点不足",
    "d435_pixel_gate_failed": "D435 标定板重投影误差超限",
    "capture_skew_failed": "两台相机抓帧时差超过 100 ms",
    "camera_unavailable": "至少一台相机当前不可用",
    "fit_not_ready": "必须先采满 12 个合格拟合姿态",
    "solve_failed": "新外参求解未通过质量门禁",
    "candidate_not_ready": "新外参尚未生成",
    "validation_pixel_gate_failed": "独立验证像素误差超限",
    "capture_rejected": "本次标定操作被安全门禁拒绝",
}


def _sample_from_fit(manifest: dict[str, Any] | None) -> dict[str, Any] | None:
    if manifest is None or not manifest["observations"]:
        return None
    latest = manifest["observations"][-1]
    return {
        "id": latest["sample_id"],
        "purpose": "fit",
        "common_points": latest["common_points"],
        "d435_reprojection_rmse_px": latest["d435_reprojection_rmse_px"],
        "lumos_reprojection_median_px": None,
        "lumos_reprojection_p95_px": latest.get("old_candidate_lumos_p95_px"),
        "capture_skew_ms": latest["capture_skew_ms"],
        "passes_pixel_gate": True,
    }


def _candidate_metrics(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        metrics = payload["metrics"]
        return {
            "samples": metrics["samples"],
            "corners": metrics["corners"],
            "median_px": metrics["median_px"],
            "p95_px": metrics["p95_px"],
            "baseline_m": metrics["baseline_m"],
            "rotation_deg": metrics["rotation_deg"],
            "nfev": metrics["nfev"],
        }
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise CalibrationCaptureError("generated candidate metrics are invalid") from exc


def workflow_status(
    *,
    fit_output: Path | str,
    validation_output: Path | str,
    candidate_output: Path | str,
    seed_path: Path | str,
    target_path: Path | str,
    action: str,
) -> dict[str, Any]:
    """Resolve phase only from verified disk artifacts and return bounded fields."""

    seed = load_dual_camera_candidate(seed_path)
    target = load_calibration_target(target_path)
    fit = load_fit_manifest(
        fit_output,
        target=target,
        seed_candidate_id=seed.candidate_id,
    )
    candidate_path = Path(candidate_output)
    sample = _sample_from_fit(fit)
    fit_metrics = None
    relative_validated = False
    if candidate_path.exists():
        candidate = load_dual_camera_candidate(candidate_path)
        fit_metrics = _candidate_metrics(candidate_path)
        validation = load_validation_manifest(
            validation_output,
            candidate=candidate,
            target=target,
        )
        validation_report = public_validation_report(validation, action="status")
        summary = validation_report["summary"]
        progress = {
            "current": summary["samples"],
            "required": summary["required_samples"],
            "purpose": "validation",
        }
        phase = (
            "relative_validated"
            if summary["relative_extrinsic_validated"]
            else "validation_collect"
        )
        sample = validation_report["sample"]
        if sample is not None:
            sample = {**sample, "purpose": "validation"}
        relative_validated = summary["relative_extrinsic_validated"]
        blockers = summary["remaining_blockers"]
    else:
        summary = fit_summary(fit) if fit is not None else {
            "phase": "fit_collect",
            "samples": 0,
            "required_samples": 12,
        }
        phase = summary["phase"]
        progress = {
            "current": summary["samples"],
            "required": summary["required_samples"],
            "purpose": "fit",
        }
        blockers = [
            "relative_extrinsic_refit_missing",
            "handeye_validation_missing",
            "table_validation_missing",
        ]
    return {
        "schema_version": 1,
        "ok": True,
        "action": action,
        "phase": phase,
        "progress": progress,
        "sample": sample,
        "fit_metrics": fit_metrics,
        "relative_extrinsic_validated": relative_validated,
        "remaining_blockers": blockers,
        "safety": {"motion_or_robot_access": False, "executable": False},
    }


def _loopback_url(value: str, name: str) -> str:
    parsed = urlparse(value)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise CalibrationCaptureError(f"{name} must be a loopback HTTP URL")
    return value


def _timed_fetch(url: str, jpeg_fetch: Callable[[str], bytes]) -> tuple[int, bytes]:
    started = time.monotonic_ns()
    jpeg = jpeg_fetch(url)
    finished = time.monotonic_ns()
    return (started + finished) // 2, jpeg


def _decode(
    jpeg: bytes,
    *,
    camera: PinholeCamera | SeucmCamera,
    name: str,
) -> np.ndarray:
    image = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise CalibrationCaptureError(f"{name} JPEG cannot be decoded")
    if image.shape != (camera.height, camera.width):
        raise CalibrationCaptureError(f"{name} image size does not match calibration")
    return image


def capture_fit_one(
    output: Path | str,
    *,
    sample_id: str,
    target: CalibrationTargetSpec,
    seed: DualCameraCandidate,
    lumos_url: str,
    d435_url: str,
    jpeg_fetch: Callable[[str], bytes] = fetch_jpeg,
) -> Path:
    """Fetch both read-only frames concurrently and append one gated fit pose."""

    lumos_url = _loopback_url(lumos_url, "Lumos camera")
    d435_url = _loopback_url(d435_url, "D435 camera")
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="dual-camera-refit") as executor:
        lumos_future = executor.submit(_timed_fetch, lumos_url, jpeg_fetch)
        d435_future = executor.submit(_timed_fetch, d435_url, jpeg_fetch)
        lumos_timestamp, lumos_jpeg = lumos_future.result()
        d435_timestamp, d435_jpeg = d435_future.result()
    lumos_image = _decode(lumos_jpeg, camera=seed.lumos, name="Lumos")
    d435_image = _decode(d435_jpeg, camera=seed.d435, name="D435")
    result = evaluate_fit_pair(
        d435=seed.d435,
        lumos=seed.lumos,
        d435_detection=detect_target_corners(d435_image, target),
        lumos_detection=detect_target_corners(lumos_image, target),
        old_candidate=seed,
    )
    return append_fit_observation(
        output,
        sample_id=sample_id,
        seed_candidate_id=seed.candidate_id,
        lumos_jpeg=lumos_jpeg,
        d435_jpeg=d435_jpeg,
        result=result,
        target=target,
        capture_skew_ms=abs(lumos_timestamp - d435_timestamp) / 1_000_000.0,
    )


def classify_workflow_error(error: BaseException) -> str:
    message = str(error).lower()
    if "not distinct" in message:
        return "pose_not_distinct"
    if "pixel gate" in message:
        return "validation_pixel_gate_failed"
    if "skew" in message or "100 ms" in message:
        return "capture_skew_failed"
    if "common point" in message:
        return "insufficient_common_points"
    if "d435" in message and ("rmse" in message or "reprojection" in message):
        return "d435_pixel_gate_failed"
    if "charuco" in message or "aprilgrid" in message or "target" in message:
        return "target_not_visible"
    if "exactly 12" in message or "12 samples" in message:
        return "fit_not_ready"
    if "candidate" in message and ("missing" in message or "not exist" in message):
        return "candidate_not_ready"
    if any(word in message for word in ("request failed", "timed out", "unavailable")):
        return "camera_unavailable"
    if any(word in message for word in ("optimization", "refit", "baseline", "rotation")):
        return "solve_failed"
    return "capture_rejected"


def _public_error(code: str) -> dict[str, Any]:
    safe_code = code if code in _ERROR_MESSAGES else "capture_rejected"
    return {
        "schema_version": 1,
        "ok": False,
        "error": {"code": safe_code, "message": _ERROR_MESSAGES[safe_code]},
    }


def _fit_content_id(output: Path) -> str:
    try:
        stored = json.loads((output / FIT_MANIFEST_NAME).read_text(encoding="utf-8"))
        value = stored["content_id"]
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise CalibrationCaptureError("fit manifest content ID is missing") from exc
    if not isinstance(value, str) or not value.startswith("sha256:") or len(value) != 71:
        raise CalibrationCaptureError("fit manifest content ID is invalid")
    return value


def _execute(arguments: argparse.Namespace) -> dict[str, Any]:
    action = arguments.action.replace("-", "_")
    status_args = {
        "fit_output": arguments.fit_output,
        "validation_output": arguments.validation_output,
        "candidate_output": arguments.candidate_output,
        "seed_path": arguments.seed,
        "target_path": arguments.target,
    }
    current = workflow_status(**status_args, action="status")
    seed = load_dual_camera_candidate(arguments.seed)
    target = load_calibration_target(arguments.target)
    if action == "status":
        return current
    if action == "capture_fit":
        if current["phase"] != "fit_collect":
            raise CalibrationCaptureError("fit capture is not available in this phase")
        sample_id = f"fit-{current['progress']['current'] + 1:02d}"
        capture_fit_one(
            arguments.fit_output,
            sample_id=sample_id,
            target=target,
            seed=seed,
            lumos_url=arguments.lumos_url,
            d435_url=arguments.d435_url,
        )
    elif action == "solve":
        if current["phase"] != "fit_ready":
            raise CalibrationCaptureError("refit solver requires exactly 12 samples")
        manifest = load_fit_manifest(
            arguments.fit_output,
            target=target,
            seed_candidate_id=seed.candidate_id,
        )
        if manifest is None:
            raise CalibrationCaptureError("refit solver requires exactly 12 samples")
        result = solve_dual_camera_refit(manifest, seed)
        seed_payload = json.loads(Path(arguments.seed).read_text(encoding="utf-8"))
        write_refit_candidate(
            arguments.candidate_output,
            result=result,
            seed_payload=seed_payload,
            fit_dataset_id=_fit_content_id(Path(arguments.fit_output)),
        )
    elif action == "capture_validation":
        if current["phase"] != "validation_collect":
            raise CalibrationCaptureError("generated candidate is not ready for validation")
        candidate = load_dual_camera_candidate(arguments.candidate_output)
        sample_id = f"pose-{current['progress']['current'] + 1:02d}"
        capture_validation_one(
            arguments.validation_output,
            sample_id=sample_id,
            target=target,
            candidate=candidate,
            lumos_url=arguments.lumos_url,
            d435_url=arguments.d435_url,
            require_pass=True,
            require_distinct=True,
        )
    else:
        raise CalibrationCaptureError("workflow action is invalid")
    return workflow_status(**status_args, action=action)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--action",
        required=True,
        choices=("status", "capture-fit", "solve", "capture-validation"),
    )
    parser.add_argument("--fit-output", required=True, type=Path)
    parser.add_argument("--validation-output", required=True, type=Path)
    parser.add_argument("--candidate-output", required=True, type=Path)
    parser.add_argument(
        "--seed",
        type=Path,
        default=Path("configs/vision/calibration/legacy_dual_camera_candidate.json"),
    )
    parser.add_argument(
        "--target",
        type=Path,
        default=Path("configs/vision/calibration/charuco_12x9.yaml"),
    )
    parser.add_argument("--lumos-url", default="http://127.0.0.1:3001/frame_raw.jpg")
    parser.add_argument("--d435-url", default="http://127.0.0.1:3100/camera_d435_raw")
    parser.add_argument("--json", action="store_true")
    arguments = parser.parse_args()
    try:
        report = _execute(arguments)
        print(json.dumps(report, sort_keys=True, ensure_ascii=False))
        return 0
    except (CalibrationCaptureError, OSError, ValueError) as error:
        code = classify_workflow_error(error)
        if arguments.json:
            print(json.dumps(_public_error(code), sort_keys=True, ensure_ascii=False))
        else:
            print(_ERROR_MESSAGES[code], file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
