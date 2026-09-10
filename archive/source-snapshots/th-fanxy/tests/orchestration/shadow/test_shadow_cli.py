import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "orchestration" / "run_startouch_shadow.py"
BUNDLE = (
    ROOT / "tests" / "fixtures" / "orchestration" / "pick_place_shadow_success.json"
)
POLICY = ROOT / "tests" / "fixtures" / "orchestration" / "startouch_preview_policy.json"
LIMITS = ROOT / "configs" / "orchestration" / "startouch_shadow.yaml"
PICK = ROOT / "configs" / "skills" / "tabletop_pick_shadow.yaml"
PLACE = ROOT / "configs" / "skills" / "tabletop_place_shadow.yaml"


def command(tmp_path: Path) -> list[str]:
    return [
        sys.executable,
        str(SCRIPT),
        "--bundle",
        str(BUNDLE),
        "--skill",
        str(PICK),
        "--skill",
        str(PLACE),
        "--limits",
        str(LIMITS),
        "--preview-policy",
        str(POLICY),
        "--preview-dir",
        str(tmp_path / "previews"),
        "--trace",
        str(tmp_path / "trace.jsonl"),
        "--metrics",
        str(tmp_path / "metrics.json"),
    ]


def test_checked_shadow_replay_writes_two_previews_and_reaches_done(tmp_path):
    completed = subprocess.run(
        command(tmp_path), cwd=ROOT, check=False, capture_output=True, text=True
    )

    assert completed.returncode == 0, completed.stderr
    summary = json.loads(completed.stdout)
    assert summary["final_state"] == "DONE"
    assert summary["preview_count"] == 2
    assert summary["robot_execution_enabled"] is False
    assert summary["can_execute_world"] is False
    previews = tuple((tmp_path / "previews").glob("*.json"))
    assert len(previews) == 2
    assert all(
        json.loads(path.read_text(encoding="utf-8"))["evidence_kind"]
        == "shadow_command_preview"
        for path in previews
    )
    events = [
        json.loads(line)
        for line in (tmp_path / "trace.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    receipt_indexes = [
        index for index, event in enumerate(events) if event["event_type"] == "command_receipt"
    ]
    post_indexes = [
        index
        for index, event in enumerate(events)
        if event["event_type"] == "observation" and event["state"] == "OBSERVE_POST"
    ]
    assert len(receipt_indexes) == len(post_indexes) == 2
    assert all(receipt < post for receipt, post in zip(receipt_indexes, post_indexes))


def test_cli_has_no_real_execution_option(tmp_path):
    completed = subprocess.run(
        [*command(tmp_path), "--execute-real"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert not (tmp_path / "previews").exists()


def test_cli_rejects_symlinked_preview_directory(tmp_path):
    target = tmp_path / "actual"
    target.mkdir()
    linked = tmp_path / "previews"
    linked.symlink_to(target, target_is_directory=True)
    args = command(tmp_path)

    completed = subprocess.run(
        args, cwd=ROOT, check=False, capture_output=True, text=True
    )

    assert completed.returncode == 2
    assert not tuple(target.iterdir())
