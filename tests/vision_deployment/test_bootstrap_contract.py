from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[2]
BOOTSTRAP = ROOT / "scripts/vision/bootstrap_remind3d_env.sh"
SMOKE = ROOT / "scripts/vision/smoke_remind3d_models.py"
CONFIG = ROOT / "configs/vision/remind3d.yaml"
SERVER = ROOT / "web-control/server"
sys.path.insert(0, str(ROOT / "scripts/vision"))

from smoke_remind3d_models import evaluate_smoke_limits  # noqa: E402


def test_bootstrap_print_plan_is_isolated_and_blackwell_compatible():
    result = subprocess.run(
        ["bash", str(BOOTSTRAP), "--print-plan"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    values = dict(
        line.split("=", 1)
        for line in result.stdout.splitlines()
        if "=" in line
    )
    assert values["ENV_NAME"] == "thirdhand-remind3d"
    assert values["PYTHON_VERSION"] == "3.11"
    assert values["TORCH_VERSION"] == "2.7.0"
    assert values["TORCHVISION_VERSION"] == "0.22.0"
    assert values["PIP_VERSION"] == "26.1.2"
    assert values["SETUPTOOLS_VERSION"] == "83.0.0"
    assert values["WHEEL_VERSION"] == "0.47.0"
    assert values["PYTORCH_INDEX_URL"] == "https://download.pytorch.org/whl/cu128"
    assert values["MUTATES_LUMOSTOUCH"] == "0"
    assert "LumosTouch" not in values["ENV_PREFIX"]


def test_smoke_config_check_runs_without_torch_or_mmdet():
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SERVER)
    result = subprocess.run(
        [sys.executable, str(SMOKE), "--check-config", str(CONFIG)],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload == {
        "canonical_image": "lumos_native_seucm",
        "config_valid": True,
        "detector_backend": "rtmdet_tiny_ins",
        "fallback_descriptor": "facebook/dinov2-small",
        "robot_execution_enabled": False,
    }


def test_requirements_and_runtime_artifacts_are_outside_robot_environment():
    requirements = (ROOT / "requirements/remind3d-cu128.txt").read_text(encoding="utf-8")
    assert "transformers==" in requirements
    assert "mmdet==3.3.0" in requirements
    assert "LumosTouch" not in requirements
    assert "startouch" not in requirements.lower()

    bootstrap = BOOTSTRAP.read_text(encoding="utf-8")
    assert "from mmcv.ops import nms" in bootstrap
    assert "MMCV_OP_GATE=PASS" in bootstrap


def test_smoke_limits_enforce_latency_and_reserved_gpu_memory():
    metrics = evaluate_smoke_limits(
        latencies_ms=[100.0, 120.0, 140.0],
        allocated_memory_gib=5.0,
        reserved_memory_gib=6.5,
        latency_p95_limit_ms=300.0,
        gpu_memory_limit_gib=7.2,
    )
    assert metrics["gpu_peak_allocated_gib"] == 5.0
    assert metrics["gpu_peak_reserved_gib"] == 6.5
    assert metrics["gpu_peak_gib"] == 6.5

    with pytest.raises(RuntimeError, match="latency p95"):
        evaluate_smoke_limits(
            [100.0, 400.0],
            allocated_memory_gib=5.0,
            reserved_memory_gib=6.0,
            latency_p95_limit_ms=300.0,
            gpu_memory_limit_gib=7.2,
        )
    with pytest.raises(RuntimeError, match="reserved/allocated"):
        evaluate_smoke_limits(
            [100.0, 120.0],
            allocated_memory_gib=6.0,
            reserved_memory_gib=7.5,
            latency_p95_limit_ms=300.0,
            gpu_memory_limit_gib=7.2,
        )
