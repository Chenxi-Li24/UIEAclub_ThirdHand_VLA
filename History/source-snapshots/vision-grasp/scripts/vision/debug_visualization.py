#!/usr/bin/env python3
"""Render registered depth over one recorded RGB-D bundle without models."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable

import numpy as np

from thirdhand_va.common.config import VisionConfig
from thirdhand_va.vision.camera.recording import read_frame_bundle
from thirdhand_va.vision.visualization import (
    DEFAULT_DEPTH_ALPHA,
    add_depth_legend,
    blend_registered_depth,
    encode_jpeg,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path, help="Recorded RGB-D frame directory")
    parser.add_argument("--config", type=Path, default=Path("configs/vision.yaml"))
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/vision/debug/depth-fusion.jpg"),
    )
    parser.add_argument("--depth-alpha", type=float, default=DEFAULT_DEPTH_ALPHA)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    config = VisionConfig.from_yaml(args.config)
    frame = read_frame_bundle(args.bundle)
    rendered, valid = blend_registered_depth(
        frame.rgb,
        frame.depth_m,
        min_depth_m=config.min_depth_m,
        max_depth_m=config.max_depth_m,
        alpha=args.depth_alpha,
    )
    if np.any(valid):
        rendered = add_depth_legend(
            rendered,
            min_depth_m=config.min_depth_m,
            max_depth_m=config.max_depth_m,
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(encode_jpeg(rendered))
    valid_pixels = int(valid.sum())
    print(
        json.dumps(
            {
                "bundle": str(args.bundle),
                "depth_alpha": args.depth_alpha,
                "max_depth_m": config.max_depth_m,
                "min_depth_m": config.min_depth_m,
                "output": str(args.output),
                "robot_control_enabled": False,
                "valid_depth_pixels": valid_pixels,
                "valid_depth_ratio": valid_pixels / valid.size,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
