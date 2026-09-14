#!/usr/bin/env python3
"""Build the content-addressed camera/table foundation for active-view geometry."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SERVER_ROOT = Path(__file__).resolve().parents[2] / "web-control" / "server"
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

from vision_models.calibration_capture import CalibrationCaptureError  # noqa: E402
from vision_models.calibration_completion import (  # noqa: E402
    load_validated_handeye_result,
)
from vision_models.dual_camera_candidate import (  # noqa: E402
    load_dual_camera_candidate,
)
from vision_models.foundation_evidence import (  # noqa: E402
    build_foundation_payloads,
    foundation_calibration_id,
    load_validated_table_result,
    write_foundation_payloads,
)
from vision_models.relative_validation_evidence import (  # noqa: E402
    load_relative_validation_evidence,
)


def load_camera_chain(
    candidate_path: Path | str,
    relative_validation_path: Path | str,
    handeye_result_path: Path | str,
):
    candidate = load_dual_camera_candidate(candidate_path)
    relative = load_relative_validation_evidence(relative_validation_path, candidate)
    handeye = load_validated_handeye_result(handeye_result_path)
    return candidate, relative, handeye


def finalize(
    *,
    candidate_path: Path | str,
    relative_validation_path: Path | str,
    handeye_result_path: Path | str,
    table_result_path: Path | str,
    output: Path | str,
    robot_model_id: str,
) -> tuple[Path, Path, dict, dict]:
    candidate, relative, handeye = load_camera_chain(
        candidate_path,
        relative_validation_path,
        handeye_result_path,
    )
    table = load_validated_table_result(table_result_path)
    camera_payload, table_payload = build_foundation_payloads(
        candidate,
        relative,
        handeye,
        table,
        robot_model_id=robot_model_id,
    )
    camera_path, table_path = write_foundation_payloads(
        output,
        camera_payload,
        table_payload,
    )
    return camera_path, table_path, camera_payload, table_payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--relative-validation", required=True, type=Path)
    parser.add_argument("--handeye-result", required=True, type=Path)
    parser.add_argument("--table-result", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--robot-model-id", default="startouch-fasttouch-v3")
    parser.add_argument(
        "--print-calibration-id",
        action="store_true",
        help="print the camera-chain ID needed by the table solver and do not finalize",
    )
    parser.add_argument("--json", action="store_true")
    arguments = parser.parse_args()

    candidate, relative, handeye = load_camera_chain(
        arguments.candidate,
        arguments.relative_validation,
        arguments.handeye_result,
    )
    calibration_id = foundation_calibration_id(candidate, relative, handeye)
    if arguments.print_calibration_id:
        result = {
            "schema_version": 1,
            "ok": True,
            "calibration_id": calibration_id,
            "candidate_id": candidate.candidate_id,
            "relative_validation_id": relative.validation_id,
            "handeye_result_id": handeye.result_id,
        }
        print(json.dumps(result, sort_keys=True) if arguments.json else calibration_id)
        return 0
    if arguments.table_result is None or arguments.output is None:
        raise CalibrationCaptureError(
            "finalize mode requires --table-result and --output"
        )
    table = load_validated_table_result(arguments.table_result)
    camera_payload, table_payload = build_foundation_payloads(
        candidate,
        relative,
        handeye,
        table,
        robot_model_id=arguments.robot_model_id,
    )
    camera_path, table_path = write_foundation_payloads(
        arguments.output,
        camera_payload,
        table_payload,
    )
    result = {
        "schema_version": 1,
        "ok": True,
        "calibration_id": calibration_id,
        "camera_path": str(camera_path),
        "camera_content_id": camera_payload["content_id"],
        "table_path": str(table_path),
        "table_content_id": table_payload["content_id"],
    }
    if arguments.json:
        print(json.dumps(result, sort_keys=True))
    else:
        print(f"calibration_id={calibration_id}")
        print(
            f"camera={camera_path} content_id={camera_payload['content_id']}"
        )
        print(f"table={table_path} content_id={table_payload['content_id']}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (CalibrationCaptureError, OSError, TypeError, ValueError) as error:
        raise SystemExit(f"foundation finalization rejected: {error}") from error
