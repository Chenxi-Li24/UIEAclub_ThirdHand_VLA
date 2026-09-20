"""Offline OpenCV eye-in-hand solver with held-out numerical validation."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

import cv2
import numpy as np

from .handeye import _rigid_transform


class HandEyeSolveError(ValueError):
    """The sample contract or its calibration geometry is insufficient."""


@dataclass(frozen=True, slots=True)
class _Sample:
    sample_id: str
    t_base_tool: np.ndarray
    t_camera_target: np.ndarray


@dataclass(frozen=True, slots=True)
class _ErrorMetrics:
    translation_rmse_m: float
    translation_p95_m: float
    rotation_rmse_deg: float
    rotation_p95_deg: float

    def as_dict(self) -> dict[str, float]:
        return {
            "translation_rmse_m": self.translation_rmse_m,
            "translation_p95_m": self.translation_p95_m,
            "rotation_rmse_deg": self.rotation_rmse_deg,
            "rotation_p95_deg": self.rotation_p95_deg,
        }


@dataclass(frozen=True, slots=True)
class HandEyeSolveReport:
    t_tool_camera: np.ndarray
    manifest_id: str
    camera_serial: str
    registration_id: str
    camera_mount_id: str
    tcp_semantics: str
    fit_sample_ids: tuple[str, ...]
    validation_sample_ids: tuple[str, ...]
    rotation_axis_diversity: float
    fit_metrics: _ErrorMetrics
    validation_metrics: _ErrorMetrics
    numerically_validated: bool

    def __post_init__(self) -> None:
        matrix = _rigid_transform(self.t_tool_camera, "T_tool_camera")
        matrix.setflags(write=False)
        object.__setattr__(self, "t_tool_camera", matrix)

    @property
    def fit_sample_count(self) -> int:
        return len(self.fit_sample_ids)

    @property
    def validation_sample_count(self) -> int:
        return len(self.validation_sample_ids)

    @property
    def validation_translation_rmse_m(self) -> float:
        return self.validation_metrics.translation_rmse_m

    @property
    def validation_rotation_rmse_deg(self) -> float:
        return self.validation_metrics.rotation_rmse_deg

    def to_calibration_payload(self) -> dict[str, Any]:
        """Return a numerical result that remains locked for physical use."""
        return {
            "schema": "thirdhand-handeye-calibration-v2",
            "camera": {
                "camera_serial": self.camera_serial,
                "registration_id": self.registration_id,
                "camera_mount_id": self.camera_mount_id,
            },
            "tcp_semantics": self.tcp_semantics,
            "T_tool_camera": {"matrix_4x4": self.t_tool_camera.tolist()},
            "solver": {
                "library": "opencv",
                "opencv_version": cv2.__version__,
                "method": "CALIB_HAND_EYE_DANIILIDIS",
            },
            "sample_manifest_id": self.manifest_id,
            "fit_sample_ids": list(self.fit_sample_ids),
            "validation_sample_ids": list(self.validation_sample_ids),
            "fit_sample_count": self.fit_sample_count,
            "validation_sample_count": self.validation_sample_count,
            "rotation_axis_diversity": self.rotation_axis_diversity,
            "fit_error": self.fit_metrics.as_dict(),
            "validation_error": self.validation_metrics.as_dict(),
            "numerically_validated": self.numerically_validated,
            "camera_mount_id_activation": False,
            "activated_camera_mount_id": None,
            "physical_validation": {
                "status": "pending",
                "measured_error_m": None,
                "required_3d_point_or_grasp_error_m_max": 0.010,
            },
            "approved_for_bottle_grasp": False,
            "robot_control_enabled": False,
        }


def _load_manifest(
    manifest: Mapping[str, Any] | str | Path,
) -> tuple[dict[str, Any], bytes]:
    if isinstance(manifest, (str, Path)):
        raw = Path(manifest).read_bytes()
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as error:
            raise HandEyeSolveError("manifest is not valid JSON") from error
    elif isinstance(manifest, Mapping):
        payload = dict(manifest)
        raw = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    else:
        raise HandEyeSolveError("manifest must be a mapping or JSON path")
    if not isinstance(payload, dict):
        raise HandEyeSolveError("manifest root must be an object")
    return payload, raw


def _parse_samples(value: Any, field: str, minimum: int) -> tuple[_Sample, ...]:
    if not isinstance(value, list) or len(value) < minimum:
        raise HandEyeSolveError(f"{field} requires at least {minimum} samples")
    parsed: list[_Sample] = []
    seen: set[str] = set()
    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            raise HandEyeSolveError(f"{field}[{index}] must be an object")
        sample_id = item.get("sample_id")
        if not isinstance(sample_id, str) or not sample_id or sample_id in seen:
            raise HandEyeSolveError(f"{field} sample_id must be unique and non-empty")
        seen.add(sample_id)
        try:
            base_tool = _rigid_transform(item.get("T_base_tool"), "T_base_tool")
            camera_target = _rigid_transform(
                item.get("T_camera_target"), "T_camera_target"
            )
        except Exception as error:
            raise HandEyeSolveError(f"{field}[{index}] transform is invalid") from error
        parsed.append(_Sample(sample_id, base_tool, camera_target))
    return tuple(parsed)


def _rotation_axis_diversity(samples: tuple[_Sample, ...]) -> float:
    axes: list[np.ndarray] = []
    for left in range(len(samples) - 1):
        r_left = samples[left].t_base_tool[:3, :3]
        for right in range(left + 1, len(samples)):
            relative = r_left.T @ samples[right].t_base_tool[:3, :3]
            vector = cv2.Rodrigues(relative)[0].reshape(3)
            angle = float(np.linalg.norm(vector))
            if angle >= math.radians(5.0):
                axes.append(vector / angle)
    if len(axes) < 6:
        return 0.0
    scatter = sum(np.outer(axis, axis) for axis in axes) / len(axes)
    eigenvalues = np.linalg.eigvalsh(scatter)
    if eigenvalues[-1] <= 0:
        return 0.0
    return float(eigenvalues[-2] / eigenvalues[-1])


def _mean_rotation(rotations: list[np.ndarray]) -> np.ndarray:
    u, _, vt = np.linalg.svd(np.mean(rotations, axis=0))
    correction = np.eye(3)
    correction[-1, -1] = np.linalg.det(u @ vt)
    return u @ correction @ vt


def _error_metrics(
    samples: tuple[_Sample, ...], t_tool_camera: np.ndarray
) -> _ErrorMetrics:
    implied = [
        sample.t_base_tool @ t_tool_camera @ sample.t_camera_target
        for sample in samples
    ]
    reference_translation = np.median(
        np.asarray([item[:3, 3] for item in implied]), axis=0
    )
    reference_rotation = _mean_rotation([item[:3, :3] for item in implied])
    translation_errors = np.asarray(
        [np.linalg.norm(item[:3, 3] - reference_translation) for item in implied]
    )
    rotation_errors = np.asarray(
        [
            math.degrees(
                math.acos(
                    float(
                        np.clip(
                            (np.trace(reference_rotation.T @ item[:3, :3]) - 1.0)
                            / 2.0,
                            -1.0,
                            1.0,
                        )
                    )
                )
            )
            for item in implied
        ]
    )
    return _ErrorMetrics(
        translation_rmse_m=float(np.sqrt(np.mean(translation_errors**2))),
        translation_p95_m=float(np.percentile(translation_errors, 95)),
        rotation_rmse_deg=float(np.sqrt(np.mean(rotation_errors**2))),
        rotation_p95_deg=float(np.percentile(rotation_errors, 95)),
    )


def solve_handeye(
    manifest: Mapping[str, Any] | str | Path,
) -> HandEyeSolveReport:
    """Solve one eye-in-hand manifest without accessing robot or camera hardware."""
    payload, raw = _load_manifest(manifest)
    if payload.get("schema") != "thirdhand-handeye-samples-v1":
        raise HandEyeSolveError("unsupported hand-eye sample schema")
    camera = payload.get("camera")
    if not isinstance(camera, Mapping):
        raise HandEyeSolveError("camera provenance is required")
    serial = camera.get("camera_serial")
    registration_id = camera.get("registration_id")
    camera_mount_id = camera.get("camera_mount_id")
    if not isinstance(serial, str) or not serial:
        raise HandEyeSolveError("camera_serial is required")
    if not isinstance(registration_id, str) or not registration_id:
        raise HandEyeSolveError("registration_id is required")
    if not isinstance(camera_mount_id, str) or not camera_mount_id:
        raise HandEyeSolveError("camera_mount_id is required")
    tcp_semantics = payload.get("tcp_semantics")
    if tcp_semantics != "configured_tool_tcp":
        raise HandEyeSolveError("tcp_semantics must be configured_tool_tcp")

    fit = _parse_samples(payload.get("fit_samples"), "fit_samples", 12)
    validation = _parse_samples(
        payload.get("validation_samples"), "validation_samples", 3
    )
    if set(item.sample_id for item in fit) & set(
        item.sample_id for item in validation
    ):
        raise HandEyeSolveError("fit and validation sample IDs must be independent")
    diversity = _rotation_axis_diversity(fit)
    if diversity < 0.05:
        raise HandEyeSolveError(
            f"rotation_axis_diversity is insufficient: {diversity:.6f}"
        )

    rotations_tool_to_base = [item.t_base_tool[:3, :3] for item in fit]
    translations_tool_to_base = [item.t_base_tool[:3, 3] for item in fit]
    rotations_target_to_camera = [item.t_camera_target[:3, :3] for item in fit]
    translations_target_to_camera = [item.t_camera_target[:3, 3] for item in fit]
    try:
        rotation, translation = cv2.calibrateHandEye(
            rotations_tool_to_base,
            translations_tool_to_base,
            rotations_target_to_camera,
            translations_target_to_camera,
            method=cv2.CALIB_HAND_EYE_DANIILIDIS,
        )
    except cv2.error as error:
        raise HandEyeSolveError(f"OpenCV calibrateHandEye failed: {error}") from error
    t_tool_camera = np.eye(4, dtype=np.float64)
    t_tool_camera[:3, :3] = np.asarray(rotation, dtype=np.float64)
    t_tool_camera[:3, 3] = np.asarray(translation, dtype=np.float64).reshape(3)
    if not np.isfinite(t_tool_camera).all():
        raise HandEyeSolveError("OpenCV calibrateHandEye returned non-finite values")

    fit_metrics = _error_metrics(fit, t_tool_camera)
    validation_metrics = _error_metrics(validation, t_tool_camera)
    numerically_validated = (
        validation_metrics.translation_rmse_m <= 0.005
        and validation_metrics.translation_p95_m <= 0.010
        and validation_metrics.rotation_rmse_deg <= 2.0
        and validation_metrics.rotation_p95_deg <= 3.0
    )
    return HandEyeSolveReport(
        t_tool_camera=t_tool_camera,
        manifest_id="sha256:" + hashlib.sha256(raw).hexdigest(),
        camera_serial=serial,
        registration_id=registration_id,
        camera_mount_id=camera_mount_id,
        tcp_semantics=tcp_semantics,
        fit_sample_ids=tuple(item.sample_id for item in fit),
        validation_sample_ids=tuple(item.sample_id for item in validation),
        rotation_axis_diversity=diversity,
        fit_metrics=fit_metrics,
        validation_metrics=validation_metrics,
        numerically_validated=numerically_validated,
    )


__all__ = ["HandEyeSolveError", "HandEyeSolveReport", "solve_handeye"]
