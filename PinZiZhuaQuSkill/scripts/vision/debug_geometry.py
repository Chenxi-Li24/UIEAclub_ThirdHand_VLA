#!/usr/bin/env python3
"""Estimate one camera-frame grasp pose from a recorded bundle and mask."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable

import numpy as np
import cv2

from thirdhand_va.common.config import VisionConfig
from thirdhand_va.common.contracts import MaskCandidate
from thirdhand_va.vision.camera.recording import read_frame_bundle
from thirdhand_va.vision.geometry import estimate_grasp_candidates
from thirdhand_va.vision.geometry.pointcloud import fit_table_plane


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument(
        "mask", type=Path,
        help="Boolean .npy mask or .npz mask archive aligned to the bundle",
    )
    parser.add_argument(
        "--mask-key",
        help="Array name when MASK is an .npz archive",
    )
    parser.add_argument("--config", type=Path, default=Path("configs/vision.yaml"))
    parser.add_argument("--output-json", type=Path)
    parser.add_argument("--output-image", type=Path)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    frame = read_frame_bundle(args.bundle)
    loaded = np.load(args.mask, allow_pickle=False)
    scene_exclusion_mask = None
    if isinstance(loaded, np.lib.npyio.NpzFile):
        try:
            if not args.mask_key or args.mask_key not in loaded.files:
                raise ValueError(
                    "--mask-key must name one array in the .npz archive: "
                    + ", ".join(loaded.files)
                )
            mask = loaded[args.mask_key].astype(bool, copy=False)
            scene_exclusion_mask = np.logical_or.reduce(
                [loaded[key].astype(bool, copy=False) for key in loaded.files]
            )
        finally:
            loaded.close()
    else:
        if args.mask_key is not None:
            raise ValueError("--mask-key is only valid for an .npz archive")
        mask = loaded.astype(bool, copy=False)
    rows, columns = np.nonzero(mask)
    if not rows.size:
        raise ValueError("mask must not be empty")
    candidate = MaskCandidate(
        detection_id=1,
        label="bottle",
        score=1.0,
        bbox_xyxy=(columns.min(), rows.min(), columns.max() + 1, rows.max() + 1),
        mask=mask,
        authorized=True,
    )
    config = VisionConfig.from_yaml(args.config)
    candidates = estimate_grasp_candidates(
        frame, candidate, config, scene_exclusion_mask=scene_exclusion_mask
    )
    table = fit_table_plane(
        frame.xyz_camera_m,
        candidate.mask if scene_exclusion_mask is None else scene_exclusion_mask,
        distance_m=config.table_plane_distance_m,
    )
    payload = {
        "schema": "thirdhand-va-geometry-debug-v1",
        "frame_id": frame.sequence,
        "table_normal": table.normal.tolist(),
        "table_offset": table.offset,
        "table_inlier_ratio": table.inlier_ratio,
        "candidates": [
            {
                "quality": item.quality,
                "height_fraction": item.height_fraction,
                "clearance_m": item.clearance_m,
                "point_m": list(item.pose.point_m),
                "axis": list(item.pose.axis),
                "approach": list(item.pose.approach),
                "width_m": item.pose.width_m,
                "position_std_m": list(item.pose.position_std_m),
                "quality_components": dict(item.quality_components),
                "blockers": list(item.blockers),
            }
            for item in candidates
        ],
        "robot_control_enabled": False,
    }
    encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output_json is not None:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(encoded + "\n", encoding="utf-8")
    if args.output_image is not None:
        rendered = cv2.cvtColor(frame.rgb, cv2.COLOR_RGB2BGR)
        contours, _hierarchy = cv2.findContours(
            candidate.mask.astype(np.uint8),
            cv2.RETR_EXTERNAL,
            cv2.CHAIN_APPROX_SIMPLE,
        )
        cv2.drawContours(rendered, contours, -1, (0, 255, 0), 2)
        top, bottom = int(rows.min()), int(rows.max()) + 1
        center_x = int(round(float(columns.mean())))
        for rank, item in enumerate(candidates, start=1):
            center_y = int(round(bottom - item.height_fraction * (bottom - top)))
            cv2.circle(rendered, (center_x, center_y), 4, (0, 255, 255), -1)
            cv2.putText(
                rendered,
                f"{rank}:{item.quality:.2f}",
                (center_x + 6, center_y),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.4,
                (0, 255, 255),
                1,
                cv2.LINE_AA,
            )
        args.output_image.parent.mkdir(parents=True, exist_ok=True)
        if not cv2.imwrite(str(args.output_image), rendered):
            raise RuntimeError(f"failed to write geometry image: {args.output_image}")
    print(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
