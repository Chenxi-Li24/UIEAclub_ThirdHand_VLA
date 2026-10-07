from __future__ import annotations

import math
from collections import OrderedDict
from pathlib import Path
import re
import struct
from typing import Any
import xml.etree.ElementTree as ET

import numpy as np


class WorkspaceGuard:
    """Shared geometry check for Dummy targets and Robot stream samples."""

    def __init__(self, config: dict[str, Any]):
        options = config.get("workspace_guard", {})
        robot = config.get("robot", {})
        root = Path(__file__).resolve().parents[3]
        self.enabled = bool(options.get("enabled", True))
        self.clearance_m = float(options.get("clearance_m", 0.0))
        self.urdf_path = self._path(
            options.get(
                "urdf_path",
                config.get("mink_lookat", {}).get(
                    "model_path",
                    str(root / "assets/robot/startouch-v3/FastTouchV3.SLDASM.urdf"),
                ),
            )
        )
        self.joint_limits = robot.get(
            "joint_limits_deg",
            [[-162, 162], [-12, 201], [-183, 0], [-98, 98], [-98, 98], [-164, 164]],
        )
        self.available = False
        self.unavailable_reason = "disabled"
        self.base_bottom_z_m: float | None = None
        self._links: dict[str, _LinkMesh] = {}
        self._joints: list[_Joint] = []
        self._cache = OrderedDict()
        if self.enabled:
            self._load()

    def check(self, joints_deg) -> tuple[bool, str]:
        if not self.enabled:
            return True, "workspace_guard_disabled"
        if not self.available:
            return False, f"workspace_guard_unavailable: {self.unavailable_reason}"
        try:
            joints = [float(value) for value in joints_deg]
        except (TypeError, ValueError):
            return False, "workspace_guard_invalid_joints"
        if len(joints) != 6:
            return False, "workspace_guard_requires_6_joints"
        for index, (value, (lo, hi)) in enumerate(zip(joints, self.joint_limits), start=1):
            if not math.isfinite(value):
                return False, "workspace_guard_invalid_joints"
            if value < float(lo) - 0.05 or value > float(hi) + 0.05:
                return False, f"workspace_guard_joint_limit_J{index}"
        key = (tuple(joints), self.clearance_m, self.base_bottom_z_m)
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        result = self._check_geometry(joints)
        self._cache[key] = result
        if len(self._cache) > 128:
            self._cache.popitem(last=False)
        return result

    def _check_geometry(self, joints):
        min_z = self.min_geometry_z_m(joints)
        if min_z is None or self.base_bottom_z_m is None:
            return False, "workspace_guard_geometry_failed"
        floor_z = self.base_bottom_z_m + self.clearance_m
        if min_z < floor_z:
            return False, f"geometry_z {min_z:.3f}m below base bottom {floor_z:.3f}m"
        return True, f"geometry_z {min_z:.3f}m >= base bottom {floor_z:.3f}m"

    def min_geometry_z_m(self, joints_deg) -> float | None:
        transforms = self._link_transforms(joints_deg)
        if transforms is None:
            return None
        z_values: list[float] = []
        for name, mesh in self._links.items():
            if name == "base_link":
                continue
            transform = transforms.get(name)
            if transform is None:
                continue
            points = mesh.points
            if points.size == 0:
                continue
            # Only the Z row is needed; this is the exact same rigid transform.
            # Avoid multithreaded BLAS dispatch for this three-column reduction.
            z = np.einsum("ij,j->i", points, transform[2, :3], optimize=False)
            z_values.append(float(np.min(z + transform[2, 3])))
        return min(z_values) if z_values else None

    def _load(self) -> None:
        if not self.urdf_path.is_file():
            self.unavailable_reason = f"urdf_not_found: {self.urdf_path}"
            return
        try:
            root = ET.fromstring(self.urdf_path.read_text(encoding="utf-8"))
            meshes = _parse_link_meshes(root, self.urdf_path)
            joints = _parse_serial_joints(root)
            if "base_link" not in meshes:
                raise ValueError("base_link_mesh_missing")
            self._links = meshes
            self._joints = joints
            self.base_bottom_z_m = float(np.min(meshes["base_link"].points[:, 2]))
        except Exception as exc:
            self.unavailable_reason = str(exc)
            return
        self.available = True
        self.unavailable_reason = None

    def _link_transforms(self, joints_deg) -> dict[str, np.ndarray] | None:
        try:
            joint_values = [math.radians(float(value)) for value in list(joints_deg)[:6]]
            transforms = {"base_link": np.eye(4)}
            for index, joint in enumerate(self._joints):
                parent = transforms[joint.parent]
                angle = joint_values[index] if index < len(joint_values) else 0.0
                transforms[joint.child] = parent @ joint.origin @ _axis_angle(joint.axis, angle)
            return transforms
        except Exception:
            return None

    @staticmethod
    def _path(value) -> Path:
        path = Path(str(value)).expanduser()
        if path.is_absolute():
            return path
        root = Path(__file__).resolve().parents[3]
        return root / path


class _LinkMesh:
    def __init__(self, points: np.ndarray):
        self.points = points


class _Joint:
    def __init__(self, parent: str, child: str, origin: np.ndarray, axis: np.ndarray):
        self.parent = parent
        self.child = child
        self.origin = origin
        self.axis = axis


