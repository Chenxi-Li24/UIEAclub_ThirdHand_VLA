#!/usr/bin/env python3
"""Build a content-addressed observation catalog without moving hardware."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
SERVER = ROOT / "web-control" / "server"
if str(SERVER) not in sys.path:
    sys.path.insert(0, str(SERVER))

from vision.calibration_gate import sdk_pose_transform
from vision.geometry import validate_transform
from vision_models.active_view_catalog import (
    ActiveViewEvidenceError,
    ActiveViewFoundation,
    audit_path_validation,
    canonical_json,
    content_id,
    d435_inner_roi_rays,
    intersect_camera_rays_with_table,
    load_active_view_foundation,
)


def _finite_vector(value: Any, length: int, name: str) -> list[float]:
    try:
        vector = np.asarray(value, dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must contain finite values") from exc
    if vector.shape != (length,) or not np.isfinite(vector).all():
        raise ValueError(f"{name} must contain {length} finite values")
    return [float(item) for item in vector]


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(canonical_json(payload) + "\n", encoding="utf-8")
    temporary.replace(path)


def finalize_catalog(
    captures: Mapping[str, Any],
    evidence: ActiveViewFoundation,
    output_path: Path | str,
) -> dict[str, Any]:
    if not isinstance(captures, dict) or set(captures) != {"schema_version", "captures"}:
        raise ValueError("capture manifest keys are invalid")
    if captures["schema_version"] != 1 or not isinstance(captures["captures"], list):
        raise ValueError("capture manifest schema is invalid")
    if not isinstance(evidence, ActiveViewFoundation):
        raise ValueError("active-view foundation is required")
    raw_captures = captures["captures"]
    if not 1 <= len(raw_captures) <= 64:
        raise ValueError("capture manifest must contain between 1 and 64 captures")
    names: set[str] = set()
    poses: list[dict[str, Any]] = []
    all_validated = True
    for index, raw_capture in enumerate(raw_captures):
        if not isinstance(raw_capture, dict):
            raise ValueError(f"captures[{index}] must be an object")
        allowed_keys = {
            "name",
            "joints_deg",
            "tcp_position_m",
            "tcp_euler_rad",
            "allowed_start_pose_ids",
            "joint_tolerance_deg",
            "path_validation",
            "captured_at",
            "server_url",
        }
        unknown = set(raw_capture) - allowed_keys
        required = allowed_keys - {"path_validation", "captured_at", "server_url"}
        if unknown or not required.issubset(raw_capture):
            raise ValueError(f"captures[{index}] keys are invalid")
        name = raw_capture["name"]
        if not isinstance(name, str) or not name or len(name) > 128:
            raise ValueError(f"captures[{index}] name is invalid")
        if name in names:
            raise ValueError("capture names must be unique; duplicate found")
        names.add(name)
        joints = _finite_vector(raw_capture["joints_deg"], 6, f"{name} joints")
        position = _finite_vector(raw_capture["tcp_position_m"], 3, f"{name} TCP position")
        euler = _finite_vector(raw_capture["tcp_euler_rad"], 3, f"{name} TCP Euler")
        transform = validate_transform(sdk_pose_transform(position, euler))
        starts = raw_capture["allowed_start_pose_ids"]
        if (
            not isinstance(starts, list)
            or not starts
            or any(not isinstance(item, str) or not item for item in starts)
        ):
            raise ValueError(f"{name} allowed starts are invalid")
        tolerance = raw_capture["joint_tolerance_deg"]
        if isinstance(tolerance, bool):
            raise ValueError(f"{name} joint tolerance must be finite and positive")
        tolerance = float(tolerance)
        if not math.isfinite(tolerance) or tolerance <= 0.0:
            raise ValueError(f"{name} joint tolerance must be finite and positive")
        t_base_from_d435 = (
            transform
            @ evidence.camera.t_flange_from_lumos
            @ evidence.camera.t_lumos_from_d435
        )
        coverage = intersect_camera_rays_with_table(
            d435_inner_roi_rays(evidence.camera.d435, inner_roi_fraction=0.60),
            t_base_from_d435,
            evidence.table,
        )
        path_validation = raw_capture.get("path_validation")
        if path_validation is None:
            path_validation_id = None
            all_validated = False
        else:
            if not isinstance(path_validation, dict):
                raise ValueError(f"{name} path validation must be an object")
            path_validation_id = audit_path_validation(path_validation, name)
        poses.append(
            {
                "allowed_start_pose_ids": list(starts),
                "coverage_polygon_xy_m": coverage.tolist(),
                "joint_tolerance_deg": tolerance,
                "joints_deg": joints,
                "path_validation": path_validation,
                "path_validation_id": path_validation_id,
                "pose_id": name,
                "t_base_from_flange": transform.tolist(),
            }
        )
    payload = {
        "calibration_id": evidence.camera.calibration.calibration_id,
        "poses": poses,
        "robot_model_id": evidence.robot_model_id,
        "schema_version": 1,
        "validated": all_validated,
    }
    result = {**payload, "content_id": content_id(payload)}
    _atomic_json(Path(output_path), result)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--captures", required=True, type=Path)
    parser.add_argument("--camera", required=True, type=Path)
    parser.add_argument("--table", required=True, type=Path)
    parser.add_argument("--evidence-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        captures = json.loads(arguments.captures.read_text(encoding="utf-8"))
        evidence = load_active_view_foundation(
            arguments.camera,
            arguments.table,
            evidence_dir=arguments.evidence_dir,
        )
        finalize_catalog(captures, evidence, arguments.output)
    except (OSError, UnicodeError, json.JSONDecodeError, ActiveViewEvidenceError, ValueError) as exc:
        raise SystemExit(f"active-view catalog finalization failed: {exc}") from exc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
