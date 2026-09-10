#!/usr/bin/env python3
"""Run the read-only hand-eye and table calibration completion workflow."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_ROOT = Path(__file__).resolve().parent
SERVER_ROOT = Path(__file__).resolve().parents[2] / "web-control" / "server"
for import_root in (SCRIPT_ROOT, SERVER_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from capture_handeye_sample import capture_one as capture_handeye_one  # noqa: E402
from capture_table_sample import capture_one as capture_table_one  # noqa: E402
from capture_table_sample import load_target as load_table_target  # noqa: E402
from solve_handeye_dataset import solve_manifest as solve_handeye_manifest  # noqa: E402
from solve_table_dataset import solve_manifest as solve_table_manifest  # noqa: E402
from vision_models.active_view_catalog import (  # noqa: E402
    load_active_view_foundation,
)
from vision_models.calibration_capture import (  # noqa: E402
    CalibrationCaptureError,
    load_calibration_target,
)
from vision_models.calibration_completion import (  # noqa: E402
    load_handeye_capture_input,
    load_validated_handeye_result,
)
from vision_models.calibration_pipeline import load_handeye_dataset  # noqa: E402
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
from vision_models.table_calibration import (  # noqa: E402
    TABLE_MAX_SAMPLES,
    TABLE_REQUIRED_SAMPLES,
    load_table_dataset,
    measure_table_fit_coverage,
)


class CompletionPaths:
    """Immutable filesystem locations owned by this workflow."""

    def __init__(
        self,
        *,
        candidate: Path | str,
        relative_validation: Path | str,
        handeye_output: Path | str,
        handeye_result: Path | str,
        table_output: Path | str,
        table_result: Path | str,
        foundation_output: Path | str,
        target: Path | str,
    ) -> None:
        for name, value in {
            "candidate": candidate,
            "relative_validation": relative_validation,
            "handeye_output": handeye_output,
            "handeye_result": handeye_result,
            "table_output": table_output,
            "table_result": table_result,
            "foundation_output": foundation_output,
            "target": target,
        }.items():
            path = Path(value)
            if not path.is_absolute():
                raise CalibrationCaptureError(f"{name} path must be absolute")
            setattr(self, name, path)

    @property
    def handeye_manifest(self) -> Path:
        return self.handeye_output / "handeye.json"

    @property
    def table_manifest(self) -> Path:
        return self.table_output / "table.json"

    @property
    def foundation_camera(self) -> Path:
        return self.foundation_output / "camera.json"

    @property
    def foundation_table(self) -> Path:
        return self.foundation_output / "table.json"


def _camera_chain(paths: CompletionPaths):
    candidate = load_dual_camera_candidate(paths.candidate)
    relative = load_relative_validation_evidence(
        paths.relative_validation,
        candidate,
    )
    return candidate, relative


def _handeye_samples(paths: CompletionPaths):
    if not paths.handeye_manifest.exists():
        return ()
    samples, _dataset_id = load_handeye_dataset(paths.handeye_manifest)
    return samples


def _table_samples(paths: CompletionPaths):
    if not paths.table_manifest.exists():
        return ()
    return load_table_dataset(paths.table_manifest).samples


def _latest_sample(path: Path, expected: int) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        samples = payload["samples"]
        if not isinstance(samples, list) or len(samples) > expected or not samples:
            return None
        item = samples[-1]
        return {
            "id": item["sample_id"],
            "split": item["split"],
            "detected_points": item["detected_points"],
            "reprojection_rmse_px": item["board_reprojection_rmse_px"],
        }
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError):
        return None


def _report(
    *,
    action: str,
    phase: str,
    current: int,
    required: int,
    candidate_id: str,
    relative_id: str,
    sample: dict[str, Any] | None,
    handeye=None,
    table=None,
    table_coverage=None,
    blockers_override: list[str] | None = None,
) -> dict[str, Any]:
    blockers = blockers_override or {
        "handeye_collect": ["handeye_samples_missing", "table_validation_missing"],
        "handeye_solve": ["handeye_validation_missing", "table_validation_missing"],
        "table_collect": ["table_samples_missing"],
        "finalize": ["table_validation_missing", "foundation_not_finalized"],
        "foundation_validated": [],
    }[phase]
    metrics = {
        "relative": {
            "validated": True,
        },
        "handeye": None
        if handeye is None
        else {
            "position_rmse_m": handeye.position_rmse_m,
            "position_p95_m": handeye.position_p95_m,
            "reprojection_rmse_px": handeye.reprojection_rmse_px,
        },
        "table": None
        if table is None
        else {
            "fit_rmse_m": table.fit_rmse_m,
            "validation_p95_m": table.validation_p95_m,
        },
        "table_coverage": None
        if table_coverage is None
        else {
            "x_span_m": table_coverage.x_span_m,
            "y_span_m": table_coverage.y_span_m,
            "required_span_m": table_coverage.required_span_m,
        },
    }
    return {
        "schema_version": 1,
        "ok": True,
        "action": action,
        "phase": phase,
        "progress": {"current": current, "required": required},
        "sample": sample,
        "metrics": metrics,
        "remaining_blockers": blockers,
        "source_ids": {
            "candidate": candidate_id,
            "relative_validation": relative_id,
            "handeye": None if handeye is None else handeye.result_id,
            "table": None if table is None else table.result_id,
        },
        "safety": {
            "robot_state_access": "read_only_status",
            "motion_command_access": False,
            "executable": False,
        },
    }


def workflow_status(paths: CompletionPaths, *, action: str) -> dict[str, Any]:
    """Resolve the current phase from strict, content-addressed disk artifacts."""

    candidate, relative = _camera_chain(paths)
    if paths.foundation_camera.exists() or paths.foundation_table.exists():
        if not paths.foundation_camera.exists() or not paths.foundation_table.exists():
            raise CalibrationCaptureError("foundation output is incomplete")
        load_active_view_foundation(
            paths.foundation_camera,
            paths.foundation_table,
            evidence_dir=paths.foundation_output,
        )
        return _report(
            action=action,
            phase="foundation_validated",
            current=1,
            required=1,
            candidate_id=candidate.candidate_id,
            relative_id=relative.validation_id,
            sample=None,
            handeye=load_validated_handeye_result(paths.handeye_result),
            table=load_validated_table_result(paths.table_result),
        )

    handeye_samples = _handeye_samples(paths)
    if len(handeye_samples) > 15:
        raise CalibrationCaptureError("hand-eye dataset exceeds 15 samples")
    if len(handeye_samples) < 15:
        return _report(
            action=action,
            phase="handeye_collect",
            current=len(handeye_samples),
            required=15,
            candidate_id=candidate.candidate_id,
            relative_id=relative.validation_id,
            sample=_latest_sample(paths.handeye_manifest, 15),
        )
    try:
        handeye = load_validated_handeye_result(paths.handeye_result)
    except (CalibrationCaptureError, OSError, ValueError):
        return _report(
            action=action,
            phase="handeye_solve",
            current=15,
            required=15,
            candidate_id=candidate.candidate_id,
            relative_id=relative.validation_id,
            sample=_latest_sample(paths.handeye_manifest, 15),
        )

    table_samples = _table_samples(paths)
    if len(table_samples) > TABLE_MAX_SAMPLES:
        raise CalibrationCaptureError("table dataset exceeds supplemental sample limit")
    table_coverage = None
    if table_samples:
        table_coverage = measure_table_fit_coverage(
            table_samples,
            t_flange_from_d435=handeye.t_flange_from_d435,
        )
    if len(table_samples) < TABLE_REQUIRED_SAMPLES:
        return _report(
            action=action,
            phase="table_collect",
            current=len(table_samples),
            required=TABLE_REQUIRED_SAMPLES,
            candidate_id=candidate.candidate_id,
            relative_id=relative.validation_id,
            sample=_latest_sample(paths.table_manifest, TABLE_MAX_SAMPLES),
            handeye=handeye,
            table_coverage=table_coverage,
        )
    if table_coverage is not None and not table_coverage.sufficient:
        if len(table_samples) >= TABLE_MAX_SAMPLES:
            raise CalibrationCaptureError(
                "table fit samples lack XY coverage after supplemental samples"
            )
        return _report(
            action=action,
            phase="table_collect",
            current=len(table_samples),
            required=len(table_samples) + 1,
            candidate_id=candidate.candidate_id,
            relative_id=relative.validation_id,
            sample=_latest_sample(paths.table_manifest, TABLE_MAX_SAMPLES),
            handeye=handeye,
            table_coverage=table_coverage,
            blockers_override=["table_xy_coverage_insufficient"],
        )
    table = None
    try:
        table = load_validated_table_result(paths.table_result)
    except (CalibrationCaptureError, OSError, ValueError):
        pass
    return _report(
        action=action,
        phase="finalize",
        current=len(table_samples),
        required=len(table_samples),
        candidate_id=candidate.candidate_id,
        relative_id=relative.validation_id,
        sample=_latest_sample(paths.table_manifest, TABLE_MAX_SAMPLES),
        handeye=handeye,
        table=table,
        table_coverage=table_coverage,
    )


def execute_action(
    action: str,
    paths: CompletionPaths,
    *,
    d435_url: str,
    robot_url: str,
) -> dict[str, Any]:
    current = workflow_status(paths, action="status")
    if action == "status":
        return current
    if action == "capture-handeye":
        if current["phase"] != "handeye_collect":
            raise CalibrationCaptureError("hand-eye capture is not available in this phase")
        capture_handeye_one(
            paths.handeye_output,
            sample_id=f"pose-{current['progress']['current'] + 1:02d}",
            target=load_calibration_target(paths.target),
            calibration=load_handeye_capture_input(paths.candidate),
            d435_url=d435_url,
            robot_url=robot_url,
        )
    elif action == "solve-handeye":
        if current["phase"] != "handeye_solve":
            raise CalibrationCaptureError("hand-eye solve is not available in this phase")
        solved = solve_handeye_manifest(paths.handeye_manifest, paths.handeye_result)
        if solved["validated"] is not True:
            raise CalibrationCaptureError(
                "hand-eye solve failed: " + ",".join(solved["reasons"])
            )
    elif action == "capture-table":
        if current["phase"] != "table_collect":
            raise CalibrationCaptureError("table capture is not available in this phase")
        handeye = load_validated_handeye_result(paths.handeye_result)
        capture_table_one(
            paths.table_output,
            sample_id=f"table-{current['progress']['current'] + 1:02d}",
            target=load_table_target(paths.target),
            calibration=load_handeye_capture_input(paths.candidate),
            handeye_result_id=handeye.result_id,
            d435_url=d435_url,
            robot_url=robot_url,
        )
    elif action == "finalize":
        if current["phase"] != "finalize":
            raise CalibrationCaptureError("foundation finalization is not available")
        candidate, relative = _camera_chain(paths)
        handeye = load_validated_handeye_result(paths.handeye_result)
        calibration_id = foundation_calibration_id(candidate, relative, handeye)
        solved = solve_table_manifest(
            paths.table_manifest,
            paths.handeye_result,
            paths.table_result,
            calibration_id,
        )
        if solved["validated"] is not True:
            raise CalibrationCaptureError(
                "table solve failed: " + ",".join(solved["reasons"])
            )
        table = load_validated_table_result(paths.table_result)
        camera_payload, table_payload = build_foundation_payloads(
            candidate,
            relative,
            handeye,
            table,
        )
        write_foundation_payloads(
            paths.foundation_output,
            camera_payload,
            table_payload,
        )
    else:
        raise CalibrationCaptureError("unknown completion action")
    return workflow_status(paths, action=action.replace("-", "_"))


def classify_error(error: BaseException) -> str:
    message = str(error).lower()
    if "table" in message and "coverage" in message:
        return "table_coverage_insufficient"
    if "distinct" in message or "different" in message:
        return "pose_not_distinct"
    if "not available" in message or "unknown" in message:
        return "action_not_available"
    if "hand-eye" in message and "solve" in message:
        return "handeye_solve_failed"
    if "table" in message and "solve" in message:
        return "table_solve_failed"
    if "15 samples" in message or "hand-eye dataset" in message:
        return "handeye_not_ready"
    if "eight samples" in message or "table dataset" in message:
        return "table_not_ready"
    if "moving" in message or "stable" in message or "velocity" in message:
        return "robot_state_unstable"
    if "target" in message or "charuco" in message:
        return "target_not_visible"
    if "camera" in message or "request failed" in message or "timed out" in message:
        return "camera_unavailable"
    if "changed" in message or "integrity" in message or "source" in message:
        return "source_changed"
    return "capture_rejected"


def _paths_from_arguments(arguments: argparse.Namespace) -> CompletionPaths:
    return CompletionPaths(
        candidate=arguments.candidate,
        relative_validation=arguments.relative_validation,
        handeye_output=arguments.handeye_output,
        handeye_result=arguments.handeye_result,
        table_output=arguments.table_output,
        table_result=arguments.table_result,
        foundation_output=arguments.foundation_output,
        target=arguments.target,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--action",
        required=True,
        choices=("status", "capture-handeye", "solve-handeye", "capture-table", "finalize"),
    )
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--relative-validation", required=True, type=Path)
    parser.add_argument("--handeye-output", required=True, type=Path)
    parser.add_argument("--handeye-result", required=True, type=Path)
    parser.add_argument("--table-output", required=True, type=Path)
    parser.add_argument("--table-result", required=True, type=Path)
    parser.add_argument("--foundation-output", required=True, type=Path)
    parser.add_argument("--target", required=True, type=Path)
    parser.add_argument("--d435-url", required=True)
    parser.add_argument("--robot-url", required=True)
    parser.add_argument("--json", action="store_true")
    arguments = parser.parse_args()
    try:
        report = execute_action(
            arguments.action,
            _paths_from_arguments(arguments),
            d435_url=arguments.d435_url,
            robot_url=arguments.robot_url,
        )
    except (CalibrationCaptureError, OSError, TypeError, ValueError) as error:
        code = classify_error(error)
        payload = {
            "schema_version": 1,
            "ok": False,
            "error": {"code": code, "message": str(error)[:240]},
        }
        output = (
            json.dumps(payload, sort_keys=True)
            if arguments.json
            else payload["error"]["message"]
        )
        print(output)
        return 2
    print(json.dumps(report, sort_keys=True) if arguments.json else report["phase"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
