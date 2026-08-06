#!/usr/bin/env python3
"""Deterministically verify active-view control evidence without robot access."""

from __future__ import annotations

import argparse
from collections import Counter
import json
import math
from pathlib import Path
import re
import statistics
import time
from typing import Any, Iterable, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import UUID


MAX_EVENTS = 100_000
MAX_TRANSLATION_M = 0.020
MAX_ROTATION_RAD = math.radians(5.0)
MIN_IDENTITY_CONFIRMATIONS = 2
MIN_DEPTH_SAMPLES = 5
MAX_CENTER_DEVIATION_M = 0.010
MAX_AXIS_MAD_M = 0.005
EVIDENCE_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
COMMAND_EVENT_TYPES = {"motion_started", "robot_command", "grasp_command"}


class ActiveViewControlEvidenceError(ValueError):
    """Raised when evidence is malformed rather than a valid failed session."""


def _evidence_id(value: Any) -> str:
    if not isinstance(value, str) or EVIDENCE_PATTERN.fullmatch(value) is None:
        raise ActiveViewControlEvidenceError("expected evidence ID must be sha256:<64 hex>")
    return value


def _uuid(value: Any, name: str) -> str:
    if not isinstance(value, str):
        raise ActiveViewControlEvidenceError(f"{name} must be a canonical UUID")
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError) as exc:
        raise ActiveViewControlEvidenceError(f"{name} must be a canonical UUID") from exc
    if parsed.version != 4 or str(parsed) != value:
        raise ActiveViewControlEvidenceError(f"{name} must be a canonical UUIDv4")
    return value


def _finite_vector(value: Any, size: int, name: str) -> tuple[float, ...]:
    if not isinstance(value, (list, tuple)) or len(value) != size:
        raise ActiveViewControlEvidenceError(f"{name} must be a {size}-vector")
    result = tuple(float(item) for item in value)
    if not all(math.isfinite(item) for item in result):
        raise ActiveViewControlEvidenceError(f"{name} must contain finite values")
    return result


