"""Content-addressed calibration audits and robot SDK pose conversion."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any

import numpy as np

from .geometry import make_transform, rpy_xyz_to_matrix, validate_transform
from .types import CalibrationRef, InvalidDataError


@dataclass(frozen=True, init=False)
class CalibrationAudit:
    calibration: CalibrationRef
    transform: np.ndarray
    transform_key: str
    reasons: tuple[str, ...]
    canonical_payload: str

    def __new__(cls, *_args, **_kwargs):
        raise TypeError("CalibrationAudit instances are created by audit functions")

    @classmethod
    def _create(
        cls,
        *,
        calibration: CalibrationRef,
        transform: np.ndarray,
        transform_key: str,
        reasons: tuple[str, ...],
        canonical_payload: str,
    ) -> "CalibrationAudit":
        result = object.__new__(cls)
        transform = np.array(transform, dtype=float, copy=True)
        transform.setflags(write=False)
        if not transform_key:
            raise InvalidDataError("calibration audit transform_key cannot be empty")
        object.__setattr__(result, "calibration", calibration)
        object.__setattr__(result, "transform", transform)
        object.__setattr__(result, "transform_key", transform_key)
        object.__setattr__(result, "reasons", tuple(reasons))
        object.__setattr__(result, "canonical_payload", canonical_payload)
        return result

    def verify_integrity(self) -> None:
        try:
            payload = json.loads(self.canonical_payload)
        except (TypeError, json.JSONDecodeError) as error:
            raise InvalidDataError("calibration audit payload is invalid") from error
        canonical = _canonical_payload(payload)
        if canonical != self.canonical_payload:
            raise InvalidDataError("calibration audit payload is not canonical")
        if _content_id_from_canonical(canonical) != self.calibration.calibration_id:
            raise InvalidDataError("calibration audit content ID mismatch")
        try:
            payload_transform = validate_transform(payload[self.transform_key])
        except (KeyError, InvalidDataError, TypeError, ValueError) as error:
            raise InvalidDataError("calibration audit transform provenance is invalid") from error
        if not np.array_equal(payload_transform, self.transform):
            raise InvalidDataError("calibration audit transform does not match its payload")
        expected = audit_handeye_calibration(payload, self.transform_key)
        if (
            expected.calibration != self.calibration
            or expected.reasons != self.reasons
            or not np.array_equal(expected.transform, self.transform)
        ):
            raise InvalidDataError("calibration audit result does not match its payload")


def sdk_pose_transform(position_m: Any, rpy_rad: Any) -> np.ndarray:
    """Build T_base_from_flange using Startouch's documented RPY convention."""

    return make_transform(rpy_xyz_to_matrix(rpy_rad), position_m)


def _canonical_payload(payload: dict[str, Any]) -> str:
    try:
        return json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise InvalidDataError("calibration payload must be canonical JSON") from error


def _content_id_from_canonical(canonical_payload: str) -> str:
    return f"sha256:{hashlib.sha256(canonical_payload.encode('utf-8')).hexdigest()}"


def _content_id(payload: dict[str, Any]) -> str:
    return _content_id_from_canonical(_canonical_payload(payload))


def audit_handeye_calibration(
    payload: dict[str, Any],
    transform_key: str,
    *,
    max_camera_offset_m: float = 0.25,
    max_reprojection_rmse_px: float = 1.0,
    max_position_rmse_m: float = 0.010,
) -> CalibrationAudit:
    """Reject hand-eye files without independent metrics or physical plausibility."""

    if not isinstance(payload, dict) or not transform_key:
        raise InvalidDataError("calibration payload and transform key are required")
    limits = np.asarray(
        [max_camera_offset_m, max_reprojection_rmse_px, max_position_rmse_m],
        dtype=float,
    )
    if not np.isfinite(limits).all() or np.any(limits <= 0.0):
        raise InvalidDataError("calibration audit limits must be finite and positive")
    canonical_payload = _canonical_payload(payload)
    calibration_id = _content_id_from_canonical(canonical_payload)
    reasons: list[str] = []
    try:
        transform = validate_transform(payload[transform_key])
    except (KeyError, InvalidDataError, TypeError, ValueError):
        transform = np.eye(4)
        reasons.append("transform_invalid")

    if float(np.linalg.norm(transform[:3, 3])) > max_camera_offset_m:
        reasons.append("camera_offset_implausible")

    validation = payload.get("validation")
    reprojection_rmse_px = None
    if not isinstance(validation, dict):
        reasons.append("independent_validation_missing")
    else:
        reprojection = validation.get("reprojection_rmse_px")
        position = validation.get("position_rmse_m")
        try:
            reprojection_rmse_px = float(reprojection)
            position_rmse_m = float(position)
        except (TypeError, ValueError):
            reasons.append("independent_validation_missing")
        else:
            if (
                not np.isfinite([reprojection_rmse_px, position_rmse_m]).all()
                or reprojection_rmse_px < 0.0
                or position_rmse_m < 0.0
            ):
                reasons.append("independent_validation_invalid")
                reprojection_rmse_px = None
            else:
                if reprojection_rmse_px > max_reprojection_rmse_px:
                    reasons.append("reprojection_error_too_high")
                if position_rmse_m > max_position_rmse_m:
                    reasons.append("position_error_too_high")

    validated = not reasons
    return CalibrationAudit._create(
        calibration=CalibrationRef(
            calibration_id=calibration_id,
            validated=validated,
            reprojection_rmse_px=reprojection_rmse_px if validated else None,
            validation_notes=tuple(reasons),
        ),
        transform=transform,
        transform_key=transform_key,
        reasons=tuple(reasons),
        canonical_payload=canonical_payload,
    )
