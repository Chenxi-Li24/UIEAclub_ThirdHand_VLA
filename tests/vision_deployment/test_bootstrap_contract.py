from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from packaging.requirements import Requirement

ROOT = Path(__file__).parents[2]
BOOTSTRAP = ROOT / "scripts/vision/bootstrap_remind3d_env.sh"
SMOKE = ROOT / "scripts/vision/smoke_remind3d_models.py"
CONFIG = ROOT / "configs/vision/remind3d.yaml"
SERVER = ROOT / "web-control/server"
sys.path.insert(0, str(ROOT / "scripts/vision"))

from smoke_remind3d_models import _cuda_device_index, evaluate_smoke_limits  # noqa: E402


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
    assert values["TORCH_VERSION"] == "2.7.0+cu128"
    assert values["TORCHVISION_VERSION"] == "0.22.0+cu128"
    assert values["CUDA_BUILD_VERSION"] == "12.8"
    assert values["PIP_VERSION"] == "26.1.2"
    assert values["SETUPTOOLS_VERSION"] == "81.0.0"
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
    parsed = {
        item.name: item
        for item in (
            Requirement(line)
            for line in requirements.splitlines()
            if line and not line.startswith("#")
        )
    }
    assert str(parsed["pyrealsense2"].specifier) == "==2.57.7.10387"

    bootstrap = BOOTSTRAP.read_text(encoding="utf-8")
    assert "/home/" not in bootstrap
    assert "from mmcv.ops import nms" in bootstrap
    assert "MMCV_OP_GATE=PASS" in bootstrap
    assert "PYTHON_PRE_GATE=PASS" in bootstrap
    assert "PYTHON_POST_GATE=PASS" in bootstrap
    assert "MMCV_WITH_OPS=1" in bootstrap
    assert "--no-build-isolation" in bootstrap
    assert "CUDA_HOME" in bootstrap
    assert "EXPECTED_TORCH_VERSION" in bootstrap
    assert "EXPECTED_TORCHVISION_VERSION" in bootstrap
    assert "EXPECTED_CUDA_BUILD" in bootstrap
    assert 'torch.version.cuda == os.environ["EXPECTED_CUDA_BUILD"]' in bootstrap
    assert "import pyrealsense2" in bootstrap


def test_bootstrap_rebuilds_mmcv_from_source_after_cuda_op_gate_failure(tmp_path):
    conda_root = tmp_path / "conda"
    conda_exe = conda_root / "bin/conda"
    env_python = conda_root / "envs/thirdhand-remind3d/bin/python"
    cuda_home = tmp_path / "cuda"
    nvcc = cuda_home / "bin/nvcc"
    log_path = tmp_path / "conda.log"
    state_path = tmp_path / "mmcv-gate-attempts"
    conda_exe.parent.mkdir(parents=True)
    env_python.parent.mkdir(parents=True)
    nvcc.parent.mkdir(parents=True)
    env_python.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    nvcc.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    conda_exe.write_text(
        """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$FAKE_CONDA_LOG"
if [[ "$*" == *"MMCV_OP_GATE=PASS"* ]]; then
  attempts=0
  [[ -f "$FAKE_MMCV_STATE" ]] && attempts=$(cat "$FAKE_MMCV_STATE")
  attempts=$((attempts + 1))
  printf '%s' "$attempts" > "$FAKE_MMCV_STATE"
  if [[ "$attempts" -eq 1 ]]; then
    exit 1
  fi
  printf 'MMCV_OP_GATE=PASS\\n'
fi
exit 0
""",
        encoding="utf-8",
    )
    for executable in (conda_exe, env_python, nvcc):
        executable.chmod(0o755)
    environment = os.environ.copy()
    environment.update(
        {
            "CONDA_ROOT": str(conda_root),
            "CONDA_EXE": str(conda_exe),
            "CUDA_HOME": str(cuda_home),
            "FAKE_CONDA_LOG": str(log_path),
            "FAKE_MMCV_STATE": str(state_path),
        }
    )

    result = subprocess.run(
        ["bash", str(BOOTSTRAP), "--install"],
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    log = log_path.read_text(encoding="utf-8")
    assert log.count("MMCV_OP_GATE=PASS") == 2
    assert "--force-reinstall --no-cache-dir --no-binary=mmcv --no-deps mmcv==2.1.0" in log


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


@pytest.mark.parametrize(
    "value,expected",
    [("cuda", 0), ("cuda:0", 0), ("cuda:2", 2)],
)
def test_smoke_cuda_device_parser_uses_one_explicit_cuda_device(value, expected):
    assert _cuda_device_index(value) == expected


@pytest.mark.parametrize("value", ["cpu", "cuda:-1", "cuda:x", "cuda:1:2", "mps"])
def test_smoke_cuda_device_parser_rejects_non_cuda_or_malformed_devices(value):
    with pytest.raises(RuntimeError, match="CUDA device"):
        _cuda_device_index(value)
