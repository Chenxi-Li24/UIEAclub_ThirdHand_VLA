#!/usr/bin/env python3
"""Sample and attest the read-only dual-camera online deployment."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import time
from typing import Any, Sequence
import urllib.error
import urllib.request
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[2]
EXPECTED_ROLES = {
    "canonicalRgb": "lumos_rgb",
    "metricDepth": "d435_depth",
    "debugRgb": "d435_rgb",
}
LATENCY_P95_LIMIT_MS = 300.0
GPU_MEMORY_LIMIT_GIB = 7.2
CRITICAL_BLOCKERS = {
    "gpu_memory_budget_exceeded",
    "latency_budget_exceeded",
    "model_unavailable",
    "vision_status_stale",
    "vision_unavailable",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return f"sha256:{digest}"


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _sequence(status: dict[str, Any], name: str) -> int | None:
    value = status.get("sequences", {}).get(name)
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _sample_errors(status: Any, index: int) -> list[str]:
    prefix = f"sample[{index}]"
    if not isinstance(status, dict):
        return [f"{prefix} is not a JSON object"]
    errors: list[str] = []
    if status.get("online") is not True:
        errors.append(f"{prefix} online state is false")
    if status.get("modelReady") is not True:
        errors.append(f"{prefix} model is not ready")
    if status.get("d435Ready") is not True or status.get("lumosReady") is not True:
        errors.append(f"{prefix} both cameras are not ready")
    if status.get("stale") is not False:
        errors.append(f"{prefix} vision status is stale")
    if status.get("robotExecutionEnabled") is not False:
        errors.append(f"{prefix} execution lock is not false")
    if status.get("roles") != EXPECTED_ROLES:
        errors.append(f"{prefix} camera roles do not match the deployment contract")
    for source in ("lumos", "d435"):
        if _sequence(status, source) is None:
            errors.append(f"{prefix} {source} sequence is invalid")
    metrics = status.get("metrics")
    if not isinstance(metrics, dict):
        errors.append(f"{prefix} metrics are missing")
    else:
        latency = _finite_number(metrics.get("latencyP95Ms"))
        memory = _finite_number(metrics.get("gpuMemoryReservedGib"))
        if latency is None or latency < 0.0:
            errors.append(f"{prefix} latency p95 is invalid")
        elif latency > LATENCY_P95_LIMIT_MS:
            errors.append(
                f"{prefix} latency p95 {latency:.3f} exceeds {LATENCY_P95_LIMIT_MS:.3f} ms"
            )
        if memory is None or memory < 0.0:
            errors.append(f"{prefix} GPU reserved memory is invalid")
        elif memory > GPU_MEMORY_LIMIT_GIB:
            errors.append(
                f"{prefix} GPU reserved memory {memory:.3f} exceeds "
                f"{GPU_MEMORY_LIMIT_GIB:.3f} GiB"
            )
    blockers = status.get("blockers")
    if not isinstance(blockers, list) or not all(isinstance(item, str) for item in blockers):
        errors.append(f"{prefix} blockers are invalid")
    else:
        for blocker in sorted(set(blockers) & CRITICAL_BLOCKERS):
            errors.append(f"{prefix} critical blocker is active: {blocker}")
    return errors


def evaluate_samples(
    samples: Sequence[dict[str, Any]],
    base_url: str,
) -> dict[str, Any]:
    statuses = list(samples)
    errors: list[str] = []
    if len(statuses) < 2:
        errors.append("at least two status samples are required to verify source advancement")
    for index, status in enumerate(statuses):
        errors.extend(_sample_errors(status, index))

    first_lumos = _sequence(statuses[0], "lumos") if statuses else None
    last_lumos = _sequence(statuses[-1], "lumos") if statuses else None
    first_d435 = _sequence(statuses[0], "d435") if statuses else None
    last_d435 = _sequence(statuses[-1], "d435") if statuses else None
    lumos_advance = 0 if None in {first_lumos, last_lumos} else last_lumos - first_lumos
    d435_advance = 0 if None in {first_d435, last_d435} else last_d435 - first_d435
    if lumos_advance <= 0:
        errors.append("Lumos source sequence did not advance")
    if d435_advance <= 0:
        errors.append("D435 source sequence did not advance")
    for source in ("lumos", "d435"):
        values = [_sequence(status, source) for status in statuses]
        if any(
            previous is not None and current is not None and current < previous
            for previous, current in zip(values, values[1:])
        ):
            errors.append(f"{source} source sequence regressed")

    histogram: Counter[str] = Counter()
    for status in statuses:
        blockers = status.get("blockers", []) if isinstance(status, dict) else []
        if isinstance(blockers, list):
            histogram.update(item for item in blockers if isinstance(item, str))

    config_path = ROOT / "configs/vision/remind3d.yaml"
    source_path = ROOT / "web-control/server/camera_bridge.py"
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "base_url": base_url,
        "passed": not errors,
        "errors": errors,
        "sample_count": len(statuses),
        "samples": statuses,
        "sequence_advancement": {"lumos": lumos_advance, "d435": d435_advance},
        "blocker_histogram": dict(sorted(histogram.items())),
        "robot_execution_enabled": any(
            status.get("robotExecutionEnabled") is not False
            for status in statuses
            if isinstance(status, dict)
        ),
        "limits": {
            "latency_p95_ms": LATENCY_P95_LIMIT_MS,
            "gpu_memory_reserved_gib": GPU_MEMORY_LIMIT_GIB,
        },
        "config_sha256": _sha256(config_path),
        "camera_bridge_sha256": _sha256(source_path),
    }


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    encoded = json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"
    temporary.write_text(encoded, encoding="utf-8")
    temporary.replace(destination)


def fetch_status(base_url: str, timeout_s: float = 2.0) -> dict[str, Any]:
    parsed = urlsplit(base_url)
    if parsed.scheme != "http" or not parsed.hostname or parsed.path not in {"", "/"}:
        raise RuntimeError("--base-url must be an HTTP origin without a path")
    url = base_url.rstrip("/") + "/api/vision/status"
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            if response.status != 200:
                raise RuntimeError(f"vision status returned HTTP {response.status}")
            payload = response.read(1024 * 1024 + 1)
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise RuntimeError(f"vision status request failed: {error}") from error
    if len(payload) > 1024 * 1024:
        raise RuntimeError("vision status response exceeds 1 MiB")
    try:
        decoded = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError(f"vision status is not valid JSON: {error}") from error
    if not isinstance(decoded, dict):
        raise RuntimeError("vision status must be a JSON object")
    return decoded


def collect_samples(base_url: str, duration_seconds: float) -> tuple[list[dict[str, Any]], list[str]]:
    if not math.isfinite(duration_seconds) or duration_seconds <= 0.0:
        raise RuntimeError("--duration-seconds must be finite and positive")
    samples: list[dict[str, Any]] = []
    fetch_errors: list[str] = []
    started = time.monotonic()
    deadline = started + duration_seconds
    next_sample = started
    while True:
        now = time.monotonic()
        if now < next_sample:
            time.sleep(min(next_sample - now, 0.25))
            continue
        try:
            samples.append(fetch_status(base_url))
        except RuntimeError as error:
            fetch_errors.append(str(error))
        if now >= deadline:
            break
        next_sample += 1.0
        if next_sample > deadline:
            next_sample = deadline
    return samples, fetch_errors


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:3100")
    parser.add_argument("--duration-seconds", type=float, default=60.0)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        samples, fetch_errors = collect_samples(
            arguments.base_url, arguments.duration_seconds
        )
        report = evaluate_samples(samples, arguments.base_url)
        report["requested_duration_seconds"] = arguments.duration_seconds
        report["fetch_errors"] = fetch_errors
        if fetch_errors:
            report["errors"].extend(fetch_errors)
            report["passed"] = False
    except RuntimeError as error:
        report = {
            "schema_version": 1,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "base_url": arguments.base_url,
            "passed": False,
            "errors": [str(error)],
            "samples": [],
            "robot_execution_enabled": False,
        }
    write_json_atomic(arguments.output, report)
    print(json.dumps(report, sort_keys=True, allow_nan=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
