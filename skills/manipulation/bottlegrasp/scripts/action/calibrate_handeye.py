#!/usr/bin/env python3
"""Solve and numerically validate a hand-eye manifest without opening hardware."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable

from thirdhand_va.action.calibration import solve_handeye


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    report = solve_handeye(args.manifest)
    payload = report.to_calibration_payload()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "type": "handeye_solve_report",
                "output": str(args.output),
                "sample_manifest_id": report.manifest_id,
                "camera_serial": report.camera_serial,
                "fit_sample_count": report.fit_sample_count,
                "validation_sample_count": report.validation_sample_count,
                "rotation_axis_diversity": report.rotation_axis_diversity,
                "validation_error": report.validation_metrics.as_dict(),
                "numerically_validated": report.numerically_validated,
                "approved_for_bottle_grasp": False,
                "robot_control_enabled": False,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
