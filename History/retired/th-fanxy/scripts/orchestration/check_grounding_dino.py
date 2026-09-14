#!/usr/bin/env python3
"""Check an explicit local Grounding DINO model without downloading files."""

from __future__ import annotations

import argparse
from pathlib import Path

from pydantic import ValidationError

from uiea_thirdhand_vla.orchestration.runtime.trace import canonical_json
from uiea_thirdhand_vla.orchestration.shadow.grounding_dino import (
    GroundingDinoConfig,
    GroundingDinoUnavailable,
    HuggingFaceGroundingDinoBackend,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, type=Path)
    parser.add_argument("--device", default="cpu")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload: dict[str, object] = {
        "local_files_only": True,
        "robot_execution_enabled": False,
        "status": "UNAVAILABLE",
    }
    try:
        config = GroundingDinoConfig(model_path=args.model, device=args.device)
        HuggingFaceGroundingDinoBackend().load(config)
    except (GroundingDinoUnavailable, ValidationError, ValueError) as exc:
        payload["reason"] = str(exc)
        print(canonical_json(payload))
        return 2
    payload["status"] = "AVAILABLE"
    payload["model_path"] = str(args.model)
    print(canonical_json(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
