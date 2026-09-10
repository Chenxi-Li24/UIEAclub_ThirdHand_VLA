"""Assemble validated camera-chain and table results into runtime evidence."""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from vision.calibration_gate import audit_handeye_calibration
from vision.dual_camera import DualCameraCalibrationBundle

from vision_models.calibration_capture import CalibrationCaptureError
from vision_models.calibration_completion import ValidatedHandEyeResult
from vision_models.dual_camera_candidate import DualCameraCandidate
from vision_models.relative_validation_evidence import RelativeValidationEvidence
from vision_models.table_calibration import (
    TABLE_FIT_REQUIRED,
    TABLE_MAX_SAMPLES,
    TABLE_VALIDATION_REQUIRED,
)


def _canonical(payload: Any) -> bytes:
    try:
        return json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError) as exc:
        raise CalibrationCaptureError("foundation evidence must be finite JSON") from exc


def _content_id(payload: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(payload)).hexdigest()


def _valid_content_id(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 71
        and value.startswith("sha256:")
        and all(character in "0123456789abcdef" for character in value[7:])
    )


@dataclass(frozen=True)
class ValidatedTableResult:
    """Independently held-out table result with frozen calibration sources."""

    result_id: str
    candidate_source_id: str
    handeye_result_id: str
    calibration_id: str
    normal_base: tuple[float, float, float]
    offset_m: float
    fit_rmse_m: float
    validation_p95_m: float

    def __post_init__(self) -> None:
        identifiers = (
            self.result_id,
            self.candidate_source_id,
            self.handeye_result_id,
            self.calibration_id,
        )
        normal = np.asarray(self.normal_base, dtype=float)
        numeric = np.asarray(
            [self.offset_m, self.fit_rmse_m, self.validation_p95_m], dtype=float
        )
        if (
            any(not _valid_content_id(value) for value in identifiers)
            or normal.shape != (3,)
            or not np.isfinite(normal).all()
            or not np.isclose(np.linalg.norm(normal), 1.0, atol=1e-8)
            or normal[2] < math.cos(math.radians(15.0))
            or not np.isfinite(numeric).all()
            or not 0.0 < self.fit_rmse_m <= 0.005
            or not 0.0 <= self.validation_p95_m <= 0.008
        ):
            raise CalibrationCaptureError("validated table result is invalid")
        object.__setattr__(self, "normal_base", tuple(float(value) for value in normal))
        object.__setattr__(self, "offset_m", float(self.offset_m))
        object.__setattr__(self, "fit_rmse_m", float(self.fit_rmse_m))
        object.__setattr__(self, "validation_p95_m", float(self.validation_p95_m))


def _camera_bundle(
    candidate: DualCameraCandidate,
    relative: RelativeValidationEvidence,
    handeye: ValidatedHandEyeResult,
) -> tuple[DualCameraCalibrationBundle, dict[str, Any], dict[str, Any]]:
    if not isinstance(candidate, DualCameraCandidate):
        raise CalibrationCaptureError("typed dual-camera candidate is required")
    if not isinstance(relative, RelativeValidationEvidence) or not isinstance(
        handeye, ValidatedHandEyeResult
    ):
        raise CalibrationCaptureError("typed relative and hand-eye evidence is required")
    if relative.candidate_id != candidate.candidate_id:
        raise CalibrationCaptureError("relative validation candidate source changed")
    t_flange_from_lumos = handeye.t_flange_from_d435 @ np.linalg.inv(
        candidate.t_lumos_from_d435
    )
    relative_payload = {
        "schema_version": 1,
        "candidate_id": candidate.candidate_id,
        "relative_validation_id": relative.validation_id,
        "T_lumos_from_d435": candidate.t_lumos_from_d435.tolist(),
        "validation": {
            "reprojection_rmse_px": relative.lumos_reprojection_rmse_px,
            "position_rmse_m": relative.relative_position_rmse_m,
        },
    }
    handeye_payload = {
        "schema_version": 1,
        "candidate_id": candidate.candidate_id,
        "handeye_result_id": handeye.result_id,
        "handeye_dataset_id": handeye.dataset_id,
        "T_flange_from_lumos": t_flange_from_lumos.tolist(),
        "validation": {
            "reprojection_rmse_px": handeye.reprojection_rmse_px,
            "position_rmse_m": handeye.position_rmse_m,
        },
    }
    relative_audit = audit_handeye_calibration(
        relative_payload,
        "T_lumos_from_d435",
        max_reprojection_rmse_px=1.0,
        max_position_rmse_m=0.008,
    )
    handeye_audit = audit_handeye_calibration(
        handeye_payload,
        "T_flange_from_lumos",
        max_reprojection_rmse_px=1.0,
        max_position_rmse_m=0.010,
    )
    if not relative_audit.calibration.validated or not handeye_audit.calibration.validated:
        raise CalibrationCaptureError("foundation camera audits are not validated")
    bundle = DualCameraCalibrationBundle.from_audits(
        d435=candidate.d435,
        lumos=candidate.lumos,
        d435_to_lumos_audit=relative_audit,
        lumos_to_flange_audit=handeye_audit,
    )
    return bundle, relative_payload, handeye_payload


