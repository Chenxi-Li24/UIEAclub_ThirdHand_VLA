from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from vision.geometry import make_transform
from vision_models.table_calibration import TableCalibrationSample

SCRIPT = (
    Path(__file__).parents[2]
    / "scripts"
    / "vision"
    / "calibration_completion_workflow.py"
)


def _module():
    spec = importlib.util.spec_from_file_location("calibration_completion_workflow", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _paths(module, root: Path):
    return module.CompletionPaths(
        candidate=root / "candidate.json",
        relative_validation=root / "relative.json",
        handeye_output=root / "handeye",
        handeye_result=root / "handeye-result.json",
        table_output=root / "table",
        table_result=root / "table-result.json",
        foundation_output=root / "foundation",
        target=root / "target.yaml",
    )


def _table_samples(*, x_span_m: float) -> tuple[TableCalibrationSample, ...]:
    locations = (
        (0.00, 0.00),
        (0.25 * x_span_m, 0.03),
        (0.50 * x_span_m, 0.06),
        (0.30 * x_span_m, 0.09),
        (x_span_m, 0.12),
        (0.75 * x_span_m, 0.15),
        (0.10 * x_span_m, 0.11),
        (0.20 * x_span_m, 0.07),
    )
    return tuple(
        TableCalibrationSample(
            sample_id=f"table-{index:02d}",
            split="validation" if index % 4 == 0 else "fit",
            t_base_from_flange=np.eye(4),
            t_d435_from_board=make_transform(np.eye(3), [x, y, 0.0]),
            board_reprojection_rmse_px=0.35,
        )
        for index, (x, y) in enumerate(locations, start=1)
    )


def test_workflow_phase_progression_is_artifact_driven(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    paths = _paths(module, tmp_path)
    candidate = SimpleNamespace(candidate_id="sha256:" + "1" * 64)
    relative = SimpleNamespace(validation_id="sha256:" + "2" * 64)
    handeye = SimpleNamespace(
        result_id="sha256:" + "3" * 64,
        position_rmse_m=0.002,
        position_p95_m=0.004,
        reprojection_rmse_px=0.5,
        t_flange_from_d435=np.eye(4),
    )
    monkeypatch.setattr(module, "_camera_chain", lambda _paths: (candidate, relative))

    report = module.workflow_status(paths, action="status")
    assert report["phase"] == "handeye_collect"
    assert report["progress"] == {"current": 0, "required": 15}
    assert report["safety"] == {
        "robot_state_access": "read_only_status",
        "motion_command_access": False,
        "executable": False,
    }

    (paths.handeye_output / "handeye.json").parent.mkdir(parents=True)
    (paths.handeye_output / "handeye.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        module,
        "load_handeye_dataset",
        lambda _path: (tuple(object() for _ in range(15)), "sha256:" + "4" * 64),
    )
    assert module.workflow_status(paths, action="status")["phase"] == "handeye_solve"

    paths.handeye_result.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(module, "load_validated_handeye_result", lambda _path: handeye)
    assert module.workflow_status(paths, action="status")["phase"] == "table_collect"

    (paths.table_output / "table.json").parent.mkdir(parents=True)
    (paths.table_output / "table.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        module,
        "load_table_dataset",
        lambda _path: SimpleNamespace(samples=_table_samples(x_span_m=0.14)),
    )
    assert module.workflow_status(paths, action="status")["phase"] == "finalize"

    paths.foundation_output.mkdir()
    (paths.foundation_output / "camera.json").write_text("{}", encoding="utf-8")
    (paths.foundation_output / "table.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(module, "load_active_view_foundation", lambda *_args, **_kw: object())
    monkeypatch.setattr(
        module,
        "load_validated_table_result",
        lambda _path: SimpleNamespace(
            result_id="sha256:" + "5" * 64,
            fit_rmse_m=0.002,
            validation_p95_m=0.004,
        ),
    )
    final = module.workflow_status(paths, action="status")
    assert final["phase"] == "foundation_validated"
    assert final["progress"] == {"current": 1, "required": 1}


def test_workflow_keeps_collecting_after_eight_samples_when_xy_coverage_is_short(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    paths = _paths(module, tmp_path)
    candidate = SimpleNamespace(candidate_id="sha256:" + "1" * 64)
    relative = SimpleNamespace(validation_id="sha256:" + "2" * 64)
    handeye = SimpleNamespace(
        result_id="sha256:" + "3" * 64,
        position_rmse_m=0.002,
        position_p95_m=0.004,
        reprojection_rmse_px=0.5,
        t_flange_from_d435=np.eye(4),
    )
    monkeypatch.setattr(module, "_camera_chain", lambda _paths: (candidate, relative))
    paths.handeye_result.parent.mkdir(parents=True, exist_ok=True)
    paths.handeye_result.write_text("{}", encoding="utf-8")
    paths.handeye_manifest.parent.mkdir(parents=True, exist_ok=True)
    paths.handeye_manifest.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        module,
        "load_handeye_dataset",
        lambda _path: (tuple(object() for _ in range(15)), "sha256:" + "4" * 64),
    )
    monkeypatch.setattr(module, "load_validated_handeye_result", lambda _path: handeye)
    paths.table_manifest.parent.mkdir(parents=True)
    paths.table_manifest.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        module,
        "load_table_dataset",
        lambda _path: SimpleNamespace(samples=_table_samples(x_span_m=0.064)),
    )

    report = module.workflow_status(paths, action="status")

    assert report["phase"] == "table_collect"
    assert report["progress"] == {"current": 8, "required": 9}
    assert report["metrics"]["table_coverage"] == pytest.approx(
        {"x_span_m": 0.064, "y_span_m": 0.15, "required_span_m": 0.10}
    )
    assert report["remaining_blockers"] == ["table_xy_coverage_insufficient"]


def test_capture_action_calls_read_only_handeye_boundary_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    paths = _paths(module, tmp_path)
    candidate = SimpleNamespace(candidate_id="sha256:" + "1" * 64)
    relative = SimpleNamespace(validation_id="sha256:" + "2" * 64)
    monkeypatch.setattr(module, "_camera_chain", lambda _paths: (candidate, relative))
    calls = []
    monkeypatch.setattr(module, "load_calibration_target", lambda _path: object())
    monkeypatch.setattr(module, "load_handeye_capture_input", lambda _path: object())
    monkeypatch.setattr(
        module,
        "capture_handeye_one",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    report = module.execute_action(
        "capture-handeye",
        paths,
        d435_url="http://127.0.0.1:3100/camera_d435_raw",
        robot_url="ws://127.0.0.1:3000/ws",
    )

    assert len(calls) == 1
    assert calls[0][1]["sample_id"] == "pose-01"
    assert set(calls[0][1]) == {
        "sample_id",
        "target",
        "calibration",
        "d435_url",
        "robot_url",
    }
    assert report["action"] == "capture_handeye"
    source = SCRIPT.read_text(encoding="utf-8").lower()
    for forbidden in ("move_joint", "move_l", "gripper", "startouch_sdk", "can0"):
        assert forbidden not in source
