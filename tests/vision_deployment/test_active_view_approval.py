from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "scripts/vision/create_active_view_approval.py"
EVIDENCE = "sha256:" + "a" * 64


def load_creator():
    spec = importlib.util.spec_from_file_location("active_view_approval_creator", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def limits() -> dict[str, object]:
    return {
        "max_speed_scale": 0.05,
        "max_translation_m": 0.020,
        "max_rotation_rad": 5 * 3.141592653589793 / 180,
        "max_refinement_steps": 3,
        "require_step_confirmation": True,
    }


def test_approval_is_atomic_content_addressed_and_short_lived(tmp_path: Path) -> None:
    output = tmp_path / "approval.json"
    approval = load_creator().create_approval(
        output_path=output,
        evidence_ids=[EVIDENCE],
        robot_model_id="startouch-fasttouch-v3",
        limits=limits(),
        issued_at_ms=1_000,
        expires_at_ms=2_000,
        operator_acknowledged=True,
    )

    assert output.exists()
    assert not output.with_suffix(".json.tmp").exists()
    assert approval["operator_acknowledged"] is True
    assert approval["evidence_ids"] == [EVIDENCE]
    assert approval["content_id"].startswith("sha256:")
    assert json.loads(output.read_text(encoding="utf-8")) == approval
    assert output.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"operator_acknowledged": False}, "acknowledgement"),
        ({"expires_at_ms": 1_000 + 8 * 60 * 60 * 1000 + 1}, "8 hours"),
        ({"expires_at_ms": 1_000}, "after"),
        ({"evidence_ids": ["not-a-hash"]}, "evidence"),
        ({"robot_model_id": ""}, "robot model"),
        ({"limits": {**limits(), "max_speed_scale": 0.051}}, "speed"),
        ({"limits": {**limits(), "max_translation_m": 0.021}}, "translation"),
        ({"limits": {**limits(), "max_refinement_steps": 4}}, "refinement"),
        ({"limits": {**limits(), "require_step_confirmation": False}}, "confirmation"),
    ],
)
def test_approval_rejects_unsafe_or_unacknowledged_content(
    tmp_path: Path,
    changes: dict[str, object],
    message: str,
) -> None:
    arguments: dict[str, object] = {
        "output_path": tmp_path / "approval.json",
        "evidence_ids": [EVIDENCE],
        "robot_model_id": "startouch-fasttouch-v3",
        "limits": limits(),
        "issued_at_ms": 1_000,
        "expires_at_ms": 2_000,
        "operator_acknowledged": True,
    }
    arguments.update(changes)
    with pytest.raises(ValueError, match=message):
        load_creator().create_approval(**arguments)


def test_cli_requires_explicit_operator_acknowledgement(tmp_path: Path) -> None:
    creator = load_creator()
    with pytest.raises(SystemExit, match="acknowledgement"):
        creator.main(
            [
                "--output", str(tmp_path / "approval.json"),
                "--evidence-id", EVIDENCE,
                "--robot-model-id", "startouch-fasttouch-v3",
                "--expires-in-seconds", "60",
            ]
        )
