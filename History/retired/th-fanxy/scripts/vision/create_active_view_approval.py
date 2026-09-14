#!/usr/bin/env python3
"""Create a short-lived, content-addressed active-view motion approval."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import time
from typing import Any, Mapping, Sequence


MAX_DURATION_MS = 8 * 60 * 60 * 1000
MAX_ROTATION_RAD = 5 * math.pi / 180
MAX_REFINEMENT_STEPS = 6
MAX_TOTAL_TRANSLATION_M = 0.060
MAX_TOTAL_ROTATION_RAD = 15 * math.pi / 180
EVIDENCE_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
LIMIT_KEYS = {
    "max_speed_scale",
    "max_translation_m",
    "max_rotation_rad",
    "max_refinement_steps",
    "require_step_confirmation",
}


def canonical_json(payload: Any) -> str:
    try:
        return json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("approval must be finite canonical JSON") from exc


def content_id(payload: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(payload).encode("ascii")).hexdigest()


def _finite(value: object, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be finite")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be finite") from exc
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _validated_limits(raw: Mapping[str, object]) -> dict[str, object]:
    if not isinstance(raw, dict) or set(raw) != LIMIT_KEYS:
        raise ValueError("approval limits keys are invalid")
    speed = _finite(raw["max_speed_scale"], "speed limit")
    translation = _finite(raw["max_translation_m"], "translation limit")
    rotation = _finite(raw["max_rotation_rad"], "rotation limit")
    refinements = raw["max_refinement_steps"]
    confirmation = raw["require_step_confirmation"]
    if not 0.0 < speed <= 0.05:
        raise ValueError("speed limit must be within 0.05")
    if not 0.0 < translation <= 0.020:
        raise ValueError("translation limit must be within 20 mm")
    if not 0.0 <= rotation <= MAX_ROTATION_RAD:
        raise ValueError("rotation limit must be within 5 degrees")
    if (
        isinstance(refinements, bool)
        or not isinstance(refinements, int)
        or not 1 <= refinements <= MAX_REFINEMENT_STEPS
    ):
        raise ValueError("refinement limit must be between one and six")
    if translation * refinements > MAX_TOTAL_TRANSLATION_M + 1e-12:
        raise ValueError("total translation limit must be within 60 mm")
    if rotation * refinements > MAX_TOTAL_ROTATION_RAD + 1e-12:
        raise ValueError("total rotation limit must be within 15 degrees")
    if confirmation is not True:
        raise ValueError("per-step confirmation must be required")
    return {
        "max_speed_scale": speed,
        "max_translation_m": translation,
        "max_rotation_rad": rotation,
        "max_refinement_steps": refinements,
        "require_step_confirmation": True,
    }


def _atomic_private_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_suffix(path.suffix + ".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(canonical_json(payload) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
        path.chmod(0o600)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def create_approval(
    *,
    output_path: Path | str,
    evidence_ids: Sequence[str],
    robot_model_id: str,
    limits: Mapping[str, object],
    issued_at_ms: int,
    expires_at_ms: int,
    operator_acknowledged: bool,
) -> dict[str, object]:
    if operator_acknowledged is not True:
        raise ValueError("explicit operator acknowledgement is required")
    if not isinstance(issued_at_ms, int) or isinstance(issued_at_ms, bool):
        raise ValueError("approval issue time must be an integer")
    if not isinstance(expires_at_ms, int) or isinstance(expires_at_ms, bool):
        raise ValueError("approval expiry time must be an integer")
    if expires_at_ms <= issued_at_ms:
        raise ValueError("approval expiry must be after issue time")
    if expires_at_ms - issued_at_ms > MAX_DURATION_MS:
        raise ValueError("approval duration cannot exceed 8 hours")
    evidence = list(evidence_ids)
    if not evidence or len(evidence) > 32 or len(set(evidence)) != len(evidence) or any(
        not isinstance(item, str) or EVIDENCE_PATTERN.fullmatch(item) is None
        for item in evidence
    ):
        raise ValueError("approval evidence IDs are invalid")
    if not isinstance(robot_model_id, str) or not robot_model_id or len(robot_model_id) > 128:
        raise ValueError("robot model ID is invalid")
    payload: dict[str, object] = {
        "schema_version": 1,
        "issued_at_ms": issued_at_ms,
        "expires_at_ms": expires_at_ms,
        "operator_acknowledged": True,
        "robot_model_id": robot_model_id,
        "evidence_ids": evidence,
        "limits": _validated_limits(limits),
    }
    approval = {**payload, "content_id": content_id(payload)}
    _atomic_private_json(Path(output_path), approval)
    return approval


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--evidence-id", required=True, action="append", dest="evidence_ids")
    parser.add_argument("--robot-model-id", required=True)
    parser.add_argument("--expires-in-seconds", required=True, type=float)
    parser.add_argument("--max-speed-scale", type=float, default=0.05)
    parser.add_argument("--max-translation-m", type=float, default=0.020)
    parser.add_argument("--max-rotation-rad", type=float, default=MAX_ROTATION_RAD)
    parser.add_argument("--max-refinement-steps", type=int, default=3)
    parser.add_argument("--operator-acknowledged", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    issued_at_ms = time.time_ns() // 1_000_000
    duration_ms = int(arguments.expires_in_seconds * 1000)
    try:
        create_approval(
            output_path=arguments.output,
            evidence_ids=arguments.evidence_ids,
            robot_model_id=arguments.robot_model_id,
            limits={
                "max_speed_scale": arguments.max_speed_scale,
                "max_translation_m": arguments.max_translation_m,
                "max_rotation_rad": arguments.max_rotation_rad,
                "max_refinement_steps": arguments.max_refinement_steps,
                "require_step_confirmation": True,
            },
            issued_at_ms=issued_at_ms,
            expires_at_ms=issued_at_ms + duration_ms,
            operator_acknowledged=arguments.operator_acknowledged,
        )
    except (OSError, ValueError) as exc:
        raise SystemExit(f"active-view approval creation failed: {exc}") from exc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
