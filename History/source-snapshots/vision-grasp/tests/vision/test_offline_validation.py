import importlib.util
from pathlib import Path


def load_validation_module():
    path = Path("scripts/vision/validate_spatial_vision_offline.py")
    spec = importlib.util.spec_from_file_location("offline_validation", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_offline_validation_covers_selection_and_failure_matrix(tmp_path: Path) -> None:
    module = load_validation_module()

    report = module.run_validation(tmp_path)

    assert report["hardware_validation"] == "pending"
    assert report["robot_control_enabled"] is False
    assert all(case["passed"] for case in report["cases"])
    assert {case["name"] for case in report["cases"]} >= {
        "one_left_1",
        "two_right_1",
        "three_left_2",
        "three_right_2",
        "four_left_2",
        "four_right_2",
        "ordinal_out_of_range",
        "horizontal_ambiguity",
        "depth_region_renumbering",
        "track_loss",
    }
    assert (tmp_path / "spatial-vision-offline.json").is_file()
    assert (tmp_path / "three-left-2-overlay.jpg").is_file()
