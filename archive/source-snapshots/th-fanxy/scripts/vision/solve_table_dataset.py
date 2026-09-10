#!/usr/bin/env python3
"""Solve and held-out validate a read-only flat-board table dataset."""

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

from vision_models.calibration_capture import CalibrationCaptureError  # noqa: E402
from vision_models.calibration_completion import (  # noqa: E402
    load_validated_handeye_result,
)
from vision_models.table_calibration import (  # noqa: E402
    load_table_dataset,
    solve_table_calibration,
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


def solve_manifest(
    manifest: Path | str,
    handeye_result: Path | str,
    output: Path | str,
    calibration_id: str,
) -> dict[str, Any]:
    dataset = load_table_dataset(manifest)
    handeye = load_validated_handeye_result(handeye_result)
    if dataset.handeye_result_id != handeye.result_id:
        raise CalibrationCaptureError("table dataset hand-eye result changed")
    solved = solve_table_calibration(
        dataset.samples,
        t_flange_from_d435=handeye.t_flange_from_d435,
        calibration_id=calibration_id,
        board_size_m=dataset.board_size_m,
    )
    payload: dict[str, Any] = {
        "schema_version": 1,
        "dataset_id": dataset.dataset_id,
        "candidate_source_id": dataset.candidate_source_id,
        "handeye_result_id": dataset.handeye_result_id,
        "calibration_id": solved.calibration_id,
        "normal_base": list(solved.normal_base),
        "offset_m": solved.offset_m,
        "fit_samples": solved.fit_samples,
        "validation_samples": solved.validation_samples,
        "fit": {"rmse_m": solved.fit_rmse_m},
        "validation": {"p95_m": solved.validation_p95_m},
        "validated": solved.validated,
        "reasons": list(solved.reasons),
    }
    payload["content_id"] = "sha256:" + hashlib.sha256(_canonical(payload)).hexdigest()
    _atomic_json(Path(output), payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--handeye-result", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--calibration-id", required=True)
    arguments = parser.parse_args()
    result = solve_manifest(
        arguments.manifest,
        arguments.handeye_result,
        arguments.output,
        arguments.calibration_id,
    )
    print(
        f"validated={str(result['validated']).lower()} "
        f"fit_rmse_m={result['fit']['rmse_m']:.6f} "
        f"validation_p95_m={result['validation']['p95_m']:.6f}"
    )
    print(f"output={arguments.output} content_id={result['content_id']}")
    return 0 if result["validated"] else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except CalibrationCaptureError as error:
        raise SystemExit(f"table solve rejected: {error}") from error
