"""Strict loading and table-footprint geometry for active-view evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import yaml

from vision.active_view_types import (
    ObservationPose,
    TablePlane,
    validated_evidence_ids,
)
from vision.calibration_gate import audit_handeye_calibration
from vision.camera_models import PinholeCamera, SeucmCamera, normalize_rows
from vision.dual_camera import DualCameraCalibrationBundle
from vision.geometry import validate_transform
from vision.types import InvalidDataError


MAX_EVIDENCE_BYTES = 8 * 1024 * 1024
JOINT_LIMITS_DEG = (
    (-162.0, 162.0),
    (-12.0, 201.0),
    (-183.0, 0.0),
    (-98.0, 98.0),
    (-98.0, 98.0),
    (-164.0, 164.0),
)


class ActiveViewEvidenceError(InvalidDataError):
    """Raised when active-view evidence is malformed, unsafe, or untrusted."""


def canonical_json(payload: Any) -> str:
    try:
        return json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ActiveViewEvidenceError("evidence must be finite canonical JSON") from exc


def content_id(payload: Any) -> str:
    encoded = canonical_json(payload).encode("ascii")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ActiveViewEvidenceError(f"{name} must be an object")
    return value


def _exact(value: Mapping[str, Any], keys: set[str], name: str) -> None:
    actual = set(value)
    if actual != keys:
        missing = sorted(keys - actual)
        unknown = sorted(actual - keys)
        raise ActiveViewEvidenceError(
            f"{name} keys are invalid; missing={missing}, unknown={unknown}"
        )


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise ActiveViewEvidenceError(f"{name} must be finite")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ActiveViewEvidenceError(f"{name} must be finite") from exc
    if not math.isfinite(result):
        raise ActiveViewEvidenceError(f"{name} must be finite")
    return result


def _positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ActiveViewEvidenceError(f"{name} must be a positive integer")
    return value


def _content_addressed(value: Any, name: str) -> tuple[Mapping[str, Any], str]:
    record = _mapping(value, name)
    supplied = record.get("content_id")
    validated_evidence_ids((supplied,))
    payload = dict(record)
    payload.pop("content_id", None)
    expected = content_id(payload)
    if supplied != expected:
        raise ActiveViewEvidenceError(f"{name} integrity check failed")
    return payload, expected


def _resolve_local(path: Path | str, root: Path, name: str) -> Path:
    raw = str(path)
    if "://" in raw:
        raise ActiveViewEvidenceError(f"{name} remote URLs are forbidden")
    candidate = Path(path)
    if candidate.is_symlink():
        raise ActiveViewEvidenceError(f"{name} symlinks are forbidden")
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise ActiveViewEvidenceError(f"{name} cannot be resolved: {exc}") from exc
    resolved_root = root.resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise ActiveViewEvidenceError(f"{name} is outside the evidence directory") from exc
    if not resolved.is_file():
        raise ActiveViewEvidenceError(f"{name} must be a regular file")
    if resolved.stat().st_size > MAX_EVIDENCE_BYTES:
        raise ActiveViewEvidenceError(f"{name} exceeds 8 MiB")
    return resolved


def _load_document(path: Path | str, root: Path, name: str) -> Mapping[str, Any]:
    resolved = _resolve_local(path, root, name)
    try:
        text = resolved.read_text(encoding="utf-8")
        if resolved.suffix.lower() == ".json":
            value = json.loads(
                text,
                parse_constant=lambda token: (_ for _ in ()).throw(
                    ActiveViewEvidenceError(f"{name} contains non-finite {token}")
                ),
            )
        elif resolved.suffix.lower() in {".yaml", ".yml"}:
            value = yaml.safe_load(text)
        else:
            raise ActiveViewEvidenceError(f"{name} must be JSON or YAML")
        canonical_json(value)
    except ActiveViewEvidenceError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError, yaml.YAMLError) as exc:
        raise ActiveViewEvidenceError(f"{name} cannot be parsed: {exc}") from exc
    return _mapping(value, name)


def _camera(record: Any, kind: str):
    value = _mapping(record, kind)
    if kind == "d435":
        _exact(value, {"fx", "fy", "cx", "cy", "width", "height"}, kind)
        return PinholeCamera(
            fx=_finite(value["fx"], f"{kind}.fx"),
            fy=_finite(value["fy"], f"{kind}.fy"),
            cx=_finite(value["cx"], f"{kind}.cx"),
            cy=_finite(value["cy"], f"{kind}.cy"),
            width=_positive_int(value["width"], f"{kind}.width"),
            height=_positive_int(value["height"], f"{kind}.height"),
        )
    _exact(
        value,
        {"fx", "fy", "cx", "cy", "alpha", "beta", "width", "height"},
        kind,
    )
    return SeucmCamera(
        fx=_finite(value["fx"], f"{kind}.fx"),
        fy=_finite(value["fy"], f"{kind}.fy"),
        cx=_finite(value["cx"], f"{kind}.cx"),
        cy=_finite(value["cy"], f"{kind}.cy"),
        alpha=_finite(value["alpha"], f"{kind}.alpha"),
        beta=_finite(value["beta"], f"{kind}.beta"),
        width=_positive_int(value["width"], f"{kind}.width"),
        height=_positive_int(value["height"], f"{kind}.height"),
    )


def _validated_camera_bundle(payload: Mapping[str, Any]) -> DualCameraCalibrationBundle:
    _exact(
        payload,
        {"schema_version", "robot_model_id", "d435", "lumos", "audits", "validation"},
        "camera evidence",
    )
    if payload["schema_version"] != 1:
        raise ActiveViewEvidenceError("camera evidence schema is unsupported")
    robot_model = payload["robot_model_id"]
    if not isinstance(robot_model, str) or not robot_model or len(robot_model) > 128:
        raise ActiveViewEvidenceError("robot model ID is invalid")
    validation = _mapping(payload["validation"], "camera validation")
    _exact(
        validation,
        {
            "lumos_median_px",
            "lumos_p95_px",
            "lumos_edge_p95_px",
            "d435_to_lumos_target_p95_px",
            "desktop_plane_p95_m",
            "full_chain_static_p95_m",
        },
        "camera validation",
    )
    checks = (
        ("Lumos median", "lumos_median_px", 1.0),
        ("Lumos P95", "lumos_p95_px", 2.5),
        ("Lumos edge P95", "lumos_edge_p95_px", 4.0),
        ("D435-to-Lumos target P95", "d435_to_lumos_target_p95_px", 4.0),
        ("desktop plane P95", "desktop_plane_p95_m", 0.008),
        ("full-chain static P95", "full_chain_static_p95_m", 0.010),
    )
    for label, key, maximum in checks:
        metric = _finite(validation[key], key)
        if metric < 0.0 or metric > maximum:
            raise ActiveViewEvidenceError(f"{label} validation gate failed")

    audits = _mapping(payload["audits"], "camera audits")
    _exact(audits, {"d435_to_lumos", "lumos_to_flange"}, "camera audits")

    def build_audit(name: str, expected_key: str, position_limit: float):
        source = _mapping(audits[name], name)
        _exact(source, {"transform_key", "payload"}, name)
        if source["transform_key"] != expected_key:
            raise ActiveViewEvidenceError(f"{name} transform direction is invalid")
        audit = audit_handeye_calibration(
            dict(_mapping(source["payload"], f"{name}.payload")),
            expected_key,
            max_reprojection_rmse_px=4.0,
            max_position_rmse_m=position_limit,
        )
        if not audit.calibration.validated:
            raise ActiveViewEvidenceError(f"{name} calibration gate failed: {audit.reasons}")
        return audit

    bundle = DualCameraCalibrationBundle.from_audits(
        d435=_camera(payload["d435"], "d435"),
        lumos=_camera(payload["lumos"], "lumos"),
        d435_to_lumos_audit=build_audit(
            "d435_to_lumos", "T_lumos_from_d435", 0.008
        ),
        lumos_to_flange_audit=build_audit(
            "lumos_to_flange", "T_flange_from_lumos", 0.010
        ),
    )
    if not bundle.calibration.validated:
        raise ActiveViewEvidenceError("camera bundle is not validated")
    return bundle


@dataclass(frozen=True)
class ActiveViewFoundation:
    camera: DualCameraCalibrationBundle
    table: TablePlane
    robot_model_id: str
    camera_source_id: str
    table_source_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.camera, DualCameraCalibrationBundle):
            raise ActiveViewEvidenceError("foundation camera bundle is invalid")
        self.camera.verify_integrity()
        if not self.camera.calibration.validated:
            raise ActiveViewEvidenceError("foundation camera bundle is unvalidated")
        if not isinstance(self.table, TablePlane) or not self.table.validated:
            raise ActiveViewEvidenceError("foundation table is unvalidated")
        if self.table.calibration_id != self.camera.calibration.calibration_id:
            raise ActiveViewEvidenceError("table calibration does not match camera bundle")
        if not isinstance(self.robot_model_id, str) or not self.robot_model_id:
            raise ActiveViewEvidenceError("foundation robot model is invalid")
        validated_evidence_ids((self.camera_source_id, self.table_source_id))


@dataclass(frozen=True)
class ActiveViewEvidence:
    camera: DualCameraCalibrationBundle
    table: TablePlane
    poses: tuple[ObservationPose, ...]
    robot_model_id: str
    catalog_id: str
    evidence_id: str
    camera_source_id: str
    table_source_id: str

    def __post_init__(self) -> None:
        ActiveViewFoundation(
            self.camera,
            self.table,
            self.robot_model_id,
            self.camera_source_id,
            self.table_source_id,
        )
        poses = tuple(self.poses)
        if not poses or any(not isinstance(pose, ObservationPose) for pose in poses):
            raise ActiveViewEvidenceError("catalog requires validated observation poses")
        if len({pose.pose_id for pose in poses}) != len(poses):
            raise ActiveViewEvidenceError("catalog pose IDs must be unique")
        validated_evidence_ids((self.catalog_id, self.evidence_id))
        object.__setattr__(self, "poses", poses)


def load_active_view_foundation(
    camera_path: Path | str,
    table_path: Path | str,
    *,
    evidence_dir: Path | str | None = None,
) -> ActiveViewFoundation:
    root = Path(evidence_dir) if evidence_dir is not None else Path(camera_path).parent
    camera_raw = _load_document(camera_path, root, "camera evidence")
    camera_payload, camera_id = _content_addressed(camera_raw, "camera evidence")
    bundle = _validated_camera_bundle(camera_payload)

    table_raw = _load_document(table_path, root, "table evidence")
    table_payload, table_id = _content_addressed(table_raw, "table evidence")
    _exact(
        table_payload,
        {
            "schema_version",
            "normal_base",
            "offset_m",
            "position_rmse_m",
            "calibration_id",
            "validated",
        },
        "table evidence",
    )
    if table_payload["schema_version"] != 1 or table_payload["validated"] is not True:
        raise ActiveViewEvidenceError("table evidence is not validated")
    rmse = _finite(table_payload["position_rmse_m"], "table position RMSE")
    if rmse <= 0.0 or rmse > 0.010:
        raise ActiveViewEvidenceError("table position validation gate failed")
    table = TablePlane(
        normal_base=table_payload["normal_base"],
        offset_m=_finite(table_payload["offset_m"], "table offset"),
        position_rmse_m=rmse,
        calibration_id=table_payload["calibration_id"],
        validated=True,
    )
    return ActiveViewFoundation(
        camera=bundle,
        table=table,
        robot_model_id=str(camera_payload["robot_model_id"]),
        camera_source_id=camera_id,
        table_source_id=table_id,
    )


def audit_path_validation(value: Any, pose_name: str) -> str:
    """Validate one manual path record and return its content ID."""

    record = _mapping(value, f"{pose_name}.path_validation")
    _exact(
        record,
        {"tested_at", "max_joint_error_deg", "speed_scale", "operator_acknowledged"},
        f"{pose_name}.path_validation",
    )
    tested_at = record["tested_at"]
    if not isinstance(tested_at, str):
        raise ActiveViewEvidenceError(f"{pose_name} path test date is invalid")
    try:
        timestamp = datetime.fromisoformat(tested_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ActiveViewEvidenceError(f"{pose_name} path test date is invalid") from exc
    if timestamp.tzinfo is None:
        raise ActiveViewEvidenceError(f"{pose_name} path test date requires a timezone")
    error = _finite(record["max_joint_error_deg"], "maximum joint error")
    if error < 0.0 or error > 1.0:
        raise ActiveViewEvidenceError(f"{pose_name} path joint error gate failed")
    speed = _finite(record["speed_scale"], "path speed scale")
    if speed <= 0.0 or speed > 0.05:
        raise ActiveViewEvidenceError(f"{pose_name} path speed gate failed")
    if record["operator_acknowledged"] is not True:
        raise ActiveViewEvidenceError(f"{pose_name} path lacks operator acknowledgment")
    return content_id(record)


def _path_validation(value: Any, supplied_id: Any, pose_name: str) -> str:
    expected_id = audit_path_validation(value, pose_name)
    if supplied_id != expected_id:
        raise ActiveViewEvidenceError(f"{pose_name} path validation integrity failed")
    validated_evidence_ids((supplied_id,))
    return supplied_id


def load_active_view_evidence(
    camera_path: Path | str,
    table_path: Path | str,
    catalog_path: Path | str,
    *,
    evidence_dir: Path | str | None = None,
) -> ActiveViewEvidence:
    root = Path(evidence_dir) if evidence_dir is not None else Path(camera_path).parent
    foundation = load_active_view_foundation(
        camera_path, table_path, evidence_dir=root
    )
    catalog_raw = _load_document(catalog_path, root, "observation catalog")
    catalog, catalog_id = _content_addressed(catalog_raw, "observation catalog")
    _exact(
        catalog,
        {"schema_version", "robot_model_id", "calibration_id", "validated", "poses"},
        "observation catalog",
    )
    if catalog["schema_version"] != 1 or catalog["validated"] is not True:
        raise ActiveViewEvidenceError("observation catalog is not validated")
    if catalog["robot_model_id"] != foundation.robot_model_id:
        raise ActiveViewEvidenceError("catalog robot model does not match camera evidence")
    calibration_id = foundation.camera.calibration.calibration_id
    if catalog["calibration_id"] != calibration_id:
        raise ActiveViewEvidenceError("catalog calibration does not match camera evidence")
    raw_poses = catalog["poses"]
    if not isinstance(raw_poses, list) or not 1 <= len(raw_poses) <= 64:
        raise ActiveViewEvidenceError("catalog must contain between 1 and 64 poses")
    poses: list[ObservationPose] = []
    for index, raw_pose in enumerate(raw_poses):
        name = f"poses[{index}]"
        pose = _mapping(raw_pose, name)
        _exact(
            pose,
            {
                "pose_id",
                "joints_deg",
                "t_base_from_flange",
                "coverage_polygon_xy_m",
                "allowed_start_pose_ids",
                "joint_tolerance_deg",
                "path_validation",
                "path_validation_id",
            },
            name,
        )
        joints = np.asarray(pose["joints_deg"], dtype=float)
        if joints.shape != (6,) or not np.isfinite(joints).all():
            raise ActiveViewEvidenceError(f"{name} joints must be six finite values")
        for joint, (lower, upper) in zip(joints, JOINT_LIMITS_DEG):
            if not lower <= float(joint) <= upper:
                raise ActiveViewEvidenceError(f"{name} joint is outside robot limits")
        path_id = _path_validation(pose["path_validation"], pose["path_validation_id"], name)
        try:
            poses.append(
                ObservationPose(
                    pose_id=pose["pose_id"],
                    joints_deg=joints,
                    t_base_from_flange=pose["t_base_from_flange"],
                    coverage_polygon_xy_m=pose["coverage_polygon_xy_m"],
                    allowed_start_pose_ids=tuple(pose["allowed_start_pose_ids"]),
                    path_validation_id=path_id,
                    calibration_id=calibration_id,
                    joint_tolerance_deg=pose["joint_tolerance_deg"],
                )
            )
        except (InvalidDataError, TypeError, ValueError) as exc:
            raise ActiveViewEvidenceError(f"{name} is invalid: {exc}") from exc
    aggregate = content_id(
        {
            "camera_source_id": foundation.camera_source_id,
            "catalog_id": catalog_id,
            "robot_model_id": foundation.robot_model_id,
            "table_source_id": foundation.table_source_id,
        }
    )
    return ActiveViewEvidence(
        camera=foundation.camera,
        table=foundation.table,
        poses=tuple(poses),
        robot_model_id=foundation.robot_model_id,
        catalog_id=catalog_id,
        evidence_id=aggregate,
        camera_source_id=foundation.camera_source_id,
        table_source_id=foundation.table_source_id,
    )


def d435_inner_roi_rays(
    camera: PinholeCamera,
    *,
    inner_roi_fraction: float = 0.60,
) -> np.ndarray:
    if not isinstance(camera, PinholeCamera):
        raise ActiveViewEvidenceError("D435 inner ROI requires a pinhole camera")
    fraction = _finite(inner_roi_fraction, "inner ROI fraction")
    if not 0.0 < fraction <= 1.0:
        raise ActiveViewEvidenceError("inner ROI fraction must be within (0, 1]")
    half_width = camera.width * fraction / 2.0
    half_height = camera.height * fraction / 2.0
    pixels = np.array(
        [
            [camera.cx - half_width, camera.cy - half_height],
            [camera.cx + half_width, camera.cy - half_height],
            [camera.cx + half_width, camera.cy + half_height],
            [camera.cx - half_width, camera.cy + half_height],
        ],
        dtype=float,
    )
    rays = np.column_stack(
        (
            (pixels[:, 0] - camera.cx) / camera.fx,
            (pixels[:, 1] - camera.cy) / camera.fy,
            np.ones(4),
        )
    )
    return normalize_rows(rays)


def intersect_camera_rays_with_table(
    rays_camera: Any,
    t_base_from_camera: Any,
    table: TablePlane,
) -> np.ndarray:
    rays = np.asarray(rays_camera, dtype=float)
    if rays.shape != (4, 3) or not np.isfinite(rays).all():
        raise ActiveViewEvidenceError("coverage requires four finite camera rays")
    transform = validate_transform(t_base_from_camera)
    if not isinstance(table, TablePlane) or not table.validated:
        raise ActiveViewEvidenceError("coverage requires a validated table")
    origin = transform[:3, 3]
    directions = rays @ transform[:3, :3].T
    denominator = directions @ table.normal_base
    numerator = -(float(table.normal_base @ origin) + table.offset_m)
    with np.errstate(divide="ignore", invalid="ignore"):
        distance = numerator / denominator
    if (
        not np.isfinite(distance).all()
        or np.any(np.abs(denominator) <= 1e-12)
        or np.any(distance <= 0.0)
    ):
        raise ActiveViewEvidenceError("D435 ROI does not intersect the table forward")
    points = origin + distance[:, None] * directions
    polygon = points[:, :2]
    # ObservationPose performs the strict-convexity and winding validation.
    edges = np.roll(polygon, -1, axis=0) - polygon
    turns = edges[:, 0] * np.roll(edges, -1, axis=0)[:, 1] - edges[:, 1] * np.roll(
        edges, -1, axis=0
    )[:, 0]
    if not (np.all(turns > 1e-12) or np.all(turns < -1e-12)):
        raise ActiveViewEvidenceError("D435 table footprint is not strictly convex")
    return polygon


__all__ = [
    "ActiveViewEvidence",
    "ActiveViewEvidenceError",
    "ActiveViewFoundation",
    "audit_path_validation",
    "canonical_json",
    "content_id",
    "d435_inner_roi_rays",
    "intersect_camera_rays_with_table",
    "load_active_view_evidence",
    "load_active_view_foundation",
]
