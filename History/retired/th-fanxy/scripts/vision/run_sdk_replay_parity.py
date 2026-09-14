#!/usr/bin/env python3
"""Compare legacy and reusable-SDK JSONL replay results fail-closed."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path
from typing import Any

import yaml
from vision_sdk_adapter import compare_replay_frames

MAX_FRAMES = 100_000
MAX_LINE_BYTES = 1024 * 1024


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    frames: list[dict[str, Any]] = []
    with path.open("rb") as stream:
        for line_number, raw in enumerate(stream, start=1):
            if len(raw) > MAX_LINE_BYTES:
                raise ValueError(f"{path}: line {line_number} exceeds 1 MiB")
            if not raw.strip():
                continue
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError(f"{path}: line {line_number} must be a JSON object")
            frames.append(value)
            if len(frames) > MAX_FRAMES:
                raise ValueError(f"{path}: replay exceeds {MAX_FRAMES} frames")
    if not frames:
        raise ValueError(f"{path}: replay is empty")
    return frames


def _read_thresholds(path: Path) -> dict[str, float]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or set(payload) != {"schema_version", "thresholds"}:
        raise ValueError("parity config must contain schema_version and thresholds only")
    if payload["schema_version"] != 1 or not isinstance(payload["thresholds"], dict):
        raise ValueError("unsupported parity config")
    return payload["thresholds"]


def _write_atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, sort_keys=True, separators=(",", ":"), allow_nan=False)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--legacy", required=True, type=Path)
    parser.add_argument("--sdk", required=True, type=Path)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        report = compare_replay_frames(
            _read_jsonl(args.legacy),
            _read_jsonl(args.sdk),
            _read_thresholds(args.config),
        )
        _write_atomic_json(args.output, report)
    except (OSError, ValueError, TypeError, json.JSONDecodeError, yaml.YAMLError) as error:
        print(f"replay parity failed closed: {error}", file=__import__("sys").stderr)
        return 2
    print(f"replay parity {'passed' if report['passed'] else 'failed'}: {args.output}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
