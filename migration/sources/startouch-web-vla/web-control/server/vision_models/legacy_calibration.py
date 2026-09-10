"""Offline audit for legacy calibration artifacts that must never authorize motion."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
from vision.geometry import validate_transform
from vision.types import InvalidDataError

MAX_LEGACY_SOURCE_BYTES = 8 * 1024 * 1024


class LegacyCalibrationError(InvalidDataError):
    """Raised when a legacy candidate cannot be audited deterministically."""


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise LegacyCalibrationError("legacy candidate is not finite JSON") from exc


def _content_id(value: Any) -> str:
    canonical = _canonical_json(value).encode("ascii")
    return f"sha256:{hashlib.sha256(canonical).hexdigest()}"


def _source_bytes(root: Path, filename: str) -> bytes:
    path = root / filename
    if path.is_symlink():
        raise LegacyCalibrationError(f"legacy source {filename} cannot be a symlink")
    if not path.exists():
        raise LegacyCalibrationError(f"legacy source {filename} is missing")
    if not path.is_file():
        raise LegacyCalibrationError(f"legacy source {filename} must be a regular file")
    try:
        size = path.stat().st_size
        if size > MAX_LEGACY_SOURCE_BYTES:
            raise LegacyCalibrationError(f"legacy source {filename} exceeds 8 MiB")
        return path.read_bytes()
    except OSError as exc:
        raise LegacyCalibrationError(f"legacy source {filename} cannot be read") from exc


def _source_json(root: Path, filename: str) -> tuple[dict[str, Any], str]:
    raw = _source_bytes(root, filename)
    try:
        payload = json.loads(
            raw.decode("utf-8"),
            parse_constant=lambda token: (_ for _ in ()).throw(
                LegacyCalibrationError(
                    f"legacy source {filename} contains non-finite {token}"
                )
            ),
        )
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise LegacyCalibrationError(f"legacy source {filename} is invalid JSON") from exc
    if not isinstance(payload, dict):
        raise LegacyCalibrationError(f"legacy source {filename} must contain an object")
    _canonical_json(payload)
    return payload, f"sha256:{hashlib.sha256(raw).hexdigest()}"


def _source_text(root: Path, filename: str) -> tuple[str, str]:
    raw = _source_bytes(root, filename)
    try:
        return raw.decode("utf-8"), f"sha256:{hashlib.sha256(raw).hexdigest()}"
    except UnicodeError as exc:
        raise LegacyCalibrationError(f"legacy source {filename} is not UTF-8") from exc


def _transform(payload: dict[str, Any], key: str, filename: str) -> np.ndarray:
    try:
        return validate_transform(payload[key])
    except (KeyError, TypeError, ValueError, InvalidDataError) as exc:
        raise LegacyCalibrationError(
            f"legacy source {filename} has an invalid {key} transform"
        ) from exc


def _samples(payload: dict[str, Any], filename: str) -> int:
    value = payload.get("pairs")
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise LegacyCalibrationError(f"legacy source {filename} has invalid pair count")
    return value


def _legacy_table_transform(payload: dict[str, Any]) -> tuple[np.ndarray, bool]:
    try:
        raw = np.asarray(payload["T_base_board"], dtype=float)
    except (KeyError, TypeError, ValueError) as exc:
        raise LegacyCalibrationError("legacy table transform is unreadable") from exc
    if (
        raw.shape != (4, 4)
        or not np.isfinite(raw).all()
        or not np.allclose(raw[3], [0.0, 0.0, 0.0, 1.0], atol=1e-12)
    ):
        raise LegacyCalibrationError("legacy table transform is not a finite 4x4 matrix")
    try:
        validate_transform(raw)
    except InvalidDataError:
        return np.array(raw, copy=True), False
    return np.array(raw, copy=True), True


def _handeye_record(
    root: Path,
    *,
    filename: str,
    transform_key: str,
) -> tuple[dict[str, Any], np.ndarray, bool]:
    payload, source_id = _source_json(root, filename)
    transform = _transform(payload, transform_key, filename)
    validation_present = isinstance(payload.get("validation"), dict)
    return (
        {
            "filename": filename,
            "source_id": source_id,
            "transform_key": transform_key,
            "transform": transform.tolist(),
            "samples": _samples(payload, filename),
            "validation_present": validation_present,
        },
        transform,
        validation_present,
    )


def _optional_homography_record(root: Path) -> dict[str, Any] | None:
    path = root / "desktop_calib_result.json"
    if not path.exists():
        return None
    payload, source_id = _source_json(root, path.name)
    homography = np.asarray(payload.get("H"), dtype=float)
    if homography.shape != (3, 3) or not np.isfinite(homography).all():
        raise LegacyCalibrationError("legacy desktop homography is invalid")
    inliers = payload.get("inliers")
    return {
        "filename": path.name,
        "source_id": source_id,
        "inliers": inliers if isinstance(inliers, int) and inliers >= 0 else None,
        "metric_3d_evidence": False,
    }


def _relative_geometry(transform: np.ndarray) -> dict[str, Any]:
    rotation = transform[:3, :3]
    return {
        "T_lumos_from_d435": transform.tolist(),
        "baseline_m": float(np.linalg.norm(transform[:3, 3])),
        "rotation_angle_deg": math.degrees(
            math.acos(
                float(np.clip((np.trace(rotation) - 1.0) / 2.0, -1.0, 1.0))
            )
        ),
    }


def audit_legacy_calibration_directory(root: Path | str) -> dict[str, Any]:
    """Create a content-addressed report while keeping every legacy result locked."""

    directory = Path(root)
    if directory.is_symlink():
        raise LegacyCalibrationError("legacy calibration directory cannot be a symlink")
    try:
        directory = directory.resolve(strict=True)
    except OSError as exc:
        raise LegacyCalibrationError("legacy calibration directory is missing") from exc
    if not directory.is_dir():
        raise LegacyCalibrationError("legacy calibration root must be a directory")

    lumos_record, t_flange_from_lumos, lumos_validated = _handeye_record(
        directory,
        filename="handeye_result.json",
        transform_key="T_flange_camera",
    )
    d435_record, t_flange_from_d435, d435_validated = _handeye_record(
        directory,
        filename="d435_handeye_result.json",
        transform_key="T_flange_d435cam",
    )
    table_payload, table_source_id = _source_json(directory, "desk_ref.json")
    t_base_from_board, table_transform_valid = _legacy_table_transform(table_payload)
    lumos_script, lumos_script_id = _source_text(directory, "handeye_calib.py")
    d435_script, d435_script_id = _source_text(directory, "d435_calibrate.py")

    reasons: list[str] = []
    if not lumos_validated or not d435_validated:
        reasons.append("independent_validation_missing")
    if "cv2.Rodrigues(np.array(euler" in lumos_script or (
        "cv2.Rodrigues(np.array(euler" in d435_script
    ):
        reasons.append("legacy_euler_rpy_passed_to_rodrigues")
    if (
        "T_cam_flange = handeye_tsai" in d435_script
        and "R_flange_cam = R_cam_flange.T" in d435_script
    ):
        reasons.append("legacy_d435_transform_direction_ambiguous")
    if "SEUCM" in lumos_script and "cv2.solvePnP" in lumos_script:
        reasons.append("legacy_lumos_seucm_processed_as_pinhole")
    if not table_transform_valid:
        reasons.append("legacy_table_transform_invalid")
    board_normal_base = t_base_from_board[:3, 2]
    normal_norm = float(np.linalg.norm(board_normal_base))
    normalized_normal_z = (
        0.0 if normal_norm <= 1e-12 else float(board_normal_base[2]) / normal_norm
    )
    if abs(normalized_normal_z) < math.cos(math.radians(45.0)):
        reasons.append("legacy_table_normal_implausible")

    desktop_homography = _optional_homography_record(directory)
    if desktop_homography is not None:
        reasons.append("legacy_desktop_homography_is_not_metric_3d_evidence")

    as_labeled = np.linalg.inv(t_flange_from_lumos) @ t_flange_from_d435
    d435_inversion_corrected = np.linalg.inv(t_flange_from_lumos) @ np.linalg.inv(
        t_flange_from_d435
    )
    seed_hypothesis = (
        "d435_extra_inversion_corrected"
        if "legacy_d435_transform_direction_ambiguous" in reasons
        else "as_labeled"
    )
    seed_transform = (
        d435_inversion_corrected if seed_hypothesis == "d435_extra_inversion_corrected"
        else as_labeled
    )
    report: dict[str, Any] = {
        "schema_version": 1,
        "status": "candidate_only",
        "validated": False,
        "executable": False,
        "sources": {
            "lumos_handeye": lumos_record,
            "d435_handeye": d435_record,
            "table_reference": {
                "filename": "desk_ref.json",
                "source_id": table_source_id,
                "transform_key": "T_base_board",
                "transform": t_base_from_board.tolist(),
            },
            "desktop_homography": desktop_homography,
            "provenance_scripts": {
                "lumos": {
                    "filename": "handeye_calib.py",
                    "source_id": lumos_script_id,
                },
                "d435": {
                    "filename": "d435_calibrate.py",
                    "source_id": d435_script_id,
                },
            },
        },
        "candidate_geometry": {
            "hypotheses": {
                "as_labeled": _relative_geometry(as_labeled),
                "d435_extra_inversion_corrected": _relative_geometry(
                    d435_inversion_corrected
                ),
            },
            "seed_hypothesis": seed_hypothesis,
            "seed_T_lumos_from_d435": seed_transform.tolist(),
            "seed_only": True,
        },
        "reasons": list(dict.fromkeys(reasons)),
        "required_replacement": "eucm_multicamera_plus_correct_rpy_handeye_and_table_validation",
    }
    report["candidate_id"] = _content_id(report)
    return report


__all__ = [
    "LegacyCalibrationError",
    "audit_legacy_calibration_directory",
]
