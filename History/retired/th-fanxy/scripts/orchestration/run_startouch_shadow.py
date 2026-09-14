#!/usr/bin/env python3
"""Run one Startouch-shaped preview episode without physical execution."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from uiea_thirdhand_vla.orchestration.runtime import (
    EvidenceGatedSupervisor,
    JsonlTrace,
    ReplayBundle,
    ReplayObservationSource,
    RuntimeState,
    SkillRegistry,
    compute_metrics,
)
from uiea_thirdhand_vla.orchestration.runtime.models import ExecutorKind, FrozenModel
from uiea_thirdhand_vla.orchestration.runtime.recovery import RecoveryManager
from uiea_thirdhand_vla.orchestration.runtime.trace import canonical_json
from uiea_thirdhand_vla.orchestration.shadow.execution import (
    ExecutionCapability,
    StartouchShadowExecutor,
    load_preview_resolver,
)
from uiea_thirdhand_vla.orchestration.shadow.startouch_preview import load_shadow_limits


class ShadowBundleManifest(FrozenModel):
    schema_version: Literal["1.0.0"]
    robot_execution_enabled: Literal[False]
    replay_bundle_file: str


def local_file(value: str) -> Path:
    path = Path(value).expanduser()
    if path.is_symlink() or not path.is_file():
        raise argparse.ArgumentTypeError(f"not a non-symlink local file: {path}")
    return path


def output_file(value: str) -> Path:
    path = Path(value).expanduser()
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise argparse.ArgumentTypeError(f"output is not a regular file: {path}")
    return path


def preview_directory(value: str) -> Path:
    path = Path(value).expanduser()
    if path.is_symlink() or (path.exists() and not path.is_dir()):
        raise argparse.ArgumentTypeError(f"preview output is not a directory: {path}")
    if path.exists() and any(path.iterdir()):
        raise argparse.ArgumentTypeError(f"preview output must be empty: {path}")
    return path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=local_file, required=True)
    parser.add_argument("--skill", type=local_file, action="append", required=True)
    parser.add_argument("--limits", type=local_file, required=True)
    parser.add_argument("--preview-policy", type=local_file, required=True)
    parser.add_argument("--preview-dir", type=preview_directory, required=True)
    parser.add_argument("--trace", type=output_file, required=True)
    parser.add_argument("--metrics", type=output_file, required=True)
    return parser.parse_args(argv)


def load_bundle(path: Path) -> ReplayBundle:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and "plan" in payload:
        return ReplayBundle.model_validate(payload)
    manifest = ShadowBundleManifest.model_validate(payload)
    relative = Path(manifest.replay_bundle_file)
    if relative.is_absolute() or ".." in relative.parts or len(relative.parts) != 1:
        raise ValueError("shadow replay bundle reference must be a sibling filename")
    referenced = path.parent / relative
    if referenced.is_symlink() or not referenced.is_file():
        raise ValueError("referenced replay bundle is not a non-symlink file")
    return ReplayBundle.model_validate_json(referenced.read_text(encoding="utf-8"))


def run(args: argparse.Namespace) -> tuple[RuntimeState, str]:
    bundle = load_bundle(args.bundle)
    trace = JsonlTrace(args.trace)
    executor = StartouchShadowExecutor(
        output_dir=args.preview_dir,
        resolver=load_preview_resolver(args.preview_policy),
        limits=load_shadow_limits(args.limits),
        capability=ExecutionCapability.shadow(),
    )
    supervisor = EvidenceGatedSupervisor(
        registry=SkillRegistry.from_paths(
            tuple(args.skill), allowed_executor_kinds=(ExecutorKind.SHADOW,)
        ),
        observations=ReplayObservationSource(bundle.observations),
        executor=executor,
        recovery=RecoveryManager(),
        trace=trace,
    )
    result = supervisor.run(bundle.plan)
    base_metrics = compute_metrics(result, bundle.ground_truth)
    metrics = {
        **base_metrics.model_dump(mode="json"),
        "preview_count": executor.dispatch_count,
        "robot_execution_enabled": False,
        "can_execute_world": False,
    }
    args.metrics.parent.mkdir(parents=True, exist_ok=True)
    args.metrics.write_text(canonical_json(metrics) + "\n", encoding="utf-8")
    summary = {
        "dispatch_count": base_metrics.dispatch_count,
        "false_advance_count": base_metrics.false_advance_count,
        "false_advance_rate": base_metrics.false_advance_rate,
        "final_state": base_metrics.final_state.value,
        "recovery_count": base_metrics.recovery_count,
        "preview_count": executor.dispatch_count,
        "robot_execution_enabled": False,
        "can_execute_world": False,
    }
    return result.final_state, canonical_json(summary)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        state, summary = run(args)
    except (OSError, json.JSONDecodeError, ValidationError, ValueError) as exc:
        print(f"Startouch shadow replay rejected: {exc}", file=sys.stderr)
        return 2
    print(summary)
    return 0 if state is RuntimeState.DONE else 1


if __name__ == "__main__":
    raise SystemExit(main())
