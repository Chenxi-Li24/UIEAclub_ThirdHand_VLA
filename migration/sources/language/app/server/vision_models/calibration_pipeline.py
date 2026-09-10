"""Kalibr import and OpenCV hand-eye validation without hardware ownership."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import yaml
from vision.camera_models import PinholeCamera, SeucmCamera
from vision.geometry import validate_transform
from vision.types import InvalidDataError

MAX_CALIBRATION_BYTES = 16 * 1024 * 1024


class CalibrationPipelineError(InvalidDataError):
    """Raised when calibration input or its mature solver backend is unavailable."""


def _finite_vector(value: Any, length: int, name: str) -> np.ndarray:
    try:
        result = np.asarray(value, dtype=float)
    except (TypeError, ValueError) as exc:
        raise CalibrationPipelineError(f"{name} must contain {length} finite values") from exc
    if result.shape != (length,) or not np.isfinite(result).all():
        raise CalibrationPipelineError(f"{name} must contain {length} finite values")
    return result


def _resolution(value: Any, name: str) -> tuple[int, int]:
    if (
        not isinstance(value, list)
        or len(value) != 2
        or any(isinstance(item, bool) or not isinstance(item, int) or item <= 0 for item in value)
    ):
        raise CalibrationPipelineError(f"{name} must be [width, height]")
    return value[0], value[1]


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CalibrationPipelineError(f"{name} must be an object")
    return value


def _read_yaml(path: Path | str) -> tuple[dict[str, Any], str]:
    source = Path(path)
    if source.is_symlink():
        raise CalibrationPipelineError("Kalibr camchain cannot be a symlink")
    try:
        source = source.resolve(strict=True)
        if not source.is_file() or source.stat().st_size > MAX_CALIBRATION_BYTES:
            raise CalibrationPipelineError("Kalibr camchain is missing or too large")
        raw = source.read_bytes()
        payload = yaml.safe_load(raw.decode("utf-8"))
    except CalibrationPipelineError:
        raise
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise CalibrationPipelineError("Kalibr camchain cannot be parsed") from exc
    return _mapping(payload, "Kalibr camchain"), f"sha256:{hashlib.sha256(raw).hexdigest()}"


@dataclass(frozen=True)
class KalibrDualCameraCalibration:
    lumos: SeucmCamera
    d435: PinholeCamera
    t_d435_from_lumos: np.ndarray = field(compare=False, repr=False)
    t_lumos_from_d435: np.ndarray = field(compare=False, repr=False)
    d435_distortion_model: str
    d435_distortion_coeffs: tuple[float, ...]
    source_id: str
    runtime_compatible: bool
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        forward = validate_transform(self.t_d435_from_lumos)
        inverse = validate_transform(self.t_lumos_from_d435)
        if not np.allclose(forward @ inverse, np.eye(4), atol=1e-9):
            raise CalibrationPipelineError("Kalibr camera transforms are not inverses")
        forward.setflags(write=False)
        inverse.setflags(write=False)
        object.__setattr__(self, "t_d435_from_lumos", forward)
        object.__setattr__(self, "t_lumos_from_d435", inverse)


def load_kalibr_camchain(path: Path | str) -> KalibrDualCameraCalibration:
    """Load official camchain ordering: cam1.T_cn_cnm1 takes cam0 into cam1."""

    payload, source_id = _read_yaml(path)
    cam0 = _mapping(payload.get("cam0"), "cam0")
    cam1 = _mapping(payload.get("cam1"), "cam1")
    if cam0.get("camera_model") != "eucm":
        raise CalibrationPipelineError("cam0 must be the Lumos eucm camera")
    if cam1.get("camera_model") != "pinhole":
        raise CalibrationPipelineError("cam1 must be the D435 pinhole camera")
    lumos_values = _finite_vector(cam0.get("intrinsics"), 6, "cam0 intrinsics")
    d435_values = _finite_vector(cam1.get("intrinsics"), 4, "cam1 intrinsics")
    lumos_width, lumos_height = _resolution(cam0.get("resolution"), "cam0 resolution")
    d435_width, d435_height = _resolution(cam1.get("resolution"), "cam1 resolution")
    if cam0.get("distortion_model") != "none" or cam0.get("distortion_coeffs") != []:
        raise CalibrationPipelineError("cam0 eucm must use the official none distortion model")
    d435_distortion_model = cam1.get("distortion_model")
    if d435_distortion_model not in {"none", "radtan", "equi"}:
        raise CalibrationPipelineError("cam1 distortion model is unsupported")
    raw_coefficients = cam1.get("distortion_coeffs")
    if not isinstance(raw_coefficients, list):
        raise CalibrationPipelineError("cam1 distortion coefficients must be a list")
    coefficients = tuple(float(item) for item in raw_coefficients)
    if not np.isfinite(coefficients).all():
        raise CalibrationPipelineError("cam1 distortion coefficients must be finite")
    if d435_distortion_model == "none" and coefficients:
        raise CalibrationPipelineError("cam1 none distortion must have no coefficients")
    try:
        t_d435_from_lumos = validate_transform(cam1["T_cn_cnm1"])
    except (KeyError, TypeError, ValueError, InvalidDataError) as exc:
        raise CalibrationPipelineError("cam1 T_cn_cnm1 is invalid") from exc
    reasons = () if d435_distortion_model == "none" else (
        "d435_runtime_rectification_required",
    )
    return KalibrDualCameraCalibration(
        lumos=SeucmCamera(
            fx=float(lumos_values[2]),
            fy=float(lumos_values[3]),
            cx=float(lumos_values[4]),
            cy=float(lumos_values[5]),
            alpha=float(lumos_values[0]),
            beta=float(lumos_values[1]),
            width=lumos_width,
            height=lumos_height,
        ),
        d435=PinholeCamera(
            fx=float(d435_values[0]),
            fy=float(d435_values[1]),
            cx=float(d435_values[2]),
            cy=float(d435_values[3]),
            width=d435_width,
            height=d435_height,
        ),
        t_d435_from_lumos=t_d435_from_lumos,
        t_lumos_from_d435=np.linalg.inv(t_d435_from_lumos),
        d435_distortion_model=str(d435_distortion_model),
        d435_distortion_coeffs=coefficients,
        source_id=source_id,
        runtime_compatible=not reasons,
        reasons=reasons,
    )


def _canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError) as exc:
        raise CalibrationPipelineError("hand-eye manifest must be canonical JSON") from exc


def load_handeye_dataset(
    path: Path | str,
) -> tuple[tuple[HandEyeSample, ...], str]:
    """Load a content-addressed capture manifest and verify every retained image."""

    source = Path(path)
    if source.is_symlink():
        raise CalibrationPipelineError("hand-eye manifest cannot be a symlink")
    try:
        source = source.resolve(strict=True)
        if not source.is_file() or source.stat().st_size > MAX_CALIBRATION_BYTES:
            raise CalibrationPipelineError("hand-eye manifest is missing or too large")
        manifest = json.loads(source.read_text(encoding="utf-8"))
    except CalibrationPipelineError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CalibrationPipelineError("hand-eye manifest cannot be parsed") from exc
    if not isinstance(manifest, dict):
        raise CalibrationPipelineError("hand-eye manifest must be an object")
    expected_keys = {
        "schema_version",
        "camera",
        "camchain_source_id",
        "target",
        "robot_state_access",
        "motion_command_access",
        "samples",
        "content_id",
    }
    if set(manifest) != expected_keys:
        raise CalibrationPipelineError("hand-eye manifest keys are invalid")
    supplied_id = manifest.pop("content_id")
    expected_id = f"sha256:{hashlib.sha256(_canonical_json(manifest)).hexdigest()}"
    if supplied_id != expected_id:
        raise CalibrationPipelineError("hand-eye manifest integrity check failed")
    schema_version = manifest["schema_version"]
    if (
        schema_version not in {1, 2}
        or manifest["camera"] != "d435_rgb_raw"
        or manifest["robot_state_access"] != "read_only_status"
        or manifest["motion_command_access"] is not False
    ):
        raise CalibrationPipelineError("hand-eye manifest provenance is invalid")
    camchain_id = manifest["camchain_source_id"]
    if (
        not isinstance(camchain_id, str)
        or len(camchain_id) != 71
        or not camchain_id.startswith("sha256:")
    ):
        raise CalibrationPipelineError("hand-eye camchain source ID is invalid")
    records = manifest["samples"]
    if not isinstance(records, list):
        raise CalibrationPipelineError("hand-eye samples must be a list")
    root = source.parent.resolve()
    samples = []
    detected_count_key = "detected_tags" if schema_version == 1 else "detected_points"
    expected_sample_keys = {
        "sample_id",
        "split",
        "image",
        "image_sha256",
        "robot_state_timestamp_ms",
        "joints_deg",
        "T_base_from_flange",
        "T_d435_from_board",
        detected_count_key,
        "board_reprojection_rmse_px",
    }
    for index, record in enumerate(records):
        if not isinstance(record, dict) or set(record) != expected_sample_keys:
            raise CalibrationPipelineError(f"hand-eye sample {index} keys are invalid")
        relative = record["image"]
        if not isinstance(relative, str) or not relative:
            raise CalibrationPipelineError("hand-eye image path is invalid")
        image = root / relative
        if image.is_symlink():
            raise CalibrationPipelineError("hand-eye image provenance is invalid")
        try:
            resolved = image.resolve(strict=True)
            resolved.relative_to(root)
            raw_image = resolved.read_bytes()
        except (OSError, ValueError) as exc:
            raise CalibrationPipelineError("hand-eye image provenance is invalid") from exc
        image_hash = record["image_sha256"]
        if not isinstance(image_hash, str) or hashlib.sha256(raw_image).hexdigest() != image_hash:
            raise CalibrationPipelineError("hand-eye image provenance is invalid")
        detected_count = record[detected_count_key]
        timestamp = record["robot_state_timestamp_ms"]
        joints = _finite_vector(record["joints_deg"], 6, "hand-eye joints")
        if (
            isinstance(detected_count, bool)
            or not isinstance(detected_count, int)
            or detected_count < 8
            or isinstance(timestamp, bool)
            or not isinstance(timestamp, int)
            or not np.isfinite(joints).all()
        ):
            raise CalibrationPipelineError("hand-eye sample quality provenance is invalid")
        try:
            samples.append(
                HandEyeSample(
                    sample_id=record["sample_id"],
                    t_base_from_flange=record["T_base_from_flange"],
                    t_d435_from_board=record["T_d435_from_board"],
                    board_reprojection_rmse_px=record["board_reprojection_rmse_px"],
                    split=record["split"],
                )
            )
        except (InvalidDataError, TypeError, ValueError) as exc:
            raise CalibrationPipelineError(f"hand-eye sample {index} is invalid") from exc
    return tuple(samples), str(supplied_id)


@dataclass(frozen=True)
class HandEyeSample:
    sample_id: str
    t_base_from_flange: np.ndarray = field(compare=False, repr=False)
    t_d435_from_board: np.ndarray = field(compare=False, repr=False)
    board_reprojection_rmse_px: float
    split: str

    def __post_init__(self) -> None:
        if not isinstance(self.sample_id, str) or not self.sample_id or len(self.sample_id) > 128:
            raise CalibrationPipelineError("hand-eye sample ID is invalid")
        base = validate_transform(self.t_base_from_flange)
        board = validate_transform(self.t_d435_from_board)
        reprojection = float(self.board_reprojection_rmse_px)
        if not math.isfinite(reprojection) or reprojection < 0.0:
            raise CalibrationPipelineError("board reprojection RMSE must be non-negative")
        if self.split not in {"fit", "validation"}:
            raise CalibrationPipelineError("hand-eye sample split must be fit or validation")
        base.setflags(write=False)
        board.setflags(write=False)
        object.__setattr__(self, "t_base_from_flange", base)
        object.__setattr__(self, "t_d435_from_board", board)
        object.__setattr__(self, "board_reprojection_rmse_px", reprojection)


@dataclass(frozen=True)
class HandEyeResult:
    t_flange_from_d435: np.ndarray = field(compare=False, repr=False)
    method: str
    fit_samples: int
    validation_samples: int
    position_rmse_m: float
    position_p95_m: float
    reprojection_rmse_px: float
    validated: bool
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        transform = validate_transform(self.t_flange_from_d435)
        transform.setflags(write=False)
        object.__setattr__(self, "t_flange_from_d435", transform)


def _rotation_angle(rotation: np.ndarray) -> float:
    return math.acos(float(np.clip((np.trace(rotation) - 1.0) / 2.0, -1.0, 1.0)))


def _validate_pose_diversity(samples: tuple[HandEyeSample, ...]) -> None:
    translations = np.array([item.t_base_from_flange[:3, 3] for item in samples])
    translation_span = float(np.max(np.ptp(translations, axis=0)))
    reference = samples[0].t_base_from_flange[:3, :3]
    rotation_span = max(
        _rotation_angle(reference.T @ item.t_base_from_flange[:3, :3])
        for item in samples[1:]
    )
    if translation_span < 0.03 or rotation_span < math.radians(15.0):
        raise CalibrationPipelineError("hand-eye fit poses lack translation or rotation diversity")


def _candidate_metrics(
    transform: np.ndarray,
    validation: tuple[HandEyeSample, ...],
) -> tuple[float, float, float]:
    board_positions = np.array(
        [
            (
                sample.t_base_from_flange
                @ transform
                @ sample.t_d435_from_board
            )[:3, 3]
            for sample in validation
        ]
    )
    center = np.median(board_positions, axis=0)
    errors = np.linalg.norm(board_positions - center, axis=1)
    position_rmse = float(np.sqrt(np.mean(errors * errors)))
    position_p95 = float(np.percentile(errors, 95))
    reprojection = np.array(
        [sample.board_reprojection_rmse_px for sample in validation], dtype=float
    )
    reprojection_rmse = float(np.sqrt(np.mean(reprojection * reprojection)))
    return position_rmse, position_p95, reprojection_rmse


def solve_d435_handeye(
    samples: tuple[HandEyeSample, ...] | list[HandEyeSample],
    *,
    cv_backend: Any = None,
) -> HandEyeResult:
    """Solve with OpenCV's published methods and rank them on held-out samples."""

    items = tuple(samples)
    if any(not isinstance(item, HandEyeSample) for item in items):
        raise CalibrationPipelineError("hand-eye inputs must be HandEyeSample records")
    fit = tuple(item for item in items if item.split == "fit")
    validation = tuple(item for item in items if item.split == "validation")
    if len(fit) < 8 or len(validation) < 3:
        raise CalibrationPipelineError("hand-eye requires at least 8 fit and 3 validation samples")
    if len({item.sample_id for item in items}) != len(items):
        raise CalibrationPipelineError("hand-eye sample IDs must be unique")
    _validate_pose_diversity(fit)
    if cv_backend is None:
        try:
            import cv2 as cv_backend
        except ImportError as exc:
            raise CalibrationPipelineError("OpenCV hand-eye backend is unavailable") from exc
    solver = getattr(cv_backend, "calibrateHandEye", None)
    if not callable(solver):
        raise CalibrationPipelineError(
            "OpenCV Python binding lacks calibrateHandEye; install opencv-contrib-python<5"
        )
    method_names = ("PARK", "TSAI", "HORAUD")
    candidates = []
    for method_name in method_names:
        method = getattr(cv_backend, f"CALIB_HAND_EYE_{method_name}", None)
        if method is None:
            continue
        try:
            rotation, translation = solver(
                [item.t_base_from_flange[:3, :3] for item in fit],
                [item.t_base_from_flange[:3, 3] for item in fit],
                [item.t_d435_from_board[:3, :3] for item in fit],
                [item.t_d435_from_board[:3, 3] for item in fit],
                method=method,
            )
            transform = np.eye(4)
            transform[:3, :3] = np.asarray(rotation, dtype=float)
            transform[:3, 3] = np.asarray(translation, dtype=float).reshape(3)
            transform = validate_transform(transform)
            metrics = _candidate_metrics(transform, validation)
        except Exception:
            continue
        candidates.append((metrics[1], metrics[0], method_name, transform, metrics))
    if not candidates:
        raise CalibrationPipelineError("all OpenCV hand-eye methods failed")
    _p95, _rmse, method_name, transform, metrics = min(candidates, key=lambda item: item[:3])
    position_rmse, position_p95, reprojection_rmse = metrics
    reasons = []
    if position_p95 > 0.010:
        reasons.append("full_chain_static_p95_too_high")
    if reprojection_rmse > 1.0:
        reasons.append("d435_board_reprojection_rmse_too_high")
    return HandEyeResult(
        t_flange_from_d435=transform,
        method=method_name,
        fit_samples=len(fit),
        validation_samples=len(validation),
        position_rmse_m=position_rmse,
        position_p95_m=position_p95,
        reprojection_rmse_px=reprojection_rmse,
        validated=not reasons,
        reasons=tuple(reasons),
    )


__all__ = [
    "CalibrationPipelineError",
    "HandEyeResult",
    "HandEyeSample",
    "KalibrDualCameraCalibration",
    "load_kalibr_camchain",
    "solve_d435_handeye",
]
