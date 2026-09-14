#!/usr/bin/env python3
"""Run only the perception backend against one recorded RGB-D bundle."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable

from thirdhand_va.common.config import VisionConfig
from thirdhand_va.vision.camera.recording import read_frame_bundle
from thirdhand_va.vision.perception.grounded_sam import GroundedSamBackend
from thirdhand_va.vision.perception.bottle_filter import evaluate_bottle_shape


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--config", type=Path, default=Path("configs/vision.yaml"))
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    config = VisionConfig.from_yaml(args.config)
    frame = read_frame_bundle(args.bundle)
    backend = GroundedSamBackend(config, local_files_only=True)
    candidates = backend.infer(frame.rgb)
    dino_ms, sam_ms = backend.inference_timings_ms
    print(json.dumps({
        "frame_id": frame.sequence,
        "provenance": backend.model_provenance(),
        "timings_ms": {"grounding_dino": dino_ms, "sam2": sam_ms},
        "candidates": [
            {
                "detection_id": item.detection_id,
                "label": item.prompt_label,
                "score": item.score,
                "has_mask": item.mask is not None,
                "mask_pixels": 0 if item.mask is None else int(item.mask.sum()),
                "shape": (
                    None
                    if item.mask is None
                    else evaluate_bottle_shape(item.mask, config).to_dict()
                ),
                "descriptor_dim": (
                    0 if item.descriptor is None else int(item.descriptor.size)
                ),
            }
            for item in candidates
        ],
        "robot_control_enabled": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
