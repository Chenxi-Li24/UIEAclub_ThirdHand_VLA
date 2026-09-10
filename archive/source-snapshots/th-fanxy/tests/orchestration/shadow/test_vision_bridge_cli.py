import json
import subprocess
import sys
from pathlib import Path

from uiea_thirdhand_vla.orchestration.runtime.models import Observation

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "orchestration" / "replay_vision_events.py"
EVENTS = (
    ROOT
    / "tests"
    / "fixtures"
    / "orchestration"
    / "vision"
    / "accepted_bottle.jsonl"
)


def test_cli_converts_checked_events_to_canonical_observations(tmp_path: Path):
    output = tmp_path / "observations.jsonl"

    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--events",
            str(EVENTS),
            "--output",
            str(output),
            "--episode-id",
            "episode-vision-cli",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {
        "actionable_count": 2,
        "first_sequence": 1,
        "last_sequence": 2,
        "observation_count": 2,
        "robot_execution_enabled": False,
    }
    observations = tuple(
        Observation.model_validate_json(line)
        for line in output.read_text(encoding="utf-8").splitlines()
    )
    assert tuple(item.sequence for item in observations) == (1, 2)
    assert all(item.objects[0].actionable for item in observations)
    assert all(item.evidence[0].evidence_id.startswith("sha256:") for item in observations)


def test_cli_rejects_symlink_output_without_touching_target(tmp_path: Path):
    target = tmp_path / "protected.jsonl"
    target.write_text("keep-me\n", encoding="utf-8")
    output = tmp_path / "linked.jsonl"
    output.symlink_to(target)

    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--events",
            str(EVENTS),
            "--output",
            str(output),
            "--episode-id",
            "episode-vision-cli",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert "symlink" in completed.stderr
    assert target.read_text(encoding="utf-8") == "keep-me\n"
