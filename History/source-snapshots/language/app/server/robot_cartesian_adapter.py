"""Bounded Cartesian-to-joint adapter for Startouch observation motions.

The vendor MoveL solver currently accepts an IK solution whose first sample can
be several millimetres away from the measured pose.  This module keeps that
hardware-specific workaround outside perception and session control: it solves
one small observation-pose adjustment against the checked-in robot chain,
validates the whole interpolated TCP path, and returns only a joint target for
the existing driver.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
from typing import Iterable, Sequence
import xml.etree.ElementTree as ET

import numpy as np
from scipy.optimize import least_squares
from scipy.spatial.transform import Rotation
import yaml


class CartesianPlanError(RuntimeError):
    """Raised when a Cartesian request cannot be converted without widening limits."""


@dataclass(frozen=True)
class CartesianJointPlan:
    target_joints_rad: tuple[float, ...]
    target_euler_rad: tuple[float, ...]
    target_rotation_delta_rad: tuple[float, ...]
    target_position_error_m: float
    target_orientation_error_rad: float
    max_tcp_displacement_m: float
    max_tcp_rotation_rad: float
    max_transverse_error_m: float
    max_joint_delta_rad: float


@dataclass(frozen=True)
class _Joint:
    origin_xyz: np.ndarray
    origin_rotation: np.ndarray
    axis: np.ndarray


def _finite_vector(value: Iterable[float], count: int, name: str) -> np.ndarray:
    try:
        result = np.asarray(tuple(value), dtype=float).reshape(-1)
    except (TypeError, ValueError) as error:
        raise CartesianPlanError(f"{name} must contain {count} finite values") from error
    if result.shape != (count,) or not np.isfinite(result).all():
        raise CartesianPlanError(f"{name} must contain {count} finite values")
    return result


def _rotation_error(target: np.ndarray, actual: np.ndarray) -> np.ndarray:
    return (
        Rotation.from_matrix(target)
        * Rotation.from_matrix(actual).inv()
    ).as_rotvec()


class CartesianTranslationPlanner:
    """Plan one fail-closed, bounded observation-pose adjustment."""

    def __init__(
        self,
        *,
        joints: Sequence[_Joint],
        tool_transform: np.ndarray,
        joint_limits_rad: Sequence[Sequence[float]],
        max_translation_m: float,
        max_rotation_rad: float = math.radians(5),
        max_joint_delta_rad: float,
        path_samples: int = 21,
    ) -> None:
        if len(joints) != 6 or len(joint_limits_rad) != 6:
            raise CartesianPlanError("Startouch Cartesian planner requires six joints")
        limits = np.asarray(joint_limits_rad, dtype=float)
        if limits.shape != (6, 2) or not np.isfinite(limits).all() or np.any(limits[:, 0] >= limits[:, 1]):
            raise CartesianPlanError("joint limits are invalid")
        if not math.isfinite(max_translation_m) or not 0 < max_translation_m <= 0.020:
            raise CartesianPlanError("maximum translation must be within 20 mm")
        if not math.isfinite(max_rotation_rad) or not 0 < max_rotation_rad <= math.radians(5):
            raise CartesianPlanError("maximum rotation must be within 5 degrees")
        if not math.isfinite(max_joint_delta_rad) or not 0 < max_joint_delta_rad <= math.radians(20):
            raise CartesianPlanError("maximum joint delta must be within 20 degrees")
        if not isinstance(path_samples, int) or not 11 <= path_samples <= 101:
            raise CartesianPlanError("path sample count must be within [11, 101]")
        tool = np.asarray(tool_transform, dtype=float)
        if tool.shape != (4, 4) or not np.isfinite(tool).all():
            raise CartesianPlanError("tool transform is invalid")
        self._joints = tuple(joints)
        self._tool = tool.copy()
        self._lower = limits[:, 0].copy()
        self._upper = limits[:, 1].copy()
        self.max_translation_m = float(max_translation_m)
        self.max_rotation_rad = float(max_rotation_rad)
        self.max_joint_delta_rad = float(max_joint_delta_rad)
        self.path_samples = path_samples

    @classmethod
    def from_urdf(
        cls,
        urdf_path: Path | str,
        *,
        tool_xyz_m: Sequence[float],
        tool_rpy_rad: Sequence[float] = (0.0, 0.0, 0.0),
        joint_limits_rad: Sequence[Sequence[float]],
        max_translation_m: float,
        max_rotation_rad: float = math.radians(5),
        max_joint_delta_rad: float,
    ) -> "CartesianTranslationPlanner":
        try:
            root = ET.parse(Path(urdf_path)).getroot()
        except (OSError, ET.ParseError) as error:
            raise CartesianPlanError(f"robot URDF is unavailable: {error}") from error
        joints: list[_Joint] = []
        for element in root.findall("joint"):
            if element.get("type") not in {"revolute", "continuous"}:
                continue
            origin = element.find("origin")
            axis = element.find("axis")
            if origin is None or axis is None:
                raise CartesianPlanError("robot URDF joint geometry is incomplete")
            try:
                xyz = np.fromstring(origin.get("xyz", ""), sep=" ", dtype=float)
                rpy = np.fromstring(origin.get("rpy", ""), sep=" ", dtype=float)
                axis_value = np.fromstring(axis.get("xyz", ""), sep=" ", dtype=float)
            except ValueError as error:
                raise CartesianPlanError("robot URDF joint geometry is invalid") from error
            if any(value.shape != (3,) or not np.isfinite(value).all() for value in (xyz, rpy, axis_value)):
                raise CartesianPlanError("robot URDF joint geometry is invalid")
            norm = float(np.linalg.norm(axis_value))
            if norm <= 1e-12:
                raise CartesianPlanError("robot URDF joint axis is invalid")
            joints.append(_Joint(xyz, Rotation.from_euler("xyz", rpy).as_matrix(), axis_value / norm))
            if len(joints) == 6:
                break
        tool_xyz = _finite_vector(tool_xyz_m, 3, "tool xyz")
        tool_rpy = _finite_vector(tool_rpy_rad, 3, "tool rpy")
        tool = np.eye(4)
        tool[:3, :3] = Rotation.from_euler("xyz", tool_rpy).as_matrix()
        tool[:3, 3] = tool_xyz
        return cls(
            joints=joints,
            tool_transform=tool,
            joint_limits_rad=joint_limits_rad,
            max_translation_m=max_translation_m,
            max_rotation_rad=max_rotation_rad,
            max_joint_delta_rad=max_joint_delta_rad,
        )

    @classmethod
    def from_sdk_path(
        cls,
        sdk_path: Path | str,
        *,
        joint_limits_rad: Sequence[Sequence[float]],
        max_translation_m: float = 0.020,
        max_rotation_rad: float = math.radians(5),
        max_joint_delta_rad: float = math.radians(15),
    ) -> "CartesianTranslationPlanner":
        config_dir = Path(sdk_path) / "src/config"
        try:
            raw = yaml.safe_load((config_dir / "robot_kinematics.yaml").read_text(encoding="utf-8"))
            tool = raw["kinematics"]["tool"]
        except (OSError, TypeError, KeyError, yaml.YAMLError) as error:
            raise CartesianPlanError(f"Startouch kinematics configuration is unavailable: {error}") from error
        return cls.from_urdf(
            config_dir / "FastTouchV2.SLDASM.urdf",
            tool_xyz_m=tool["xyz"],
            tool_rpy_rad=tool["rpy"],
            joint_limits_rad=joint_limits_rad,
            max_translation_m=max_translation_m,
            max_rotation_rad=max_rotation_rad,
            max_joint_delta_rad=max_joint_delta_rad,
        )

    @staticmethod
    def euler_xyz(rotation: np.ndarray) -> np.ndarray:
        return Rotation.from_matrix(np.asarray(rotation, dtype=float)).as_euler("xyz")

    @staticmethod
    def apply_base_rotation(
        euler_xyz_rad: Iterable[float], rotation_delta_base_rad: Iterable[float]
    ) -> np.ndarray:
        euler = _finite_vector(euler_xyz_rad, 3, "TCP euler")
        delta = _finite_vector(rotation_delta_base_rad, 3, "base-frame rotation delta")
        target = (
            Rotation.from_rotvec(delta).as_matrix()
            @ Rotation.from_euler("xyz", euler).as_matrix()
        )
        return CartesianTranslationPlanner.euler_xyz(target)

    @staticmethod
    def rotation_distance(
        first_euler_xyz_rad: Iterable[float], second_euler_xyz_rad: Iterable[float]
    ) -> float:
        first = Rotation.from_euler(
            "xyz", _finite_vector(first_euler_xyz_rad, 3, "first TCP euler")
        ).as_matrix()
        second = Rotation.from_euler(
            "xyz", _finite_vector(second_euler_xyz_rad, 3, "second TCP euler")
        ).as_matrix()
        return float(np.linalg.norm(_rotation_error(first, second)))

    def forward_kinematics(self, joints_rad: Iterable[float]) -> np.ndarray:
        joints = _finite_vector(joints_rad, 6, "joints")
        transform = np.eye(4)
        for joint, value in zip(self._joints, joints):
            origin = np.eye(4)
            origin[:3, :3] = joint.origin_rotation
            origin[:3, 3] = joint.origin_xyz
            motion = np.eye(4)
            motion[:3, :3] = Rotation.from_rotvec(joint.axis * value).as_matrix()
            transform = transform @ origin @ motion
        return transform @ self._tool

    def plan_translation(
        self,
        *,
        current_joints_rad: Iterable[float],
        measured_position_m: Iterable[float],
        measured_euler_rad: Iterable[float],
        target_position_m: Iterable[float],
        target_euler_rad: Iterable[float],
    ) -> CartesianJointPlan:
        measured_euler = _finite_vector(measured_euler_rad, 3, "measured euler")
        target_euler = _finite_vector(target_euler_rad, 3, "target euler")
        measured_rotation = Rotation.from_euler("xyz", measured_euler).as_matrix()
        target_rotation = Rotation.from_euler("xyz", target_euler).as_matrix()
        requested_rotation = float(
            np.linalg.norm(_rotation_error(target_rotation, measured_rotation))
        )
        if requested_rotation > 1e-4:
            raise CartesianPlanError("translation-only adjustment must preserve TCP orientation")
        return self.plan_pose_delta(
            current_joints_rad=current_joints_rad,
            measured_position_m=measured_position_m,
            measured_euler_rad=measured_euler,
            target_position_m=target_position_m,
            rotation_delta_base_rad=np.zeros(3),
        )

    def plan_pose_delta(
        self,
        *,
        current_joints_rad: Iterable[float],
        measured_position_m: Iterable[float],
        measured_euler_rad: Iterable[float],
        target_position_m: Iterable[float],
        rotation_delta_base_rad: Iterable[float],
    ) -> CartesianJointPlan:
        current = _finite_vector(current_joints_rad, 6, "current joints")
        measured_position = _finite_vector(measured_position_m, 3, "measured position")
        measured_euler = _finite_vector(measured_euler_rad, 3, "measured euler")
        target_position = _finite_vector(target_position_m, 3, "target position")
        rotation_delta = _finite_vector(
            rotation_delta_base_rad, 3, "base-frame rotation delta"
        )
        if np.any(current < self._lower) or np.any(current > self._upper):
            raise CartesianPlanError("current joints are outside configured limits")

        start = self.forward_kinematics(current)
        measured_rotation = Rotation.from_euler("xyz", measured_euler).as_matrix()
        model_position_error = float(np.linalg.norm(start[:3, 3] - measured_position))
        model_orientation_error = float(np.linalg.norm(_rotation_error(measured_rotation, start[:3, :3])))
        if model_position_error > 0.002 or model_orientation_error > 0.02:
            raise CartesianPlanError(
                "measured pose does not match the configured Startouch kinematic chain"
            )

        delta = target_position - measured_position
        distance = float(np.linalg.norm(delta))
        requested_rotation = float(np.linalg.norm(rotation_delta))
        if distance <= 1e-6 and requested_rotation <= 1e-6:
            raise CartesianPlanError("pose adjustment must contain translation or rotation")
        if distance > self.max_translation_m + 1e-12:
            raise CartesianPlanError("translation must be within 20 mm")
        if requested_rotation > self.max_rotation_rad + 1e-12:
            raise CartesianPlanError("observation rotation exceeds 5 degrees")
        target_euler = self.apply_base_rotation(measured_euler, rotation_delta)
        target_rotation = Rotation.from_euler("xyz", target_euler).as_matrix()

        def residual(candidate: np.ndarray) -> np.ndarray:
            pose = self.forward_kinematics(candidate)
            return np.concatenate(
                (
                    (pose[:3, 3] - target_position) * 100.0,
                    _rotation_error(target_rotation, pose[:3, :3]) * 10.0,
                    (candidate - current) * 0.001,
                )
            )

        solved = least_squares(
            residual,
            current,
            bounds=(self._lower, self._upper),
            max_nfev=1_000,
            ftol=1e-13,
            xtol=1e-13,
            gtol=1e-13,
        )
        if not solved.success or not np.isfinite(solved.x).all():
            raise CartesianPlanError("bounded Cartesian IK did not converge")
        joint_delta = solved.x - current
        max_joint_delta = float(np.max(np.abs(joint_delta)))
        if max_joint_delta > self.max_joint_delta_rad + 1e-12:
            raise CartesianPlanError("bounded Cartesian IK exceeds the joint step limit")

        samples = [
            self.forward_kinematics(current + joint_delta * fraction)
            for fraction in np.linspace(0.0, 1.0, self.path_samples)
        ]
        positions = np.asarray([pose[:3, 3] for pose in samples])
        relative = positions - measured_position
        displacements = np.linalg.norm(relative, axis=1)
        if distance > 1e-6:
            direction = delta / distance
            projections = relative @ direction
            transverse = relative - projections[:, None] * direction
            transverse_errors = np.linalg.norm(transverse, axis=1)
        else:
            projections = np.zeros(len(relative), dtype=float)
            transverse_errors = displacements
        rotations = np.asarray(
            [
                np.linalg.norm(_rotation_error(pose[:3, :3], start[:3, :3]))
                for pose in samples
            ]
        )
        if distance > 1e-6 and np.min(np.diff(projections)) < -0.0005:
            raise CartesianPlanError("planned TCP path is not monotonic")
        max_displacement = float(np.max(displacements))
        max_rotation = float(np.max(rotations))
        max_transverse = float(np.max(transverse_errors))
        displacement_limit = distance + 0.001 if distance > 1e-6 else 0.002
        if max_displacement > displacement_limit or max_transverse > 0.002:
            raise CartesianPlanError("planned TCP path leaves the bounded translation corridor")
        if max_rotation > requested_rotation + 0.025:
            raise CartesianPlanError("planned TCP path exceeds the bounded rotation corridor")

        final = samples[-1]
        position_error = float(np.linalg.norm(final[:3, 3] - target_position))
        orientation_error = float(np.linalg.norm(_rotation_error(target_rotation, final[:3, :3])))
        if position_error > 0.001 or orientation_error > 0.025:
            raise CartesianPlanError("bounded Cartesian IK target residual is too large")
        if distance > 1e-6 and projections[-1] < distance - 0.001:
            raise CartesianPlanError("bounded Cartesian IK did not make sufficient progress")
        return CartesianJointPlan(
            target_joints_rad=tuple(float(value) for value in solved.x),
            target_euler_rad=tuple(float(value) for value in target_euler),
            target_rotation_delta_rad=tuple(float(value) for value in rotation_delta),
            target_position_error_m=position_error,
            target_orientation_error_rad=orientation_error,
            max_tcp_displacement_m=max_displacement,
            max_tcp_rotation_rad=max_rotation,
            max_transverse_error_m=max_transverse,
            max_joint_delta_rad=max_joint_delta,
        )

    def plan_pose_target(
        self,
        *,
        current_joints_rad: Iterable[float],
        measured_position_m: Iterable[float],
        measured_euler_rad: Iterable[float],
        target_position_m: Iterable[float],
        target_euler_rad: Iterable[float],
    ) -> CartesianJointPlan:
        """Replan from measured state to one already-authorized absolute pose."""

        measured_euler = _finite_vector(measured_euler_rad, 3, "measured euler")
        target_euler = _finite_vector(target_euler_rad, 3, "target euler")
        measured_rotation = Rotation.from_euler("xyz", measured_euler).as_matrix()
        target_rotation = Rotation.from_euler("xyz", target_euler).as_matrix()
        rotation_delta_base = _rotation_error(target_rotation, measured_rotation)
        return self.plan_pose_delta(
            current_joints_rad=current_joints_rad,
            measured_position_m=measured_position_m,
            measured_euler_rad=measured_euler,
            target_position_m=target_position_m,
            rotation_delta_base_rad=rotation_delta_base,
        )
