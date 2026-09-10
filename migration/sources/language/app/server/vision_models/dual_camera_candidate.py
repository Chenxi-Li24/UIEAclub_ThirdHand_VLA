"""Typed, non-executable dual-camera calibration candidate records."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from vision.camera_models import PinholeCamera, SeucmCamera
from vision.geometry import validate_transform

from vision_models.calibration_capture import CalibrationCaptureError

MAX_CANDIDATE_BYTES = 1024 * 1024
_CONTENT_ID = re.compile(r"sha256:[0-9a-f]{64}\Z")
_LEGACY_SEED_HYPOTHESIS = "d435_extra_inversion_corrected"


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")


def _content_id(value: dict[str, Any]) -> str:
    return f"sha256:{hashlib.sha256(_canonical(value)).hexdigest()}"


def _valid_content_id(value: Any) -> bool:
    return isinstance(value, str) and _CONTENT_ID.fullmatch(value) is not None


@dataclass(frozen=True)
class DualCameraCandidate:
    """Validated calibration geometry with no execution authority."""

    candidate_id: str
    provenance: str
    t_lumos_from_d435: np.ndarray = field(compare=False, repr=False)
    d435: PinholeCamera = field(compare=False)
    lumos: SeucmCamera = field(compare=False)
    executable: bool = False

    def __post_init__(self) -> None:
        if not _valid_content_id(self.candidate_id):
            raise CalibrationCaptureError("dual-camera candidate ID is invalid")
        if self.provenance not in {
            "legacy_seed",
            "charuco_fixed_intrinsics_refit",
        }:
            raise CalibrationCaptureError("dual-camera candidate provenance is invalid")
        if self.executable is not False:
            raise CalibrationCaptureError("dual-camera candidate must be non-executable")
        try:
            transform = validate_transform(self.t_lumos_from_d435)
        except (TypeError, ValueError) as exc:
            raise CalibrationCaptureError(
                "dual-camera candidate transform is invalid"
            ) from exc
        transform.setflags(write=False)
        object.__setattr__(self, "t_lumos_from_d435", transform)


def _read_payload(path: Path) -> dict[str, Any]:
    if path.is_symlink():
        raise CalibrationCaptureError("dual-camera candidate cannot be a symlink")
    try:
        resolved = path.resolve(strict=True)
        if not resolved.is_file() or resolved.stat().st_size > MAX_CANDIDATE_BYTES:
            raise CalibrationCaptureError("dual-camera candidate is unsafe")
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CalibrationCaptureError(
            "dual-camera candidate cannot be parsed"
        ) from exc
    if not isinstance(payload, dict):
        raise CalibrationCaptureError("dual-camera candidate must be a JSON object")
    return payload


def _camera_models(payload: dict[str, Any]) -> tuple[PinholeCamera, SeucmCamera]:
    d435_payload = payload.get("d435")
    lumos_payload = payload.get("lumos")
    if not isinstance(d435_payload, dict) or not isinstance(lumos_payload, dict):
        raise CalibrationCaptureError("dual-camera candidate camera records are missing")
    if (
        d435_payload.get("model") != "pinhole"
        or d435_payload.get("distortion_model") != "none"
        or lumos_payload.get("model") != "eucm"
    ):
        raise CalibrationCaptureError("dual-camera candidate models are unsupported")
    try:
        d435 = PinholeCamera(
            fx=d435_payload["fx"],
            fy=d435_payload["fy"],
            cx=d435_payload["cx"],
            cy=d435_payload["cy"],
            width=d435_payload["width"],
            height=d435_payload["height"],
        )
        lumos = SeucmCamera(
            fx=lumos_payload["fx"],
            fy=lumos_payload["fy"],
            cx=lumos_payload["cx"],
            cy=lumos_payload["cy"],
            alpha=lumos_payload["alpha"],
            beta=lumos_payload["beta"],
            width=lumos_payload["width"],
            height=lumos_payload["height"],
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise CalibrationCaptureError(
            "dual-camera candidate intrinsics are invalid"
        ) from exc
    return d435, lumos


def load_dual_camera_candidate(path: Path | str) -> DualCameraCandidate:
    """Load an audited legacy seed or a content-addressed refit candidate."""

    payload = _read_payload(Path(path))
    if payload.get("status") != "candidate_only" or payload.get("executable") is not False:
        raise CalibrationCaptureError("dual-camera candidate is not seed-only")
    schema = payload.get("schema_version")
    if schema == 1:
        if (
            payload.get("seed_hypothesis") != _LEGACY_SEED_HYPOTHESIS
            or not _valid_content_id(payload.get("candidate_id"))
        ):
            raise CalibrationCaptureError("legacy candidate is not an approved seed")
        provenance = "legacy_seed"
    elif schema == 2:
        supplied_id = payload.get("candidate_id")
        unsigned = {key: value for key, value in payload.items() if key != "candidate_id"}
        if (
            payload.get("provenance") != "charuco_fixed_intrinsics_refit"
            or not _valid_content_id(payload.get("source_fit_dataset_id"))
            or supplied_id != _content_id(unsigned)
        ):
            raise CalibrationCaptureError("dual-camera candidate integrity check failed")
        provenance = "charuco_fixed_intrinsics_refit"
    else:
        raise CalibrationCaptureError("dual-camera candidate schema is unsupported")
    d435, lumos = _camera_models(payload)
    try:
        transform = validate_transform(payload["T_lumos_from_d435"])
    except (KeyError, TypeError, ValueError) as exc:
        raise CalibrationCaptureError(
            "dual-camera candidate geometry is invalid"
        ) from exc
    return DualCameraCandidate(
        candidate_id=payload["candidate_id"],
        provenance=provenance,
        t_lumos_from_d435=transform,
        d435=d435,
        lumos=lumos,
    )


def build_refit_candidate_payload(
    *,
    seed_payload: dict[str, Any],
    transform: Any,
    fit_dataset_id: str,
    metrics: dict[str, Any],
) -> dict[str, Any]:
    """Create the bounded schema-v2 payload; caller performs physical fit gates."""

    if not isinstance(seed_payload, dict):
        raise CalibrationCaptureError("dual-camera seed payload is invalid")
    if not _valid_content_id(fit_dataset_id):
        raise CalibrationCaptureError("fit dataset ID is invalid")
    try:
        relative = validate_transform(transform)
    except (TypeError, ValueError) as exc:
        raise CalibrationCaptureError("refit transform is invalid") from exc
    d435 = seed_payload.get("d435")
    lumos = seed_payload.get("lumos")
    if not isinstance(d435, dict) or not isinstance(lumos, dict):
        raise CalibrationCaptureError("dual-camera seed camera records are missing")
    required_metrics = {
        "samples",
        "corners",
        "median_px",
        "p95_px",
        "baseline_m",
        "rotation_deg",
        "nfev",
    }
    if set(metrics) != required_metrics:
        raise CalibrationCaptureError("refit metrics have an invalid schema")
    numeric = np.asarray(list(metrics.values()), dtype=float)
    if not np.isfinite(numeric).all() or np.any(numeric < 0.0):
        raise CalibrationCaptureError("refit metrics must be finite and non-negative")
    unsigned: dict[str, Any] = {
        "schema_version": 2,
        "status": "candidate_only",
        "executable": False,
        "provenance": "charuco_fixed_intrinsics_refit",
        "source_fit_dataset_id": fit_dataset_id,
        "solver": {
            "name": "scipy.optimize.least_squares",
            "method": "trf",
            "loss": "soft_l1",
            "f_scale": 2.0,
            "x_scale": "jac",
            "optimized_parameters": "T_lumos_from_d435_6dof",
            "fixed_intrinsics": True,
        },
        "metrics": dict(metrics),
        "T_lumos_from_d435": relative.tolist(),
        "lumos": dict(lumos),
        "d435": dict(d435),
    }
    return {**unsigned, "candidate_id": _content_id(unsigned)}


__all__ = [
    "DualCameraCandidate",
    "build_refit_candidate_payload",
    "load_dual_camera_candidate",
]
