"""Read-only table-plane capture records and held-out base-frame validation."""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from vision.geometry import transform_points, validate_transform

from vision_models.calibration_capture import (
    CalibrationCaptureError,
    CalibrationTargetObservation,
    CharucoSpec,
    ReadOnlyRobotState,
)

MAX_TABLE_MANIFEST_BYTES = 16 * 1024 * 1024
TABLE_REQUIRED_SAMPLES = 8
TABLE_MAX_SAMPLES = 12
TABLE_FIT_REQUIRED = 6
TABLE_VALIDATION_REQUIRED = 2
TABLE_REQUIRED_XY_SPAN_M = 0.10


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
        raise CalibrationCaptureError("table calibration must be finite JSON") from exc


def _content_id(payload: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(payload)).hexdigest()


def _valid_content_id(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 71
        and value.startswith("sha256:")
        and all(character in "0123456789abcdef" for character in value[7:])
    )


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


@dataclass(frozen=True)
class TableCalibrationSample:
    sample_id: str
    split: str
    t_base_from_flange: np.ndarray = field(compare=False, repr=False)
    t_d435_from_board: np.ndarray = field(compare=False, repr=False)
    board_reprojection_rmse_px: float

    def __post_init__(self) -> None:
        if not isinstance(self.sample_id, str) or not self.sample_id or len(self.sample_id) > 128:
            raise CalibrationCaptureError("table sample ID is invalid")
        if self.split not in {"fit", "validation"}:
            raise CalibrationCaptureError("table sample split must be fit or validation")
        base = validate_transform(self.t_base_from_flange)
        board = validate_transform(self.t_d435_from_board)
        reprojection = float(self.board_reprojection_rmse_px)
        if not math.isfinite(reprojection) or not 0.0 <= reprojection <= 1.5:
            raise CalibrationCaptureError("table sample reprojection RMSE exceeds 1.5 px")
        base.setflags(write=False)
        board.setflags(write=False)
        object.__setattr__(self, "t_base_from_flange", base)
        object.__setattr__(self, "t_d435_from_board", board)
        object.__setattr__(self, "board_reprojection_rmse_px", reprojection)


@dataclass(frozen=True)
class TableCalibrationDataset:
    samples: tuple[TableCalibrationSample, ...]
    board_size_m: tuple[float, float]
    candidate_source_id: str
    handeye_result_id: str
    dataset_id: str

    def __post_init__(self) -> None:
        samples = tuple(self.samples)
        size = tuple(float(value) for value in self.board_size_m)
        if not 1 <= len(samples) <= TABLE_MAX_SAMPLES or any(
            not isinstance(sample, TableCalibrationSample) for sample in samples
        ):
            raise CalibrationCaptureError("table dataset sample count is invalid")
        if len(size) != 2 or not np.isfinite(size).all() or any(
            not 0.05 <= value <= 1.0 for value in size
        ):
            raise CalibrationCaptureError("table board dimensions are invalid")
        for identifier in (
            self.candidate_source_id,
            self.handeye_result_id,
            self.dataset_id,
        ):
            if not _valid_content_id(identifier):
                raise CalibrationCaptureError("table dataset source ID is invalid")
        object.__setattr__(self, "samples", samples)
        object.__setattr__(self, "board_size_m", size)


@dataclass(frozen=True)
class TableCalibrationResult:
    normal_base: tuple[float, float, float]
    offset_m: float
    fit_rmse_m: float
    validation_p95_m: float
    fit_samples: int
    validation_samples: int
    calibration_id: str
    validated: bool
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        normal = np.asarray(self.normal_base, dtype=float)
        numeric = np.asarray(
            [self.offset_m, self.fit_rmse_m, self.validation_p95_m], dtype=float
        )
        if (
            normal.shape != (3,)
            or not np.isfinite(normal).all()
            or not np.isclose(np.linalg.norm(normal), 1.0, atol=1e-8)
            or not np.isfinite(numeric).all()
            or self.fit_rmse_m < 0.0
            or self.validation_p95_m < 0.0
            or not _valid_content_id(self.calibration_id)
        ):
            raise CalibrationCaptureError("table calibration result is invalid")
        object.__setattr__(self, "normal_base", tuple(float(value) for value in normal))
        object.__setattr__(self, "offset_m", float(self.offset_m))
        object.__setattr__(self, "fit_rmse_m", float(self.fit_rmse_m))
        object.__setattr__(self, "validation_p95_m", float(self.validation_p95_m))
        object.__setattr__(self, "reasons", tuple(self.reasons))


