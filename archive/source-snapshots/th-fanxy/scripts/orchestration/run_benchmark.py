#!/usr/bin/env python3
"""Run the deterministic ten-scenario orchestration shadow benchmark."""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

from pydantic import ValidationError

from uiea_thirdhand_vla.orchestration.benchmark.baselines import BaselineKind
from uiea_thirdhand_vla.orchestration.benchmark.evaluator import BenchmarkEvaluator
from uiea_thirdhand_vla.orchestration.benchmark.metrics import (
    aggregate_metrics,
    compute_run_metrics,
)
from uiea_thirdhand_vla.orchestration.benchmark.models import load_manifest
from uiea_thirdhand_vla.orchestration.benchmark.report import ReportWriter
from uiea_thirdhand_vla.orchestration.runtime.trace import canonical_json, content_id


def local_file(value: str) -> Path:
    path = Path(value).expanduser()
    if path.is_symlink() or not path.is_file():
        raise argparse.ArgumentTypeError(f"not a non-symlink local file: {path}")
    return path


def output_directory(value: str) -> Path:
    path = Path(value).expanduser()
    if path.is_symlink() or (path.exists() and not path.is_dir()):
        raise argparse.ArgumentTypeError(f"output is not a non-symlink directory: {path}")
    return path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=local_file, required=True)
    parser.add_argument("--skills", type=local_file, nargs="+", required=True)
    parser.add_argument("--output-dir", type=output_directory, required=True)
    parser.add_argument(
        "--baseline",
        choices=tuple(item.value for item in BaselineKind),
        action="append",
        required=True,
    )
    args = parser.parse_args(argv)
    if len(args.baseline) != len(set(args.baseline)):
        parser.error("baseline selections must be unique")
    return args


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _source_revision(root: Path) -> str:
    dot_git = root / ".git"
    try:
        if dot_git.is_file():
            line = dot_git.read_text(encoding="utf-8").strip()
            if not line.startswith("gitdir: "):
                return "unresolved"
            git_dir = Path(line.removeprefix("gitdir: "))
            if not git_dir.is_absolute():
                git_dir = (root / git_dir).resolve()
        else:
            git_dir = dot_git
        head = (git_dir / "HEAD").read_text(encoding="utf-8").strip()
        if not head.startswith("ref: "):
            return head if len(head) == 40 else "unresolved"
        reference = head.removeprefix("ref: ")
        direct = git_dir / reference
        if direct.is_file():
            return direct.read_text(encoding="utf-8").strip()
        common_file = git_dir / "commondir"
        if common_file.is_file():
            common = (git_dir / common_file.read_text(encoding="utf-8").strip()).resolve()
            shared = common / reference
            if shared.is_file():
                return shared.read_text(encoding="utf-8").strip()
    except OSError:
        return "unresolved"
    return "unresolved"


def run(args: argparse.Namespace) -> dict:
    manifest = load_manifest(args.manifest)
    baselines = tuple(BaselineKind(value) for value in args.baseline)
    evaluator = BenchmarkEvaluator.from_skill_paths(tuple(args.skills))
    runs = tuple(
        evaluator.run(case, baseline)
        for case in manifest.cases
        for baseline in baselines
    )
    root = Path(__file__).resolve().parents[2]
    provenance = {
        "source_revision": _source_revision(root),
        "manifest_id": _sha256(args.manifest),
        "skill_ids": {
            path.name: _sha256(path) for path in sorted(args.skills, key=lambda item: item.name)
        },
        "fixture_ids": {
            entry.scenario_id: entry.content_id for entry in manifest.entries
        },
        "prompt_bundle_id": content_id(()),
        "model_access": "disabled-scripted-accounting-only",
    }
    ReportWriter().write(args.output_dir, runs, provenance=provenance)
    traces = args.output_dir / "traces"
    traces.mkdir(parents=True, exist_ok=True)
    for item in sorted(runs, key=lambda run: (run.scenario_id, run.baseline.value)):
        records = item.events if item.events else item.decisions
        text = "".join(canonical_json(record) + "\n" for record in records)
        name = f"{item.scenario_id}__{item.baseline.value}.jsonl"
        (traces / name).write_text(text, encoding="utf-8", newline="\n")

    metrics = tuple(compute_run_metrics(None, item) for item in runs)
    summaries = aggregate_metrics(metrics)
    hybrid = next(
        (item for item in summaries if item.baseline is BaselineKind.HYBRID), None
    )
    return {
        "run_count": len(runs),
        "scenario_count": len(manifest.cases),
        "baseline_count": len(baselines),
        "hybrid_false_advance_count": (
            0 if hybrid is None else hybrid.false_advance_count
        ),
        "robot_execution_enabled": False,
        "can_execute_world": False,
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        summary = run(args)
    except (OSError, ValidationError, ValueError) as exc:
        print(f"benchmark rejected: {exc}", file=sys.stderr)
        return 2
    print(canonical_json(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
