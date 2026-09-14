#!/usr/bin/env python3
"""Exercise horizontal ordinal selection from synthetic mask centers."""

from __future__ import annotations

import argparse
import json
from typing import Iterable

import numpy as np

from thirdhand_va.common.contracts import MaskCandidate
from thirdhand_va.vision.selection import SelectionRequest, SpatialBottleSelector


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--centers", nargs="+", type=int, required=True)
    parser.add_argument("--side", choices=("left", "right"), required=True)
    parser.add_argument("--ordinal", type=int, required=True)
    parser.add_argument("--min-gap-px", type=float, default=12.0)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    width = max(args.centers) + 20
    candidates = []
    for detection_id, center in enumerate(args.centers, start=1):
        mask = np.zeros((20, width), dtype=bool)
        mask[5:15, max(0, center - 3):min(width, center + 4)] = True
        candidates.append(MaskCandidate(
            detection_id=detection_id,
            label="bottle",
            score=1.0,
            bbox_xyxy=(center - 3, 5, center + 3, 15),
            mask=mask,
            authorized=True,
        ))
    result = SpatialBottleSelector(args.min_gap_px).select(
        tuple(candidates), SelectionRequest(args.side, args.ordinal)
    )
    print(json.dumps({
        "selected_detection_id": (
            None if result.selected is None else result.selected.detection_id
        ),
        "reasons": list(result.reasons),
        "ranks": [
            {
                "detection_id": rank.detection_id,
                "left_ordinal": rank.left_ordinal,
                "right_ordinal": rank.right_ordinal,
            }
            for rank in result.ranks
        ],
        "robot_control_enabled": False,
    }, sort_keys=True))
    return 0 if result.selected is not None else 2


if __name__ == "__main__":
    raise SystemExit(main())