@dataclass(frozen=True)
class TableFitCoverage:
    x_span_m: float
    y_span_m: float
    required_span_m: float = TABLE_REQUIRED_XY_SPAN_M

    def __post_init__(self) -> None:
        values = np.asarray(
            [self.x_span_m, self.y_span_m, self.required_span_m], dtype=float
        )
        if (
            not np.isfinite(values).all()
            or self.x_span_m < 0.0
            or self.y_span_m < 0.0
            or self.required_span_m <= 0.0
        ):
            raise CalibrationCaptureError("table coverage is invalid")
        object.__setattr__(self, "x_span_m", float(self.x_span_m))
        object.__setattr__(self, "y_span_m", float(self.y_span_m))
        object.__setattr__(self, "required_span_m", float(self.required_span_m))

    @property
    def sufficient(self) -> bool:
        return (
            self.x_span_m >= self.required_span_m - 1e-12
            and self.y_span_m >= self.required_span_m - 1e-12
        )


def _load_existing(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_TABLE_MANIFEST_BYTES:
        raise CalibrationCaptureError("existing table manifest is unsafe")
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CalibrationCaptureError("existing table manifest cannot be parsed") from exc
    if not isinstance(record, dict):
        raise CalibrationCaptureError("existing table manifest is invalid")
    payload = dict(record)
    supplied = payload.pop("content_id", None)
    if supplied != _content_id(payload):
        raise CalibrationCaptureError("existing table manifest integrity check failed")
    return payload


def append_table_sample(
    output: Path | str,
    *,
    sample_id: str,
    jpeg: bytes,
    robot: ReadOnlyRobotState,
    observation: CalibrationTargetObservation,
    target: CharucoSpec,
    candidate_source_id: str,
    handeye_result_id: str,
) -> Path:
    """Atomically append one read-only table observation; every fourth is held out."""

    if not isinstance(sample_id, str) or not sample_id or len(sample_id) > 128:
        raise CalibrationCaptureError("table sample ID is invalid")
    if not isinstance(jpeg, bytes) or not jpeg:
        raise CalibrationCaptureError("table sample JPEG is empty")
    if not isinstance(robot, ReadOnlyRobotState) or not isinstance(
        observation, CalibrationTargetObservation
    ):
        raise CalibrationCaptureError("typed robot and board observations are required")
    if not isinstance(target, CharucoSpec):
        raise CalibrationCaptureError("table calibration requires the ChArUco target")
    if observation.detected_points < 24 or observation.reprojection_rmse_px > 1.5:
        raise CalibrationCaptureError("table observation does not satisfy image gates")
    if not _valid_content_id(candidate_source_id) or not _valid_content_id(handeye_result_id):
        raise CalibrationCaptureError("table calibration source ID is invalid")

    root = Path(output)
    manifest_path = root / "table.json"
    manifest = _load_existing(manifest_path)
    if manifest is None:
        manifest = {
            "schema_version": 1,
            "candidate_source_id": candidate_source_id,
            "handeye_result_id": handeye_result_id,
            "target": target.to_json(),
            "robot_state_access": "read_only_status",
            "motion_command_access": False,
            "samples": [],
        }
    expected_keys = {
        "schema_version",
        "candidate_source_id",
        "handeye_result_id",
        "target",
        "robot_state_access",
        "motion_command_access",
        "samples",
    }
    if set(manifest) != expected_keys or manifest["schema_version"] != 1:
        raise CalibrationCaptureError("table manifest schema is invalid")
    if (
        manifest["candidate_source_id"] != candidate_source_id
        or manifest["handeye_result_id"] != handeye_result_id
        or manifest["target"] != target.to_json()
        or manifest["robot_state_access"] != "read_only_status"
        or manifest["motion_command_access"] is not False
    ):
        raise CalibrationCaptureError("table calibration sources changed during capture")
    samples = manifest["samples"]
    if not isinstance(samples, list):
        raise CalibrationCaptureError("table manifest samples are invalid")
    if len(samples) >= TABLE_MAX_SAMPLES:
        raise CalibrationCaptureError("table dataset reached the supplemental sample limit")
    if any(isinstance(item, dict) and item.get("sample_id") == sample_id for item in samples):
        raise CalibrationCaptureError("table sample ID is duplicated")
    from vision_models.calibration_diversity import transform_is_distinct

    for item in samples:
        if not isinstance(item, dict):
            raise CalibrationCaptureError("table manifest sample is invalid")
        robot_changed = transform_is_distinct(
            robot.t_base_from_flange,
            (item["T_base_from_flange"],),
            translation_m=0.008,
            rotation_deg=3.0,
        )
        board_changed = transform_is_distinct(
            observation.t_camera_from_board,
            (item["T_d435_from_board"],),
            translation_m=0.020,
            rotation_deg=3.0,
        )
        if not robot_changed and not board_changed:
            raise CalibrationCaptureError(
                "table robot and board pose must be different from every accepted sample"
            )

    image_relative = Path("images") / f"{sample_id}.jpg"
    image_path = root / image_relative
    if image_path.exists():
        raise CalibrationCaptureError("table sample image already exists")
    _atomic_write(image_path, jpeg)
    sample_number = len(samples) + 1
    samples.append(
        {
            "sample_id": sample_id,
            "split": "validation" if sample_number % 4 == 0 else "fit",
            "image": image_relative.as_posix(),
            "image_sha256": hashlib.sha256(jpeg).hexdigest(),
            "robot_state_timestamp_ms": robot.timestamp_ms,
            "joints_deg": list(robot.joints_deg),
            "T_base_from_flange": robot.t_base_from_flange.tolist(),
            "T_d435_from_board": observation.t_camera_from_board.tolist(),
            "detected_points": observation.detected_points,
            "board_reprojection_rmse_px": observation.reprojection_rmse_px,
        }
    )
    saved = dict(manifest)
    saved["content_id"] = _content_id(manifest)
    _atomic_write(
        manifest_path,
        json.dumps(saved, sort_keys=True, indent=2, ensure_ascii=True).encode("ascii") + b"\n",
    )
    return manifest_path


def _target_board_size(value: Any) -> tuple[float, float]:
    if not isinstance(value, dict) or set(value) != {
        "family",
        "rows",
        "columns",
        "square_size_m",
        "marker_size_m",
        "dictionary",
    }:
        raise CalibrationCaptureError("table target is invalid")
    try:
        target = CharucoSpec(
            rows=value["rows"],
            columns=value["columns"],
            square_size_m=value["square_size_m"],
            marker_size_m=value["marker_size_m"],
            dictionary=value["dictionary"],
        )
    except (TypeError, ValueError) as exc:
        raise CalibrationCaptureError("table target is invalid") from exc
    return (
        target.columns * target.square_size_m,
        target.rows * target.square_size_m,
    )


def load_table_dataset(path: Path | str) -> TableCalibrationDataset:
    source = Path(path)
    if source.is_symlink():
        raise CalibrationCaptureError("table manifest cannot be a symlink")
    try:
        source = source.resolve(strict=True)
        record = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CalibrationCaptureError("table manifest cannot be parsed") from exc
    if not isinstance(record, dict) or source.stat().st_size > MAX_TABLE_MANIFEST_BYTES:
        raise CalibrationCaptureError("table manifest is unsafe")
    expected_keys = {
        "schema_version",
        "candidate_source_id",
        "handeye_result_id",
        "target",
        "robot_state_access",
        "motion_command_access",
        "samples",
        "content_id",
    }
    if set(record) != expected_keys:
        raise CalibrationCaptureError("table manifest keys are invalid")
    payload = dict(record)
    dataset_id = payload.pop("content_id")
    if dataset_id != _content_id(payload):
        raise CalibrationCaptureError("table manifest integrity check failed")
    if (
        payload["schema_version"] != 1
        or payload["robot_state_access"] != "read_only_status"
        or payload["motion_command_access"] is not False
        or not _valid_content_id(payload["candidate_source_id"])
        or not _valid_content_id(payload["handeye_result_id"])
    ):
        raise CalibrationCaptureError("table manifest provenance is invalid")
    records = payload["samples"]
    if not isinstance(records, list):
        raise CalibrationCaptureError("table manifest samples are invalid")
    root = source.parent.resolve()
    samples = []
    expected_sample_keys = {
        "sample_id",
        "split",
        "image",
        "image_sha256",
        "robot_state_timestamp_ms",
        "joints_deg",
        "T_base_from_flange",
        "T_d435_from_board",
        "detected_points",
        "board_reprojection_rmse_px",
    }
    for index, item in enumerate(records):
        if not isinstance(item, dict) or set(item) != expected_sample_keys:
            raise CalibrationCaptureError(f"table sample {index} keys are invalid")
        image = root / item["image"] if isinstance(item["image"], str) else root
        if image.is_symlink():
            raise CalibrationCaptureError("table image provenance is invalid")
        try:
            resolved = image.resolve(strict=True)
            resolved.relative_to(root)
            raw = resolved.read_bytes()
        except (OSError, ValueError) as exc:
            raise CalibrationCaptureError("table image provenance is invalid") from exc
        if hashlib.sha256(raw).hexdigest() != item["image_sha256"]:
            raise CalibrationCaptureError("table image provenance is invalid")
        points = item["detected_points"]
        timestamp = item["robot_state_timestamp_ms"]
        joints = np.asarray(item["joints_deg"], dtype=float)
        if (
            isinstance(points, bool)
            or not isinstance(points, int)
            or points < 24
            or isinstance(timestamp, bool)
            or not isinstance(timestamp, int)
            or joints.shape != (6,)
            or not np.isfinite(joints).all()
        ):
            raise CalibrationCaptureError("table sample quality provenance is invalid")
        samples.append(
            TableCalibrationSample(
                sample_id=item["sample_id"],
                split=item["split"],
                t_base_from_flange=item["T_base_from_flange"],
                t_d435_from_board=item["T_d435_from_board"],
                board_reprojection_rmse_px=item["board_reprojection_rmse_px"],
            )
        )
    return TableCalibrationDataset(
        samples=tuple(samples),
        board_size_m=_target_board_size(payload["target"]),
        candidate_source_id=payload["candidate_source_id"],
        handeye_result_id=payload["handeye_result_id"],
        dataset_id=dataset_id,
    )


def _fit_plane(points: np.ndarray) -> tuple[np.ndarray, float]:
    center = np.mean(points, axis=0)
    _u, _s, vectors = np.linalg.svd(points - center, full_matrices=False)
    normal = vectors[-1]
    if normal[2] < 0.0:
        normal = -normal
    normal = normal / np.linalg.norm(normal)
    return normal, -float(normal @ center)


def _board_points(transform: np.ndarray, board_size_m: tuple[float, float]) -> np.ndarray:
    width, height = board_size_m
    corners = np.array(
        [[0.0, 0.0, 0.0], [width, 0.0, 0.0], [width, height, 0.0], [0.0, height, 0.0]]
    )
    return transform_points(transform, corners)


def measure_table_fit_coverage(
    samples: tuple[TableCalibrationSample, ...] | list[TableCalibrationSample],
    *,
    t_flange_from_d435: Any,
) -> TableFitCoverage:
    """Measure independent fit-sample origin coverage in the robot base XY plane."""

    items = tuple(samples)
    if not items or any(not isinstance(item, TableCalibrationSample) for item in items):
        raise CalibrationCaptureError("table coverage requires typed samples")
    handeye = validate_transform(t_flange_from_d435)
    fit_origins = np.stack(
        [
            (item.t_base_from_flange @ handeye @ item.t_d435_from_board)[:3, 3]
            for item in items
            if item.split == "fit"
        ]
    )
    spans = np.ptp(fit_origins, axis=0)
    return TableFitCoverage(x_span_m=spans[0], y_span_m=spans[1])


def solve_table_calibration(
    samples: tuple[TableCalibrationSample, ...] | list[TableCalibrationSample],
    *,
    t_flange_from_d435: Any,
    calibration_id: str,
    board_size_m: tuple[float, float],
) -> TableCalibrationResult:
    items = tuple(samples)
    fit = tuple(item for item in items if item.split == "fit")
    validation = tuple(item for item in items if item.split == "validation")
    if (
        not TABLE_REQUIRED_SAMPLES <= len(items) <= TABLE_MAX_SAMPLES
        or len(fit) < TABLE_FIT_REQUIRED
        or len(validation) < TABLE_VALIDATION_REQUIRED
        or len({item.sample_id for item in items}) != len(items)
    ):
        raise CalibrationCaptureError(
            "table solve requires at least six fit and two validation samples"
        )
    if any(not isinstance(item, TableCalibrationSample) for item in items):
        raise CalibrationCaptureError("table solve requires typed samples")
    handeye = validate_transform(t_flange_from_d435)
    if not _valid_content_id(calibration_id):
        raise CalibrationCaptureError("table calibration ID is invalid")
    size = tuple(float(value) for value in board_size_m)
    if len(size) != 2 or not np.isfinite(size).all() or any(
        not 0.05 <= value <= 1.0 for value in size
    ):
        raise CalibrationCaptureError("table board dimensions are invalid")

    transforms = {
        item.sample_id: item.t_base_from_flange @ handeye @ item.t_d435_from_board
        for item in items
    }
    coverage = measure_table_fit_coverage(items, t_flange_from_d435=handeye)
    if not coverage.sufficient:
        raise CalibrationCaptureError("table fit samples lack XY coverage")
    fit_points = np.concatenate(
        [_board_points(transforms[item.sample_id], size) for item in fit], axis=0
    )
    normal, offset = _fit_plane(fit_points)
    initial_distances = np.abs(fit_points @ normal + offset)
    median = float(np.median(initial_distances))
    mad = float(np.median(np.abs(initial_distances - median)))
    threshold = max(0.002, median + 3.5 * 1.4826 * mad)
    retained = fit_points[initial_distances <= threshold]
    if len(retained) < max(12, math.ceil(0.75 * len(fit_points))):
        raise CalibrationCaptureError("table plane has too many outliers")
    normal, offset = _fit_plane(retained)
    fit_distances = np.abs(retained @ normal + offset)
    fit_rmse = float(np.sqrt(np.mean(fit_distances * fit_distances)))
    validation_points = np.concatenate(
        [_board_points(transforms[item.sample_id], size) for item in validation], axis=0
    )
    validation_distances = np.abs(validation_points @ normal + offset)
    validation_p95 = float(np.percentile(validation_distances, 95))
    tilt = math.acos(float(np.clip(normal[2], -1.0, 1.0)))
    reasons = []
    if tilt > math.radians(15.0):
        reasons.append("table_normal_tilt_too_high")
    if fit_rmse > 0.005:
        reasons.append("table_fit_rmse_too_high")
    if validation_p95 > 0.008:
        reasons.append("table_validation_p95_too_high")
    return TableCalibrationResult(
        normal_base=tuple(float(value) for value in normal),
        offset_m=offset,
        fit_rmse_m=fit_rmse,
        validation_p95_m=validation_p95,
        fit_samples=len(fit),
        validation_samples=len(validation),
        calibration_id=calibration_id,
        validated=not reasons,
        reasons=tuple(reasons),
    )


__all__ = [
    "TABLE_MAX_SAMPLES",
    "TABLE_REQUIRED_SAMPLES",
    "TableFitCoverage",
    "TableCalibrationDataset",
    "TableCalibrationResult",
    "TableCalibrationSample",
    "append_table_sample",
    "load_table_dataset",
    "measure_table_fit_coverage",
    "solve_table_calibration",
]
