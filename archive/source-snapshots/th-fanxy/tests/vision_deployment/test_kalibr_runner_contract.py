from __future__ import annotations

from pathlib import Path


def test_kalibr_runner_builds_official_commands_without_shell_or_hardware_access(
    tmp_path: Path,
) -> None:
    script_path = Path(__file__).parents[2] / "scripts/vision/run_kalibr_calibration.py"
    namespace: dict[str, object] = {
        "__name__": "run_kalibr_calibration_test",
        "__file__": str(script_path),
    }
    exec(compile(script_path.read_text(encoding="utf-8"), script_path, "exec"), namespace)
    commands = namespace["build_commands"](
        tmp_path / "dataset",
        tmp_path / "target.yaml",
        tmp_path / "output",
    )

    assert commands[0][0] == "kalibr_bagcreater"
    assert commands[1][0] == "kalibr_calibrate_cameras"
    assert commands[1][commands[1].index("--topics") + 1 : commands[1].index("--models")] == [
        "/cam0/image_raw",
        "/cam1/image_raw",
    ]
    assert commands[1][commands[1].index("--models") + 1 : commands[1].index("--target")] == [
        "eucm-none",
        "pinhole-none",
    ]
    source = script_path.read_text(encoding="utf-8").lower()
    for forbidden in ("shell=true", "startouch", "pyrealsense2", "move_joint", "move_l"):
        assert forbidden not in source


def test_kalibr_runner_rejects_validation_dataset_as_fit_input(tmp_path: Path) -> None:
    script_path = Path(__file__).parents[2] / "scripts/vision/run_kalibr_calibration.py"
    namespace: dict[str, object] = {
        "__name__": "run_kalibr_calibration_test",
        "__file__": str(script_path),
    }
    exec(compile(script_path.read_text(encoding="utf-8"), script_path, "exec"), namespace)
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    (dataset / "manifest.json").write_text(
        '{"kalibr_topics":["/cam0/image_raw","/cam1/image_raw"],'
        '"kalibr_models":["eucm-none","pinhole-none"],'
        '"purpose":"validation","records":['
        + ",".join('{"capture_skew_ns":1}' for _ in range(20))
        + "]}",
        encoding="utf-8",
    )
    target = tmp_path / "target.yaml"
    target.write_text("target_type: aprilgrid\n", encoding="utf-8")

    try:
        namespace["_validate_capture"](dataset, target)
    except ValueError as error:
        assert "fit" in str(error)
    else:
        raise AssertionError("validation dataset was accepted for fitting")