def foundation_calibration_id(
    candidate: DualCameraCandidate,
    relative: RelativeValidationEvidence,
    handeye: ValidatedHandEyeResult,
) -> str:
    """Return the immutable camera-chain ID needed before table solving."""

    bundle, _relative_payload, _handeye_payload = _camera_bundle(
        candidate, relative, handeye
    )
    return bundle.calibration.calibration_id


def build_foundation_payloads(
    candidate: DualCameraCandidate,
    relative: RelativeValidationEvidence,
    handeye: ValidatedHandEyeResult,
    table: ValidatedTableResult,
    *,
    robot_model_id: str = "startouch-fasttouch-v3",
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build the exact content-addressed schemas consumed by active-view runtime."""

    if not isinstance(table, ValidatedTableResult):
        raise CalibrationCaptureError("typed table evidence is required")
    if not isinstance(robot_model_id, str) or not robot_model_id or len(robot_model_id) > 128:
        raise CalibrationCaptureError("robot model ID is invalid")
    if (
        table.candidate_source_id != candidate.candidate_id
        or table.handeye_result_id != handeye.result_id
    ):
        raise CalibrationCaptureError("table calibration source changed")
    bundle, relative_payload, handeye_payload = _camera_bundle(
        candidate, relative, handeye
    )
    if table.calibration_id != bundle.calibration.calibration_id:
        raise CalibrationCaptureError("table calibration does not match camera foundation")
    camera: dict[str, Any] = {
        "schema_version": 1,
        "robot_model_id": robot_model_id,
        "d435": {
            "fx": candidate.d435.fx,
            "fy": candidate.d435.fy,
            "cx": candidate.d435.cx,
            "cy": candidate.d435.cy,
            "width": candidate.d435.width,
            "height": candidate.d435.height,
        },
        "lumos": {
            "fx": candidate.lumos.fx,
            "fy": candidate.lumos.fy,
            "cx": candidate.lumos.cx,
            "cy": candidate.lumos.cy,
            "alpha": candidate.lumos.alpha,
            "beta": candidate.lumos.beta,
            "width": candidate.lumos.width,
            "height": candidate.lumos.height,
        },
        "audits": {
            "d435_to_lumos": {
                "transform_key": "T_lumos_from_d435",
                "payload": relative_payload,
            },
            "lumos_to_flange": {
                "transform_key": "T_flange_from_lumos",
                "payload": handeye_payload,
            },
        },
        "validation": {
            "lumos_median_px": relative.lumos_median_px,
            "lumos_p95_px": relative.lumos_p95_px,
            "lumos_edge_p95_px": relative.lumos_edge_p95_px,
            "d435_to_lumos_target_p95_px": relative.lumos_p95_px,
            "desktop_plane_p95_m": table.validation_p95_m,
            "full_chain_static_p95_m": handeye.position_p95_m,
        },
    }
    camera["content_id"] = _content_id(camera)
    table_payload: dict[str, Any] = {
        "schema_version": 1,
        "normal_base": list(table.normal_base),
        "offset_m": table.offset_m,
        "position_rmse_m": table.fit_rmse_m,
        "calibration_id": table.calibration_id,
        "validated": True,
    }
    table_payload["content_id"] = _content_id(table_payload)
    return camera, table_payload


def load_validated_table_result(path: Path | str) -> ValidatedTableResult:
    """Load the strict held-out table solver output without weakening any gates."""

    source = Path(path)
    if source.is_symlink():
        raise CalibrationCaptureError("table result cannot be a symlink")
    try:
        source = source.resolve(strict=True)
        if not source.is_file() or source.stat().st_size > 1024 * 1024:
            raise CalibrationCaptureError("table result is unsafe")
        record = json.loads(source.read_text(encoding="utf-8"))
        _canonical(record)
    except CalibrationCaptureError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CalibrationCaptureError("table result cannot be parsed") from exc
    expected_keys = {
        "schema_version",
        "dataset_id",
        "candidate_source_id",
        "handeye_result_id",
        "calibration_id",
        "normal_base",
        "offset_m",
        "fit_samples",
        "validation_samples",
        "fit",
        "validation",
        "validated",
        "reasons",
        "content_id",
    }
    if not isinstance(record, dict) or set(record) != expected_keys:
        raise CalibrationCaptureError("table result keys are invalid")
    unsigned = dict(record)
    supplied_id = unsigned.pop("content_id")
    fit = record["fit"]
    validation = record["validation"]
    fit_samples = record["fit_samples"]
    validation_samples = record["validation_samples"]
    if (
        supplied_id != _content_id(unsigned)
        or record["schema_version"] != 1
        or record["validated"] is not True
        or record["reasons"] != []
        or isinstance(fit_samples, bool)
        or not isinstance(fit_samples, int)
        or fit_samples < TABLE_FIT_REQUIRED
        or isinstance(validation_samples, bool)
        or not isinstance(validation_samples, int)
        or validation_samples < TABLE_VALIDATION_REQUIRED
        or fit_samples + validation_samples > TABLE_MAX_SAMPLES
        or not isinstance(fit, dict)
        or set(fit) != {"rmse_m"}
        or not isinstance(validation, dict)
        or set(validation) != {"p95_m"}
        or not _valid_content_id(record["dataset_id"])
    ):
        raise CalibrationCaptureError("table result is not independently validated")
    try:
        return ValidatedTableResult(
            result_id=supplied_id,
            candidate_source_id=record["candidate_source_id"],
            handeye_result_id=record["handeye_result_id"],
            calibration_id=record["calibration_id"],
            normal_base=record["normal_base"],
            offset_m=record["offset_m"],
            fit_rmse_m=fit["rmse_m"],
            validation_p95_m=validation["p95_m"],
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise CalibrationCaptureError("validated table result is invalid") from exc


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(
                json.dumps(
                    payload,
                    sort_keys=True,
                    indent=2,
                    ensure_ascii=True,
                    allow_nan=False,
                ).encode("ascii")
                + b"\n"
            )
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def write_foundation_payloads(
    output: Path | str,
    camera_payload: dict[str, Any],
    table_payload: dict[str, Any],
) -> tuple[Path, Path]:
    """Atomically persist generated payloads, then round-trip validate them."""

    if not isinstance(camera_payload, dict) or not isinstance(table_payload, dict):
        raise CalibrationCaptureError("foundation payloads must be objects")
    camera_unsigned = dict(camera_payload)
    table_unsigned = dict(table_payload)
    camera_id = camera_unsigned.pop("content_id", None)
    table_id = table_unsigned.pop("content_id", None)
    if camera_id != _content_id(camera_unsigned) or table_id != _content_id(
        table_unsigned
    ):
        raise CalibrationCaptureError("foundation payload integrity check failed")
    root = Path(output)
    if root.is_symlink():
        raise CalibrationCaptureError("foundation output cannot be a symlink")
    camera_path = root / "camera.json"
    table_path = root / "table.json"
    _atomic_json(camera_path, camera_payload)
    _atomic_json(table_path, table_payload)
    try:
        from vision_models.active_view_catalog import load_active_view_foundation

        load_active_view_foundation(
            camera_path,
            table_path,
            evidence_dir=root,
        )
    except (OSError, TypeError, ValueError) as exc:
        raise CalibrationCaptureError(
            "generated foundation failed runtime round-trip validation"
        ) from exc
    return camera_path, table_path


__all__ = [
    "ValidatedTableResult",
    "build_foundation_payloads",
    "foundation_calibration_id",
    "load_validated_table_result",
    "write_foundation_payloads",
]
