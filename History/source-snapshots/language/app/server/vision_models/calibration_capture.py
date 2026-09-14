"""Read-only calibration-target and robot-state capture for hand-eye datasets."""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from vision.calibration_gate import sdk_pose_transform
from vision.geometry import make_transform, validate_transform

from vision_models.calibration_targets import (
    AprilGridSpec,
    CalibrationTargetError,
    CalibrationTargetSpec,
    CharucoSpec,
    TargetCorners,
    detect_target_corners,
    load_calibration_target,
)

MAX_MANIFEST_BYTES = 16 * 1024 * 1024

CalibrationCaptureError = CalibrationTargetError


def _finite_vector(value: Any, length: int, name: str) -> np.ndarray:
    try:
        result = np.asarray(value, dtype=float)
    except (TypeError, ValueError) as exc:
        raise CalibrationCaptureError(f"{name} must contain {length} finite values") from exc
    if result.shape != (length,) or not np.isfinite(result).all():
        raise CalibrationCaptureError(f"{name} must contain {length} finite values")
    return result


def load_aprilgrid_target(path: Path | str) -> AprilGridSpec:
    target = load_calibration_target(path)
    if not isinstance(target, AprilGridSpec):
        raise CalibrationCaptureError("target_type must be aprilgrid")
    return target


@dataclass(frozen=True)
class CalibrationTargetObservation:
    t_camera_from_board: np.ndarray = field(compare=False, repr=False)
    detected_points: int
    reprojection_rmse_px: float

    def __post_init__(self) -> None:
        transform = validate_transform(self.t_camera_from_board)
        if (
            isinstance(self.detected_points, bool)
            or not isinstance(self.detected_points, int)
            or self.detected_points < 4
        ):
            raise CalibrationCaptureError(
                "calibration target observation requires at least four points"
            )
        error = float(self.reprojection_rmse_px)
        if not math.isfinite(error) or error < 0.0:
            raise CalibrationCaptureError("target reprojection RMSE is invalid")
        transform.setflags(write=False)
        object.__setattr__(self, "t_camera_from_board", transform)
        object.__setattr__(self, "reprojection_rmse_px", error)


@dataclass(frozen=True)
class ReadOnlyRobotState:
    t_base_from_flange: np.ndarray = field(compare=False, repr=False)
    joints_deg: tuple[float, ...]
    timestamp_ms: int

    def __post_init__(self) -> None:
        transform = validate_transform(self.t_base_from_flange)
        joints = tuple(float(item) for item in self.joints_deg)
        if len(joints) != 6 or not np.isfinite(joints).all():
            raise CalibrationCaptureError("robot state must contain six finite joints")
        if isinstance(self.timestamp_ms, bool) or not isinstance(self.timestamp_ms, int):
            raise CalibrationCaptureError("robot state timestamp is invalid")
        transform.setflags(write=False)
        object.__setattr__(self, "t_base_from_flange", transform)
        object.__setattr__(self, "joints_deg", joints)


def detect_target_pose(
    image: np.ndarray,
    *,
    target: CalibrationTargetSpec,
    camera_matrix: np.ndarray,
    distortion_coeffs: np.ndarray,
) -> CalibrationTargetObservation:
    """Estimate T_camera_from_board from any supported planar target."""

    detected = detect_target_corners(image, target)
    intrinsics = np.asarray(camera_matrix, dtype=np.float64)
    distortion = np.asarray(distortion_coeffs, dtype=np.float64).reshape(-1)
    if intrinsics.shape != (3, 3) or not np.isfinite(intrinsics).all():
        raise CalibrationCaptureError("camera matrix must be finite 3x3")
    if not np.isfinite(distortion).all():
        raise CalibrationCaptureError("distortion coefficients must be finite")
    solved, rotation_vector, translation = cv2.solvePnP(
        detected.object_points,
        detected.image_points,
        intrinsics,
        distortion,
        flags=cv2.SOLVEPNP_IPPE,
    )
    if not solved:
        raise CalibrationCaptureError("calibration target PnP failed")
    rotation_vector, translation = cv2.solvePnPRefineLM(
        detected.object_points,
        detected.image_points,
        intrinsics,
        distortion,
        rotation_vector,
        translation,
    )
    rotation, _jacobian = cv2.Rodrigues(rotation_vector)
    transform = make_transform(rotation, np.asarray(translation).reshape(3))
    projected, _jacobian = cv2.projectPoints(
        detected.object_points,
        rotation_vector,
        translation,
        intrinsics,
        distortion,
    )
    residuals = np.asarray(projected).reshape(-1, 2) - detected.image_points
    rmse = float(np.sqrt(np.mean(np.sum(residuals * residuals, axis=1))))
    return CalibrationTargetObservation(
        t_camera_from_board=transform,
        detected_points=len(detected.point_ids),
        reprojection_rmse_px=rmse,
    )


