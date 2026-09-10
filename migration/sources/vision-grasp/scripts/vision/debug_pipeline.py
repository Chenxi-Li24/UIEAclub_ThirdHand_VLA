#!/usr/bin/env python3
"""Run the complete Vision pipeline over explicit recorded RGB-D bundles."""

from __future__ import annotations

import argparse
from dataclasses import replace
import json
from pathlib import Path
from typing import Iterable

import numpy as np

from thirdhand_va.common.config import VisionConfig
from thirdhand_va.vision.camera.recording import read_frame_bundle
from thirdhand_va.vision.perception.grounded_sam import GroundedSamBackend
from thirdhand_va.vision.perception.interfaces import RawCandidate
from thirdhand_va.vision.pipeline import VisionPipeline


class FixtureMaskBackend:
    """Small deterministic adapter for pipeline debugging without learned models."""

    def __init__(self, masks_path: Path) -> None:
        with np.load(masks_path, allow_pickle=False) as stored:
            keys = sorted(stored.files)
            if not keys:
                raise ValueError("synthetic mask archive must not be empty")
            self.masks = tuple(stored[key].astype(bool, copy=True) for key in keys)

    def infer(self, rgb: np.ndarray) -> tuple[RawCandidate, ...]:
        candidates = []
        for index, mask in enumerate(self.masks, start=1):
            if mask.shape != rgb.shape[:2]:
                raise ValueError("synthetic mask does not align to RGB")
            rows, columns = np.nonzero(mask)
            descriptor = np.zeros(len(self.masks), dtype=np.float32)
            descriptor[index - 1] = 1.0
            candidates.append(RawCandidate(
                detection_id=index,
                prompt_label="bottle",
                score=0.99,
                bbox_xyxy=(
                    float(columns.min()), float(rows.min()),
                    float(columns.max() + 1), float(rows.max() + 1),
                ),
                mask=mask,
                descriptor=descriptor,
            ))
        return tuple(candidates)

    def model_provenance(self) -> dict[str, str]:
        return {"backend": "synthetic-mask-fixture"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundles", nargs="+", type=Path)
    parser.add_argument("--config", type=Path, default=Path("configs/vision.yaml"))
    parser.add_argument("--target-id", type=int, choices=range(1, 6), required=True)
    parser.add_argument("--request-id", default="vision-debug")
    parser.add_argument(
        "--synthetic-masks",
        type=Path,
        help="debug-only .npz masks; bypasses learned perception but runs tracking/geometry",
    )
    parser.add_argument(
        "--repeat-last",
        type=int,
        default=0,
        help="repeat the last recorded image with fresh monotonic frame IDs",
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    if args.repeat_last < 0 or args.repeat_last > 30:
        raise ValueError("--repeat-last must be within [0, 30]")
    config = VisionConfig.from_yaml(args.config)
    backend = (
        FixtureMaskBackend(args.synthetic_masks)
        if args.synthetic_masks is not None
        else GroundedSamBackend(config, local_files_only=True)
    )
    pipeline = VisionPipeline(config, backend)
    frames = [read_frame_bundle(bundle) for bundle in args.bundles]
    if args.repeat_last:
        last = frames[-1]
        step_ns = (
            last.monotonic_ns - frames[-2].monotonic_ns
            if len(frames) > 1
            else 100_000_000
        )
        step_ns = max(1, step_ns)
        frames.extend(
            replace(
                last,
                sequence=last.sequence + index,
                monotonic_ns=last.monotonic_ns + index * step_ns,
            )
            for index in range(1, args.repeat_last + 1)
        )
    decisions = []
    for frame in frames:
        decision = pipeline.process(frame, now_ns=frame.monotonic_ns)
        decisions.append(decision)
        if pipeline.selection is None:
            pipeline.select(args.target_id, args.request_id)
    decision = decisions[-1]
    print(json.dumps({
        "status": decision.status,
        "frame_id": decision.frame_id,
        "target_id": args.target_id,
        "selected_stable_id": decision.selected_stable_id,
        "target_detection_id": (
            None if decision.target is None else decision.target.detection_id
        ),
        "motion_epoch": decision.motion_epoch,
        "evidence_id": decision.evidence_id,
        "tracks": [
            {
                "stable_id": track.stable_id,
                "backend_track_id": track.backend_track_id,
                "detection_id": track.candidate.detection_id,
                "state": track.state,
                "depth_supported": track.depth_supported,
                "blockers": list(track.blockers),
            }
            for track in decision.tracks
        ],
        "reasons": list(decision.reasons),
        "processed_frames": len(decisions),
        "repeated_frames": args.repeat_last,
        "robot_control_enabled": False,
    }, sort_keys=True))
    return 0 if decision.status == "ready" else 2


if __name__ == "__main__":
    raise SystemExit(main())
