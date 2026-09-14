import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "orchestration" / "run_benchmark.py"
MANIFEST = ROOT / "configs" / "orchestration" / "benchmark_v1.yaml"
SKILLS = (
    ROOT / "configs" / "skills" / "tabletop_pick.yaml",
    ROOT / "configs" / "skills" / "tabletop_place.yaml",
)
BASELINES = ("receipt_only", "rule_only", "post_action", "always_model", "hybrid")


def command(output: Path) -> list[str]:
    args = [
        sys.executable,
        str(SCRIPT),
        "--manifest",
        str(MANIFEST),
        "--skills",
        *(str(path) for path in SKILLS),
        "--output-dir",
        str(output),
    ]
    for baseline in BASELINES:
        args.extend(("--baseline", baseline))
    return args


def run(output: Path):
    return subprocess.run(
        command(output), cwd=ROOT, check=False, capture_output=True, text=True
    )


def files(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_cli_runs_fifty_cases_and_is_byte_repeatable(tmp_path):
    first = run(tmp_path / "first")
    second = run(tmp_path / "second")

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    summary = json.loads(first.stdout)
    assert summary == {
        "baseline_count": 5,
        "can_execute_world": False,
        "hybrid_false_advance_count": 0,
        "robot_execution_enabled": False,
        "run_count": 50,
        "scenario_count": 10,
    }
    assert files(tmp_path / "first") == files(tmp_path / "second")


def test_cli_writes_per_run_traces_and_exposes_reference_counterexamples(tmp_path):
    completed = run(tmp_path / "output")

    assert completed.returncode == 0, completed.stderr
    traces = tuple((tmp_path / "output" / "traces").glob("*.jsonl"))
    assert len(traces) == 50
    payload = json.loads(
        (tmp_path / "output" / "metrics.json").read_text(encoding="utf-8")
    )
    summaries = {item["baseline"]: item for item in payload["summaries"]}
    assert summaries["hybrid"]["false_advance_count"] == 0
    assert summaries["receipt_only"]["false_effect_advance_count"] > 0
    assert summaries["post_action"]["false_handoff_advance_count"] > 0
    assert "handoff_fail" in (
        tmp_path / "output" / "failure-gallery.md"
    ).read_text(encoding="utf-8")


def test_cli_rejects_duplicate_baselines_without_outputs(tmp_path):
    args = command(tmp_path / "output")
    args.extend(("--baseline", "hybrid"))

    completed = subprocess.run(
        args, cwd=ROOT, check=False, capture_output=True, text=True
    )

    assert completed.returncode == 2
    assert not (tmp_path / "output").exists()
