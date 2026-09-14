#!/usr/bin/env python3
"""Query Startouch joint feedback without enabling motors and run offline FK."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib
import json
import math
from pathlib import Path
import sys
from typing import Any

import yaml


DEFAULT_SDK_PATH = Path("/home/nieqingcao/arm/startouch_sdk")
DEFAULT_BRIDGE_ROOT = Path("/home/nieqingcao/TH-Fanxy/web-control/server")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read joints with the Startouch CAN 0xCC status query and compute both "
            "the real flange pose and the SDK configured-tool pose. This never "
            "constructs SingleArm and never enables motors."
        )
    )
    parser.add_argument("--sdk-path", type=Path, default=DEFAULT_SDK_PATH)
    parser.add_argument(
        "--bridge-root",
        type=Path,
        default=DEFAULT_BRIDGE_ROOT,
        help="Directory containing startouch_bridge.py and robot_cartesian_adapter.py",
    )
    parser.add_argument(
        "--offline-joints-deg",
        type=float,
        nargs=6,
        metavar=("J1", "J2", "J3", "J4", "J5", "J6"),
        help="Offline fixture mode; skips CAN and uses these signed SDK joint degrees",
    )
    return parser.parse_args()


def resolve_bridge_server(path: Path) -> Path:
    candidates = (path, path / "server", path / "web-control/server")
    for candidate in candidates:
        if (
            (candidate / "startouch_bridge.py").is_file()
            and (candidate / "robot_cartesian_adapter.py").is_file()
        ):
            return candidate.resolve()
    raise RuntimeError(f"Startouch bridge modules not found below {path}")


def load_modules(bridge_server: Path) -> tuple[Any, Any]:
    sys.path.insert(0, str(bridge_server))
    try:
        bridge = importlib.import_module("startouch_bridge")
        adapter = importlib.import_module("robot_cartesian_adapter")
    finally:
        sys.path.pop(0)
    # Keep the report as the only stdout JSON document if the legacy probe logs.
    bridge._event_stream = sys.stderr
    return bridge, adapter


def pose_json(planner: Any, transform: Any) -> dict[str, Any]:
    return {
        "xyz_m": [float(value) for value in transform[:3, 3]],
        "rpy_rad": [
            float(value) for value in planner.euler_xyz(transform[:3, :3])
        ],
        "matrix_4x4": [
            [float(value) for value in row] for row in transform.tolist()
        ],
    }


def main() -> int:
    args = parse_args()
    sdk_path = args.sdk_path.expanduser().resolve()
    bridge_server = resolve_bridge_server(args.bridge_root.expanduser().resolve())
    bridge, adapter = load_modules(bridge_server)

    config_path = sdk_path / "src/config/robot_kinematics.yaml"
    urdf_path = sdk_path / "src/config/FastTouchV2.SLDASM.urdf"
    if not config_path.is_file() or not urdf_path.is_file():
        raise RuntimeError(f"SDK kinematics files are unavailable below {sdk_path}")
    raw_config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    tool_xyz = raw_config["kinematics"]["tool"]["xyz"]
    tool_rpy = raw_config["kinematics"]["tool"]["rpy"]

    motor_feedback = None
    if args.offline_joints_deg is not None:
        mode = "offline_fixture"
        hardware_access = "none"
        joints_rad = [math.radians(value) for value in args.offline_joints_deg]
    else:
        mode = "can_status_query"
        hardware_access = "CAN 0x7FF/0xCC query only"
        motor_feedback = bridge.RobotBridge._probe_can_feedback()
        unacceptable = [
            item for item in motor_feedback if item.get("error_code") not in {0, 1}
        ]
        if unacceptable:
            details = ", ".join(
                f"J{item['joint']}=0x{item['error_code']:X}" for item in unacceptable
            )
            raise RuntimeError(
                "motor feedback is not position-reliable without enabling: " + details
            )
        joints_rad = [
            float(item["position_rad"]) * bridge.MOTOR_SIGNS[item["joint"] - 1]
            for item in motor_feedback
        ]

    tool_planner = adapter.CartesianTranslationPlanner.from_sdk_path(
        sdk_path,
        joint_limits_rad=bridge.JOINT_LIMITS_RAD,
    )
    flange_planner = adapter.CartesianTranslationPlanner.from_urdf(
        urdf_path,
        tool_xyz_m=(0.0, 0.0, 0.0),
        tool_rpy_rad=(0.0, 0.0, 0.0),
        joint_limits_rad=bridge.JOINT_LIMITS_RAD,
        max_translation_m=0.020,
        max_joint_delta_rad=math.radians(15.0),
    )
    base_from_tool = tool_planner.forward_kinematics(joints_rad)
    base_from_flange = flange_planner.forward_kinematics(joints_rad)
    now = datetime.now().astimezone()
    report = {
        "schema": "thirdhand-read-grasp-robot-pose-v1",
        "timestamp": now.isoformat(),
        "timestamp_utc": now.astimezone(timezone.utc).isoformat(),
        "mode": mode,
        "hardware_access": hardware_access,
        "single_arm_constructed": False,
        "sdk_path": str(sdk_path),
        "bridge_server": str(bridge_server),
        "joints": {
            "signed_sdk_rad": [float(value) for value in joints_rad],
            "signed_sdk_deg": [math.degrees(value) for value in joints_rad],
            "motor_signs": list(bridge.MOTOR_SIGNS),
        },
        "motor_feedback": motor_feedback,
        "sdk_tool_offset": {
            "xyz_m": [float(value) for value in tool_xyz],
            "rpy_rad": [float(value) for value in tool_rpy],
            "semantics": "T_flange_sdk_tool from robot_kinematics.yaml",
        },
        "base_from_flange": pose_json(flange_planner, base_from_flange),
        "base_from_sdk_tool": pose_json(tool_planner, base_from_tool),
        "pose_convention": {
            "rpy_order": "xyz",
            "composition": "Rz(yaw) @ Ry(pitch) @ Rx(roll)",
        },
    }
    json.dump(report, sys.stdout, ensure_ascii=False, indent=2, allow_nan=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (KeyError, OSError, RuntimeError, TypeError, ValueError) as error:
        print(f"read_grasp_robot_pose: {error}", file=sys.stderr)
        raise SystemExit(1)
