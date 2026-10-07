from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np


@dataclass(frozen=True)
class HandEyeProjectionResult:
    ok: bool
    xyz_m: list[float] | None
    source: str
    calibration_id: str | None = None
    reason: str | None = None


class FollowHandEyeProjector:
    """Project a camera-frame follow target into the robot base frame.

    This intentionally reuses the existing ThirdHand hand-eye calibration
    contract, but it does not require the arm to be stationary. Follow control
    needs the current moving FK, while the bottle-grasp vision bridge is
    stricter and only emits base coordinates when stationary.
    """

    def __init__(self, config: dict[str, Any]):
        options = config.get("follow_handeye", {})
        mink_options = config.get("mink_lookat", {})
        self.enabled = bool(options.get("enabled", True))
        self.prefer_service_base = bool(options.get("prefer_service_base", True))
        self.min_base_target_z_m = _optional_float(options.get("min_base_target_z_m"))
        self.allow_pending_physical_validation = bool(
            options.get("allow_pending_physical_validation", True)
        )
        self.calibration_path = self._path(
            options.get(
                "calibration_path",
                "skills/manipulation/bottlegrasp/configs/calibration/lumos-handeye.pending.json",
            )
        )
        self.urdf_path = self._path(
            options.get("urdf_path", mink_options.get("model_path", ""))
        )
        self.available = False
        self.unavailable_reason = "disabled"
        self.calibration_id = None
        self.physically_validated = False
        self._flange_camera = None
        self._chain = None
        if self.enabled:
            self._load()

    def reset(self):
        pass

    def project(self, joints, target) -> HandEyeProjectionResult:
        if not self.enabled:
            return HandEyeProjectionResult(False, None, "disabled", reason="disabled")
        service_xyz = getattr(target, "base_xyz_m", None)
        service_status = getattr(target, "base_pose_status", None)
        if self.prefer_service_base and _finite_xyz(service_xyz):
            return HandEyeProjectionResult(
                True,
                [float(value) for value in service_xyz],
                "vision_service_base",
                self.calibration_id,
                str(service_status or "ready"),
            )
        if not self.available:
            return HandEyeProjectionResult(
                False,
                None,
                "unavailable",
                self.calibration_id,
                self.unavailable_reason,
            )
        camera_xyz = getattr(target, "xyz_m", None)
        if not _finite_xyz(camera_xyz):
            return HandEyeProjectionResult(
                False,
                None,
                "camera_xyz_missing",
                self.calibration_id,
                "target has no camera-frame xyz",
            )
        try:
            t_base_flange = self._fk(joints)
            point = t_base_flange @ self._flange_camera @ np.asarray(
                [float(camera_xyz[0]), float(camera_xyz[1]), float(camera_xyz[2]), 1.0],
                dtype=np.float64,
            )
        except Exception as exc:
            return HandEyeProjectionResult(
                False,
                None,
                "fk_failed",
                self.calibration_id,
                str(exc),
            )
        xyz = [float(value) for value in point[:3]]
        if self.min_base_target_z_m is not None:
            xyz[2] = max(xyz[2], self.min_base_target_z_m)
        return HandEyeProjectionResult(
            True,
            xyz,
            "local_fk_handeye",
            self.calibration_id,
            None,
        )

    def _load(self):
        if not self.calibration_path.is_file():
            self.unavailable_reason = f"calibration_not_found: {self.calibration_path}"
            return
        if not self.urdf_path.is_file():
            self.unavailable_reason = f"urdf_not_found: {self.urdf_path}"
            return
        try:
            raw = self.calibration_path.read_bytes()
            data = json.loads(raw)
            if data.get("schema") != "thirdhand-handeye-calibration-v3":
                raise ValueError("unsupported_handeye_schema")
            if data.get("robot_state_semantics") != "T_base_flange":
                raise ValueError("robot_state_semantics_not_T_base_flange")
            if data.get("extrinsic_semantics") != "T_flange_camera":
                raise ValueError("extrinsic_semantics_not_T_flange_camera")
            physical = data.get("physical_validation", {})
            self.physically_validated = physical.get("status") == "passed"
            if not self.physically_validated and not self.allow_pending_physical_validation:
                raise ValueError("physical_validation_pending")
            self._flange_camera = _rigid_matrix(
                data["T_flange_camera"]["matrix_4x4"]
            )
            self.calibration_id = "sha256:" + hashlib.sha256(raw).hexdigest()

            from ikpy.chain import Chain

            parsed = Chain.from_urdf_file(
                str(self.urdf_path),
                base_elements=["base_link"],
                active_links_mask=[False, True, True, True, True, True, True, False],
            )
            self._chain = Chain(
                parsed.links[:7],
                active_links_mask=[False] + [True] * 6,
            )
        except Exception as exc:
            self.unavailable_reason = str(exc)
            return
        self.available = True
        self.unavailable_reason = None

    def _fk(self, joints):
        q = [0.0]
        for value in list(joints)[:6]:
            q.append(math.radians(float(value)))
        return np.asarray(self._chain.forward_kinematics(q), dtype=np.float64)

    @staticmethod
    def _path(value) -> Path:
        path = Path(str(value)).expanduser()
        if path.is_absolute():
            return path
        root = Path(__file__).resolve().parents[5]
        return root / path


def _rigid_matrix(value):
    matrix = np.asarray(value, dtype=np.float64)
    if matrix.shape != (4, 4) or not np.isfinite(matrix).all():
        raise ValueError("handeye_matrix_invalid")
    rotation = matrix[:3, :3]
    if (
        not np.allclose(matrix[3], [0.0, 0.0, 0.0, 1.0], atol=1e-9)
        or not np.allclose(rotation.T @ rotation, np.eye(3), atol=1e-6)
        or not np.isclose(np.linalg.det(rotation), 1.0, atol=1e-6)
    ):
        raise ValueError("handeye_matrix_not_rigid")
    return matrix


def _finite_xyz(value):
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        return False
    try:
        return all(math.isfinite(float(item)) for item in value)
    except (TypeError, ValueError):
        return False


def _optional_float(value):
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None
