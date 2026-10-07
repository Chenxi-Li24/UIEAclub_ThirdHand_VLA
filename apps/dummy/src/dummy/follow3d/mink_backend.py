from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import math
import tempfile

import numpy as np


@dataclass
class MinkLookAtResult:
    ok: bool
    joints_deg: list[float]
    reason: str = ""


class MinkLookAtController:
    """Mink-based real/virtual 3D look-at IK backend."""

    def __init__(self, config):
        options = config.get("mink_lookat", {})
        self.enabled = bool(options.get("enabled", False))
        self.model_path = str(options.get("model_path", "") or "")
        self.camera_frame = str(options.get("camera_frame", "camera"))
        self.frame_type = str(options.get("frame_type", "body"))
        self.camera_axis = options.get("camera_axis", [0.0, 0.0, 1.0])
        self.dt = float(options.get("dt", 0.1))
        self.solver = str(options.get("solver", "daqp"))
        self.lookat_cost = float(options.get("lookat_cost", 1.0))
        self.posture_cost = float(options.get("posture_cost", 0.05))
        self.damping = float(options.get("damping", 1e-6))
        self.max_velocity_rad_s = float(options.get("max_velocity_rad_s", math.radians(50.0)))
        self.available = False
        self.unavailable_reason = "disabled"
        self._mink = None
        self._mujoco = None
        self._model = None
        self._configuration = None
        self._lookat_task = None
        self._posture_task = None
        self._limits = None
        if self.enabled:
            self._load()

    def _load(self):
        try:
            import mink  # type: ignore
            import mujoco  # type: ignore
        except Exception as exc:
            self.unavailable_reason = f"mink_or_mujoco_missing: {exc}"
            return
        if not self.model_path:
            self.unavailable_reason = "model_path_missing"
            return
        path = Path(self.model_path).expanduser()
        if not path.is_file():
            self.unavailable_reason = f"model_not_found: {path}"
            return
        try:
            self._model = mujoco.MjModel.from_xml_path(str(self._resolved_model_path(path)))
        except Exception as exc:
            self.unavailable_reason = f"model_load_failed: {exc}"
            return
        self._mink = mink
        self._mujoco = mujoco
        self._configuration = mink.Configuration(self._model)
        self._lookat_task = mink.LookAtTask(self.camera_frame, self.frame_type, axis=self.camera_axis, cost=self.lookat_cost)
        self._posture_task = mink.PostureTask(self._model, cost=self.posture_cost)
        velocities = {}
        for index in range(min(6, self._model.njnt)):
            name = mujoco.mj_id2name(self._model, mujoco.mjtObj.mjOBJ_JOINT, index)
            if name:
                velocities[name] = self.max_velocity_rad_s
        self._limits = [mink.ConfigurationLimit(self._model), mink.VelocityLimit(self._model, velocities)]
        self.available = True
        self.unavailable_reason = None

    def reset(self, joints):
        if self._configuration is not None:
            self._configuration.update(self._q_from_six_deg(joints))

    def target_for(self, joints, target):
        xyz = getattr(target, "xyz_m", None)
        if not self.enabled:
            return MinkLookAtResult(False, list(joints), "disabled")
        if not self.available:
            return MinkLookAtResult(False, list(joints), self.unavailable_reason or "unavailable")
        if not _finite_xyz(xyz):
            return MinkLookAtResult(False, list(joints), "target_xyz_missing")
        try:
            q = self._q_from_six_deg(joints)
            self._configuration.update(q)
            self._lookat_task.set_target(np.asarray(xyz, dtype=float))
            posture = getattr(target, "posture_joints_deg", None)
            self._posture_task.set_target(self._q_from_six_deg(posture) if _finite_joints(posture) else q)
            velocity = self._mink.solve_ik(
                self._configuration,
                [self._lookat_task, self._posture_task],
                self.dt,
                self.solver,
                damping=self.damping,
                limits=self._limits,
            )
            return MinkLookAtResult(True, self._six_deg_from_q(self._configuration.integrate(velocity, self.dt)), "mink")
        except Exception as exc:
            return MinkLookAtResult(False, list(joints), f"mink_solve_failed: {exc}")

    def _resolved_model_path(self, path):
        if path.suffix.lower() != ".urdf":
            return path
        text = path.read_text(encoding="utf-8")
        package_prefix = f"package://{path.stem}/"
        if package_prefix not in text:
            return path
        temporary = tempfile.NamedTemporaryFile("w", suffix=".urdf", delete=False, encoding="utf-8")
        with temporary:
            temporary.write(text.replace(package_prefix, str(path.parent) + "/"))
        return Path(temporary.name)

    def _q_from_six_deg(self, joints):
        q = np.zeros(self._model.nq, dtype=float)
        for index, value in enumerate(list(joints)[:6]):
            if index < q.shape[0]:
                q[index] = math.radians(float(value))
        return q

    def _six_deg_from_q(self, q):
        return [math.degrees(float(value)) for value in q[:6]]


def _finite_xyz(value):
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        return False
    try:
        return all(float(item) == float(item) for item in value)
    except (TypeError, ValueError):
        return False


def _finite_joints(value):
    if not isinstance(value, (list, tuple)) or len(value) != 6:
        return False
    try:
        return all(float(item) == float(item) for item in value)
    except (TypeError, ValueError):
        return False
