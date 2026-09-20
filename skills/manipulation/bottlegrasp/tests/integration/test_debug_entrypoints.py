import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import cv2
import numpy as np

from thirdhand_va.common.contracts import RgbdFrame
from thirdhand_va.vision.camera.recording import write_frame_bundle


ROOT = Path(__file__).resolve().parents[2]
PYTHON = sys.executable


def load_script_module(relative_path: str, name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_vscode_exposes_all_core_modules_as_independent_debug_sessions() -> None:
    launch = json.loads((ROOT / ".vscode/launch.json").read_text(encoding="utf-8"))
    configurations = {
        item["name"]: item for item in launch["configurations"]
    }
    expected = {
        "Vision: Debug Perception",
        "Vision: Debug Stable IDs",
        "Vision: Debug Geometry",
        "Vision: Debug Pipeline",
        "Action: Debug Calibration",
        "Action: Debug Alignment",
        "Action: Debug Grasp",
        "Action: Debug Fixed Placement Plan",
        "Action: Debug Startouch Protocol (Simulated)",
        "VA: Debug Simulated Workflow",
    }

    assert expected <= configurations.keys()
    for name in expected:
        item = configurations[name]
        assert item["cwd"] == "${workspaceFolder}"
        assert item["console"] == "integratedTerminal"
        assert item["request"] == "launch"
        if item["type"] == "debugpy":
            assert item["python"] == PYTHON
            assert item["env"]["PYTHONPATH"] == "${workspaceFolder}/src"
        else:
            assert item["type"] == "node"
            assert item["runtimeExecutable"] == (
                "/usr/local/lib/nodejs/node-v24.18.0-linux-x64/bin/node"
            )


def test_primary_docs_use_stable_id_and_local_va_api_as_the_formal_interface() -> None:
    paths = (
        "README.md",
        "docs/architecture.md",
        "docs/vision/modules.md",
        "docs/action/modules.md",
        "docs/integration/contracts.md",
    )
    joined = "\n".join((ROOT / path).read_text(encoding="utf-8") for path in paths)

    assert "POST /api/va/start" in joined
    assert "thirdhand-va-detection-v3" in joined
    assert "debug_workflow.js" in joined
    assert "debug_execution_plan.js" in joined
    assert "debug_startouch_protocol.js" in joined
    assert "fixed_xy_keep_grasp_z" in joined
    assert "thirdhand-startouch-bridge-v1" in joined
    assert "--selection-side" not in joined
    assert "--ordinal" not in joined
    assert "closed_loop_pick" not in joined


def run_python(relative_path: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ROOT / relative_path), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def run_node(relative_path: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "/usr/local/lib/nodejs/node-v24.18.0-linux-x64/bin/node",
            str(ROOT / relative_path),
            *args,
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_fixed_placement_debug_is_deterministic_and_hardware_free() -> None:
    result = run_node(
        "scripts/action/debug_execution_plan.js",
        "--fixture",
        "tests/fixtures/integration/full-cycle.json",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["strategy"] == "fixed_xy_keep_grasp_z"
    assert payload["detected_grasp_point_m"] == [0.45, 0.05, 0.18]
    assert payload["commanded_flange_grasp_point_m"] == [0.4975, 0.06, 0.18]
    assert payload["waypoints"]["place_m"] == [
        0.267834822128,
        0.010668622393,
        0.18,
    ]
    assert payload["hardware_connected"] is False
    assert payload["robot_control_enabled"] is False


def test_startouch_protocol_debug_uses_only_the_simulated_bridge() -> None:
    result = run_node("scripts/action/debug_startouch_protocol.js", "--simulate")

    assert result.returncode == 0, result.stderr
    lines = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    assert lines[0]["bridge_schema"] == "thirdhand-startouch-bridge-v1"
    assert lines[0]["backend"] == "simulate"
    assert lines[-1] == {
        "cleanup_acknowledged": True,
        "depower_independently_confirmed": False,
        "hardware_connected": False,
        "ok": True,
    }


def test_target_python_debug_scripts_expose_side_effect_free_help() -> None:
    paths = (
        "scripts/vision/build_debug_fixture.py",
        "scripts/vision/camera_smoke.py",
        "scripts/vision/record_rgbd.py",
        "scripts/vision/replay_rgbd.py",
        "scripts/vision/debug_perception.py",
        "scripts/vision/debug_tracking.py",
        "scripts/vision/debug_selection.py",
        "scripts/vision/debug_geometry.py",
        "scripts/vision/debug_pipeline.py",
        "scripts/vision/debug_visualization.py",
        "scripts/action/debug_calibration.py",
    )
    for path in paths:
        result = run_python(path, "--help")
        assert result.returncode == 0, (path, result.stderr)
        assert "usage:" in result.stdout

    pipeline_help = run_python("scripts/vision/debug_pipeline.py", "--help")
    assert "--repeat-last" in pipeline_help.stdout


def test_clean_checkout_debug_fixture_runs_geometry_and_pipeline(tmp_path: Path) -> None:
    root = tmp_path / "debug-fixture"
    generated = run_python(
        "scripts/vision/build_debug_fixture.py", "--output-root", str(root)
    )
    assert generated.returncode == 0, generated.stderr
    fixture = json.loads(generated.stdout)
    bundle = fixture["bundle"]
    masks = fixture["masks"]

    geometry = run_python(
        "scripts/vision/debug_geometry.py", bundle, masks,
        "--mask-key", "mask_2",
    )
    assert geometry.returncode == 0, geometry.stderr
    assert json.loads(geometry.stdout)["robot_control_enabled"] is False

    pipeline = run_python(
        "scripts/vision/debug_pipeline.py", "--target-id", "2",
        "--synthetic-masks", masks, bundle, "--repeat-last", "6",
    )
    assert pipeline.returncode == 0, pipeline.stderr
    payload = json.loads(pipeline.stdout)
    assert payload["status"] == "ready"
    assert payload["selected_stable_id"] == 2
    assert payload["robot_control_enabled"] is False


def test_camera_smoke_is_blocked_without_explicit_hardware_permission() -> None:
    result = run_python("scripts/vision/camera_smoke.py")

    assert result.returncode == 2
    assert json.loads(result.stdout) == {
        "reasons": ["camera_access_not_authorized"],
        "robot_control_enabled": False,
        "status": "blocked",
    }


def test_camera_alignment_is_blocked_without_explicit_hardware_permission(
    tmp_path: Path,
) -> None:
    result = run_python(
        "scripts/vision/validate_camera_alignment.py",
        "--duration-s", "0.01",
        "--output", str(tmp_path / "report.json"),
    )

    assert result.returncode == 2
    assert json.loads(result.stdout) == {
        "passed": False,
        "reasons": ["camera_access_not_authorized"],
        "robot_control_enabled": False,
    }
    assert not (tmp_path / "report.json").exists()


def test_camera_alignment_cannot_pass_without_measured_target_check() -> None:
    module = load_script_module(
        "scripts/vision/validate_camera_alignment.py", "camera_alignment_validator"
    )
    report = {
        "frame_count": 30,
        "monotonic_frames": True,
        "common_rgb_depth_xyz_grid": True,
        "target_alignment_check_passed": False,
    }

    assert module.alignment_passed(report) is False
    report["target_alignment_check_passed"] = True
    assert module.alignment_passed(report) is True


def test_selection_debug_runs_from_synthetic_centers_without_models() -> None:
    result = run_python(
        "scripts/vision/debug_selection.py",
        "--centers", "30", "100", "180",
        "--side", "right",
        "--ordinal", "2",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["selected_detection_id"] == 2
    assert payload["reasons"] == []
    assert payload["robot_control_enabled"] is False


def test_visualization_debug_renders_a_recorded_bundle(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    output = tmp_path / "depth-fusion.jpg"
    rgb = np.full((72, 96, 3), 40, dtype=np.uint8)
    depth = np.full((72, 96), np.nan, dtype=np.float32)
    depth[12:64, 18:82] = np.linspace(
        0.2,
        1.0,
        64,
        dtype=np.float32,
    )
    xyz = np.full((72, 96, 3), np.nan, dtype=np.float32)
    xyz[..., 2] = depth
    write_frame_bundle(
        bundle,
        RgbdFrame(
            sequence=7,
            monotonic_ns=123_000_000,
            camera_serial="debug-camera",
            rgb=rgb,
            depth_m=depth,
            xyz_camera_m=xyz,
        ),
    )

    result = run_python(
        "scripts/vision/debug_visualization.py",
        str(bundle),
        "--output",
        str(output),
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["output"] == str(output)
    assert payload["valid_depth_pixels"] == 52 * 64
    assert payload["valid_depth_ratio"] == 52 * 64 / (72 * 96)
    assert payload["robot_control_enabled"] is False
    rendered = cv2.imread(str(output), cv2.IMREAD_COLOR)
    assert rendered is not None
    assert rendered.shape == rgb.shape


def test_geometry_debug_accepts_one_named_mask_from_an_npz_fixture(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "bundle"
    masks = tmp_path / "masks.npz"
    rgb = np.full((80, 100, 3), 80, dtype=np.uint8)
    yy, xx = np.mgrid[:80, :100]
    depth = np.full((80, 100), 0.8, dtype=np.float32)
    xyz = np.stack(
        ((xx - 50) * 0.002, (yy - 40) * 0.002, depth), axis=-1
    ).astype(np.float32)
    mask = np.zeros((80, 100), dtype=bool)
    mask[15:70, 43:57] = True
    write_frame_bundle(
        bundle,
        RgbdFrame(
            sequence=8,
            monotonic_ns=124_000_000,
            camera_serial="debug-camera",
            rgb=rgb,
            depth_m=depth,
            xyz_camera_m=xyz,
        ),
    )
    np.savez_compressed(masks, bottle=mask)

    result = run_python(
        "scripts/vision/debug_geometry.py",
        str(bundle),
        str(masks),
        "--mask-key", "bottle",
    )

    assert result.returncode != 2
    assert "unrecognized arguments" not in result.stderr
