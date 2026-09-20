"""Fail-closed eye-in-hand projection from XVisio camera to robot base."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
from threading import Lock
import time
from typing import Any, Mapping

import numpy as np

from thirdhand_va.common.contracts import ArmState, VisionDecision
from thirdhand_va.common.errors import ContractError


class HandEyeError(ContractError):
    """Calibration or arm-state evidence is invalid."""


def _rigid_transform(value: Any, name: str) -> np.ndarray:
    matrix = np.asarray(value, dtype=np.float64)
    if matrix.shape != (4, 4) or not np.isfinite(matrix).all():
        raise HandEyeError(f"{name} must be a finite 4x4 transform")
    if not np.allclose(matrix[3], [0.0, 0.0, 0.0, 1.0], atol=1e-10):
        raise HandEyeError(f"{name} has an invalid homogeneous row")
    rotation = matrix[:3, :3]
    if not np.allclose(rotation.T @ rotation, np.eye(3), atol=1e-7):
        raise HandEyeError(f"{name} rotation is not orthonormal")
    if not np.isclose(np.linalg.det(rotation), 1.0, atol=1e-7):
        raise HandEyeError(f"{name} rotation determinant is not +1")
    return np.array(matrix, copy=True)


def rpy_xyz_transform(position_m: Any, rpy_rad: Any) -> np.ndarray:
    """Match Startouch: Rz(yaw) @ Ry(pitch) @ Rx(roll)."""
    position = np.asarray(position_m, dtype=np.float64)
    rpy = np.asarray(rpy_rad, dtype=np.float64)
    if position.shape != (3,) or rpy.shape != (3,) or not np.isfinite(
        np.concatenate((position, rpy))
    ).all():
        raise HandEyeError("arm pose must contain finite position and RPY triplets")
    roll, pitch, yaw = rpy
    cx, sx = math.cos(roll), math.sin(roll)
    cy, sy = math.cos(pitch), math.sin(pitch)
    cz, sz = math.cos(yaw), math.sin(yaw)
    rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]], dtype=float)
    ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]], dtype=float)
    rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]], dtype=float)
    result = np.eye(4)
    result[:3, :3] = rz @ ry @ rx
    result[:3, 3] = position
    return result


@dataclass(frozen=True, slots=True)
class HandEyeCalibration:
    t_flange_camera: np.ndarray
    content_id: str
    camera_serial: str
    registration_id: str
    camera_mount_id: str
    robot_state_semantics: str
    extrinsic_semantics: str
    pose_semantics_compatible: bool
    numerically_validated: bool
    physically_validated: bool
    approved_for_bottle_grasp: bool

    def __post_init__(self) -> None:
        matrix = _rigid_transform(self.t_flange_camera, "T_flange_camera")
        matrix.setflags(write=False)
        object.__setattr__(self, "t_flange_camera", matrix)

    @classmethod
    def load(
        cls,
        path: Path | str,
        *,
        expected_camera_serial: str | None = None,
        expected_registration_id: str | None = None,
        expected_camera_mount_id: str | None = None,
    ) -> "HandEyeCalibration":
        source = Path(path)
        raw = source.read_bytes()
        try:
            payload = json.loads(raw)
            schema = payload.get("schema")
            if schema == "thirdhand-handeye-calibration-v3":
                matrix = payload["T_flange_camera"]["matrix_4x4"]
                robot_state_semantics = payload["robot_state_semantics"]
                extrinsic_semantics = payload["extrinsic_semantics"]
            elif schema == "thirdhand-handeye-calibration-v2":
                # V2 described a configurable tool TCP, so it is retained for
                # offline diagnosis only.  It can never authorize motion.
                matrix = payload["T_tool_camera"]["matrix_4x4"]
                tcp_semantics = payload["tcp_semantics"]
                robot_state_semantics = f"T_base_{tcp_semantics}"
                extrinsic_semantics = f"T_{tcp_semantics}_camera"
            else:
                raise HandEyeError("unsupported hand-eye calibration schema")
            serial = payload["camera"]["camera_serial"]
            registration_id = payload["camera"]["registration_id"]
            camera_mount_id = payload["camera"]["camera_mount_id"]
        except HandEyeError:
            raise
        except (KeyError, TypeError, json.JSONDecodeError) as error:
            raise HandEyeError("hand-eye calibration contract is incomplete") from error
        physical = payload.get("physical_validation", {})
        measured = physical.get("measured_error_m")
        limit = physical.get("required_3d_point_or_grasp_error_m_max")
        pose_semantics_compatible = (
            schema == "thirdhand-handeye-calibration-v3"
            and robot_state_semantics == "T_base_flange"
            and extrinsic_semantics == "T_flange_camera"
        )
        identity_valid = (
            isinstance(serial, str) and bool(serial.strip())
            and isinstance(registration_id, str) and bool(registration_id.strip())
            and isinstance(camera_mount_id, str) and bool(camera_mount_id.strip())
            and pose_semantics_compatible
            and (expected_camera_serial is None or serial == expected_camera_serial)
            and (
                expected_registration_id is None
                or registration_id == expected_registration_id
            )
            and (
                expected_camera_mount_id is None
                or camera_mount_id == expected_camera_mount_id
            )
        )
        physically_validated = (
            physical.get("status") == "passed"
            and isinstance(measured, (int, float))
            and isinstance(limit, (int, float))
            and math.isfinite(float(measured))
            and 0.0 <= float(measured)
            and math.isfinite(float(limit))
            and 0.0 < float(limit) <= 0.010
            and float(measured) <= float(limit)
            and float(measured) <= 0.010
        )
        numerically_validated = payload.get("numerically_validated") is True
        mount_activated = (
            payload.get("camera_mount_id_activation") is True
            and payload.get("activated_camera_mount_id") == camera_mount_id
        )
        return cls(
            t_flange_camera=_rigid_transform(matrix, "T_flange_camera"),
            content_id="sha256:" + hashlib.sha256(raw).hexdigest(),
            camera_serial=str(serial),
            registration_id=str(registration_id),
            camera_mount_id=str(camera_mount_id),
            robot_state_semantics=str(robot_state_semantics),
            extrinsic_semantics=str(extrinsic_semantics),
            pose_semantics_compatible=pose_semantics_compatible,
            numerically_validated=numerically_validated,
            physically_validated=physically_validated,
            approved_for_bottle_grasp=(
                payload.get("approved_for_bottle_grasp") is True
                and identity_valid
                and mount_activated
                and numerically_validated
                and physically_validated
            ),
        )

class ArmStateStore:
    def __init__(self) -> None:
        self._lock = Lock()
        self._state: ArmState | None = None

    def update(self, message: Mapping[str, Any]) -> None:
        received_ns = time.monotonic_ns()
        with self._lock:
            stationary = message.get("stationary") is True
            stationary_since_ns = received_ns
            if stationary and self._state is not None and self._state.stationary:
                stationary_since_ns = self._state.stationary_since_monotonic_ns
            state = ArmState.from_message(
                message,
                received_monotonic_ns=received_ns,
                stationary_since_monotonic_ns=stationary_since_ns,
            )
            self._state = state

    def latest(self) -> ArmState | None:
        with self._lock:
            return self._state


def build_base_grasp_preview(
    decision: VisionDecision,
    calibration: HandEyeCalibration,
    arm_state: ArmState | None,
    *,
    observed_at_ms: int,
    now_monotonic_ns: int,
    frame_monotonic_ns: int | None = None,
    vision_config_id: str,
    model_provenance: Mapping[str, str],
    pregrasp_offset_m: float = 0.10,
    max_arm_state_age_ms: float = 250.0,
    stationary_settle_ms: float = 300.0,
) -> dict[str, Any] | None:
    """Return a provenance-bound preview; never claim approval prematurely."""
    if decision.pose is None or decision.target is None:
        return None
    blockers: list[str] = []
    if decision.status != "ready":
        blockers.append("vision_not_ready")
    if calibration.camera_serial == "":
        blockers.append("camera_serial_invalid")
    if not calibration.numerically_validated:
        blockers.append("handeye_numerical_validation_missing")
    if not calibration.pose_semantics_compatible:
        blockers.append("handeye_pose_semantics_mismatch")
    if not calibration.physically_validated:
        blockers.append("handeye_physical_validation_pending")
    if not calibration.approved_for_bottle_grasp:
        blockers.append("handeye_activation_locked")
    if arm_state is None:
        blockers.append("arm_state_missing")
        return {"blockers": blockers, "allowed": False}
    age_ms = (now_monotonic_ns - arm_state.received_monotonic_ns) / 1_000_000
    if age_ms < 0 or age_ms > max_arm_state_age_ms:
        blockers.append("arm_state_stale")
    if not arm_state.stationary:
        blockers.append("arm_not_stationary")
    if frame_monotonic_ns is not None:
        settled_frame_ns = arm_state.stationary_since_monotonic_ns + int(
            stationary_settle_ms * 1_000_000
        )
        if frame_monotonic_ns < settled_frame_ns:
            blockers.append("frame_precedes_stationary_settle")

    t_base_camera = rpy_xyz_transform(
        arm_state.flange_position_m, arm_state.flange_euler_rad
    ) @ calibration.t_flange_camera
    point_camera = np.array([*decision.pose.point_m, 1.0])
    surface_point_base = (t_base_camera @ point_camera)[:3]
    # This cell uses a horizontal side grasp whose final insertion axis is the
    # robot-base +X axis.  Do not derive that axis from per-frame PCA: a partly
    # transparent bottle makes the fitted camera ray wobble laterally and would
    # turn both the center correction and the final approach into a diagonal.
    # Registered depth observes the near bottle skin, not its centerline, so
    # advance one measured silhouette radius along the same fixed +X axis.
    approach_base = np.array([1.0, 0.0, 0.0], dtype=float)
    checked_approach_camera = np.asarray(decision.pose.approach, dtype=float)
    checked_approach_base = t_base_camera[:3, :3] @ checked_approach_camera
    checked_norm = float(np.linalg.norm(checked_approach_base))
    if checked_norm <= 1e-9 or not np.isfinite(checked_norm):
        blockers.append("approach_corridor_axis_invalid")
    elif float(np.dot(checked_approach_base / checked_norm, approach_base)) < 0.999:
        blockers.append("approach_corridor_axis_mismatch")
    center_advance_m = float(np.clip(decision.pose.width_m * 0.5, 0.006, 0.040))
    point_base = surface_point_base + approach_base * center_advance_m
    pregrasp = point_base - approach_base * float(pregrasp_offset_m)
    retreat = np.array(pregrasp, copy=True)

    evidence = [
        calibration.content_id,
        "sha256:" + hashlib.sha256(
            f"{decision.frame_id}:{observed_at_ms}:{decision.target.detection_id}".encode()
        ).hexdigest(),
    ]
    arm_state_core = {
        "pose_frame": arm_state.pose_frame,
        "flange_position_m": list(arm_state.flange_position_m),
        "flange_euler_rad": list(arm_state.flange_euler_rad),
        "observed_monotonic_ns": arm_state.observed_monotonic_ns,
        "received_monotonic_ns": arm_state.received_monotonic_ns,
        "stationary_since_monotonic_ns": arm_state.stationary_since_monotonic_ns,
    }
    arm_state_id = "sha256:" + hashlib.sha256(
        json.dumps(arm_state_core, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    preview_core = {
        "identity_id": (
            decision.selected_stable_id
            if decision.selected_stable_id is not None
            else decision.target.detection_id
        ),
        "detection_id": decision.target.detection_id,
        "frame": "robot_base",
        "calibration_id": calibration.content_id,
        "evidence_ids": evidence,
        "vision_evidence_id": decision.evidence_id,
        "vision_config_id": vision_config_id,
        "model_provenance": dict(model_provenance),
        "arm_state_id": arm_state_id,
        "arm_state": arm_state_core,
        "grasp_xyz_m": point_base.tolist(),
        "surface_xyz_m": surface_point_base.tolist(),
        "approach_base": approach_base.tolist(),
        "center_advance_m": center_advance_m,
        "grasp_lumos_px": [
            float(np.nonzero(decision.target.mask)[1].mean()),
            float(np.nonzero(decision.target.mask)[0].mean()),
        ],
        "pregrasp_xyz_m": pregrasp.tolist(),
        "retreat_xyz_m": retreat.tolist(),
        "yaw_rad": float(arm_state.flange_euler_rad[2]),
        "width_m": float(decision.pose.width_m),
        "object_height_m": (
            None if decision.pose.height_m is None else float(decision.pose.height_m)
        ),
        "central_fraction": float(decision.pose.depth_valid_ratio),
        "stable_samples": int(decision.stable_hits),
        "allowed": len(blockers) == 0,
        "blockers": blockers,
    }
    preview_core["preview_id"] = "sha256:" + hashlib.sha256(
        json.dumps(preview_core, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return preview_core
