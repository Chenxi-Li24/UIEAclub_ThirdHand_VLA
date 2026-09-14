#!/usr/bin/env python3
"""Validate a legacy Lumos-to-D435 seed from one read-only target pair."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import cv2
import numpy as np

SERVER_ROOT = Path(__file__).resolve().parents[2] / "web-control" / "server"
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

from vision.camera_models import PinholeCamera, SeucmCamera  # noqa: E402
from vision_models.calibration_capture import (  # noqa: E402
    CalibrationCaptureError,
)
from vision_models.calibration_targets import (  # noqa: E402
    AprilGridSpec,
    CalibrationTargetSpec,
    CharucoSpec,
    detect_target_corners,
    load_calibration_target,
)
from vision_models.dual_camera_candidate import (  # noqa: E402
    DualCameraCandidate,
    load_dual_camera_candidate,
)
from vision_models.legacy_dual_camera_validation import (  # noqa: E402
    LegacyCandidatePairResult,
    evaluate_legacy_candidate_pair,
    pose_is_distinct,
    summarize_legacy_candidate,
)
from vision_models.read_only_http import fetch_jpeg  # noqa: E402

MAX_MANIFEST_BYTES = 16 * 1024 * 1024
MAX_OBSERVATIONS = 64
_SAMPLE_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_PUBLIC_SUMMARY_KEYS = (
    "samples",
    "required_samples",
    "passing_pairs",
    "distinct_poses",
    "relative_extrinsic_validated",
    "remaining_blockers",
)


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _valid_content_id(value: Any) -> bool:
    return bool(
        isinstance(value, str)
        and re.fullmatch(r"sha256:[0-9a-f]{64}", value) is not None
    )


def _read_json(path: Path, *, name: str) -> dict[str, Any]:
    if path.is_symlink():
        raise CalibrationCaptureError(f"{name} cannot be a symlink")
    try:
        resolved = path.resolve(strict=True)
        if not resolved.is_file() or resolved.stat().st_size > MAX_MANIFEST_BYTES:
            raise CalibrationCaptureError(f"{name} is unsafe")
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CalibrationCaptureError(f"{name} cannot be parsed") from exc
    if not isinstance(payload, dict):
        raise CalibrationCaptureError(f"{name} must contain a JSON object")
    return payload


def _result_from_record(record: dict[str, Any]) -> LegacyCandidatePairResult:
    metrics = record.get("metrics")
    if not isinstance(metrics, dict):
        raise CalibrationCaptureError("legacy validation observation metrics are invalid")
    try:
        return LegacyCandidatePairResult(
            common_points=metrics["common_points"],
            d435_reprojection_rmse_px=metrics["d435_reprojection_rmse_px"],
            lumos_reprojection_median_px=metrics["lumos_reprojection_median_px"],
            lumos_reprojection_p95_px=metrics["lumos_reprojection_p95_px"],
            passes_pixel_gate=metrics["passes_pixel_gate"],
            lumos_errors_px=np.asarray(metrics["lumos_errors_px"], dtype=float),
            t_d435_from_board=metrics["T_d435_from_board"],
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise CalibrationCaptureError(
            "legacy validation observation metrics are invalid"
        ) from exc


def _load_manifest(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    payload = _read_json(path, name="legacy validation manifest")
    supplied = payload.pop("content_id", None)
    expected = f"sha256:{hashlib.sha256(_canonical(payload)).hexdigest()}"
    if supplied != expected:
        raise CalibrationCaptureError("legacy validation manifest integrity check failed")
    if (
        payload.get("schema_version") != 1
        or payload.get("motion_or_robot_access") is not False
        or not isinstance(payload.get("observations"), list)
    ):
        raise CalibrationCaptureError("legacy validation manifest is invalid")
    return payload


def _validated_manifest(
    output: Path | str,
    *,
    candidate: DualCameraCandidate,
    target: CalibrationTargetSpec,
) -> dict[str, Any] | None:
    manifest = _load_manifest(Path(output) / "legacy-dual-camera-validation.json")
    if manifest is None:
        return None
    if manifest.get("candidate_id") != candidate.candidate_id:
        raise CalibrationCaptureError("legacy candidate changed during validation")
    if manifest.get("target") != target.to_json():
        raise CalibrationCaptureError("calibration target changed during validation")
    return manifest


def _empty_summary() -> dict[str, Any]:
    return {
        "samples": 0,
        "required_samples": 10,
        "passing_pairs": 0,
        "distinct_poses": 0,
        "relative_extrinsic_validated": False,
        "remaining_blockers": [
            "pose_diversity_insufficient",
            "relative_extrinsic_validation_failed",
            "handeye_validation_missing",
            "table_validation_missing",
        ],
    }


def public_validation_report(
    manifest: dict[str, Any] | None,
    *,
    action: str,
) -> dict[str, Any]:
    """Build the bounded process-to-Web response without paths or command details."""

    if action not in {"status", "capture"}:
        raise CalibrationCaptureError("public report action is invalid")
    sample = None
    if manifest is None:
        summary = _empty_summary()
    else:
        observations = manifest.get("observations")
        candidate_id = manifest.get("candidate_id")
        if not isinstance(observations, list) or not _valid_content_id(candidate_id):
            raise CalibrationCaptureError("legacy validation manifest is invalid")
        if observations:
            complete_summary = summarize_legacy_candidate(
                (_result_from_record(item) for item in observations),
                candidate_id=candidate_id,
            )
            latest = observations[-1]
            latest_metrics = latest["metrics"]
            sample = {
                "id": latest["sample_id"],
                "common_points": latest_metrics["common_points"],
                "d435_reprojection_rmse_px": latest_metrics[
                    "d435_reprojection_rmse_px"
                ],
                "lumos_reprojection_median_px": latest_metrics[
                    "lumos_reprojection_median_px"
                ],
                "lumos_reprojection_p95_px": latest_metrics[
                    "lumos_reprojection_p95_px"
                ],
                "capture_skew_ms": latest.get("capture_skew_ms"),
                "passes_pixel_gate": latest_metrics["passes_pixel_gate"],
            }
            summary = {key: complete_summary[key] for key in _PUBLIC_SUMMARY_KEYS}
        else:
            summary = _empty_summary()
    return {
        "schema_version": 1,
        "ok": True,
        "action": action,
        "sample": sample,
        "summary": summary,
        "safety": {
            "motion_or_robot_access": False,
            "executable": False,
        },
    }


def classify_capture_error(error: BaseException) -> str:
    """Map internal failures to stable, path-free browser error codes."""

    message = str(error).lower()
    if "not distinct" in message:
        return "pose_not_distinct"
    if "pixel gate" in message:
        return "pixel_gate_failed"
    if "both cameras must share" in message or "common point" in message:
        return "insufficient_common_points"
    if "charuco" in message or "aprilgrid" in message or "target points" in message:
        return "target_not_visible"
    if any(word in message for word in ("request failed", "timed out", "unavailable")):
        return "camera_unavailable"
    return "capture_rejected"


def _public_error(code: str) -> dict[str, Any]:
    messages = {
        "pose_not_distinct": "请明显移动或倾斜标定板后重试",
        "target_not_visible": "标定板未同时被两台相机完整识别",
        "pixel_gate_failed": "当前图像误差超过验证门限",
        "insufficient_common_points": "两台相机共同识别的角点不足",
        "camera_unavailable": "至少一台相机当前不可用",
        "capture_rejected": "本次采集被安全门禁拒绝",
    }
    return {
        "schema_version": 1,
        "ok": False,
        "error": {"code": code, "message": messages[code]},
    }


def append_observation(
    output: Path | str,
    *,
    sample_id: str,
    candidate_id: str,
    lumos_jpeg: bytes,
    d435_jpeg: bytes,
    result: LegacyCandidatePairResult,
    target: CalibrationTargetSpec,
    capture_skew_ms: float | None = None,
    require_pass: bool = False,
    require_distinct: bool = False,
) -> Path:
    """Atomically append one immutable, non-executable validation observation."""

    if not isinstance(sample_id, str) or _SAMPLE_ID_PATTERN.fullmatch(sample_id) is None:
        raise CalibrationCaptureError("sample ID is invalid")
    if not _valid_content_id(candidate_id):
        raise CalibrationCaptureError("legacy candidate ID is invalid")
    if not isinstance(lumos_jpeg, bytes) or not lumos_jpeg:
        raise CalibrationCaptureError("Lumos JPEG is empty")
    if not isinstance(d435_jpeg, bytes) or not d435_jpeg:
        raise CalibrationCaptureError("D435 JPEG is empty")
    if not isinstance(result, LegacyCandidatePairResult):
        raise CalibrationCaptureError("typed legacy validation result is required")
    if not isinstance(target, (AprilGridSpec, CharucoSpec)):
        raise CalibrationCaptureError("typed calibration target is required")
    if not isinstance(require_pass, bool) or not isinstance(require_distinct, bool):
        raise CalibrationCaptureError("capture gate flags are invalid")
    if capture_skew_ms is not None and (
        isinstance(capture_skew_ms, bool)
        or not np.isfinite(capture_skew_ms)
        or not 0.0 <= capture_skew_ms <= 5000.0
    ):
        raise CalibrationCaptureError("capture skew is invalid")

    root = Path(output)
    manifest_path = root / "legacy-dual-camera-validation.json"
    manifest = _load_manifest(manifest_path)
    if manifest is None:
        manifest = {
            "schema_version": 1,
            "candidate_id": candidate_id,
            "target": target.to_json(),
            "motion_or_robot_access": False,
            "observations": [],
        }
    if manifest.get("candidate_id") != candidate_id:
        raise CalibrationCaptureError("legacy candidate changed during validation")
    if manifest.get("target") != target.to_json():
        raise CalibrationCaptureError("calibration target changed during validation")
    observations = manifest["observations"]
    if any(
        isinstance(item, dict) and item.get("sample_id") == sample_id
        for item in observations
    ):
        raise CalibrationCaptureError("sample ID is duplicated")
    if len(observations) >= MAX_OBSERVATIONS:
        raise CalibrationCaptureError("legacy validation cannot exceed 64 observations")
    if require_pass and not result.passes_pixel_gate:
        raise CalibrationCaptureError("sample failed the pixel gate")
    if require_distinct and not pose_is_distinct(
        result,
        (_result_from_record(item) for item in observations),
    ):
        raise CalibrationCaptureError("board pose is not distinct from existing evidence")

    lumos_relative = Path("images/lumos") / f"{sample_id}.jpg"
    d435_relative = Path("images/d435") / f"{sample_id}.jpg"
    lumos_path = root / lumos_relative
    d435_path = root / d435_relative
    if lumos_path.exists() or d435_path.exists():
        raise CalibrationCaptureError("sample image already exists")
    _atomic_write(lumos_path, lumos_jpeg)
    _atomic_write(d435_path, d435_jpeg)
    observation: dict[str, Any] = {
        "sample_id": sample_id,
        "lumos_image": lumos_relative.as_posix(),
        "lumos_image_sha256": hashlib.sha256(lumos_jpeg).hexdigest(),
        "d435_image": d435_relative.as_posix(),
        "d435_image_sha256": hashlib.sha256(d435_jpeg).hexdigest(),
        "metrics": {
            "common_points": result.common_points,
            "d435_reprojection_rmse_px": result.d435_reprojection_rmse_px,
            "lumos_reprojection_median_px": result.lumos_reprojection_median_px,
            "lumos_reprojection_p95_px": result.lumos_reprojection_p95_px,
            "passes_pixel_gate": result.passes_pixel_gate,
            "lumos_errors_px": result.lumos_errors_px.tolist(),
            "T_d435_from_board": result.t_d435_from_board.tolist(),
        },
    }
    if capture_skew_ms is not None:
        observation["capture_skew_ms"] = float(capture_skew_ms)
    observations.append(observation)
    manifest["summary"] = summarize_legacy_candidate(
        (_result_from_record(item) for item in observations),
        candidate_id=candidate_id,
    )
    stored = dict(manifest)
    stored["content_id"] = f"sha256:{hashlib.sha256(_canonical(manifest)).hexdigest()}"
    _atomic_write(
        manifest_path,
        json.dumps(stored, sort_keys=True, indent=2, ensure_ascii=True).encode("ascii") + b"\n",
    )
    return manifest_path


def _loopback_http_url(value: str, name: str) -> str:
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


def _decode(jpeg: bytes, *, camera: PinholeCamera | SeucmCamera, name: str) -> np.ndarray:
    image = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise CalibrationCaptureError(f"{name} JPEG cannot be decoded")
    if image.shape != (camera.height, camera.width):
        raise CalibrationCaptureError(
            f"{name} image size {image.shape[1]}x{image.shape[0]} does not match calibration"
        )
    return image


def capture_one(
    output: Path | str,
    *,
    sample_id: str,
    target: CalibrationTargetSpec,
    candidate: DualCameraCandidate,
    lumos_url: str,
    d435_url: str,
    jpeg_fetch: Callable[[str], bytes] = fetch_jpeg,
    require_pass: bool = False,
    require_distinct: bool = False,
) -> Path:
    """Fetch both cameras concurrently, score the seed, and append evidence."""

    if not isinstance(candidate, DualCameraCandidate):
        raise CalibrationCaptureError("typed target and legacy candidate are required")
    lumos_url = _loopback_http_url(lumos_url, "Lumos camera")
    d435_url = _loopback_http_url(d435_url, "D435 camera")
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="legacy-validation") as executor:
        lumos_future = executor.submit(_timed_fetch, lumos_url, jpeg_fetch)
        d435_future = executor.submit(_timed_fetch, d435_url, jpeg_fetch)
        lumos_timestamp, lumos_jpeg = lumos_future.result()
        d435_timestamp, d435_jpeg = d435_future.result()
    lumos_image = _decode(lumos_jpeg, camera=candidate.lumos, name="Lumos")
    d435_image = _decode(d435_jpeg, camera=candidate.d435, name="D435")
    result = evaluate_legacy_candidate_pair(
        d435=candidate.d435,
        lumos=candidate.lumos,
        t_lumos_from_d435=candidate.t_lumos_from_d435,
        d435_detection=detect_target_corners(d435_image, target),
        lumos_detection=detect_target_corners(lumos_image, target),
    )
    return append_observation(
        output,
        sample_id=sample_id,
        candidate_id=candidate.candidate_id,
        lumos_jpeg=lumos_jpeg,
        d435_jpeg=d435_jpeg,
        result=result,
        target=target,
        capture_skew_ms=abs(lumos_timestamp - d435_timestamp) / 1_000_000.0,
        require_pass=require_pass,
        require_distinct=require_distinct,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--sample-id")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--require-pass", action="store_true")
    parser.add_argument("--require-distinct", action="store_true")
    parser.add_argument(
        "--candidate",
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
    arguments = parser.parse_args()
    try:
        if arguments.status and arguments.sample_id is not None:
            raise CalibrationCaptureError("status mode cannot include a sample ID")
        if not arguments.status and arguments.sample_id is None:
            raise CalibrationCaptureError("capture mode requires a sample ID")
        candidate = load_dual_camera_candidate(arguments.candidate)
        target = load_calibration_target(arguments.target)
        if arguments.status:
            manifest = _validated_manifest(
                arguments.output,
                candidate=candidate,
                target=target,
            )
            report = public_validation_report(manifest, action="status")
            if arguments.json:
                print(json.dumps(report, sort_keys=True, ensure_ascii=False))
            else:
                summary = report["summary"]
                print(
                    f"progress={summary['samples']}/{summary['required_samples']} "
                    f"relative_extrinsic_validated="
                    f"{str(summary['relative_extrinsic_validated']).lower()} "
                    "executable=false"
                )
            return 0

        manifest_path = capture_one(
            arguments.output,
            sample_id=arguments.sample_id,
            target=target,
            candidate=candidate,
            lumos_url=arguments.lumos_url,
            d435_url=arguments.d435_url,
            require_pass=arguments.require_pass,
            require_distinct=arguments.require_distinct,
        )
        manifest = _validated_manifest(
            arguments.output,
            candidate=candidate,
            target=target,
        )
        report = public_validation_report(manifest, action="capture")
        if arguments.json:
            print(json.dumps(report, sort_keys=True, ensure_ascii=False))
        else:
            stored = json.loads(manifest_path.read_text(encoding="utf-8"))
            latest = stored["observations"][-1]
            metrics = latest["metrics"]
            summary = stored["summary"]
            print(
                f"sample={latest['sample_id']} common_points={metrics['common_points']} "
                f"d435_rmse_px={metrics['d435_reprojection_rmse_px']:.3f} "
                f"lumos_p95_px={metrics['lumos_reprojection_p95_px']:.3f} "
                f"pair_pass={str(metrics['passes_pixel_gate']).lower()}"
            )
            print(
                f"progress={summary['samples']}/{summary['required_samples']} "
                f"relative_extrinsic_validated="
                f"{str(summary['relative_extrinsic_validated']).lower()} "
                "executable=false"
            )
            print(f"manifest={manifest_path} content_id={stored['content_id']}")
        return 0
    except (CalibrationCaptureError, OSError, ValueError) as error:
        code = classify_capture_error(error)
        if arguments.json:
            print(json.dumps(_public_error(code), sort_keys=True, ensure_ascii=False))
        else:
            print(f"legacy dual-camera validation rejected: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
