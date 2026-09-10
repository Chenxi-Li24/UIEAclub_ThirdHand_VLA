#!/usr/bin/env python3
"""Run one evidence-gated episode using only checked local replay data."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pydantic import ValidationError

from uiea_thirdhand_vla.orchestration.runtime import (
    EvidenceGatedSupervisor,
    FakeExecutor,
    JsonlTrace,
    ReplayBundle,
    ReplayObservationSource,
    RuntimeState,
    SkillRegistry,
    compute_metrics,
)
from uiea_thirdhand_vla.orchestration.runtime.recovery import RecoveryManager
from uiea_thirdhand_vla.orchestration.runtime.trace import canonical_json


def local_file(value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_file():
        raise argparse.ArgumentTypeError(f"not a local file: {path}")
    return path


def output_file(value: str) -> Path:
    path = Path(value).expanduser()
    if path.exists() and not path.is_file():
        raise argparse.ArgumentTypeError(f"output is not a regular file: {path}")
    return path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=local_file, required=True)
    parser.add_argument("--skill", type=local_file, action="append", required=True)
    parser.add_argument("--trace", type=output_file, required=True)
    parser.add_argument("--metrics", type=output_file, required=True)
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> tuple[RuntimeState, str]:
    bundle = ReplayBundle.model_validate_json(args.bundle.read_text(encoding="utf-8"))
    trace = JsonlTrace(args.trace)
    supervisor = EvidenceGatedSupervisor(
        registry=SkillRegistry.from_paths(tuple(args.skill)),
        observations=ReplayObservationSource(bundle.observations),
        executor=FakeExecutor(bundle.receipt_statuses),
        recovery=RecoveryManager(),
        trace=trace,
    )
    result = supervisor.run(bundle.plan)
    metrics = compute_metrics(result, bundle.ground_truth)
    args.metrics.parent.mkdir(parents=True, exist_ok=True)
    args.metrics.write_text(canonical_json(metrics) + "\n", encoding="utf-8")
    summary = {
        "dispatch_count": metrics.dispatch_count,
        "false_advance_count": metrics.false_advance_count,
        "false_advance_rate": metrics.false_advance_rate,
        "final_state": metrics.final_state.value,
        "recovery_count": metrics.recovery_count,
        "robot_execution_enabled": False,
    }
    return result.final_state, canonical_json(summary)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        state, summary = run(args)
    except (OSError, ValidationError, ValueError) as exc:
        print(f"shadow replay rejected: {exc}", file=sys.stderr)
        return 2
    print(summary)
    return 0 if state is RuntimeState.DONE else 1


if __name__ == "__main__":
    raise SystemExit(main())
