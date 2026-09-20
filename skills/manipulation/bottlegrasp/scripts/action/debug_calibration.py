#!/usr/bin/env python3
"""Validate and summarize one hand-eye calibration without opening hardware."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable

from thirdhand_va.action.calibration import HandEyeCalibration


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("calibration", type=Path)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    calibration = HandEyeCalibration.load(args.calibration)
    print(json.dumps({
        "calibration_id": calibration.content_id,
        "camera_serial": calibration.camera_serial,
        "robot_state_semantics": calibration.robot_state_semantics,
        "transform_semantics": calibration.extrinsic_semantics,
        "T_flange_camera": calibration.t_flange_camera.tolist(),
        "pose_semantics_compatible": calibration.pose_semantics_compatible,
        "numerically_validated": calibration.numerically_validated,
        "physically_validated": calibration.physically_validated,
        "approved_for_bottle_grasp": calibration.approved_for_bottle_grasp,
        "robot_control_enabled": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
