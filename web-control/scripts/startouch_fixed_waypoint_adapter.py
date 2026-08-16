#!/usr/bin/env python3
"""Contract adapter for the fixed Startouch A-to-B waypoint skill.

This delivery implements software-only ``simulate`` and a stricter no-motion
``dry-run``.  It validates an ``execution.request``, reads the existing
fixed-pick-place configuration and route, and returns a truthful
``execution.result`` without starting the bridge, initialising the SDK, opening
CAN, or issuing motion/gripper commands.  ``real`` is always fail-closed.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import re
import sys
import time
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

ADAPTER_ID = "startouch_fixed_waypoint_adapter_v1"
BRIDGE_REF = "web-control/server/startouch_bridge.py"
CONFIG_REF = "configs/tasks/fixed_pick_place.yaml"
FINAL_ROUTE_STATE = "RETURN_B_UP_TO_HOME"
MAX_SPEED_SCALE = 0.15
IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")

ROOT = Path(__file__).resolve().parents[2]
FIXED_RUNNER_PATH = ROOT / "web-control" / "scripts" / "fixed_pick_place.py"


def _load_fixed_runner() -> Any:
    spec = importlib.util.spec_from_file_location("fixed_pick_place_for_adapter", FIXED_RUNNER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load fixed runner: {FIXED_RUNNER_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fixed_runner = _load_fixed_runner()


class AdapterBlocked(ValueError):
    """A request that must be refused without touching robot infrastructure."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class AdapterFailure(RuntimeError):
    """A local preflight failure reported without touching robot hardware."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class DuplicateKeyError(ValueError):
    """Raised when JSON contains a duplicate object key."""


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateKeyError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def loads_json_strict(text: str) -> Any:
    """Parse JSON while rejecting duplicate keys instead of keeping the last."""

    return json.loads(text, object_pairs_hook=_strict_object)


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise AdapterBlocked("invalid_request", f"{field} must be an object")
    return value


def _identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or IDENTIFIER_RE.fullmatch(value) is None:
        raise AdapterBlocked("invalid_request", f"{field} must be a contract identifier")
    return value


def _safe_identifier(value: Any, fallback: str) -> str:
    if isinstance(value, str) and IDENTIFIER_RE.fullmatch(value):
        return value
    return fallback


def _safe_mode(value: Any) -> str:
    return value if value in {"simulate", "dry-run", "real"} else "simulate"


def _contract_validator(root: Path) -> Draft202012Validator:
    override = os.environ.get("THIRDHAND_CONTRACT_SCHEMA")
    override_path = Path(override) if override else None
    if override_path is not None and not override_path.is_absolute():
        override_path = root / override_path
    if override_path is not None:
        candidates = (override_path,)
    else:
        candidates = (
            root / "contracts" / "schema.json",
            root.parent / "contracts" / "schema.json",
        )
    schema_path = next((path for path in candidates if path.is_file()), None)
    if schema_path is None:
        raise AdapterBlocked(
            "contract_schema_unavailable",
            "schema.json was not found via THIRDHAND_CONTRACT_SCHEMA, "
            "the repository, or its parent folder; explicit overrides never fall back",
        )
    with schema_path.open("r", encoding="utf-8") as stream:
        schema = json.load(stream)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _validate_contract_message(
    validator: Draft202012Validator, message: Mapping[str, Any], label: str
) -> None:
    errors = sorted(validator.iter_errors(message), key=lambda item: list(item.absolute_path))
    if not errors:
        return
    leaves = []
    pending = list(errors)
    while pending:
        error = pending.pop()
        if error.context:
            pending.extend(error.context)
        else:
            leaves.append(error)
    error = max(leaves or errors, key=lambda item: len(item.absolute_path))
    location = ".".join(str(part) for part in error.absolute_path) or "<root>"
    raise AdapterBlocked(
        "schema_validation_failed",
        f"{label} failed schema validation at {location}: {error.message}",
    )


def _route_from_existing_runner(root: Path) -> tuple[list[str], dict[str, Any]]:
    bridge_path = root / BRIDGE_REF
    config_path = root / CONFIG_REF
    if not FIXED_RUNNER_PATH.is_file():
        raise AdapterBlocked("invalid_local_config", f"runner is missing: {FIXED_RUNNER_PATH}")
    if not bridge_path.is_file():
        raise AdapterBlocked("invalid_local_config", f"bridge is missing: {bridge_path}")
    if not config_path.is_file():
        raise AdapterBlocked("invalid_local_config", f"config is missing: {config_path}")

    config = fixed_runner.load_config(config_path)
    if config.get("workflow") != "home_transit_ab":
        raise AdapterBlocked("invalid_local_config", "fixed config must use home_transit_ab")
    if not math.isclose(float(config.get("speed_scale", 0.0)), MAX_SPEED_SCALE):
        raise AdapterBlocked("invalid_local_config", "fixed config speed_scale must be 0.15")

    sequence = fixed_runner.action_sequence_for(config)
    states = [state for state, _kind, _target in sequence]
    try:
        final_index = states.index(FINAL_ROUTE_STATE)
    except ValueError as exc:
        raise AdapterBlocked(
            "invalid_local_config",
            f"existing runner route does not contain {FINAL_ROUTE_STATE}",
        ) from exc
    return states[: final_index + 1], config


def _validate_base_request(request: Mapping[str, Any]) -> Mapping[str, Any]:
    if request.get("schemaVersion") != "1.0":
        raise AdapterBlocked("invalid_request", "schemaVersion must be 1.0")
    if request.get("type") != "execution.request":
        raise AdapterBlocked("invalid_request", "type must be execution.request")
    if request.get("source") != "orchestrator" or request.get("target") != "robot":
        raise AdapterBlocked("invalid_request", "request must be orchestrator -> robot")
    if request.get("status") != "ready":
        raise AdapterBlocked("invalid_request", "request status must be ready")

    for field in ("messageId", "sessionId", "traceId"):
        _identifier(request.get(field), field)
    timestamp = request.get("ts")
    if isinstance(timestamp, bool) or not isinstance(timestamp, int) or timestamp < 0:
        raise AdapterBlocked("invalid_request", "ts must be a non-negative integer")
    return _mapping(request.get("payload"), "payload")


def _validate_safety(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    safety = _mapping(payload.get("safety"), "payload.safety")
    for field in ("uniqueTargetAuthorized", "frameFresh", "mutuallyExclusiveMotion"):
        if safety.get(field) is not True:
            raise AdapterBlocked("safety_gate_failed", f"payload.safety.{field} must be true")
    if not isinstance(safety.get("physicalEStopReady"), bool):
        raise AdapterBlocked(
            "invalid_request", "payload.safety.physicalEStopReady must be boolean"
        )
    speed = safety.get("speedScale")
    if isinstance(speed, bool) or not isinstance(speed, (int, float)):
        raise AdapterBlocked("invalid_request", "payload.safety.speedScale must be numeric")
    if not math.isfinite(float(speed)) or float(speed) != MAX_SPEED_SCALE:
        raise AdapterBlocked("safety_gate_failed", "safety speedScale must be 0.15")
    return safety


def _validate_identity_binding(
    request: Mapping[str, Any],
    payload: Mapping[str, Any],
    expected_identity: Mapping[str, str] | None,
) -> None:
    """Compare the request with an optional Orchestrator-supplied binding.

    ``execution.request`` contains identifiers but no upstream confirmation or
    vision evidence.  When the Orchestrator supplies a trusted binding, all four
    values are required and compared.  Without it, this adapter can only validate
    identifier syntax and the contract's authorization booleans.
    """

    if expected_identity is None:
        return
    actual = {
        "traceId": request.get("traceId"),
        "candidateId": payload.get("candidateId"),
        "decisionId": payload.get("decisionId"),
        "targetId": payload.get("targetId"),
    }
    for field, value in actual.items():
        expected = expected_identity.get(field)
        if not isinstance(expected, str):
            raise AdapterBlocked(
                "identity_binding_invalid",
                f"trusted identity binding is missing {field}",
            )
        if value != expected:
            raise AdapterBlocked(
                "identity_mismatch",
                f"{field} does not match the trusted Orchestrator binding",
            )


def _validate_fixed_plan(
    plan: Mapping[str, Any], expected_route: list[str]
) -> tuple[str, list[str]]:
    if plan.get("kind") == "act_chunk":
        raise AdapterBlocked(
            "action_chunk_adapter_unavailable",
            "startouch_action_chunk_adapter_v1 is not installed",
        )

    constants = {
        "kind": "fixed_waypoint_a_to_b",
        "adapterId": ADAPTER_ID,
        "bridgeRef": BRIDGE_REF,
        "configRef": CONFIG_REF,
        "sourceWorkflow": "home_transit_ab",
        "sourceZoneId": "pick_zone_a",
        "destinationZoneId": "drop_zone_b",
        "cycles": 1,
        "confirmEachStep": True,
    }
    for field, expected in constants.items():
        if plan.get(field) != expected:
            raise AdapterBlocked("invalid_execution_plan", f"executionPlan.{field} is invalid")

    plan_id = _identifier(plan.get("planId"), "payload.executionPlan.planId")
    speed = plan.get("speedScale")
    if isinstance(speed, bool) or not isinstance(speed, (int, float)):
        raise AdapterBlocked("invalid_execution_plan", "executionPlan.speedScale must be numeric")
    if not math.isclose(float(speed), MAX_SPEED_SCALE):
        raise AdapterBlocked("invalid_execution_plan", "executionPlan.speedScale must be 0.15")

    route = plan.get("routeStates")
    if route != expected_route:
        raise AdapterBlocked(
            "invalid_execution_plan",
            f"routeStates must end at {FINAL_ROUTE_STATE} with no B-to-A continuation",
        )
    return plan_id, list(route)


def _empty_bridge_evidence() -> dict[str, Any]:
    return {
        "bridgeRef": BRIDGE_REF,
        "commandCompleteCount": 0,
        "finalRobotStateRef": None,
        "postMotionJointFeedbackVerified": False,
        "gripperFeedbackVerified": False,
        "canFeedbackVerified": False,
        "softwareStopConfirmed": False,
    }


def _local_no_motion_dry_run_preflight(root: Path, route: list[str]) -> None:
    """Verify local references and route without constructing robot objects."""

    required = (
        root / BRIDGE_REF,
        root / CONFIG_REF,
        root / "web-control" / "scripts" / "fixed_pick_place.py",
    )
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise AdapterFailure(
            "local_preflight_failed",
            "required local execution references are missing: " + ", ".join(missing),
        )
    if len(route) != 11 or route[-1] != FINAL_ROUTE_STATE:
        raise AdapterFailure(
            "local_preflight_failed",
            "fixed A-to-B route is not the required 11-state route ending at HOME",
        )


def _result_context(request: Mapping[str, Any]) -> tuple[str, str, str, str]:
    payload = request.get("payload") if isinstance(request.get("payload"), Mapping) else {}
    plan = payload.get("executionPlan") if isinstance(payload.get("executionPlan"), Mapping) else {}
    return (
        _safe_identifier(request.get("sessionId"), "session-local-simulate"),
        _safe_identifier(request.get("traceId"), "trace-local-simulate"),
        _safe_identifier(payload.get("candidateId"), "candidate-blocked"),
        _safe_identifier(plan.get("planId"), "sequence-blocked"),
    )


def _build_result(
    request: Mapping[str, Any],
    *,
    status: str,
    executed_steps: int,
    now_ms: int,
    error: AdapterBlocked | AdapterFailure | None = None,
) -> dict[str, Any]:
    session_id, trace_id, candidate_id, sequence_id = _result_context(request)
    result: dict[str, Any] = {
        "schemaVersion": "1.0",
        "type": "execution.result",
        "messageId": f"msg-{uuid.uuid4().hex}",
        "replyTo": (
            request.get("messageId")
            if isinstance(request.get("messageId"), str)
            and IDENTIFIER_RE.fullmatch(request["messageId"])
            else None
        ),
        "sessionId": session_id,
        "traceId": trace_id,
        "ts": now_ms,
        "source": "robot",
        "target": "orchestrator",
        "mode": _safe_mode(request.get("mode")),
        "status": status,
        "payload": {
            "candidateId": candidate_id,
            "sequenceId": sequence_id,
            "executor": "fixed_pick_place_adapter",
            "executedSteps": executed_steps,
            "hardwareFeedbackVerified": False,
            "safetyEvent": status != "success",
            "bridgeEvidence": _empty_bridge_evidence(),
        },
    }
    if error is not None:
        message = str(error)
        result["error"] = {
            "code": error.code,
            "message": message[:1000],
            "retryable": False,
        }
    return result


def process_execution_request(
    request: Mapping[str, Any],
    *,
    root: Path = ROOT,
    now_ms: int | None = None,
    expected_identity: Mapping[str, str] | None = None,
    dry_run_probe: Any | None = None,
) -> dict[str, Any]:
    """Validate and process one contract ``execution.request``.

    No bridge or runner object is constructed.  For ``simulate``,
    ``executedSteps`` counts route states processed by the software simulator,
    not physical robot motion.  For ``dry-run``, it remains zero because the
    preflight performs no route execution at all.
    """

    timestamp = int(time.time() * 1000) if now_ms is None else now_ms
    try:
        validator = _contract_validator(root)
        _validate_contract_message(validator, request, "execution.request")
        payload = _validate_base_request(request)
        _identifier(payload.get("candidateId"), "payload.candidateId")
        _identifier(payload.get("decisionId"), "payload.decisionId")
        _identifier(payload.get("targetId"), "payload.targetId")
        _validate_identity_binding(request, payload, expected_identity)
        if payload.get("confirmed") is not True:
            raise AdapterBlocked("confirmation_required", "confirmed must be true")
        _validate_safety(payload)

        plan = _mapping(payload.get("executionPlan"), "payload.executionPlan")
        mode = request.get("mode")
        if mode == "real":
            raise AdapterBlocked(
                "real_mode_disabled",
                "real mode is disabled for this delivery; no hardware command was sent",
            )

        try:
            expected_route, _config = _route_from_existing_runner(root)
        except AdapterBlocked:
            raise
        except Exception as exc:
            raise AdapterFailure(
                "local_preflight_failed",
                f"fixed runner or YAML validation failed: {exc}",
            ) from exc
        _plan_id, route = _validate_fixed_plan(plan, expected_route)
        if mode == "dry-run":
            probe = dry_run_probe or _local_no_motion_dry_run_preflight
            try:
                probe(root, route)
            except (AdapterBlocked, AdapterFailure):
                raise
            except Exception as exc:
                raise AdapterFailure(
                    "local_preflight_failed",
                    f"dry-run preflight failed: {exc}",
                ) from exc
            executed_steps = 0
        elif mode == "simulate":
            executed_steps = len(route)
        else:
            raise AdapterBlocked("invalid_request", "mode must be simulate, dry-run or real")
        result = _build_result(
            request,
            status="success",
            executed_steps=executed_steps,
            now_ms=timestamp,
        )
        _validate_contract_message(validator, result, "execution.result")
        return result
    except AdapterBlocked as exc:
        result = _build_result(
            request,
            status="blocked",
            executed_steps=0,
            now_ms=timestamp,
            error=exc,
        )
        validator = _contract_validator(root)
        _validate_contract_message(validator, result, "blocked execution.result")
        return result
    except AdapterFailure as exc:
        result = _build_result(
            request,
            status="failure",
            executed_steps=0,
            now_ms=timestamp,
            error=exc,
        )
        validator = _contract_validator(root)
        _validate_contract_message(validator, result, "failed execution.result")
        return result


def _read_request(path: str) -> Mapping[str, Any]:
    if path == "-":
        data = loads_json_strict(sys.stdin.read())
    else:
        with Path(path).open("r", encoding="utf-8") as stream:
            data = loads_json_strict(stream.read())
    if not isinstance(data, Mapping):
        raise ValueError("request JSON must be an object")
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "request",
        nargs="?",
        default="-",
        help="execution.request JSON file, or - for standard input",
    )
    parser.add_argument("--compact", action="store_true", help="print compact JSON")
    args = parser.parse_args()

    try:
        request = _read_request(args.request)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"cannot read execution.request: {exc}", file=sys.stderr)
        return 2

    result = process_execution_request(request)
    json.dump(
        result,
        sys.stdout,
        ensure_ascii=False,
        indent=None if args.compact else 2,
        separators=(",", ":") if args.compact else None,
    )
    print()
    return 0 if result["status"] == "success" else 3


if __name__ == "__main__":
    raise SystemExit(main())
