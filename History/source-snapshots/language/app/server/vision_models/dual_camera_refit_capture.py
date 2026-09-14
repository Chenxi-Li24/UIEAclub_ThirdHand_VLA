"""Immutable fit evidence capture for fixed-intrinsics dual-camera refitting."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from vision.camera_models import PinholeCamera, SeucmCamera
from vision.geometry import make_transform, validate_transform

from vision_models.calibration_capture import CalibrationCaptureError
from vision_models.calibration_targets import (
    AprilGridSpec,
    CalibrationTargetSpec,
    CharucoSpec,
    TargetCorners,
)
from vision_models.dual_camera_candidate import DualCameraCandidate

FIT_MANIFEST_NAME = "dual-camera-refit-fit.json"
FIT_REQUIRED_SAMPLES = 12
MAX_MANIFEST_BYTES = 16 * 1024 * 1024
_FIT_ID = re.compile(r"fit-[0-9]{2}\Z")
_CONTENT_ID = re.compile(r"sha256:[0-9a-f]{64}\Z")


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")


def _content_id(payload: dict[str, Any]) -> str:
    return f"sha256:{hashlib.sha256(_canonical(payload)).hexdigest()}"


def _valid_content_id(value: Any) -> bool:
    return isinstance(value, str) and _CONTENT_ID.fullmatch(value) is not None


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
class DualCameraFitObservation:
    """One matched target pose used only for relative-extrinsic fitting."""

    point_ids: tuple[int, ...]
    object_points_m: np.ndarray = field(compare=False, repr=False)
    d435_image_points_px: np.ndarray = field(compare=False, repr=False)
    lumos_image_points_px: np.ndarray = field(compare=False, repr=False)
    t_d435_from_board: np.ndarray = field(compare=False, repr=False)
    d435_reprojection_rmse_px: float
    old_candidate_lumos_p95_px: float | None = None

    def __post_init__(self) -> None:
        identifiers = tuple(self.point_ids)
        objects = np.asarray(self.object_points_m, dtype=float)
        d435_pixels = np.asarray(self.d435_image_points_px, dtype=float)
        lumos_pixels = np.asarray(self.lumos_image_points_px, dtype=float)
        try:
            board_pose = validate_transform(self.t_d435_from_board)
        except (TypeError, ValueError) as exc:
            raise CalibrationCaptureError("fit board pose is invalid") from exc
        old_p95 = self.old_candidate_lumos_p95_px
        scalars = [self.d435_reprojection_rmse_px]
        if old_p95 is not None:
            scalars.append(old_p95)
        if (
            len(identifiers) < 4
            or len(set(identifiers)) != len(identifiers)
            or any(
                isinstance(identifier, bool)
                or not isinstance(identifier, int)
                or identifier < 0
                for identifier in identifiers
            )
            or objects.shape != (len(identifiers), 3)
            or d435_pixels.shape != (len(identifiers), 2)
            or lumos_pixels.shape != (len(identifiers), 2)
            or not np.isfinite(objects).all()
            or not np.isfinite(d435_pixels).all()
            or not np.isfinite(lumos_pixels).all()
            or not np.isfinite(np.asarray(scalars, dtype=float)).all()
            or np.any(np.asarray(scalars, dtype=float) < 0.0)
        ):
            raise CalibrationCaptureError("fit observation is invalid")
        for array in (objects, d435_pixels, lumos_pixels, board_pose):
            array.setflags(write=False)
        object.__setattr__(self, "point_ids", identifiers)
        object.__setattr__(self, "object_points_m", objects)
        object.__setattr__(self, "d435_image_points_px", d435_pixels)
        object.__setattr__(self, "lumos_image_points_px", lumos_pixels)
        object.__setattr__(self, "t_d435_from_board", board_pose)
        object.__setattr__(self, "d435_reprojection_rmse_px", float(scalars[0]))
        if old_p95 is not None:
            object.__setattr__(self, "old_candidate_lumos_p95_px", float(old_p95))

    @property
    def common_points(self) -> int:
        return len(self.point_ids)


def _camera_matrix(camera: PinholeCamera) -> np.ndarray:
    return np.array(
        [[camera.fx, 0.0, camera.cx], [0.0, camera.fy, camera.cy], [0.0, 0.0, 1.0]],
        dtype=np.float64,
    )


def _matched(
    d435_detection: TargetCorners,
    lumos_detection: TargetCorners,
) -> tuple[tuple[int, ...], np.ndarray, np.ndarray, np.ndarray]:
    d435_index = {identifier: index for index, identifier in enumerate(d435_detection.point_ids)}
    lumos_index = {identifier: index for index, identifier in enumerate(lumos_detection.point_ids)}
    common = tuple(sorted(set(d435_index).intersection(lumos_index)))
    if len(common) < 4:
        raise CalibrationCaptureError("both cameras have insufficient common points")
    objects = np.asarray(
        [d435_detection.object_points[d435_index[key]] for key in common], dtype=float
    )
    lumos_objects = np.asarray(
        [lumos_detection.object_points[lumos_index[key]] for key in common], dtype=float
    )
    if not np.allclose(objects, lumos_objects, atol=1e-12, rtol=0.0):
        raise CalibrationCaptureError("target common point geometry disagrees")
    d435_pixels = np.asarray(
        [d435_detection.image_points[d435_index[key]] for key in common], dtype=float
    )
    lumos_pixels = np.asarray(
        [lumos_detection.image_points[lumos_index[key]] for key in common], dtype=float
    )
    return common, objects, d435_pixels, lumos_pixels


def evaluate_fit_pair(
    *,
    d435: PinholeCamera,
    lumos: SeucmCamera,
    d435_detection: TargetCorners,
    lumos_detection: TargetCorners,
    old_candidate: DualCameraCandidate | None = None,
) -> DualCameraFitObservation:
    """Solve board pose in D435 and retain matched native camera pixels."""

    if not isinstance(d435, PinholeCamera) or not isinstance(lumos, SeucmCamera):
        raise CalibrationCaptureError("typed camera models are required")
    if not isinstance(d435_detection, TargetCorners) or not isinstance(
        lumos_detection, TargetCorners
    ):
        raise CalibrationCaptureError("typed target detections are required")
    intrinsics = _camera_matrix(d435)
    distortion = np.zeros(4, dtype=np.float64)
    solved, rotation_vector, translation = cv2.solvePnP(
        d435_detection.object_points,
        d435_detection.image_points,
        intrinsics,
        distortion,
        flags=cv2.SOLVEPNP_IPPE,
    )
    if not solved:
        raise CalibrationCaptureError("D435 target PnP failed")
    rotation_vector, translation = cv2.solvePnPRefineLM(
        d435_detection.object_points,
        d435_detection.image_points,
        intrinsics,
        distortion,
        rotation_vector,
        translation,
    )
    rotation, _jacobian = cv2.Rodrigues(rotation_vector)
    board_pose = make_transform(rotation, np.asarray(translation).reshape(3))
    projected, _jacobian = cv2.projectPoints(
        d435_detection.object_points,
        rotation_vector,
        translation,
        intrinsics,
        distortion,
    )
    residuals = np.asarray(projected).reshape(-1, 2) - d435_detection.image_points
    rmse = float(np.sqrt(np.mean(np.sum(residuals * residuals, axis=1))))
    common, objects, d435_pixels, lumos_pixels = _matched(
        d435_detection, lumos_detection
    )
    old_p95: float | None = None
    if old_candidate is not None:
        points_d435 = objects @ board_pose[:3, :3].T + board_pose[:3, 3]
        relative = old_candidate.t_lumos_from_d435
        points_lumos = points_d435 @ relative[:3, :3].T + relative[:3, 3]
        predicted, valid = lumos.project(points_lumos)
        if valid.all():
            old_p95 = float(np.percentile(np.linalg.norm(predicted - lumos_pixels, axis=1), 95))
    return DualCameraFitObservation(
        point_ids=common,
        object_points_m=objects,
        d435_image_points_px=d435_pixels,
        lumos_image_points_px=lumos_pixels,
        t_d435_from_board=board_pose,
        d435_reprojection_rmse_px=rmse,
        old_candidate_lumos_p95_px=old_p95,
    )


def _rotation_delta_rad(first: np.ndarray, second: np.ndarray) -> float:
    relative = first[:3, :3].T @ second[:3, :3]
    return math.acos(float(np.clip((np.trace(relative) - 1.0) / 2.0, -1.0, 1.0)))


def pose_is_distinct(
    candidate_pose: Any,
    previous_poses: Iterable[Any],
    *,
    translation_m: float = 0.015,
    rotation_deg: float = 3.0,
) -> bool:
    candidate = validate_transform(candidate_pose)
    previous = tuple(validate_transform(item) for item in previous_poses)
    return all(
        np.linalg.norm(candidate[:3, 3] - item[:3, 3]) >= translation_m - 1e-12
        or _rotation_delta_rad(candidate, item) >= math.radians(rotation_deg) - 1e-12
        for item in previous
    )


def _record_to_observation(record: dict[str, Any]) -> DualCameraFitObservation:
    try:
        return DualCameraFitObservation(
            point_ids=tuple(record["point_ids"]),
            object_points_m=record["object_points_m"],
            d435_image_points_px=record["d435_image_points_px"],
            lumos_image_points_px=record["lumos_image_points_px"],
            t_d435_from_board=record["T_d435_from_board"],
            d435_reprojection_rmse_px=record["d435_reprojection_rmse_px"],
            old_candidate_lumos_p95_px=record.get("old_candidate_lumos_p95_px"),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise CalibrationCaptureError("fit observation record is invalid") from exc


def observations_from_manifest(manifest: dict[str, Any]) -> tuple[DualCameraFitObservation, ...]:
    if not isinstance(manifest, dict) or manifest.get("purpose") != "fit":
        raise CalibrationCaptureError("fit manifest purpose is invalid")
    records = manifest.get("observations")
    if not isinstance(records, list):
        raise CalibrationCaptureError("fit observations are invalid")
    return tuple(_record_to_observation(record) for record in records)


def fit_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    observations = observations_from_manifest(manifest)
    count = len(observations)
    return {
        "phase": "fit_ready" if count == FIT_REQUIRED_SAMPLES else "fit_collect",
        "samples": count,
        "required_samples": FIT_REQUIRED_SAMPLES,
        "common_points_min": min((item.common_points for item in observations), default=0),
        "d435_reprojection_rmse_max_px": max(
            (item.d435_reprojection_rmse_px for item in observations), default=0.0
        ),
    }


def _read_manifest(path: Path) -> dict[str, Any]:
    if path.is_symlink():
        raise CalibrationCaptureError("fit manifest cannot be a symlink")
    try:
        resolved = path.resolve(strict=True)
        if not resolved.is_file() or resolved.stat().st_size > MAX_MANIFEST_BYTES:
            raise CalibrationCaptureError("fit manifest is unsafe")
        stored = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CalibrationCaptureError("fit manifest cannot be parsed") from exc
    if not isinstance(stored, dict):
        raise CalibrationCaptureError("fit manifest must be a JSON object")
    supplied = stored.pop("content_id", None)
    if supplied != _content_id(stored):
        raise CalibrationCaptureError("fit manifest integrity check failed")
    return stored


def load_fit_manifest(
    output: Path | str,
    *,
    target: CalibrationTargetSpec,
    seed_candidate_id: str,
) -> dict[str, Any] | None:
    path = Path(output) / FIT_MANIFEST_NAME
    if not path.exists():
        return None
    manifest = _read_manifest(path)
    if (
        manifest.get("schema_version") != 1
        or manifest.get("purpose") != "fit"
        or manifest.get("motion_or_robot_access") is not False
        or manifest.get("target") != target.to_json()
        or manifest.get("seed_candidate_id") != seed_candidate_id
    ):
        raise CalibrationCaptureError("fit manifest contract changed")
    observations = observations_from_manifest(manifest)
    if len(observations) > FIT_REQUIRED_SAMPLES:
        raise CalibrationCaptureError("fit manifest exceeds required samples")
    return manifest


def append_fit_observation(
    output: Path | str,
    *,
    sample_id: str,
    seed_candidate_id: str,
    lumos_jpeg: bytes,
    d435_jpeg: bytes,
    result: DualCameraFitObservation,
    target: CalibrationTargetSpec,
    capture_skew_ms: float,
) -> Path:
    """Append one passing, distinct fit pose after every gate has passed."""

    if not isinstance(sample_id, str) or _FIT_ID.fullmatch(sample_id) is None:
        raise CalibrationCaptureError("fit sample ID is invalid")
    if not _valid_content_id(seed_candidate_id):
        raise CalibrationCaptureError("seed candidate ID is invalid")
    if not isinstance(result, DualCameraFitObservation):
        raise CalibrationCaptureError("typed fit observation is required")
    if not isinstance(target, (AprilGridSpec, CharucoSpec)):
        raise CalibrationCaptureError("typed calibration target is required")
    if not isinstance(lumos_jpeg, bytes) or not lumos_jpeg:
        raise CalibrationCaptureError("Lumos JPEG is empty")
    if not isinstance(d435_jpeg, bytes) or not d435_jpeg:
        raise CalibrationCaptureError("D435 JPEG is empty")
    if (
        isinstance(capture_skew_ms, bool)
        or not np.isfinite(capture_skew_ms)
        or capture_skew_ms < 0.0
        or capture_skew_ms > 100.0
    ):
        raise CalibrationCaptureError("capture skew exceeds 100 ms")
    if result.common_points < 24:
        raise CalibrationCaptureError("fit requires at least 24 common points")
    if result.d435_reprojection_rmse_px > 1.5:
        raise CalibrationCaptureError("D435 reprojection RMSE exceeds 1.5 px")

    root = Path(output)
    manifest = load_fit_manifest(
        root, target=target, seed_candidate_id=seed_candidate_id
    )
    if manifest is None:
        manifest = {
            "schema_version": 1,
            "purpose": "fit",
            "seed_candidate_id": seed_candidate_id,
            "target": target.to_json(),
            "motion_or_robot_access": False,
            "observations": [],
        }
    records = manifest["observations"]
    if len(records) >= FIT_REQUIRED_SAMPLES:
        raise CalibrationCaptureError("fit evidence already has 12 samples")
    if any(record.get("sample_id") == sample_id for record in records):
        raise CalibrationCaptureError("fit sample ID is duplicated")
    previous = tuple(_record_to_observation(record) for record in records)
    if not pose_is_distinct(
        result.t_d435_from_board,
        (item.t_d435_from_board for item in previous),
    ):
        raise CalibrationCaptureError("fit board pose is not distinct")

    lumos_relative = Path("images/lumos") / f"{sample_id}.jpg"
    d435_relative = Path("images/d435") / f"{sample_id}.jpg"
    lumos_path = root / lumos_relative
    d435_path = root / d435_relative
    if lumos_path.exists() or d435_path.exists():
        raise CalibrationCaptureError("fit image already exists")
    record: dict[str, Any] = {
        "sample_id": sample_id,
        "lumos_image": lumos_relative.as_posix(),
        "lumos_image_sha256": hashlib.sha256(lumos_jpeg).hexdigest(),
        "d435_image": d435_relative.as_posix(),
        "d435_image_sha256": hashlib.sha256(d435_jpeg).hexdigest(),
        "capture_skew_ms": float(capture_skew_ms),
        "common_points": result.common_points,
        "point_ids": list(result.point_ids),
        "object_points_m": result.object_points_m.tolist(),
        "d435_image_points_px": result.d435_image_points_px.tolist(),
        "lumos_image_points_px": result.lumos_image_points_px.tolist(),
        "T_d435_from_board": result.t_d435_from_board.tolist(),
        "d435_reprojection_rmse_px": result.d435_reprojection_rmse_px,
        "old_candidate_lumos_p95_px": result.old_candidate_lumos_p95_px,
    }
    _atomic_write(lumos_path, lumos_jpeg)
    _atomic_write(d435_path, d435_jpeg)
    records.append(record)
    stored = dict(manifest)
    stored["content_id"] = _content_id(manifest)
    manifest_path = root / FIT_MANIFEST_NAME
    _atomic_write(
        manifest_path,
        json.dumps(stored, sort_keys=True, indent=2, ensure_ascii=True).encode("ascii")
        + b"\n",
    )
    return manifest_path


__all__ = [
    "DualCameraFitObservation",
    "FIT_MANIFEST_NAME",
    "FIT_REQUIRED_SAMPLES",
    "append_fit_observation",
    "evaluate_fit_pair",
    "fit_summary",
    "load_fit_manifest",
    "observations_from_manifest",
    "pose_is_distinct",
]
