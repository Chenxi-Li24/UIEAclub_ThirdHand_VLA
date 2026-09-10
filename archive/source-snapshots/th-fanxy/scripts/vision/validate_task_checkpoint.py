#!/usr/bin/env python3
"""Validate a labeled tabletop manifest against the exact deployed models."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
SERVER = ROOT / "web-control" / "server"
if str(SERVER) not in sys.path:
    sys.path.insert(0, str(SERVER))

from vision.model_acceptance import ModelAcceptanceError, evaluate_task_checkpoint


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--detector-config", required=True, type=Path)
    parser.add_argument("--detector-checkpoint", required=True, type=Path)
    parser.add_argument("--descriptor-model-id", required=True)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    try:
        evidence = evaluate_task_checkpoint(
            arguments.manifest,
            detector_config_path=arguments.detector_config,
            detector_checkpoint_path=arguments.detector_checkpoint,
            descriptor_model_id=arguments.descriptor_model_id,
            output_path=arguments.output,
        )
    except ModelAcceptanceError as exc:
        raise SystemExit(f"task checkpoint validation failed: {exc}") from exc
    print(evidence["content_id"])
    if not evidence["validated"]:
        print(
            "task checkpoint rejected: " + ",".join(evidence["failure_reasons"]),
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