def _finite_tree(value: Any, path: str = "events") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            _finite_tree(child, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _finite_tree(child, f"{path}[{index}]")
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        if not math.isfinite(float(value)):
            raise ActiveViewControlEvidenceError(f"{path} must contain finite numbers")


def _evidence_ids(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or not value:
        raise ActiveViewControlEvidenceError("session evidence_ids must be non-empty")
    result = tuple(_evidence_id(item) for item in value)
    if len(set(result)) != len(result):
        raise ActiveViewControlEvidenceError("session evidence_ids must be unique")
    return result


def _bound_evidence(value: Any, expected: str) -> tuple[str, ...]:
    result = _evidence_ids(value)
    if expected not in result:
        raise ActiveViewControlEvidenceError("expected evidence ID is not bound")
    return result


def _stable_depth(samples: Sequence[tuple[float, float, float]]) -> tuple[bool, float, float]:
    if len(samples) < MIN_DEPTH_SAMPLES:
        return False, math.inf, math.inf
    center = tuple(statistics.median(sample[axis] for sample in samples) for axis in range(3))
    deviations = [math.dist(sample, center) for sample in samples]
    axis_mads = [
        statistics.median(abs(sample[axis] - center[axis]) for sample in samples)
        for axis in range(3)
    ]
    maximum_deviation = max(deviations)
    maximum_mad = max(axis_mads)
    return (
        maximum_deviation <= MAX_CENTER_DEVIATION_M
        and maximum_mad <= MAX_AXIS_MAD_M,
        maximum_deviation,
        maximum_mad,
    )


def evaluate_active_view_control(
    events: Iterable[Mapping[str, Any]],
    expected_evidence_id: str,
    real_motion_allowed: bool = False,
) -> dict[str, Any]:
    """Evaluate bounded event evidence; never import or call a robot transport."""

    expected_evidence = _evidence_id(expected_evidence_id)
    event_list = list(events)
    if len(event_list) > MAX_EVENTS:
        raise ActiveViewControlEvidenceError("active-view control evidence exceeds 100,000 events")
    _finite_tree(event_list)

    errors: list[str] = []
    abort_reasons: Counter[str] = Counter()
    phase = "idle"
    session_id: str | None = None
    identity_id: int | None = None
    evidence_ids: tuple[str, ...] | None = None
    proposal: dict[str, Any] | None = None
    request_id: str | None = None
    aborted = False
    previous_ts = -1
    identity_confirmations_since_motion = 0
    depth_since_motion: list[tuple[float, float, float]] = []
    session_count = 0
    completed_sessions = 0
    observation_moves = 0
    grasp_commands = 0
    commands_after_abort = 0
    max_translation_m = 0.0
    max_rotation_rad = 0.0
    settling_time_ms_max = 0
    identity_confirmations = 0
    depth_samples = 0
    identity_changes = 0
    execution_gate_samples = 0
    execution_gate_violations = 0
    stale_accepted_proposals = 0
    unexpected_transitions = 0

    def record_error(message: str, reason: str | None = None) -> None:
        nonlocal aborted, phase
        errors.append(message)
        if reason is not None:
            abort_reasons[reason] += 1
        aborted = True
        phase = "aborted"

    def transition_error(event_type: str) -> None:
        nonlocal unexpected_transitions
        unexpected_transitions += 1
        record_error(
            f"unexpected {event_type} transition from {phase}",
            "unexpected_transition",
        )

    for index, raw_event in enumerate(event_list):
        if not isinstance(raw_event, Mapping):
            raise ActiveViewControlEvidenceError(f"events[{index}] must be an object")
        event = dict(raw_event)
        event_type = event.get("type")
        if not isinstance(event_type, str) or not event_type:
            raise ActiveViewControlEvidenceError(f"events[{index}].type must be a string")
        timestamp = event.get("ts_ms")
        if (
            isinstance(timestamp, bool)
            or not isinstance(timestamp, int)
            or timestamp <= previous_ts
        ):
            raise ActiveViewControlEvidenceError("event timestamps must be strictly increasing integers")
        previous_ts = timestamp

        if aborted:
            if event_type in COMMAND_EVENT_TYPES:
                commands_after_abort += 1
                if event_type in {"grasp_command", "robot_command"} and event.get("cmd") in {
                    "grasp", "grasp_object", "gripper",
                }:
                    grasp_commands += 1
            continue

        if event_type == "session_started":
            if phase != "idle" or session_id is not None:
                transition_error(event_type)
                continue
            session_id = _uuid(event.get("session_id"), "session_id")
            candidate_identity = event.get("identity_id")
            if (
                isinstance(candidate_identity, bool)
                or not isinstance(candidate_identity, int)
                or candidate_identity < 0
            ):
                raise ActiveViewControlEvidenceError("identity_id must be non-negative")
            identity_id = candidate_identity
            evidence_ids = _bound_evidence(event.get("evidence_ids"), expected_evidence)
            execution_gate_samples += 1
            if event.get("robot_execution_enabled") is not False:
                execution_gate_violations += 1
                record_error("robot execution gate was not false", "execution_gate")
                continue
            if not real_motion_allowed and event.get("active_view_execution_enabled") is not False:
                execution_gate_violations += 1
                record_error("active-view execution gate was not false in simulation", "execution_gate")
                continue
            phase = "target_locked"
            session_count += 1
            proposal = None
            request_id = None
            identity_confirmations_since_motion = 0
            depth_since_motion = []
            continue

        if event_type == "proposal":
            if phase not in {"target_locked", "acquiring_depth"} or session_id is None:
                transition_error(event_type)
                continue
            if event.get("session_id") != session_id or event.get("identity_id") != identity_id:
                record_error("proposal session or identity correlation failed", "identity")
                continue
            candidate_evidence = _evidence_ids(event.get("evidence_ids"))
            if candidate_evidence != evidence_ids:
                record_error("proposal evidence changed during the session", "evidence")
                continue
            proposal_id = _uuid(event.get("proposal_id"), "proposal_id")
            expires_ms = event.get("expires_ms")
            if isinstance(expires_ms, bool) or not isinstance(expires_ms, int):
                raise ActiveViewControlEvidenceError("proposal expires_ms must be an integer")
            if timestamp >= expires_ms:
                stale_accepted_proposals += 1
                record_error("stale proposal was accepted", "stale proposal")
                continue
            kind = event.get("kind")
            if kind not in {"coarse_pose", "refine_delta"}:
                raise ActiveViewControlEvidenceError("proposal kind is invalid")
            translation = 0.0
            rotation = 0.0
            if kind == "coarse_pose":
                if phase != "target_locked":
                    transition_error(event_type)
                    continue
            else:
                if phase != "acquiring_depth" or not depth_since_motion:
                    record_error("refinement requires a fresh depth observation", "depth")
                    continue
                delta = _finite_vector(event.get("delta_base_m"), 3, "delta_base_m")
                optical_axis = _finite_vector(
                    event.get("optical_axis_base"),
                    3,
                    "optical_axis_base",
                )
                rotation_delta = _finite_vector(
                    event.get("rotation_delta_rad"),
                    3,
                    "rotation_delta_rad",
                )
                translation = math.sqrt(sum(value * value for value in delta))
                rotation = math.sqrt(sum(value * value for value in rotation_delta))
                axis_norm = math.sqrt(sum(value * value for value in optical_axis))
                if translation <= 1e-12:
                    record_error("refinement translation is zero", "motion bound")
                    continue
                if translation > MAX_TRANSLATION_M + 1e-12:
                    record_error("refinement translation exceeds 20 mm", "motion bound")
                    continue
                if rotation > MAX_ROTATION_RAD + 1e-12:
                    record_error("refinement rotation exceeds 5 degrees", "motion bound")
                    continue
                if axis_norm <= 0.0:
                    raise ActiveViewControlEvidenceError("optical_axis_base has zero norm")
                axial = abs(sum(delta[i] * optical_axis[i] for i in range(3)) / axis_norm)
                if axial > 1e-9:
                    record_error("refinement contains optical-axis motion", "motion bound")
                    continue
            max_translation_m = max(max_translation_m, translation)
            max_rotation_rad = max(max_rotation_rad, rotation)
            proposal = {
                "proposal_id": proposal_id,
                "expires_ms": expires_ms,
                "translation_m": translation,
                "rotation_rad": rotation,
            }
            phase = "coarse_view_planned" if kind == "coarse_pose" else "refine_view"
            continue

        if event_type == "operator_confirmed":
            if phase not in {"coarse_view_planned", "refine_view"} or proposal is None:
                transition_error(event_type)
                continue
            if event.get("session_id") != session_id or event.get("proposal_id") != proposal["proposal_id"]:
                record_error("operator confirmation proposal correlation failed", "proposal")
                continue
            if timestamp >= proposal["expires_ms"]:
                record_error("operator confirmed a stale proposal", "stale proposal")
                continue
            phase = "move_authorized"
            continue

        if event_type == "motion_started":
            if phase != "move_authorized" or proposal is None:
                transition_error(event_type)
                continue
            if event.get("session_id") != session_id or event.get("proposal_id") != proposal["proposal_id"]:
                record_error("motion proposal correlation failed", "proposal")
                continue
            if not real_motion_allowed and event.get("simulated") is not True:
                record_error("non-simulated motion appeared in simulation evidence", "execution_gate")
                continue
            request_id = _uuid(event.get("request_id"), "request_id")
            observation_moves += 1
            phase = "moving_to_view"
            continue

        if event_type == "motion_completed":
            if phase != "moving_to_view":
                transition_error(event_type)
                continue
            if event.get("session_id") != session_id or event.get("request_id") != request_id:
                record_error("motion completion request ID mismatch", "request")
                continue
            phase = "settling"
            continue

        if event_type == "settled":
            if phase != "settling" or event.get("session_id") != session_id:
                transition_error(event_type)
                continue
            settle_ms = event.get("settling_ms")
            if isinstance(settle_ms, bool) or not isinstance(settle_ms, int) or settle_ms < 0:
                raise ActiveViewControlEvidenceError("settling_ms must be non-negative")
            settling_time_ms_max = max(settling_time_ms_max, settle_ms)
            identity_confirmations_since_motion = 0
            depth_since_motion = []
            proposal = None
            request_id = None
            phase = "verifying_identity"
            continue

        if event_type == "identity_observed":
            if phase not in {"verifying_identity", "acquiring_depth"}:
                transition_error(event_type)
                continue
            if event.get("session_id") != session_id or event.get("identity_id") != identity_id:
                identity_changes += 1
                record_error("target identity changed after observation motion", "identity")
                continue
            if event.get("confirmed") is not True:
                record_error("target identity is ambiguous after observation motion", "identity")
                continue
            identity_confirmations += 1
            if phase == "verifying_identity":
                identity_confirmations_since_motion += 1
                if identity_confirmations_since_motion >= MIN_IDENTITY_CONFIRMATIONS:
                    phase = "acquiring_depth"
            continue

        if event_type == "depth_observed":
            if phase != "acquiring_depth":
                transition_error(event_type)
                continue
            if event.get("session_id") != session_id or event.get("identity_id") != identity_id:
                identity_changes += 1
                record_error("depth observation identity changed", "identity")
                continue
            if event.get("fresh") is not True:
                record_error("stale depth observation was used", "stale depth")
                continue
            center = _finite_vector(event.get("center_m"), 3, "depth center_m")
            depth_since_motion.append(center)
            depth_samples += 1
            continue

        if event_type == "grasp_preview":
            if phase != "acquiring_depth" or event.get("session_id") != session_id:
                transition_error(event_type)
                continue
            if event.get("identity_id") != identity_id:
                identity_changes += 1
                record_error("grasp preview identity changed", "identity")
                continue
            stable, maximum_deviation, maximum_mad = _stable_depth(depth_since_motion)
            if not stable:
                record_error(
                    "grasp preview lacks five stable depth samples "
                    f"(max deviation={maximum_deviation}, max MAD={maximum_mad})",
                    "depth stability",
                )
                continue
            if event.get("grasp_command_emitted") is not False:
                grasp_commands += 1
                record_error("grasp preview emitted a grasp command", "grasp")
                continue
            phase = "grasp_preview"
            continue

        if event_type == "session_complete":
            if phase != "grasp_preview" or event.get("session_id") != session_id:
                transition_error(event_type)
                continue
            completed_sessions += 1
            phase = "idle"
            session_id = None
            identity_id = None
            evidence_ids = None
            proposal = None
            request_id = None
            continue

        if event_type in {
            "disconnect",
            "approval_expired",
            "d435_disconnected",
            "evidence_expired",
            "motion_timeout",
            "target_ambiguous",
            "operator_cancelled",
        }:
            reason = {
                "disconnect": "disconnect",
                "approval_expired": "approval expired",
                "d435_disconnected": "D435 disconnect",
                "evidence_expired": "evidence expired",
                "motion_timeout": "motion timeout",
                "target_ambiguous": "identity ambiguous",
                "operator_cancelled": "operator cancelled",
            }[event_type]
            record_error(reason, reason)
            continue

        if event_type in {"robot_command", "grasp_command"}:
            command = event.get("cmd")
            if event_type == "grasp_command" or command in {"grasp", "grasp_object", "gripper"}:
                grasp_commands += 1
            record_error("robot or grasp command appeared in simulation evidence", "robot command")
            continue

        raise ActiveViewControlEvidenceError(f"unsupported event type: {event_type}")

    terminal_ok = session_count > 0 and (
        completed_sessions == session_count
        or (completed_sessions == session_count - 1 and phase == "grasp_preview")
    )
    if not aborted and not terminal_ok:
        errors.append(f"simulation ended in non-terminal phase: {phase}")
        unexpected_transitions += 1
    passed = not errors and terminal_ok and grasp_commands == 0 and commands_after_abort == 0
    return {
        "abort_reason_histogram": dict(sorted(abort_reasons.items())),
        "commands_after_abort": commands_after_abort,
        "completed_sessions": completed_sessions,
        "depth_samples": depth_samples,
        "errors": errors,
        "execution_gate_samples": execution_gate_samples,
        "execution_gate_violations": execution_gate_violations,
        "grasp_commands": grasp_commands,
        "identity_changes": identity_changes,
        "identity_confirmations": identity_confirmations,
        "max_rotation_rad": max_rotation_rad,
        "max_translation_m": max_translation_m,
        "observation_moves": observation_moves,
        "passed": passed,
        "session_count": session_count,
        "settling_time_ms_max": settling_time_ms_max,
        "stale_accepted_proposals": stale_accepted_proposals,
        "unexpected_transitions": unexpected_transitions,
    }


def _deterministic_uuid(number: int) -> str:
    return str(UUID(int=number, version=4))


def simulated_success_events(
    evidence_id: str,
    *,
    duration_seconds: int = 30,
) -> tuple[dict[str, Any], ...]:
    """Generate repeated successful sessions on a virtual clock; performs no waiting."""

    evidence = _evidence_id(evidence_id)
    if isinstance(duration_seconds, bool) or not isinstance(duration_seconds, int):
        raise ActiveViewControlEvidenceError("duration_seconds must be an integer")
    if not 1 <= duration_seconds <= 24 * 60 * 60:
        raise ActiveViewControlEvidenceError("duration_seconds must be within [1, 86400]")
    cycle_count = max(1, math.ceil(duration_seconds / 30))
    events: list[dict[str, Any]] = []
    for cycle in range(cycle_count):
        base = cycle * 30_000
        identity = cycle + 1
        session = _deterministic_uuid(cycle * 10 + 1)
        coarse_proposal = _deterministic_uuid(cycle * 10 + 2)
        coarse_request = _deterministic_uuid(cycle * 10 + 3)
        refine_proposal = _deterministic_uuid(cycle * 10 + 4)
        refine_request = _deterministic_uuid(cycle * 10 + 5)
        common = {"session_id": session, "identity_id": identity}
        events.extend(
            [
                {
                    "type": "session_started",
                    "ts_ms": base,
                    **common,
                    "evidence_ids": [evidence],
                    "robot_execution_enabled": False,
                    "active_view_execution_enabled": False,
                },
                {
                    "type": "proposal",
                    "ts_ms": base + 10,
                    **common,
                    "proposal_id": coarse_proposal,
                    "kind": "coarse_pose",
                    "evidence_ids": [evidence],
                    "expires_ms": base + 200,
                },
                {
                    "type": "operator_confirmed",
                    "ts_ms": base + 20,
                    "session_id": session,
                    "proposal_id": coarse_proposal,
                },
                {
                    "type": "motion_started",
                    "ts_ms": base + 30,
                    "session_id": session,
                    "proposal_id": coarse_proposal,
                    "request_id": coarse_request,
                    "simulated": True,
                },
                {
                    "type": "motion_completed",
                    "ts_ms": base + 40,
                    "session_id": session,
                    "request_id": coarse_request,
                },
                {
                    "type": "settled",
                    "ts_ms": base + 50,
                    "session_id": session,
                    "settling_ms": 250,
                },
                {"type": "identity_observed", "ts_ms": base + 60, **common, "confirmed": True},
                {"type": "identity_observed", "ts_ms": base + 70, **common, "confirmed": True},
                {
                    "type": "depth_observed",
                    "ts_ms": base + 80,
                    **common,
                    "fresh": True,
                    "center_m": [0.200, 0.100, 0.050],
                },
                {
                    "type": "proposal",
                    "ts_ms": base + 90,
                    **common,
                    "proposal_id": refine_proposal,
                    "kind": "refine_delta",
                    "evidence_ids": [evidence],
                    "expires_ms": base + 280,
                    "delta_base_m": [0.015, 0.0, 0.0],
                    "optical_axis_base": [0.0, 0.0, 1.0],
                    "rotation_delta_rad": [0.0, 0.0, 0.0],
                },
                {
                    "type": "operator_confirmed",
                    "ts_ms": base + 100,
                    "session_id": session,
                    "proposal_id": refine_proposal,
                },
                {
                    "type": "motion_started",
                    "ts_ms": base + 110,
                    "session_id": session,
                    "proposal_id": refine_proposal,
                    "request_id": refine_request,
                    "simulated": True,
                },
                {
                    "type": "motion_completed",
                    "ts_ms": base + 120,
                    "session_id": session,
                    "request_id": refine_request,
                },
                {
                    "type": "settled",
                    "ts_ms": base + 130,
                    "session_id": session,
                    "settling_ms": 250,
                },
                {"type": "identity_observed", "ts_ms": base + 140, **common, "confirmed": True},
                {"type": "identity_observed", "ts_ms": base + 150, **common, "confirmed": True},
            ]
        )
        for sample_index, offset in enumerate((-0.002, -0.001, 0.0, 0.001, 0.002)):
            events.append(
                {
                    "type": "depth_observed",
                    "ts_ms": base + 160 + sample_index * 10,
                    **common,
                    "fresh": True,
                    "center_m": [0.215 + offset, 0.100, 0.050],
                }
            )
        events.extend(
            [
                {
                    "type": "grasp_preview",
                    "ts_ms": base + 215,
                    **common,
                    "grasp_command_emitted": False,
                },
                {
                    "type": "session_complete",
                    "ts_ms": base + 220,
                    "session_id": session,
                },
            ]
        )
    return tuple(events)


def _write_json_atomic(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    payload = json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"
    temporary.write_text(payload, encoding="utf-8")
    temporary.replace(path)


def _read_events(path: Path) -> list[Mapping[str, Any]]:
    if path.stat().st_size > 32 * 1024 * 1024:
        raise ActiveViewControlEvidenceError("event input exceeds 32 MiB")
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=lambda token: (_ for _ in ()).throw(
                ActiveViewControlEvidenceError(f"non-finite JSON value: {token}")
            ),
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ActiveViewControlEvidenceError(f"cannot read event input: {exc}") from exc
    if not isinstance(value, list):
        raise ActiveViewControlEvidenceError("event input must be a JSON array")
    return value


def _verify_read_only_status(base_url: str, duration_seconds: int) -> dict[str, Any]:
    """Sample sanitized status only; this path never sends a control request."""

    deadline = time.monotonic() + duration_seconds
    samples = 0
    errors: list[str] = []
    while True:
        try:
            request = Request(
                f"{base_url.rstrip('/')}/api/vision/status",
                headers={"Accept": "application/json"},
                method="GET",
            )
            with urlopen(request, timeout=2.0) as response:
                status = json.loads(response.read(1_048_577))
            samples += 1
            if status.get("robotExecutionEnabled") is not False:
                errors.append("robot execution gate is not false")
            if status.get("activeViewExecutionEnabled") is not False:
                errors.append("active-view execution gate is not false")
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            errors.append(f"status fetch failed: {exc}")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(1.0, remaining))
    return {
        "errors": errors,
        "passed": samples > 0 and not errors,
        "read_only_status_samples": samples,
        "simulation_only": False,
        "virtual_duration_seconds": None,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:3100")
    parser.add_argument("--duration-seconds", type=int, default=60)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-evidence-id", required=True)
    parser.add_argument("--simulation-only", action="store_true")
    parser.add_argument("--events", type=Path)
    arguments = parser.parse_args(argv)
    evidence_id = _evidence_id(arguments.expected_evidence_id)
    if not 1 <= arguments.duration_seconds <= 24 * 60 * 60:
        parser.error("--duration-seconds must be within [1, 86400]")
    if arguments.simulation_only:
        events = (
            _read_events(arguments.events)
            if arguments.events is not None
            else simulated_success_events(
                evidence_id,
                duration_seconds=arguments.duration_seconds,
            )
        )
        report = evaluate_active_view_control(events, evidence_id)
        report.update(
            {
                "simulation_only": True,
                "virtual_duration_seconds": arguments.duration_seconds,
            }
        )
    else:
        if arguments.events is not None:
            parser.error("--events requires --simulation-only")
        report = _verify_read_only_status(arguments.base_url, arguments.duration_seconds)
        report["expected_evidence_id"] = evidence_id
    _write_json_atomic(arguments.output, report)
    print(json.dumps(report, sort_keys=True, allow_nan=False))
    return 0 if report.get("passed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
