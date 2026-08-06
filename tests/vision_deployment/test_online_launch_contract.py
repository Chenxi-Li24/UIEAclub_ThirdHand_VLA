from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[2]
LAUNCHER = ROOT / "scripts/vision/start_dual_camera_online.sh"
VERIFIER = ROOT / "scripts/vision/verify_dual_camera_online.py"


def load_verifier():
    spec = importlib.util.spec_from_file_location("dual_camera_verifier", VERIFIER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def healthy_status(lumos=10, d435=20):
    return {
        "online": True,
        "modelReady": True,
        "d435Ready": True,
        "lumosReady": True,
        "stale": False,
        "robotExecutionEnabled": False,
        "roles": {
            "canonicalRgb": "lumos_rgb",
            "metricDepth": "d435_depth",
            "debugRgb": "d435_rgb",
        },
        "sequences": {"lumos": lumos, "d435": d435},
        "metrics": {
            "latencyMs": 100.0,
            "latencyP95Ms": 180.0,
            "gpuMemoryReservedGib": 5.5,
        },
        "blockers": ["calibration_unavailable", "task_checkpoint_unvalidated"],
        "taskCheckpointValidated": False,
        "sourceAgeMs": 50,
        "targets": [],
        "error": None,
    }


def test_launcher_is_fixed_to_simulation_placeholder_can_online_models_and_port_3100():
    source = LAUNCHER.read_text(encoding="utf-8")

    assert "STARTOUCH_SIMULATE=1" in source
    assert "STARTOUCH_CAN_INTERFACE=thirdhand-vision-test" in source
    assert "STARTOUCH_GRIPPER=0" in source
    assert "VISION_ONLINE_ENABLED=1" in source
    assert "WEB_HOST=0.0.0.0" in source
    assert "WEB_PORT=3100" in source
    assert "systemd-run --user" in source
    assert "thirdhand-dual-camera-online" in source
    assert "D435_RGBD_PREFLIGHT=PASS" in source
    assert "pkill" not in source
    assert "killall" not in source
    assert "fuser -k" not in source


def test_launcher_status_is_non_destructive_when_no_owned_process_exists(tmp_path):
    result = subprocess.run(
        ["bash", str(LAUNCHER), "--status"],
        cwd=ROOT,
        env={"PATH": "/usr/bin:/bin", "VISION_RUNTIME_DIR": str(tmp_path)},
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )

    assert result.returncode == 1
    assert "stopped" in result.stdout.lower()
    assert list(tmp_path.iterdir()) == []


def test_verifier_accepts_expected_nonactionability_blockers_and_advancing_sources():
    verifier = load_verifier()
    statuses = [healthy_status(10, 20), healthy_status(11, 22), healthy_status(12, 24)]

    report = verifier.evaluate_samples(statuses, base_url="http://127.0.0.1:3100")

    assert report["passed"] is True
    assert report["errors"] == []
    assert report["sequence_advancement"] == {"lumos": 2, "d435": 4}
    assert report["blocker_histogram"] == {
        "calibration_unavailable": 3,
        "task_checkpoint_unvalidated": 3,
    }
    assert report["robot_execution_enabled"] is False


def test_verifier_rejects_stale_wrong_roles_execution_model_and_budget_failures():
    verifier = load_verifier()
    status = healthy_status()
    status.update(stale=True, robotExecutionEnabled=True, modelReady=False, online=False)
    status["roles"] = {"canonicalRgb": "d435_rgb", "metricDepth": "lumos_depth"}
    status["metrics"] = {
        "latencyMs": 400.0,
        "latencyP95Ms": 401.0,
        "gpuMemoryReservedGib": 8.0,
    }
    status["blockers"] = ["model_unavailable", "vision_status_stale"]

    report = verifier.evaluate_samples([status, status], "http://127.0.0.1:3100")

    assert report["passed"] is False
    joined = "\n".join(report["errors"])
    for expected in (
        "online",
        "model",
        "stale",
        "roles",
        "execution",
        "latency",
        "GPU",
        "advance",
    ):
        assert expected.lower() in joined.lower()


def test_verifier_rejects_nonadvancing_sequences_even_when_each_sample_is_healthy():
    verifier = load_verifier()

    report = verifier.evaluate_samples(
        [healthy_status(10, 20), healthy_status(10, 20)],
        "http://127.0.0.1:3100",
    )

    assert report["passed"] is False
    assert any("advance" in error for error in report["errors"])


def test_verifier_writes_json_atomically_without_numpy_or_nan(tmp_path):
    verifier = load_verifier()
    destination = tmp_path / "readiness.json"
    report = verifier.evaluate_samples(
        [healthy_status(10, 20), healthy_status(11, 21)],
        "http://127.0.0.1:3100",
    )

    verifier.write_json_atomic(destination, report)

    assert json.loads(destination.read_text(encoding="utf-8"))["passed"] is True
    assert not destination.with_suffix(".json.tmp").exists()
