"""Fail-closed Lumos RGB and D435 depth fusion for persistent identities."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Iterable, Optional

import numpy as np

from vision_models.contracts import InstanceDetection

from .calibration_gate import CalibrationAudit
from .camera_models import PinholeCamera, SeucmCamera
from .depth_registration import register_depth_to_lumos
from .identity import (
    IdentityObservation,
    IdentityStatus,
    PersistentIdentityMemory,
)
from .instance_pose import InstancePoseConfig, estimate_instance_pose
from .geometry import validate_transform
from .types import CalibrationRef, FrameStamp, InvalidDataError, PoseEstimate


def dual_camera_calibration_id(
    d435: PinholeCamera,
    lumos: SeucmCamera,
    t_lumos_from_d435: np.ndarray,
    t_flange_from_lumos: np.ndarray,
    reprojection_rmse_px: Optional[float],
    source_audit_ids: tuple[str, str],
) -> str:
    """Hash every fixed camera-model and extrinsic value used by fusion."""

    reprojection = None if reprojection_rmse_px is None else float(reprojection_rmse_px)
    if reprojection is not None and (not np.isfinite(reprojection) or reprojection < 0.0):
        raise InvalidDataError("reprojection_rmse_px must be finite and non-negative")
    d435_transform = validate_transform(t_lumos_from_d435)
    lumos_transform = validate_transform(t_flange_from_lumos)
    if (
        len(source_audit_ids) != 2
        or any(not value.startswith("sha256:") for value in source_audit_ids)
    ):
        raise InvalidDataError("fusion calibration requires two content-addressed audits")
    payload = {
        "schema_version": 1,
        "d435": {
            "fx": d435.fx,
            "fy": d435.fy,
            "cx": d435.cx,
            "cy": d435.cy,
            "width": d435.width,
            "height": d435.height,
        },
        "lumos": {
            "fx": lumos.fx,
            "fy": lumos.fy,
            "cx": lumos.cx,
            "cy": lumos.cy,
            "alpha": lumos.alpha,
            "beta": lumos.beta,
            "width": lumos.width,
            "height": lumos.height,
        },
        "t_lumos_from_d435": d435_transform.tolist(),
        "t_flange_from_lumos": lumos_transform.tolist(),
        "reprojection_rmse_px": reprojection,
        "source_audit_ids": list(source_audit_ids),
    }
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("ascii")
    return f"sha256:{hashlib.sha256(canonical).hexdigest()}"


@dataclass(frozen=True, init=False)
class DualCameraCalibrationBundle:
    calibration: CalibrationRef
    d435: PinholeCamera
    lumos: SeucmCamera
    t_lumos_from_d435: np.ndarray
    t_flange_from_lumos: np.ndarray
    source_audit_ids: tuple[str, str]

    def __new__(cls, *_args, **_kwargs):
        raise TypeError("use DualCameraCalibrationBundle.from_audits()")

    @classmethod
    def from_audits(
        cls,
        *,
        d435: PinholeCamera,
        lumos: SeucmCamera,
        d435_to_lumos_audit: CalibrationAudit,
        lumos_to_flange_audit: CalibrationAudit,
    ) -> "DualCameraCalibrationBundle":
        if not isinstance(d435_to_lumos_audit, CalibrationAudit) or not isinstance(
            lumos_to_flange_audit, CalibrationAudit
        ):
            raise InvalidDataError("fusion bundle requires concrete calibration audits")
        source_audits = (d435_to_lumos_audit, lumos_to_flange_audit)
        for audit in source_audits:
            audit.verify_integrity()
        expected_keys = ("T_lumos_from_d435", "T_flange_from_lumos")
        if tuple(item.transform_key for item in source_audits) != expected_keys:
            raise InvalidDataError("calibration audit directions do not match the fusion chain")
        source_ids = tuple(item.calibration.calibration_id for item in source_audits)
        validated = all(item.calibration.validated for item in source_audits)
        reprojection = (
            max(float(item.calibration.reprojection_rmse_px) for item in source_audits)
            if validated
            else None
        )
        d435_transform = validate_transform(d435_to_lumos_audit.transform)
        lumos_transform = validate_transform(lumos_to_flange_audit.transform)
        calibration_id = dual_camera_calibration_id(
            d435,
            lumos,
            d435_transform,
            lumos_transform,
            reprojection,
            source_ids,
        )
        calibration = CalibrationRef(
            calibration_id=calibration_id,
            validated=validated,
            reprojection_rmse_px=reprojection,
            validation_notes=tuple(
                f"source_audit:{calibration_id}"
                for calibration_id in source_ids
            ),
        )
        d435_transform.setflags(write=False)
        lumos_transform.setflags(write=False)
        bundle = object.__new__(cls)
        object.__setattr__(bundle, "calibration", calibration)
        object.__setattr__(bundle, "d435", d435)
        object.__setattr__(bundle, "lumos", lumos)
        object.__setattr__(bundle, "t_lumos_from_d435", d435_transform)
        object.__setattr__(bundle, "t_flange_from_lumos", lumos_transform)
        object.__setattr__(bundle, "source_audit_ids", source_ids)
        return bundle

    def verify_integrity(self) -> None:
        expected_id = dual_camera_calibration_id(
            self.d435,
            self.lumos,
            self.t_lumos_from_d435,
            self.t_flange_from_lumos,
            self.calibration.reprojection_rmse_px,
            self.source_audit_ids,
        )
        if self.calibration.calibration_id != expected_id:
            raise InvalidDataError("fusion calibration bundle content ID mismatch")


@dataclass(frozen=True)
class StampedRobotPose:
    stamp: FrameStamp
    t_base_from_flange: np.ndarray

    def __post_init__(self) -> None:
        if self.stamp.source != "robot_flange_pose":
            raise InvalidDataError("robot pose source must be robot_flange_pose")
        transform = validate_transform(self.t_base_from_flange)
        transform.setflags(write=False)
        object.__setattr__(self, "t_base_from_flange", transform)


@dataclass(frozen=True)
class DualCameraConfig:
    max_frame_skew_ns: int
    max_frame_age_ns: int
    max_robot_pose_skew_ns: int
    min_depth_m: float
    max_depth_m: float
    pose: InstancePoseConfig

    def __post_init__(self) -> None:
        time_limits = (
            self.max_frame_skew_ns,
            self.max_frame_age_ns,
            self.max_robot_pose_skew_ns,
        )
        if any(not isinstance(value, int) or value < 0 for value in time_limits):
            raise InvalidDataError("camera and robot time limits must be non-negative integers")
        limits = np.asarray([self.min_depth_m, self.max_depth_m], dtype=float)
        if not np.isfinite(limits).all() or not 0.0 < limits[0] < limits[1]:
            raise InvalidDataError("depth limits must satisfy 0 < min < max")


@dataclass(frozen=True)
class DualCameraTarget:
    detection_id: int
    label: str
    score: float
    identity_id: Optional[int]
    identity_status: IdentityStatus
    pose: Optional[PoseEstimate]
    registered_depth_points: int
    actionable: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class DualCameraResult:
    canonical_rgb_source: str
    metric_depth_source: str
    frame_skew_ns: int
    targets: tuple[DualCameraTarget, ...]


class DualCameraPerception:
    """Compose registration, mask depth, and appearance identity in one gate."""

    def __init__(
        self,
        identity_memory: PersistentIdentityMemory,
        config: DualCameraConfig,
    ) -> None:
        self.identity_memory = identity_memory
        self.config = config

    def process(
        self,
        *,
        lumos_stamp: FrameStamp,
        d435_stamp: FrameStamp,
        robot_pose: StampedRobotPose,
        detections: Iterable[InstanceDetection],
        descriptors: Iterable[np.ndarray],
        visibilities: Iterable[float],
        d435_depth_z_m: np.ndarray,
        calibration: DualCameraCalibrationBundle,
        arm_stationary: bool,
        now_ns: int,
    ) -> DualCameraResult:
        if lumos_stamp.source != "lumos_rgb":
            raise InvalidDataError("canonical RGB source must be lumos_rgb")
        if d435_stamp.source != "d435_depth":
            raise InvalidDataError("metric depth source must be d435_depth")
        if not isinstance(calibration, DualCameraCalibrationBundle):
            raise InvalidDataError("calibration must be a DualCameraCalibrationBundle")
        calibration.verify_integrity()
        if not isinstance(robot_pose, StampedRobotPose):
            raise InvalidDataError("robot_pose must be a StampedRobotPose")
        if robot_pose.stamp.source != "robot_flange_pose":
            raise InvalidDataError("robot pose source must be robot_flange_pose")
        robot_transform = validate_transform(robot_pose.t_base_from_flange)
        if not isinstance(arm_stationary, (bool, np.bool_)):
            raise InvalidDataError("arm_stationary must be an explicit boolean")

        detection_list = tuple(detections)
        descriptor_list = tuple(descriptors)
        visibility_list = tuple(visibilities)
        if not (
            len(detection_list) == len(descriptor_list) == len(visibility_list)
        ):
            raise InvalidDataError(
                "detections, descriptors, and visibilities must have equal length"
            )
        for item in detection_list:
            if item.mask.shape != (calibration.lumos.height, calibration.lumos.width):
                raise InvalidDataError("instance masks must use native Lumos pixels")

        frame_skew_ns = abs(lumos_stamp.monotonic_ns - d435_stamp.monotonic_ns)
        fusion_ns = max(lumos_stamp.monotonic_ns, d435_stamp.monotonic_ns)
        robot_pose_skew_ns = abs(robot_pose.stamp.monotonic_ns - fusion_ns)
        if now_ns < max(fusion_ns, robot_pose.stamp.monotonic_ns):
            raise InvalidDataError("now_ns cannot precede camera or robot observations")
        fusion_stamp = FrameStamp(
            "lumos_rgb+d435_depth",
            lumos_stamp.frame_id,
            fusion_ns,
        )

        common_reasons: list[str] = []
        if not calibration.calibration.validated:
            common_reasons.append("calibration_not_validated")
        if not arm_stationary:
            common_reasons.append("arm_not_stationary")
        if frame_skew_ns > self.config.max_frame_skew_ns:
            common_reasons.append("frame_skew_exceeded")
        if now_ns - fusion_ns > self.config.max_frame_age_ns:
            common_reasons.append("camera_frames_stale")
        if robot_pose_skew_ns > self.config.max_robot_pose_skew_ns:
            common_reasons.append("robot_pose_skew_exceeded")

        can_fuse_depth = not common_reasons
        registered = None
        t_base_from_lumos = robot_transform @ (
            calibration.t_flange_from_lumos
        )
        t_base_from_lumos = validate_transform(t_base_from_lumos)
        if can_fuse_depth:
            registered = register_depth_to_lumos(
                d435_depth_z_m,
                calibration.d435,
                calibration.t_lumos_from_d435,
                calibration.lumos,
                self.config.min_depth_m,
                self.config.max_depth_m,
            )

        observations: list[IdentityObservation] = []
        pose_by_detection: dict[int, Optional[PoseEstimate]] = {}
        point_count_by_detection: dict[int, int] = {}
        depth_reason_by_detection: dict[int, Optional[str]] = {}
        for item, descriptor, visibility in zip(
            detection_list, descriptor_list, visibility_list
        ):
            pose = None
            point_count = 0
            depth_reason = None
            if registered is not None:
                point_count = int(np.count_nonzero(registered.valid & item.mask))
                try:
                    pose = estimate_instance_pose(
                        registered,
                        item.mask,
                        t_base_from_lumos,
                        fusion_stamp,
                        calibration.calibration.calibration_id,
                        self.config.pose,
                    )
                except InvalidDataError:
                    depth_reason = "insufficient_mask_depth"
            pose_by_detection[item.detection_id] = pose
            point_count_by_detection[item.detection_id] = point_count
            depth_reason_by_detection[item.detection_id] = depth_reason
            observations.append(
                IdentityObservation(
                    observation_id=item.detection_id,
                    label=item.label,
                    confidence=item.score,
                    visibility=float(visibility),
                    descriptor=descriptor,
                    stamp=fusion_stamp,
                    pose=pose,
                )
            )

        self.identity_memory.set_calibration(calibration.calibration)
        update = self.identity_memory.update(observations, fusion_ns)
        snapshots = {item.identity_id: item for item in update.snapshots}
        targets: list[DualCameraTarget] = []
        for item, assignment in zip(detection_list, update.assignments):
            reasons = list(common_reasons)
            depth_reason = depth_reason_by_detection[item.detection_id]
            if depth_reason is not None:
                reasons.append(depth_reason)
            snapshot = snapshots.get(assignment.identity_id)
            if assignment.identity_id is None and assignment.reason:
                reasons.append(assignment.reason)
            if snapshot is None or not snapshot.actionable:
                reasons.append("identity_not_actionable")
            reasons = list(dict.fromkeys(reasons))
            actionable = not reasons
            targets.append(
                DualCameraTarget(
                    detection_id=item.detection_id,
                    label=item.label,
                    score=item.score,
                    identity_id=assignment.identity_id,
                    identity_status=assignment.status,
                    pose=pose_by_detection[item.detection_id],
                    registered_depth_points=point_count_by_detection[item.detection_id],
                    actionable=actionable,
                    reasons=tuple(reasons),
                )
            )
        return DualCameraResult(
            canonical_rgb_source="lumos_rgb",
            metric_depth_source="d435_depth",
            frame_skew_ns=frame_skew_ns,
            targets=tuple(targets),
        )
