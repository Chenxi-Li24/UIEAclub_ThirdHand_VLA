#!/usr/bin/env python3
"""Replay synthetic detections and print stable bottle IDs frame by frame."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from thirdhand_va.common.config import VisionConfig
from thirdhand_va.common.contracts import MaskCandidate
from thirdhand_va.vision.tracking import StableTrackManager


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=Path("configs/vision.yaml"))
    return parser


def _candidate(row: dict[str, int], width: int, height: int) -> MaskCandidate:
    center_x = int(row["center_x"])
    physical_id = int(row["physical_id"])
    mask = np.zeros((height, width), dtype=bool)
    mask[10:height - 10, center_x - 7:center_x + 7] = True
    descriptor = np.zeros(8, dtype=np.float32)
    descriptor[physical_id] = 1.0
    return MaskCandidate(
        detection_id=int(row["detection_id"]),
        label="bottle",
        score=0.95,
        bbox_xyxy=(center_x - 7, 10, center_x + 7, height - 10),
        mask=mask,
        authorized=True,
        descriptor=descriptor,
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload = json.loads(args.fixture.read_text(encoding="utf-8"))
    width, height = (int(value) for value in payload["canvas"])
    manager = StableTrackManager.from_config(VisionConfig.from_yaml(args.config))
    output = []
    for frame_index, rows in enumerate(payload["frames"], start=1):
        tracks = manager.update(
            tuple(_candidate(row, width, height) for row in rows),
            now_ns=frame_index * 1_000_000,
            camera_moving=False,
        )
        output.append({
            "frame": frame_index,
            "tracks": [
                {
                    "physical_id": int(np.argmax(track.candidate.descriptor)),
                    "detection_id": track.candidate.detection_id,
                    "backend_track_id": track.backend_track_id,
                    "stable_id": track.stable_id,
                    "state": track.state,
                    "blockers": list(track.blockers),
                }
                for track in tracks
            ],
        })
    print(json.dumps({
        "schema": "thirdhand-va-tracking-debug-v1",
        "frames": output,
        "robot_control_enabled": False,
    }, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
