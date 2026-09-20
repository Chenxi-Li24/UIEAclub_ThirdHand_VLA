#!/usr/bin/env python3
"""Validate bounded XVisio alignment evidence after explicit camera permission."""

import argparse
import hashlib
import json
import time
from pathlib import Path

import numpy as np

from thirdhand_va.common.config import VisionConfig
from thirdhand_va.vision.camera.stream import XVisioStream


def alignment_passed(report: dict[str, object]) -> bool:
    """Return true only for synchronized frames plus a measured target check."""
    return bool(
        report.get("frame_count")
        and report.get("monotonic_frames") is True
        and report.get("common_rgb_depth_xyz_grid") is True
        and report.get("target_alignment_check_passed") is True
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("configs/vision.yaml"))
    parser.add_argument("--duration-s", type=float, default=1800.0)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--target-check-passed", action="store_true")
    parser.add_argument("--allow-camera", action="store_true")
    parser.add_argument(
        "--executable",
        type=Path,
        default=Path("build/vision/xvisio_rgbd_stream/xvisio_rgbd_stream"),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.allow_camera:
        print(json.dumps({
            "passed": False,
            "reasons": ["camera_access_not_authorized"],
            "robot_control_enabled": False,
        }, sort_keys=True))
        return 2
    if args.duration_s <= 0:
        raise SystemExit("--duration-s must be positive")
    config = VisionConfig.from_yaml(args.config)
    start, sequence = time.monotonic(), 0
    stamps, ratios, shapes = [], [], set()
    with XVisioStream(
        args.executable,
        expected_serial=config.camera_serial,
    ) as stream:
        while time.monotonic() - start < args.duration_s:
            frame = stream.read_after(sequence, 5.0)
            if frame is None:
                raise RuntimeError("camera timeout during stability run")
            sequence = frame.sequence
            stamps.append(frame.monotonic_ns)
            ratios.append(float(np.isfinite(frame.depth_m).mean()))
            shapes.add((frame.rgb.shape[:2], frame.depth_m.shape, frame.xyz_camera_m.shape[:2]))
    intervals = np.diff(stamps) / 1e6
    report = {
        "schema": "thirdhand-va-camera-validation-v1",
        "robot_control_enabled": False,
        "camera_serial": config.camera_serial,
        "vision_config_sha256": "sha256:" + hashlib.sha256(
            args.config.read_bytes()
        ).hexdigest(),
        "capture_executable": str(args.executable),
        "duration_s": time.monotonic() - start,
        "frame_count": len(stamps),
        "monotonic_frames": bool(stamps and np.all(np.diff(stamps) > 0)),
        "common_rgb_depth_xyz_grid": len(shapes) == 1,
        "mean_valid_depth_ratio": float(np.mean(ratios)),
        "frame_interval_ms_p50": float(np.percentile(intervals, 50)) if intervals.size else None,
        "frame_interval_ms_p95": float(np.percentile(intervals, 95)) if intervals.size else None,
        "geometric_alignment_claimed": bool(args.target_check_passed),
        "target_alignment_check_passed": bool(args.target_check_passed),
    }
    report["passed"] = alignment_passed(report)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temp = args.output.with_suffix(args.output.suffix + ".tmp")
    temp.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(args.output)
    print(json.dumps(report, sort_keys=True))
    return 0 if report["passed"] else 2

if __name__ == "__main__":
    raise SystemExit(main())
