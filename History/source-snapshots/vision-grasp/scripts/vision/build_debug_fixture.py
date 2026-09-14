#!/usr/bin/env python3
"""Generate a deterministic, hardware-free RGB-D bottle debug fixture."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable

import cv2
import numpy as np

from thirdhand_va.common.contracts import RgbdFrame
from thirdhand_va.vision.camera.recording import write_frame_bundle


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("artifacts/vision/debug-fixture"),
    )
    return parser


def bottle_mask(center_x: int) -> np.ndarray:
    mask = np.zeros((120, 240), dtype=bool)
    mask[10:35, center_x - 5 : center_x + 5] = True
    mask[35:110, center_x - 15 : center_x + 15] = True
    return mask


def build_fixture(output_root: Path) -> dict[str, object]:
    output_root.mkdir(parents=True, exist_ok=True)
    centers = (45, 120, 195)
    masks = tuple(bottle_mask(center) for center in centers)
    yy, xx = np.indices((120, 240))
    rgb = np.full((120, 240, 3), (38, 42, 46), dtype=np.uint8)
    xyz = np.empty((120, 240, 3), dtype=np.float32)
    xyz[..., 0] = (xx - 120.0) * 0.002
    xyz[..., 1] = 0.07
    xyz[..., 2] = 0.45 + (yy - 60.0) * 0.0001
    colors = ((190, 60, 40), (45, 150, 220), (70, 180, 80))
    for index, (center, mask, color) in enumerate(
        zip(centers, masks, colors, strict=True), start=1
    ):
        rgb[mask] = color
        xyz[..., 0][mask] = (center - 120.0) * 0.002 + (
            xx[mask] - center
        ) * 0.0015
        xyz[..., 1][mask] = (yy[mask] - 60.0) * 0.0015
        xyz[..., 2][mask] = 0.42 + index * 0.02
    frame = RgbdFrame(
        sequence=1,
        monotonic_ns=100_000_000,
        camera_serial="synthetic-debug-camera",
        rgb=rgb,
        depth_m=xyz[..., 2],
        xyz_camera_m=xyz,
    )
    bundle = output_root / "frame_000000"
    content_id = write_frame_bundle(bundle, frame)
    masks_path = output_root / "masks.npz"
    np.savez_compressed(
        masks_path,
        **{f"mask_{index}": mask for index, mask in enumerate(masks, start=1)},
    )
    image_path = output_root / "rgb.jpg"
    if not cv2.imwrite(str(image_path), cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)):
        raise RuntimeError(f"failed to write debug image: {image_path}")
    return {
        "schema": "thirdhand-va-debug-fixture-v1",
        "bundle": str(bundle),
        "bundle_content_id": content_id,
        "masks": str(masks_path),
        "image": str(image_path),
        "robot_control_enabled": False,
    }


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    print(json.dumps(build_fixture(args.output_root), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
