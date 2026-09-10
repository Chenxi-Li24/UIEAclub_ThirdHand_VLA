#!/usr/bin/env python3
"""Validate and summarize one or more recorded RGB-D frame bundles."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from thirdhand_va.vision.camera.recording import read_frame_bundle


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundles", nargs="+", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    for bundle in args.bundles:
        frame = read_frame_bundle(bundle)
        valid = np.isfinite(frame.depth_m)
        print(
            json.dumps(
                {
                    "bundle": str(bundle),
                    "sequence": frame.sequence,
                    "monotonic_ns": frame.monotonic_ns,
                    "camera_serial": frame.camera_serial,
                    "shape": list(frame.depth_m.shape),
                    "valid_depth_pixels": int(valid.sum()),
                    "robot_control_enabled": False,
                },
                sort_keys=True,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