def detect_aprilgrid_corners(
    image: np.ndarray,
    *,
    spec: AprilGridSpec,
) -> TargetCorners:
    if not isinstance(spec, AprilGridSpec):
        raise CalibrationCaptureError("AprilGrid specification is required")
    return detect_target_corners(image, spec)


def detect_aprilgrid_pose(
    image: np.ndarray,
    *,
    spec: AprilGridSpec,
    camera_matrix: np.ndarray,
    distortion_coeffs: np.ndarray,
) -> CalibrationTargetObservation:
    if not isinstance(spec, AprilGridSpec):
        raise CalibrationCaptureError("AprilGrid specification is required")
    return detect_target_pose(
        image,
        target=spec,
        camera_matrix=camera_matrix,
        distortion_coeffs=distortion_coeffs,
    )


AprilGridCorners = TargetCorners
AprilGridObservation = CalibrationTargetObservation


def parse_robot_state(message: Mapping[str, Any]) -> ReadOnlyRobotState:
    if not isinstance(message, Mapping) or message.get("type") != "robot_state":
        raise CalibrationCaptureError("expected one robot_state message")
    joints = _finite_vector(message.get("joints"), 6, "joints")
    velocities = _finite_vector(message.get("velocities"), 6, "joint velocities")
    if np.any(np.abs(velocities) > 0.5):
        raise CalibrationCaptureError("robot must be stationary")
    if str(message.get("stateName", "")).strip().lower() not in {
        "idle",
        "stationary",
        "standby",
        "ready",
    }:
        raise CalibrationCaptureError("robot must report a stationary state")
    position_m = _finite_vector(message.get("tcpPos"), 3, "TCP position") / 1000.0
    rpy_rad = np.deg2rad(_finite_vector(message.get("tcpEuler"), 3, "TCP Euler"))
    timestamp = message.get("ts")
    if isinstance(timestamp, bool) or not isinstance(timestamp, int):
        raise CalibrationCaptureError("robot state timestamp is invalid")
    return ReadOnlyRobotState(
        t_base_from_flange=sdk_pose_transform(position_m, rpy_rad),
        joints_deg=tuple(float(item) for item in joints),
        timestamp_ms=timestamp,
    )


