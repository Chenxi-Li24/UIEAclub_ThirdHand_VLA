#!/usr/bin/env python3
"""Interactively capture operator-confirmed views of the fixed experiment bottle."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image

from thirdhand_va.vision.camera.stream import XVisioStream
from thirdhand_va.common.config import VisionConfig
from thirdhand_va.vision.perception.grounded_sam import GroundedSamBackend
from thirdhand_va.vision.perception.references import ReferenceBank


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/vision.yaml"),
    )
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--count", type=int, default=20)
    parser.add_argument(
        "--executable",
        type=Path,
        default=Path("build/vision/xvisio_rgbd_stream/xvisio_rgbd_stream"),
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.count <= 0:
        raise SystemExit("--count must be positive")
    if not args.executable.is_file():
        raise SystemExit(
            "native camera executable is missing; run scripts/vision/build_native.sh"
        )
    if not __import__("sys").stdin.isatty():
        raise SystemExit("operator confirmation requires an interactive terminal")

    config = VisionConfig.from_yaml(args.config)
    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    manifest_path = output / "manifest.json"
    if manifest_path.exists():
        bank = ReferenceBank.from_manifest(manifest_path)
        descriptors = list(bank.descriptors)
    else:
        descriptors = []
    backend = GroundedSamBackend(config, local_files_only=True)
    sequence = 0
    print(
        json.dumps(
            {
                "robot_control_enabled": False,
                "existing_references": len(descriptors),
                "requested_count": args.count,
                "instruction": (
                    "Place only the fixed experiment Coke bottle in view; "
                    "rotate it slightly between accepted samples."
                ),
            },
            ensure_ascii=False,
        )
    )

    with XVisioStream(
        args.executable,
        expected_serial=config.camera_serial,
    ) as stream:
        while len(descriptors) < args.count:
            frame = stream.read_after(sequence, timeout_s=5.0)
            if frame is None:
                print("camera timeout; retrying")
                continue
            sequence = frame.sequence
            candidates = [
                item
                for item in backend.infer(frame.rgb)
                if item.prompt_label == "coca-cola plastic bottle"
                and item.score >= config.min_coke_score
                and item.mask is not None
                and item.descriptor is not None
                and int(item.mask.sum()) >= config.min_mask_pixels
            ]
            if len(candidates) != 1:
                print(f"refused frame {sequence}: expected one candidate, got {len(candidates)}")
                continue
            candidate = candidates[0]
            crop_path = _write_crop(output, frame.rgb, candidate.bbox_xyxy)
            answer = input(
                f"Confirm fixed bottle view {len(descriptors) + 1}/{args.count} "
                f"(score={candidate.score:.3f}, preview={crop_path}) [y/N]: "
            )
            if answer.strip().lower() not in {"y", "yes"}:
                crop_path.unlink(missing_ok=True)
                print("candidate rejected by operator")
                continue
            descriptors.append(candidate.descriptor)
            ReferenceBank.write_manifest(manifest_path, descriptors)
            print(f"accepted {len(descriptors)}/{args.count}")
    print(
        json.dumps(
            {
                "status": "complete",
                "robot_control_enabled": False,
                "reference_count": len(descriptors),
                "manifest": str(manifest_path),
            },
            ensure_ascii=False,
        )
    )
    return 0


def _write_crop(
    output: Path,
    rgb: np.ndarray,
    bbox_xyxy: tuple[float, float, float, float],
) -> Path:
    height, width = rgb.shape[:2]
    x0, y0, x1, y1 = bbox_xyxy
    left = max(0, min(width - 1, int(np.floor(x0))))
    top = max(0, min(height - 1, int(np.floor(y0))))
    right = max(left + 1, min(width, int(np.ceil(x1))))
    bottom = max(top + 1, min(height, int(np.ceil(y1))))
    crop = np.ascontiguousarray(rgb[top:bottom, left:right])
    content_id = hashlib.sha256(crop.tobytes()).hexdigest()
    path = output / f"crop_{content_id}.png"
    Image.fromarray(crop, mode="RGB").save(path)
    return path


if __name__ == "__main__":
    raise SystemExit(main())
