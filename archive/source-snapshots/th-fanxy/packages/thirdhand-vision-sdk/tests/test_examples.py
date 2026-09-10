from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).parents[1]


def run_example(name: str) -> dict:
    environment = {
        **os.environ,
        "http_proxy": "http://127.0.0.1:9",
        "https_proxy": "http://127.0.0.1:9",
        "NO_PROXY": "",
    }
    result = subprocess.run(
        [sys.executable, str(ROOT / "examples" / name)],
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_minimal_example_runs_without_model_dependencies() -> None:
    payload = run_example("minimal_mock.py")
    assert payload["instances"][0]["label"] == "bottle"
    assert payload["selected_identity_id"] is None


def test_multimodal_example_selects_existing_visual_identity() -> None:
    payload = run_example("multimodal_extension.py")
    assert payload["instances"][0]["annotations"]["query_match"] is True
    assert payload["selected_identity_id"] == payload["instances"][0]["identity_id"]
