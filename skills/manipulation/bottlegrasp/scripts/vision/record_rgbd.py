#!/usr/bin/env python3
"""Record content-addressed RGB-D bundles from an explicitly authorized camera."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Iterable

from thirdhand_va.common.config import VisionConfig
from thirdhand_va.vision.camera.recording import write_frame_bundle
from thirdhand_va.vision.camera.stream import XVisioStream


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
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
    content_ids = []
    sequence = -1
    with XVisioStream(args.executable, expected_serial=config.camera_serial) as stream:
        while len(content_ids) < args.frames:
            frame = stream.read_after(sequence, timeout_s=5.0)
            if frame is None:
                raise RuntimeError("camera frame timeout")
            sequence = frame.sequence
            target = args.output / f"frame_{len(content_ids):06d}"
            content_ids.append(write_frame_bundle(target, frame))
    print(json.dumps({
        "status": "complete",
        "camera_serial": config.camera_serial,
        "vision_config_sha256": "sha256:" + hashlib.sha256(
            args.config.read_bytes()
        ).hexdigest(),
        "capture_executable": str(args.executable),
        "frame_count": len(content_ids),
        "content_ids": content_ids,
        "robot_control_enabled": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