def _parse_link_meshes(root: ET.Element, urdf_path: Path) -> dict[str, _LinkMesh]:
    meshes = {}
    for link in root.findall("link"):
        name = str(link.attrib.get("name", ""))
        mesh_node = link.find("./collision/geometry/mesh")
        origin_node = link.find("./collision/origin")
        if mesh_node is None:
            mesh_node = link.find("./visual/geometry/mesh")
            origin_node = link.find("./visual/origin")
        if mesh_node is None:
            continue
        filename = str(mesh_node.attrib.get("filename", ""))
        mesh_path = _resolve_mesh_path(filename, urdf_path)
        points = _read_stl_vertices(mesh_path)
        origin = _origin_matrix(origin_node)
        homogeneous = np.c_[points, np.ones(points.shape[0])]
        meshes[name] = _LinkMesh((origin @ homogeneous.T).T[:, :3])
    return meshes


def _parse_serial_joints(root: ET.Element) -> list[_Joint]:
    joints = []
    parent = "base_link"
    for joint_node in root.findall("joint"):
        if joint_node.attrib.get("type") != "revolute":
            continue
        name = str(joint_node.attrib.get("name", ""))
        if name.startswith("gripper_"):
            continue
        parent_node = joint_node.find("parent")
        child_node = joint_node.find("child")
        axis_node = joint_node.find("axis")
        if parent_node is None or child_node is None:
            continue
        joint_parent = str(parent_node.attrib.get("link", ""))
        child = str(child_node.attrib.get("link", ""))
        if joint_parent != parent:
            continue
        origin = _origin_matrix(joint_node.find("origin"))
        axis = _xyz(axis_node.attrib.get("xyz", "0 0 1") if axis_node is not None else "0 0 1")
        joints.append(_Joint(joint_parent, child, origin, axis))
        parent = child
        if len(joints) >= 6:
            break
    if len(joints) != 6:
        raise ValueError("serial_6dof_chain_not_found")
    return joints


def _resolve_mesh_path(filename: str, urdf_path: Path) -> Path:
    if filename.startswith("package://"):
        suffix = filename.removeprefix("package://")
        parts = suffix.split("/", 1)
        if len(parts) == 2:
            return urdf_path.parent / parts[1]
    path = Path(filename)
    return path if path.is_absolute() else urdf_path.parent / path


def _read_stl_vertices(path: Path) -> np.ndarray:
    raw = path.read_bytes()
    if len(raw) >= 84:
        count = struct.unpack_from("<I", raw, 80)[0]
        expected = 84 + count * 50
        if expected == len(raw):
            vertices = []
            offset = 84
            for _ in range(count):
                offset += 12
                for _vertex in range(3):
                    vertices.append(struct.unpack_from("<fff", raw, offset))
                    offset += 12
                offset += 2
            return np.asarray(vertices, dtype=np.float64)
    text = raw.decode("utf-8", errors="ignore")
    vertices = [
        tuple(float(part) for part in match.group(1).split())
        for match in re.finditer(r"vertex\s+([^\n]+)", text)
    ]
    if not vertices:
        raise ValueError(f"stl_vertices_missing: {path}")
    return np.asarray(vertices, dtype=np.float64)


def _origin_matrix(node: ET.Element | None) -> np.ndarray:
    if node is None:
        xyz = np.zeros(3)
        rpy = np.zeros(3)
    else:
        xyz = _xyz(node.attrib.get("xyz", "0 0 0"))
        rpy = _xyz(node.attrib.get("rpy", "0 0 0"))
    result = _rpy_matrix(rpy)
    result[:3, 3] = xyz
    return result


def _xyz(value: str) -> np.ndarray:
    parts = [float(part) for part in str(value).split()]
    if len(parts) != 3:
        raise ValueError("xyz_triplet_required")
    return np.asarray(parts, dtype=np.float64)


def _rpy_matrix(rpy: np.ndarray) -> np.ndarray:
    roll, pitch, yaw = [float(value) for value in rpy]
    cr, sr = math.cos(roll), math.sin(roll)
    cp, sp = math.cos(pitch), math.sin(pitch)
    cy, sy = math.cos(yaw), math.sin(yaw)
    rx = np.array([[1, 0, 0], [0, cr, -sr], [0, sr, cr]], dtype=np.float64)
    ry = np.array([[cp, 0, sp], [0, 1, 0], [-sp, 0, cp]], dtype=np.float64)
    rz = np.array([[cy, -sy, 0], [sy, cy, 0], [0, 0, 1]], dtype=np.float64)
    out = np.eye(4)
    out[:3, :3] = rz @ ry @ rx
    return out


def _axis_angle(axis: np.ndarray, angle: float) -> np.ndarray:
    axis = np.asarray(axis, dtype=np.float64)
    norm = float(np.linalg.norm(axis))
    if norm <= 0:
        raise ValueError("joint_axis_invalid")
    x, y, z = axis / norm
    c, s = math.cos(angle), math.sin(angle)
    c1 = 1.0 - c
    out = np.eye(4)
    out[:3, :3] = np.array(
        [
            [c + x * x * c1, x * y * c1 - z * s, x * z * c1 + y * s],
            [y * x * c1 + z * s, c + y * y * c1, y * z * c1 - x * s],
            [z * x * c1 - y * s, z * y * c1 + x * s, c + z * z * c1],
        ],
        dtype=np.float64,
    )
    return out
