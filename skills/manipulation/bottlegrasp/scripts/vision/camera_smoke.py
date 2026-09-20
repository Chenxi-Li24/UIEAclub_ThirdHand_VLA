#!/usr/bin/env python3
"""Read a bounded number of XVisio RGB-D frames after explicit authorization."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Iterable

from thirdhand_va.common.config import VisionConfig
from thirdhand_va.vision.camera.stream import XVisioStream


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("configs/vision.yaml"))
    parser.add_argument(
        "--executable",
        type=Path,
        default=Path("build/vision/xvisio_rgbd_stream/xvisio_rgbd_stream"),
    )
    parser.add_argument("--frames", type=int, default=5)
    parser.add_argument("--allow-camera", action="store_true")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    if not args.allow_camera:
        print(json.dumps({
            "status": "blocked",
            "reasons": ["camera_access_not_authorized"],
            "robot_control_enabled": False,
        }, sort_keys=True))
        return 2
    if args.frames <= 0:
        raise SystemExit("--frames must be positive")
    config = VisionConfig.from_yaml(args.config)
    frames = []
    sequence = -1
    with XVisioStream(args.executable, expected_serial=config.camera_serial) as stream:
        while len(frames) < args.frames:
            frame = stream.read_after(sequence, timeout_s=5.0)
            if frame is None:
                raise RuntimeError("camera frame timeout")
            sequence = frame.sequence
            frames.append({
                "sequence": frame.sequence,
                "rgb_shape": list(frame.rgb.shape),
                "depth_shape": list(frame.depth_m.shape),
                "xyz_shape": list(frame.xyz_camera_m.shape),
            })
    print(json.dumps({
        "status": "complete",
        "camera_serial": config.camera_serial,
        "vision_config_sha256": "sha256:" + hashlib.sha256(
            args.config.read_bytes()
        ).hexdigest(),
        "capture_executable": str(args.executable),
        "frames": frames,
        "robot_control_enabled": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