def _canonical(payload: Any) -> bytes:
    return json.dumps(
        payload,
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


def _load_manifest(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_MANIFEST_BYTES:
        raise CalibrationCaptureError("existing hand-eye manifest is unsafe")
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CalibrationCaptureError("existing hand-eye manifest cannot be parsed") from exc
    if not isinstance(manifest, dict) or not isinstance(manifest.get("samples"), list):
        raise CalibrationCaptureError("existing hand-eye manifest is invalid")
    supplied = manifest.pop("content_id", None)
    expected = f"sha256:{hashlib.sha256(_canonical(manifest)).hexdigest()}"
    if supplied != expected:
        raise CalibrationCaptureError("existing hand-eye manifest integrity check failed")
    return manifest


def append_handeye_sample(
    output: Path | str,
    *,
    sample_id: str,
    jpeg: bytes,
    robot: ReadOnlyRobotState,
    observation: CalibrationTargetObservation,
    target: CalibrationTargetSpec,
    camchain_source_id: str,
) -> Path:
    """Atomically append one observation; every fifth pose is held out."""

    if not isinstance(sample_id, str) or not sample_id or len(sample_id) > 128:
        raise CalibrationCaptureError("sample ID is invalid")
    if not isinstance(jpeg, bytes) or not jpeg:
        raise CalibrationCaptureError("sample JPEG is empty")
    if not isinstance(robot, ReadOnlyRobotState) or not isinstance(
        observation, CalibrationTargetObservation
    ):
        raise CalibrationCaptureError("typed robot and board observations are required")
    if not isinstance(target, (AprilGridSpec, CharucoSpec)):
        raise CalibrationCaptureError("typed calibration target is required")
    if (
        not isinstance(camchain_source_id, str)
        or len(camchain_source_id) != 71
        or not camchain_source_id.startswith("sha256:")
    ):
        raise CalibrationCaptureError("camchain source ID is invalid")
    root = Path(output)
    manifest_path = root / "handeye.json"
    manifest = _load_manifest(manifest_path)
    if manifest is None:
        manifest = {
            "schema_version": 2,
            "camera": "d435_rgb_raw",
            "camchain_source_id": camchain_source_id,
            "target": target.to_json(),
            "robot_state_access": "read_only_status",
            "motion_command_access": False,
            "samples": [],
        }
    if manifest.get("schema_version") != 2:
        raise CalibrationCaptureError("hand-eye dataset schema cannot change during capture")
    if manifest.get("camchain_source_id") != camchain_source_id:
        raise CalibrationCaptureError("camchain changed during hand-eye capture")
    if manifest.get("target") != target.to_json():
        raise CalibrationCaptureError(
            "calibration target changed during hand-eye capture"
        )
    samples = manifest["samples"]
    if any(item.get("sample_id") == sample_id for item in samples if isinstance(item, dict)):
        raise CalibrationCaptureError("sample ID is duplicated")
    if len(samples) >= 128:
        raise CalibrationCaptureError("hand-eye dataset cannot exceed 128 samples")
    from vision_models.calibration_diversity import transform_is_distinct

    previous_flange_poses = [
        item["T_base_from_flange"]
        for item in samples
        if isinstance(item, dict) and "T_base_from_flange" in item
    ]
    if previous_flange_poses and not transform_is_distinct(
        robot.t_base_from_flange,
        previous_flange_poses,
        translation_m=0.008,
        rotation_deg=3.0,
    ):
        raise CalibrationCaptureError(
            "hand-eye robot pose must be distinct from every accepted sample"
        )
    image_relative = Path("images") / f"{sample_id}.jpg"
    image_path = root / image_relative
    if image_path.exists():
        raise CalibrationCaptureError("sample image already exists")
    _atomic_write(image_path, jpeg)
    sample_number = len(samples) + 1
    samples.append(
        {
            "sample_id": sample_id,
            "split": "validation" if sample_number % 5 == 0 else "fit",
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
    result = dict(manifest)
    result["content_id"] = f"sha256:{hashlib.sha256(_canonical(manifest)).hexdigest()}"
    _atomic_write(
        manifest_path,
        json.dumps(result, sort_keys=True, indent=2, ensure_ascii=True).encode("ascii") + b"\n",
    )
    return manifest_path


__all__ = [
    "AprilGridCorners",
    "AprilGridObservation",
    "AprilGridSpec",
    "CalibrationCaptureError",
    "CalibrationTargetObservation",
    "CalibrationTargetSpec",
    "CharucoSpec",
    "ReadOnlyRobotState",
    "TargetCorners",
    "append_handeye_sample",
    "detect_aprilgrid_corners",
    "detect_aprilgrid_pose",
    "detect_target_corners",
    "detect_target_pose",
    "load_aprilgrid_target",
    "load_calibration_target",
    "parse_robot_state",
]
