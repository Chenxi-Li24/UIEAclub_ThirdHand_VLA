#!/usr/bin/env python3
"""Sample and attest execution-locked active-view status reports."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import time
from typing import Any, Sequence
import urllib.error
import urllib.request
from urllib.parse import urlsplit


MAX_STATUS_BYTES = 1024 * 1024
MAX_REPORTS = 256
MAX_SOURCE_AGE_MS = 2_000.0
VALID_KINDS = {"none", "coarse_pose", "refine_delta"}


def _finite(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _sequence(status: Any, name: str) -> int | None:
    if not isinstance(status, dict) or not isinstance(status.get("sequences"), dict):
        return None
    value = status["sequences"].get(name)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _finite_vector(value: Any, length: int) -> bool:
    return (
        isinstance(value, list)
        and len(value) == length
        and all(_finite(item) is not None for item in value)
    )


def _report_errors(report: Any, prefix: str, now_ns: int) -> list[str]:
    if not isinstance(report, dict):
        return [f"{prefix} active-view report is not an object"]
    errors: list[str] = []
    if report.get("executionEnabled") is not False:
        errors.append(f"{prefix} active-view report execution lock is not false")
    kind = report.get("kind")
    if kind not in VALID_KINDS:
        errors.append(f"{prefix} active-view report kind is invalid")
    identity_id = report.get("identityId")
    if identity_id is not None and (
        isinstance(identity_id, bool) or not isinstance(identity_id, int) or identity_id < 0
    ):
        errors.append(f"{prefix} active-view report identity is invalid")
    target_pose_id = report.get("targetPoseId")
    expires_ns = report.get("expiresNs")
    if kind == "none":
        if target_pose_id is not None:
            errors.append(f"{prefix} rejected active-view report contains a target pose")
    else:
        if kind == "coarse_pose" and (
            not isinstance(target_pose_id, str) or not target_pose_id
        ):
            errors.append(f"{prefix} active-view proposal target pose is missing")
        if kind == "refine_delta" and target_pose_id is not None:
            errors.append(f"{prefix} refinement report contains an absolute target pose")
        if (
            isinstance(expires_ns, bool)
            or not isinstance(expires_ns, int)
            or expires_ns <= 0
        ):
            errors.append(f"{prefix} active-view proposal expiry is invalid")
        elif expires_ns <= now_ns:
            errors.append(f"{prefix} active-view proposal is expired")
    center = report.get("coarseCenterXYM")
    if center is not None and not _finite_vector(center, 2):
        errors.append(f"{prefix} active-view report coarse center is non-finite")
    central = report.get("centralFraction")
    if central is not None:
        fraction = _finite(central)
        if fraction is None or not 0.0 <= fraction <= 1.0:
            errors.append(f"{prefix} active-view report central fraction is invalid")
    for field in ("validDepthPoints", "stableSamples", "remainingRefinements"):
        value = report.get(field)
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, int) or value < 0
        ):
            errors.append(f"{prefix} active-view report {field} is invalid")
    reasons = report.get("reasons")
    if not isinstance(reasons, list) or not all(
        isinstance(reason, str) and reason for reason in reasons
    ):
        errors.append(f"{prefix} active-view report reasons are invalid")
    return errors


def _sample_errors(status: Any, index: int, now_ns: int) -> tuple[list[str], int]:
    prefix = f"sample[{index}]"
    if not isinstance(status, dict):
        return [f"{prefix} is not a JSON object"], 0
    errors: list[str] = []
    execution_enabled = 0
    if status.get("online") is not True or status.get("modelReady") is not True:
        errors.append(f"{prefix} online model is not ready")
    if status.get("d435Ready") is not True or status.get("lumosReady") is not True:
        errors.append(f"{prefix} both cameras are not ready")
    age = _finite(status.get("sourceAgeMs"))
    if status.get("stale") is not False or age is None or age > MAX_SOURCE_AGE_MS:
        errors.append(f"{prefix} status is stale")
    if status.get("robotExecutionEnabled") is not False:
        errors.append(f"{prefix} robot execution lock is not false")
        execution_enabled = 1
    roles = status.get("roles")
    if not isinstance(roles, dict) or roles.get("canonicalRgb") != "lumos_rgb" or roles.get(
        "metricDepth"
    ) != "d435_depth":
        errors.append(f"{prefix} camera roles do not match")
    for source in ("lumos", "d435"):
        if _sequence(status, source) is None:
            errors.append(f"{prefix} {source} sequence is invalid")
    blockers = status.get("blockers")
    if not isinstance(blockers, list) or not all(
        isinstance(blocker, str) and blocker for blocker in blockers
    ):
        errors.append(f"{prefix} blockers are invalid")
    active_view = status.get("activeView")
    if not isinstance(active_view, dict):
        errors.append(f"{prefix} active-view status is missing")
        return errors, execution_enabled
    if active_view.get("executionEnabled") is not False:
        errors.append(f"{prefix} active-view execution lock is not false")
        execution_enabled = 1
    reports = active_view.get("reports")
    if not isinstance(reports, list) or len(reports) > MAX_REPORTS:
        errors.append(f"{prefix} active-view reports are invalid or unbounded")
        return errors, execution_enabled
    for report_index, report in enumerate(reports):
        errors.extend(
            _report_errors(report, f"{prefix}.reports[{report_index}]", now_ns)
        )
        if isinstance(report, dict) and report.get("executionEnabled") is not False:
            execution_enabled = 1
    return errors, execution_enabled


def evaluate_samples(
    statuses: Sequence[dict[str, Any]],
    expected_execution: bool = False,
) -> dict[str, Any]:
    samples = list(statuses)
    errors: list[str] = []
    if expected_execution is not False:
        errors.append("active-view verifier only supports execution disabled")
    if len(samples) < 2:
        errors.append("at least two status samples are required")
    execution_enabled_samples = 0
    blocker_histogram: Counter[str] = Counter()
    report_reason_histogram: Counter[str] = Counter()
    now_ns = time.monotonic_ns()
    for index, status in enumerate(samples):
        sample_errors, enabled = _sample_errors(status, index, now_ns)
        errors.extend(sample_errors)
        execution_enabled_samples += enabled
        if isinstance(status, dict):
            blockers = status.get("blockers")
            if isinstance(blockers, list):
                blocker_histogram.update(item for item in blockers if isinstance(item, str))
            active_view = status.get("activeView")
            reports = active_view.get("reports") if isinstance(active_view, dict) else None
            if isinstance(reports, list):
                for report in reports:
                    reasons = report.get("reasons") if isinstance(report, dict) else None
                    if isinstance(reasons, list):
                        report_reason_histogram.update(
                            reason for reason in reasons if isinstance(reason, str)
                        )

    first_lumos = _sequence(samples[0], "lumos") if samples else None
    last_lumos = _sequence(samples[-1], "lumos") if samples else None
    first_d435 = _sequence(samples[0], "d435") if samples else None
    last_d435 = _sequence(samples[-1], "d435") if samples else None
    lumos_advance = 0 if None in {first_lumos, last_lumos} else last_lumos - first_lumos
    d435_advance = 0 if None in {first_d435, last_d435} else last_d435 - first_d435
    if lumos_advance <= 0:
        errors.append("Lumos source sequence did not advance")
    if d435_advance <= 0:
        errors.append("D435 source sequence did not advance")
    for source in ("lumos", "d435"):
        values = [_sequence(status, source) for status in samples]
        if any(
            before is not None and after is not None and after < before
            for before, after in zip(values, values[1:])
        ):
            errors.append(f"{source} source sequence regressed")

    return {
        "active_view_execution_enabled": execution_enabled_samples > 0,
        "blocker_histogram": dict(sorted(blocker_histogram.items())),
        "d435_sequence_advancement": d435_advance,
        "errors": errors,
        "execution_enabled_samples": execution_enabled_samples,
        "lumos_sequence_advancement": lumos_advance,
        "passed": not errors,
        "report_reason_histogram": dict(sorted(report_reason_histogram.items())),
        "sample_count": len(samples),
        "schema_version": 1,
    }


def write_json_atomic(path: Path | str, payload: dict[str, Any]) -> None:
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
    request = urllib.request.Request(
        base_url.rstrip("/") + "/api/vision/status",
        headers={"Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            if response.status != 200:
                raise RuntimeError(f"vision status returned HTTP {response.status}")
            payload = response.read(MAX_STATUS_BYTES + 1)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"vision status request failed: {exc}") from exc
    if len(payload) > MAX_STATUS_BYTES:
        raise RuntimeError("vision status response exceeds 1 MiB")
    try:
        decoded = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"vision status is not valid JSON: {exc}") from exc
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
        except RuntimeError as exc:
            fetch_errors.append(str(exc))
        if now >= deadline:
            break
        next_sample = min(next_sample + 1.0, deadline)
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
        samples, fetch_errors = collect_samples(arguments.base_url, arguments.duration_seconds)
        report = evaluate_samples(samples, expected_execution=False)
        report.update(
            {
                "base_url": arguments.base_url,
                "fetch_errors": fetch_errors,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "requested_duration_seconds": arguments.duration_seconds,
                "samples": samples,
            }
        )
        if fetch_errors:
            report["errors"].extend(fetch_errors)
            report["passed"] = False
    except RuntimeError as exc:
        report = {
            "base_url": arguments.base_url,
            "errors": [str(exc)],
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "passed": False,
            "samples": [],
            "schema_version": 1,
        }
    write_json_atomic(arguments.output, report)
    print(json.dumps(report, sort_keys=True, allow_nan=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
