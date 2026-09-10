"""Typed adapters and evidence assembly for calibration completion."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from vision.camera_models import PinholeCamera
from vision.geometry import validate_transform

from vision_models.calibration_capture import CalibrationCaptureError
from vision_models.dual_camera_candidate import load_dual_camera_candidate


@dataclass(frozen=True)
class HandEyeCaptureInput:
    """The minimal immutable camera contract required by hand-eye capture."""

    d435: PinholeCamera
    distortion_coeffs: tuple[float, ...]
    source_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.d435, PinholeCamera):
            raise CalibrationCaptureError("hand-eye D435 model is invalid")
        if self.distortion_coeffs != ():
            raise CalibrationCaptureError("hand-eye capture requires rectified D435 RGB")
        if (
            not isinstance(self.source_id, str)
            or len(self.source_id) != 71
            or not self.source_id.startswith("sha256:")
        ):
            raise CalibrationCaptureError("hand-eye calibration source ID is invalid")


def load_handeye_capture_input(path: Path | str) -> HandEyeCaptureInput:
    """Adapt one validated refit candidate without granting execution authority."""

    candidate = load_dual_camera_candidate(path)
    if candidate.provenance != "charuco_fixed_intrinsics_refit":
        raise CalibrationCaptureError("hand-eye capture requires a refit candidate")
    return HandEyeCaptureInput(
        d435=candidate.d435,
        distortion_coeffs=(),
        source_id=candidate.candidate_id,
    )


@dataclass(frozen=True)
class ValidatedHandEyeResult:
    t_flange_from_d435: np.ndarray
    result_id: str
    dataset_id: str
    position_rmse_m: float
    position_p95_m: float
    reprojection_rmse_px: float
    audit_payload: dict

    def __post_init__(self) -> None:
        transform = validate_transform(self.t_flange_from_d435)
        metrics = np.asarray(
            [self.position_rmse_m, self.position_p95_m, self.reprojection_rmse_px],
            dtype=float,
        )
        if (
            any(
                not isinstance(identifier, str)
                or len(identifier) != 71
                or not identifier.startswith("sha256:")
                for identifier in (self.result_id, self.dataset_id)
            )
            or not np.isfinite(metrics).all()
            or np.any(metrics < 0.0)
            or self.position_p95_m > 0.010
            or self.reprojection_rmse_px > 1.0
            or not isinstance(self.audit_payload, dict)
        ):
            raise CalibrationCaptureError("validated hand-eye result is invalid")
        transform.setflags(write=False)
        object.__setattr__(self, "t_flange_from_d435", transform)
        object.__setattr__(self, "position_rmse_m", float(self.position_rmse_m))
        object.__setattr__(self, "position_p95_m", float(self.position_p95_m))
        object.__setattr__(self, "reprojection_rmse_px", float(self.reprojection_rmse_px))
        object.__setattr__(self, "audit_payload", dict(self.audit_payload))


def _canonical(payload: object) -> bytes:
    try:
        return json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError) as exc:
        raise CalibrationCaptureError("hand-eye result must be finite JSON") from exc


def load_validated_handeye_result(path: Path | str) -> ValidatedHandEyeResult:
    source = Path(path)
    if source.is_symlink():
        raise CalibrationCaptureError("hand-eye result cannot be a symlink")
    try:
        source = source.resolve(strict=True)
        if not source.is_file() or source.stat().st_size > 1024 * 1024:
            raise CalibrationCaptureError("hand-eye result is unsafe")
        record = json.loads(source.read_text(encoding="utf-8"))
    except CalibrationCaptureError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CalibrationCaptureError("hand-eye result cannot be parsed") from exc
    expected_keys = {
        "schema_version",
        "dataset_id",
        "method",
        "T_flange_from_d435",
        "fit_samples",
        "validation_samples",
        "validation",
        "validated",
        "reasons",
        "audit_payload",
        "content_id",
    }
    if not isinstance(record, dict) or set(record) != expected_keys:
        raise CalibrationCaptureError("hand-eye result keys are invalid")
    payload = dict(record)
    supplied_id = payload.pop("content_id")
    expected_id = "sha256:" + hashlib.sha256(_canonical(payload)).hexdigest()
    validation = payload.get("validation")
    if (
        supplied_id != expected_id
        or payload.get("schema_version") != 1
        or payload.get("validated") is not True
        or payload.get("reasons") != []
        or isinstance(payload.get("fit_samples"), bool)
        or not isinstance(payload.get("fit_samples"), int)
        or payload["fit_samples"] < 8
        or isinstance(payload.get("validation_samples"), bool)
        or not isinstance(payload.get("validation_samples"), int)
        or payload["validation_samples"] < 3
        or not isinstance(validation, dict)
        or set(validation)
        != {"position_rmse_m", "position_p95_m", "reprojection_rmse_px"}
    ):
        raise CalibrationCaptureError("hand-eye result is not independently validated")
    try:
        return ValidatedHandEyeResult(
            t_flange_from_d435=payload["T_flange_from_d435"],
            result_id=supplied_id,
            dataset_id=payload["dataset_id"],
            position_rmse_m=validation["position_rmse_m"],
            position_p95_m=validation["position_p95_m"],
            reprojection_rmse_px=validation["reprojection_rmse_px"],
            audit_payload=payload["audit_payload"],
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise CalibrationCaptureError("hand-eye result is invalid") from exc


__all__ = [
    "HandEyeCaptureInput",
    "ValidatedHandEyeResult",
    "load_handeye_capture_input",
    "load_validated_handeye_result",
]
