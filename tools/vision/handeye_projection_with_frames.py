"""Read-only, timestamp-bound XVisio to robot-base projection."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from contextlib import contextmanager
from pathlib import Path
from threading import Lock

import numpy as np


@dataclass(frozen=True)
class FrameProjectionSnapshot:
    frame_monotonic_ns: int
    robot_observed_monotonic_ns: int | None
    policy_id: str
    calibration_id: str
    invalidation_epoch: int
    matrix_4x4: tuple | None
    status: str
    owner: object = field(repr=False, compare=False)
    frame_id: int | None = None
    camera_serial: str | None = None
    frame_token: object | None = field(default=None, repr=False, compare=False)


def rigid_matrix(value):
    matrix = np.asarray(value, dtype=np.float64)
    if matrix.shape != (4, 4) or not np.isfinite(matrix).all():
        raise ValueError("handeye_matrix_invalid")
    rotation = matrix[:3, :3]
    if (not np.allclose(matrix[3], [0, 0, 0, 1], atol=1e-9)
            or not np.allclose(rotation.T @ rotation, np.eye(3), atol=1e-6)
            or not np.isclose(np.linalg.det(rotation), 1.0, atol=1e-6)):
        raise ValueError("handeye_matrix_not_rigid")
    return matrix


def flange_transform(position, euler):
    xyz = np.asarray(position, dtype=np.float64)
    rpy = np.asarray(euler, dtype=np.float64)
    if xyz.shape != (3,) or rpy.shape != (3,) or not np.isfinite(xyz).all() or not np.isfinite(rpy).all():
        raise ValueError("flange_pose_invalid")
    roll, pitch, yaw = rpy
    cr, sr = math.cos(roll), math.sin(roll)
    cp, sp = math.cos(pitch), math.sin(pitch)
    cy, sy = math.cos(yaw), math.sin(yaw)
    rx = np.array([[1, 0, 0], [0, cr, -sr], [0, sr, cr]])
    ry = np.array([[cp, 0, sp], [0, 1, 0], [-sp, 0, cp]])
    rz = np.array([[cy, -sy, 0], [sy, cy, 0], [0, 0, 1]])
    matrix = np.eye(4)
    matrix[:3, :3] = rz @ ry @ rx
    matrix[:3, 3] = xyz
    return matrix


class HandEyeProjection:
    def __init__(self, calibration_path: Path, camera_serial: str,
                 registration_id: str, mount_id: str, urdf_path: Path,
                 allow_numerical_only: bool = False):
        raw = Path(calibration_path).read_bytes()
        data = json.loads(raw)
        camera = data.get("camera", {})
        if (data.get("schema") != "thirdhand-handeye-calibration-v3"
                or data.get("robot_state_semantics") != "T_base_flange"
                or data.get("extrinsic_semantics") != "T_flange_camera"
                or camera.get("camera_serial") != camera_serial
                or camera.get("registration_id") != registration_id
                or camera.get("camera_mount_id") != mount_id):
            raise ValueError("handeye_identity_or_frame_mismatch")
        self.flange_camera = rigid_matrix(data["T_flange_camera"]["matrix_4x4"])
        self.frame_policy_id = data.get("frame_normalization", {}).get("policy_id")
        if not isinstance(self.frame_policy_id, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", self.frame_policy_id):
            raise ValueError("frame_policy_required")
        self.calibration_id = "sha256:" + hashlib.sha256(raw).hexdigest()
        self.physically_validated = (
            data.get("physical_validation", {}).get("status") == "passed"
        )
        self.allow_numerical_only = bool(allow_numerical_only)
        self.projection_allowed = (
            self.physically_validated
            or (self.allow_numerical_only and data.get("numerically_validated") is True)
        )
        from ikpy.chain import Chain
        parsed = Chain.from_urdf_file(str(urdf_path), base_elements=["base_link"],
                                      active_links_mask=[False, True, True, True,
                                                         True, True, True, False])
        if [link.name for link in parsed.links[1:7]] != [f"joint{i}" for i in range(1, 7)]:
            raise ValueError("urdf_joint_chain_mismatch")
        self.chain = Chain(parsed.links[:7], active_links_mask=[False] + [True] * 6)
        self._lock = Lock()
        self._state = None
        self._invalidation_epoch = 0
        self._snapshot_owner = object()
        self.last_rejection = "robot_state_missing"

    def _invalidate(self, reason):
        with self._lock:
            self._state = None
            self._invalidation_epoch += 1
            self.last_rejection = reason

    def update(self, message, received_ns):
        marker = message.get("frame_normalization") if isinstance(message, dict) else None
        if not isinstance(marker, dict) or marker.get("policy_id") != self.frame_policy_id:
            self._invalidate("robot_frame_policy_mismatch")
            return False
        if (message.get("type") != "arm_state" or message.get("pose_frame") != "robot_flange"
                or message.get("connected") is not True or message.get("healthy") is not True
                or message.get("stationary") is not True):
            self._invalidate("robot_not_stationary_or_healthy")
            return False
        try:
            pose = flange_transform(message["flange_position_m"], message["flange_euler_rad"])
            observed_ns = int(message["observed_monotonic_ns"])
            if observed_ns > received_ns or received_ns - observed_ns > 250_000_000:
                raise ValueError("robot_state_stale")
            joints = np.asarray(message["joints_deg"], dtype=np.float64)
            if joints.shape != (6,) or not np.isfinite(joints).all():
                raise ValueError("robot_joints_invalid")
            # Frame normalization removes the old SDK-tool discrepancy. Never
            # bypass FK agreement, even for numerical-only read-only projection.
            fk = self.chain.forward_kinematics([0.0, *np.deg2rad(joints)])
            orientation_difference = fk[:3, :3].T @ pose[:3, :3]
            orientation_error = math.acos(float(np.clip(
                (np.trace(orientation_difference) - 1) / 2, -1, 1)))
            if (np.linalg.norm(fk[:3, 3] - pose[:3, 3]) > 0.010
                    or orientation_error > 0.10):
                raise ValueError("robot_urdf_fk_mismatch")
        except (ValueError, TypeError, KeyError) as error:
            self._invalidate(str(error) if isinstance(error, ValueError) else "robot_pose_invalid")
            return False
        with self._lock:
            self._state = (pose, observed_ns, joints.tolist())
            self.last_rejection = None
        return True

    def snapshot_for_frame(self, frame_ns, *, frame_id=None, camera_serial=None, frame_token=None):
        """Freeze one transform and its identities atomically, before inference."""
        frame_ns = int(frame_ns)
        with self._lock:
            state = self._state
            status = "ready"
            matrix = None
            observed_ns = None if state is None else state[1]
            if not self.projection_allowed:
                status = "physical_validation_pending"
            elif state is None:
                status = self.last_rejection or "robot_state_unavailable"
            elif abs(frame_ns - observed_ns) > 250_000_000:
                status = "robot_state_stale"
            else:
                # Tuples prevent downstream numpy consumers from mutating the snapshot.
                matrix = tuple(tuple(float(v) for v in row) for row in state[0] @ self.flange_camera)
            return FrameProjectionSnapshot(frame_ns, observed_ns, self.frame_policy_id,
                self.calibration_id, self._invalidation_epoch, matrix, status, self._snapshot_owner,
                frame_id, camera_serial, frame_token)

    def _snapshot_rejection(self, snapshot, frame_ns, now_ns, frame_id, camera_serial, frame_token):
        """Caller owns _lock; never substitute a newer pose for captured geometry."""
        if snapshot is None:
            return "frame_projection_missing"
        if not isinstance(snapshot, FrameProjectionSnapshot) or snapshot.owner is not self._snapshot_owner:
            return "frame_projection_owner_mismatch"
        if (snapshot.frame_monotonic_ns != int(frame_ns) or snapshot.frame_id != frame_id
                or snapshot.camera_serial != camera_serial or snapshot.frame_token is not frame_token):
            return "frame_projection_frame_mismatch"
        if snapshot.policy_id != self.frame_policy_id or snapshot.calibration_id != self.calibration_id:
            return "frame_projection_identity_mismatch"
        if snapshot.invalidation_epoch != self._invalidation_epoch:
            return "frame_projection_invalidated"
        if snapshot.status != "ready" or snapshot.matrix_4x4 is None:
            return snapshot.status
        if not self.projection_allowed:
            return "physical_validation_pending"
        if self._state is None:
            return self.last_rejection or "robot_state_unavailable"
        if not 0 <= int(now_ns) - self._state[1] <= 250_000_000:
            return "robot_state_stale"
        return None

    def validate_snapshot(self, snapshot, frame_ns, now_ns, *, frame_id=None, camera_serial=None, frame_token=None):
        with self._lock:
            return self._snapshot_rejection(snapshot, frame_ns, now_ns, frame_id, camera_serial, frame_token)

    @contextmanager
    def publication_guard(self, snapshot, frame_ns, *, clock, frame_id, camera_serial, frame_token):
        # Evaluate the clock AFTER acquiring the lock. Feedback invalidation and
        # the final event write share this linearization boundary.
        with self._lock:
            rejection = self._snapshot_rejection(snapshot, frame_ns, clock(), frame_id, camera_serial, frame_token)
            yield rejection

    def for_frame(self, frame_ns):
        with self._lock:
            state = self._state
        if state is None:
            return None
        pose, observed_ns, _joints = state
        if abs(int(frame_ns) - observed_ns) > 250_000_000:
            return None
        return pose @ self.flange_camera

    def joints_for_frame(self, frame_ns):
        with self._lock:
            state = self._state
        if state is None or abs(int(frame_ns) - state[1]) > 250_000_000:
            return None
        return list(state[2])

    def flange_for_frame(self, frame_ns):
        with self._lock:
            state = self._state
        if state is None or abs(int(frame_ns) - state[1]) > 250_000_000:
            return None
        return state[0][:3, 3].tolist()


def project_point(transform, camera_xyz):
    point = np.asarray(camera_xyz, dtype=np.float64)
    if point.shape != (3,) or not np.isfinite(point).all() or point[2] <= 0:
        raise ValueError("camera_point_invalid")
    return (transform @ np.asarray([*point, 1.0]))[:3].tolist()
