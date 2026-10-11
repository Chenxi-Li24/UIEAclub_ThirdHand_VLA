#!/usr/bin/env python3
"""One-request JSON adapter for the pure TCP calibration solver."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.tcp_calibration.pivot_solver import derive_grasp_tcp, solve_pivot, validate_pivot


def main() -> int:
    request = json.load(sys.stdin)
    operation = request.get("operation")
    if operation == "solve":
        result = solve_pivot(request["fit_samples"], request["thresholds"])
    elif operation == "validate":
        result = validate_pivot(request["candidate"], request["validation_samples"], request["thresholds"])
    elif operation == "derive":
        result = derive_grasp_tcp(
            request["T_flange_probe_tip"],
            request["distance_m"],
            request["tool_axis_flange"],
            request["measurement_uncertainty_m"],
        )
    else:
        raise ValueError("operation_invalid")
    json.dump(result, sys.stdout, allow_nan=False, separators=(",", ":"))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
