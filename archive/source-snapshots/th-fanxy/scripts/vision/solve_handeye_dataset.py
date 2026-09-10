#!/usr/bin/env python3
"""Solve and held-out validate a read-only D435 hand-eye capture dataset."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

SERVER_ROOT = Path(__file__).resolve().parents[2] / "web-control" / "server"
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

from vision_models.calibration_pipeline import (  # noqa: E402
    CalibrationPipelineError,
    load_handeye_dataset,
    solve_d435_handeye,
)


def _canonical(payload: Any) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(json.dumps(payload, sort_keys=True, indent=2).encode("ascii") + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def solve_manifest(manifest: Path | str, output: Path | str) -> dict[str, Any]:
    samples, dataset_id = load_handeye_dataset(manifest)
    solved = solve_d435_handeye(samples)
    audit_payload = {
        "schema_version": 1,
        "dataset_id": dataset_id,
        "solver": f"opencv_calibrateHandEye_{solved.method.lower()}",
        "T_flange_from_d435": solved.t_flange_from_d435.tolist(),
        "validation": {
            "reprojection_rmse_px": solved.reprojection_rmse_px,
            "position_rmse_m": solved.position_rmse_m,
        },
    }
    payload: dict[str, Any] = {
        "schema_version": 1,
        "dataset_id": dataset_id,
        "method": solved.method,
        "T_flange_from_d435": solved.t_flange_from_d435.tolist(),
        "fit_samples": solved.fit_samples,
        "validation_samples": solved.validation_samples,
        "validation": {
            "position_rmse_m": solved.position_rmse_m,
            "position_p95_m": solved.position_p95_m,
            "reprojection_rmse_px": solved.reprojection_rmse_px,
        },
        "validated": solved.validated,
        "reasons": list(solved.reasons),
        "audit_payload": audit_payload,
    }
    payload["content_id"] = f"sha256:{hashlib.sha256(_canonical(payload)).hexdigest()}"
    _atomic_json(Path(output), payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    result = solve_manifest(arguments.manifest, arguments.output)
    print(
        f"validated={str(result['validated']).lower()} method={result['method']} "
        f"position_p95_m={result['validation']['position_p95_m']:.6f} "
        f"reprojection_rmse_px={result['validation']['reprojection_rmse_px']:.3f}"
    )
    print(f"output={arguments.output} content_id={result['content_id']}")
    return 0 if result["validated"] else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except CalibrationPipelineError as error:
        raise SystemExit(f"hand-eye solve rejected: {error}") from error
