from pathlib import Path

from tools.assets.build_startouch_python import stage_runtime


def write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_stage_runtime_preserves_sdk_resource_layout(tmp_path: Path) -> None:
    source = tmp_path / "source"
    extension = source / "interface_py" / "startouch.cpython-test.so"
    write_file(extension, "extension")
    write_file(source / "interface_py/startouchclass.py", "wrapper")
    write_file(source / "src/libstartouch.so", "library")
    write_file(
        source / "src/config/robot_kinematics.yaml",
        "kinematics: test",
    )
    write_file(source / "src/config/robot.urdf", "<robot/>")
    write_file(
        source / "src/param_csv_gripper/permutationMatrix.csv",
        "1,0",
    )

    staged = tmp_path / "runtime"
    staged_extension = stage_runtime(source, extension, staged)

    assert staged_extension == (
        staged / "startouch_sdk/interface_py/startouch.cpython-test.so"
    )
    sdk_root = staged / "startouch_sdk"
    assert (sdk_root / "interface_py/startouchclass.py").is_file()
    assert (sdk_root / "interface_py/libstartouch.so").is_file()
    assert (sdk_root / "src/config/robot_kinematics.yaml").is_file()
    assert (sdk_root / "src/config/robot.urdf").is_file()
    assert (sdk_root / "param_csv_gripper/permutationMatrix.csv").is_file()
