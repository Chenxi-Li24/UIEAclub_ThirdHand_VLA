"""Immutable, JSON-friendly public data contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping, Optional

import numpy as np

from .errors import InputValidationError


def _integer(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
        raise InputValidationError(f"{name} must be an integer")
    result = int(value)
    if result < 0:
        raise InputValidationError(f"{name} must be non-negative")
    return result


def _readonly_array(value: Any, shape: tuple[int, ...], name: str) -> np.ndarray:
    array = np.asarray(value, dtype=float)
    if array.shape != shape or not np.isfinite(array).all():
        raise InputValidationError(f"{name} must be finite with shape {shape}")
    result = np.array(array, copy=True)
    result.setflags(write=False)
    return result


@dataclass(frozen=True)
class FrameStamp:
    source: str
    frame_id: int
    monotonic_ns: int

    def __post_init__(self) -> None:
        if not isinstance(self.source, str) or not self.source.strip():
            raise InputValidationError("frame source must be a non-empty string")
        object.__setattr__(self, "frame_id", _integer(self.frame_id, "frame_id"))
        object.__setattr__(
            self,
            "monotonic_ns",
            _integer(self.monotonic_ns, "monotonic_ns"),
        )


@dataclass(frozen=True)
class CameraCalibrationRef:
    calibration_id: str
    validated: bool
    reprojection_rmse_px: Optional[float] = None

    def __post_init__(self) -> None:
        if not isinstance(self.calibration_id, str) or not self.calibration_id.strip():
            raise InputValidationError("calibration_id must be a non-empty string")
        if not isinstance(self.validated, bool):
            raise InputValidationError("validated must be a boolean")
        if self.reprojection_rmse_px is not None:
            error = float(self.reprojection_rmse_px)
            if not np.isfinite(error) or error < 0.0:
                raise InputValidationError("reprojection RMSE must be finite and non-negative")
            object.__setattr__(self, "reprojection_rmse_px", error)
        if self.validated and self.reprojection_rmse_px is None:
            raise InputValidationError("validated calibration requires reprojection RMSE")


@dataclass(frozen=True)
class FrameBundle:
    rgb: np.ndarray = field(compare=False, repr=False)
    stamp: FrameStamp
    depth_m: Optional[np.ndarray] = field(default=None, compare=False, repr=False)
    depth_stamp: Optional[FrameStamp] = None
    calibration: Any = field(default=None, compare=False, repr=False)
    metadata: Mapping[str, Any] = field(default_factory=dict, compare=False)

    def __post_init__(self) -> None:
        image = np.asarray(self.rgb)
        if image.ndim != 3 or image.shape[2] != 3 or image.dtype != np.uint8:
            raise InputValidationError("RGB image must be a uint8 HxWx3 array")
        rgb = np.array(image, copy=True)
        rgb.setflags(write=False)
        object.__setattr__(self, "rgb", rgb)
        if not isinstance(self.stamp, FrameStamp):
            raise InputValidationError("stamp must be a FrameStamp")
        if self.depth_m is not None:
            depth = np.asarray(self.depth_m)
            if depth.ndim != 2 or not np.issubdtype(depth.dtype, np.floating):
                raise InputValidationError("depth image must be a floating-point 2D array in metres")
            invalid_values = np.isfinite(depth) & (depth <= 0.0)
            if np.isinf(depth).any() or invalid_values.any():
                raise InputValidationError("finite depth values must be positive metres")
            depth_copy = np.array(depth, dtype=np.float32, copy=True)
            depth_copy.setflags(write=False)
            object.__setattr__(self, "depth_m", depth_copy)
            if self.depth_stamp is None:
                object.__setattr__(self, "depth_stamp", self.stamp)
        elif self.depth_stamp is not None:
            raise InputValidationError("depth_stamp requires a depth image")
        if self.depth_stamp is not None and not isinstance(self.depth_stamp, FrameStamp):
            raise InputValidationError("depth_stamp must be a FrameStamp")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True)
class InstanceDetection:
    detection_id: int
    label: str
    score: float
    bbox_xyxy: np.ndarray = field(compare=False, repr=False)
    mask: np.ndarray = field(compare=False, repr=False)
    image_shape: tuple[int, int]

    def __post_init__(self) -> None:
        object.__setattr__(self, "detection_id", _integer(self.detection_id, "detection_id"))
        if not isinstance(self.label, str) or not self.label.strip():
            raise InputValidationError("detection label must be a non-empty string")
        score = float(self.score)
        if not np.isfinite(score) or not 0.0 <= score <= 1.0:
            raise InputValidationError("detection score must be within [0, 1]")
        object.__setattr__(self, "score", score)
        if (
            not isinstance(self.image_shape, tuple)
            or len(self.image_shape) != 2
            or any(isinstance(value, bool) or not isinstance(value, int) or value < 1 for value in self.image_shape)
        ):
            raise InputValidationError("image_shape must contain positive height and width")
        box = _readonly_array(self.bbox_xyxy, (4,), "bbox_xyxy")
        mask = np.asarray(self.mask)
        if mask.dtype != np.bool_ or mask.shape != self.image_shape:
            raise InputValidationError("instance mask must be boolean and match image_shape")
        mask_copy = np.array(mask, copy=True)
        mask_copy.setflags(write=False)
        object.__setattr__(self, "bbox_xyxy", box)
        object.__setattr__(self, "mask", mask_copy)


@dataclass(frozen=True)
class PoseEstimate:
    xyz_m: np.ndarray = field(compare=False, repr=False)
    covariance_m2: np.ndarray = field(compare=False, repr=False)
    frame: str
    stamp: FrameStamp
    calibration_id: str

    def __post_init__(self) -> None:
        xyz = _readonly_array(self.xyz_m, (3,), "xyz_m")
        covariance = _readonly_array(self.covariance_m2, (3, 3), "covariance_m2")
        if not np.allclose(covariance, covariance.T, atol=1e-12):
            raise InputValidationError("covariance must be symmetric")
        if float(np.min(np.linalg.eigvalsh(covariance))) < -1e-12:
            raise InputValidationError("covariance must be positive semidefinite")
        if not isinstance(self.frame, str) or not self.frame.strip():
            raise InputValidationError("pose frame must be a non-empty string")
        if not isinstance(self.stamp, FrameStamp):
            raise InputValidationError("pose stamp must be a FrameStamp")
        if not isinstance(self.calibration_id, str) or not self.calibration_id.strip():
            raise InputValidationError("pose calibration_id must be a non-empty string")
        object.__setattr__(self, "xyz_m", xyz)
        object.__setattr__(self, "covariance_m2", covariance)

    def to_dict(self) -> dict[str, Any]:
        return {
            "xyz_m": self.xyz_m.tolist(),
            "covariance_m2": self.covariance_m2.tolist(),
            "frame": self.frame,
            "frame_id": self.stamp.frame_id,
            "monotonic_ns": self.stamp.monotonic_ns,
            "calibration_id": self.calibration_id,
        }


@dataclass(frozen=True)
class PerceptionInstance:
    detection: InstanceDetection
    identity_id: Optional[int]
    identity_status: str
    descriptor: np.ndarray = field(compare=False, repr=False)
    pose: Optional[PoseEstimate]
    reasons: tuple[str, ...] = ()
    annotations: Mapping[str, Any] = field(default_factory=dict, compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self.detection, InstanceDetection):
            raise InputValidationError("detection must be an InstanceDetection")
        if self.identity_id is not None:
            object.__setattr__(self, "identity_id", _integer(self.identity_id, "identity_id"))
        if not isinstance(self.identity_status, str) or not self.identity_status:
            raise InputValidationError("identity_status must be a non-empty string")
        descriptor = np.asarray(self.descriptor, dtype=float)
        if descriptor.ndim != 1 or not len(descriptor) or not np.isfinite(descriptor).all():
            raise InputValidationError("descriptor must be a finite non-empty vector")
        norm = float(np.linalg.norm(descriptor))
        if not np.isfinite(norm) or norm <= 0.0:
            raise InputValidationError("descriptor norm must be positive")
        descriptor = np.array(descriptor / norm, copy=True)
        descriptor.setflags(write=False)
        object.__setattr__(self, "descriptor", descriptor)
        if self.pose is not None and not isinstance(self.pose, PoseEstimate):
            raise InputValidationError("pose must be a PoseEstimate or None")
        if any(not isinstance(reason, str) or not reason for reason in self.reasons):
            raise InputValidationError("reasons must contain non-empty strings")
        object.__setattr__(self, "reasons", tuple(dict.fromkeys(self.reasons)))
        object.__setattr__(self, "annotations", MappingProxyType(dict(self.annotations)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "detection_id": self.detection.detection_id,
            "label": self.detection.label,
            "score": self.detection.score,
            "bbox_xyxy": self.detection.bbox_xyxy.tolist(),
            "identity_id": self.identity_id,
            "identity_status": self.identity_status,
            "pose": None if self.pose is None else self.pose.to_dict(),
            "reasons": list(self.reasons),
            "annotations": dict(self.annotations),
        }


@dataclass(frozen=True)
class PerceptionResult:
    frame_id: int
    monotonic_ns: int
    instances: tuple[PerceptionInstance, ...]
    blockers: tuple[str, ...] = ()
    extension_errors: tuple[str, ...] = ()
    selected_identity_id: Optional[int] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "frame_id", _integer(self.frame_id, "frame_id"))
        object.__setattr__(self, "monotonic_ns", _integer(self.monotonic_ns, "monotonic_ns"))
        instances = tuple(self.instances)
        if any(not isinstance(item, PerceptionInstance) for item in instances):
            raise InputValidationError("instances must contain PerceptionInstance values")
        object.__setattr__(self, "instances", instances)
        for name in ("blockers", "extension_errors"):
            values = tuple(getattr(self, name))
            if any(not isinstance(value, str) or not value for value in values):
                raise InputValidationError(f"{name} must contain non-empty strings")
            object.__setattr__(self, name, tuple(dict.fromkeys(values)))
        if self.selected_identity_id is not None:
            selected = _integer(self.selected_identity_id, "selected_identity_id")
            known = {item.identity_id for item in instances if item.identity_id is not None}
            if selected not in known:
                raise InputValidationError("selected identity must exist in instances")
            object.__setattr__(self, "selected_identity_id", selected)

    def to_dict(self) -> dict[str, Any]:
        return {
            "frame_id": self.frame_id,
            "monotonic_ns": self.monotonic_ns,
            "instances": [item.to_dict() for item in self.instances],
            "blockers": list(self.blockers),
            "extension_errors": list(self.extension_errors),
            "selected_identity_id": self.selected_identity_id,
        }
