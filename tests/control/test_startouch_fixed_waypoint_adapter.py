from __future__ import annotations

import importlib.util
import socket
import subprocess
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
ADAPTER_PATH = ROOT / "web-control" / "scripts" / "startouch_fixed_waypoint_adapter.py"
SPEC = importlib.util.spec_from_file_location("startouch_fixed_waypoint_adapter", ADAPTER_PATH)
assert SPEC and SPEC.loader
adapter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(adapter)


def execution_request() -> dict:
    route, _config = adapter._route_from_existing_runner(ROOT)
    return {
        "schemaVersion": "1.0",
        "type": "execution.request",
        "messageId": "msg-control-001",
        "replyTo": "msg-confirmation-001",
        "sessionId": "session-control-001",
        "traceId": "trace-control-001",
        "ts": 1786890000000,
        "source": "orchestrator",
        "target": "robot",
        "mode": "simulate",
        "status": "ready",
        "payload": {
            "candidateId": "candidate-control-001",
            "decisionId": "decision-control-001",
            "confirmed": True,
            "targetId": "coke-01",
            "executionPlan": {
                "kind": "fixed_waypoint_a_to_b",
                "planId": "plan-control-001",
                "adapterId": "startouch_fixed_waypoint_adapter_v1",
                "bridgeRef": "web-control/server/startouch_bridge.py",
                "configRef": "configs/tasks/fixed_pick_place.yaml",
                "sourceWorkflow": "home_transit_ab",
                "sourceZoneId": "pick_zone_a",
                "destinationZoneId": "drop_zone_b",
                "routeStates": route,
                "cycles": 1,
                "confirmEachStep": True,
                "speedScale": 0.15,
            },
            "safety": {
                "uniqueTargetAuthorized": True,
                "frameFresh": True,
                "mutuallyExclusiveMotion": True,
                "physicalEStopReady": False,
                "speedScale": 0.15,
            },
        },
    }


def test_simulate_returns_truthful_contract_result_without_hardware_feedback():
    request = execution_request()
    result = adapter.process_execution_request(request, root=ROOT, now_ms=1786890000100)

    assert result["status"] == "success"
    assert result["mode"] == "simulate"
    assert result["messageId"] != request["messageId"]
    assert result["replyTo"] == request["messageId"]
    assert result["sessionId"] == request["sessionId"]
    assert result["traceId"] == request["traceId"]
    assert result["source"] == "robot"
    assert result["target"] == "orchestrator"
    assert result["payload"]["sequenceId"] == "plan-control-001"
    assert result["payload"]["executedSteps"] == 11
    assert result["payload"]["hardwareFeedbackVerified"] is False
    assert result["payload"]["safetyEvent"] is False
    assert result["payload"]["bridgeEvidence"] == adapter._empty_bridge_evidence()


def test_simulate_does_not_construct_bridge_or_runner():
    with (
        patch.object(adapter.fixed_runner, "BridgeClient", side_effect=AssertionError),
        patch.object(adapter.fixed_runner, "FixedPickPlaceRunner", side_effect=AssertionError),
    ):
        result = adapter.process_execution_request(execution_request(), root=ROOT)
    assert result["status"] == "success"


def test_simulate_and_dry_run_cannot_touch_bridge_sdk_can_or_commands():
    real_import = __import__

    def guarded_import(name, *args, **kwargs):
        if name == "startouchclass" or name.startswith("startouchclass."):
            raise AssertionError("vendor SDK import is prohibited")
        return real_import(name, *args, **kwargs)

    for mode in ("simulate", "dry-run"):
        request = execution_request()
        request["mode"] = mode
        with (
            patch.object(adapter.fixed_runner, "BridgeClient", side_effect=AssertionError),
            patch.object(adapter.fixed_runner, "FixedPickPlaceRunner", side_effect=AssertionError),
            patch.object(subprocess, "Popen", side_effect=AssertionError),
            patch.object(socket, "socket", side_effect=AssertionError),
            patch("builtins.__import__", side_effect=guarded_import),
        ):
            result = adapter.process_execution_request(request, root=ROOT)
        assert result["status"] == "success"
        assert result["payload"]["hardwareFeedbackVerified"] is False
        assert result["payload"]["bridgeEvidence"] == adapter._empty_bridge_evidence()


def test_route_stops_at_home_and_excludes_b_to_a_continuation():
    route, _config = adapter._route_from_existing_runner(ROOT)
    assert len(route) == 11
    assert route[-1] == "RETURN_B_UP_TO_HOME"
    assert "MOVE_HOME_TO_B_UP" not in route
    assert "TRANSFER_B_UP_TO_A_UP" not in route


def test_unconfirmed_request_is_blocked():
    request = execution_request()
    request["payload"]["confirmed"] = False
    result = adapter.process_execution_request(request, root=ROOT)
    assert result["status"] == "blocked"
    assert result["payload"]["executedSteps"] == 0
    assert result["error"]["code"] == "schema_validation_failed"


def test_missing_confirmation_is_blocked():
    request = execution_request()
    del request["payload"]["confirmed"]
    result = adapter.process_execution_request(request, root=ROOT)
    assert result["status"] == "blocked"
    assert result["payload"]["executedSteps"] == 0
    assert result["error"]["code"] == "schema_validation_failed"


def test_false_safety_gates_are_blocked_by_contract_validation():
    for field in (
        "uniqueTargetAuthorized",
        "frameFresh",
        "mutuallyExclusiveMotion",
    ):
        request = execution_request()
        request["payload"]["safety"][field] = False
        result = adapter.process_execution_request(request, root=ROOT)
        assert result["status"] == "blocked"
        assert result["error"]["code"] == "schema_validation_failed"


def test_fixed_plan_requires_matching_safety_speed_scale():
    request = execution_request()
    request["payload"]["safety"]["speedScale"] = 0.10
    result = adapter.process_execution_request(request, root=ROOT)
    assert result["status"] == "blocked"
    assert result["error"]["code"] == "safety_gate_failed"


@pytest.mark.parametrize("speed", [0, -0.1, 0.16])
def test_out_of_contract_safety_speed_is_blocked(speed):
    request = execution_request()
    request["payload"]["safety"]["speedScale"] = speed
    result = adapter.process_execution_request(request, root=ROOT)
    assert result["status"] == "blocked"
    assert result["payload"]["executedSteps"] == 0
    assert result["error"]["code"] == "schema_validation_failed"


def test_wrong_or_extended_route_is_blocked():
    request = execution_request()
    request["payload"]["executionPlan"]["routeStates"].append("MOVE_HOME_TO_B_UP")
    result = adapter.process_execution_request(request, root=ROOT)
    assert result["status"] == "blocked"
    assert result["error"]["code"] == "schema_validation_failed"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("adapterId", "unregistered_robot_adapter_v1"),
        ("kind", "unsupported_plan_kind"),
    ],
)
def test_unknown_adapter_or_plan_kind_is_blocked_by_contract(field, value):
    request = execution_request()
    request["payload"]["executionPlan"][field] = value
    result = adapter.process_execution_request(request, root=ROOT)
    assert result["status"] == "blocked"
    assert result["payload"]["executedSteps"] == 0
    assert result["error"]["code"] == "schema_validation_failed"


def test_contract_rejects_an_invented_extra_field():
    request = execution_request()
    request["payload"]["inventedField"] = "must-not-be-accepted"
    result = adapter.process_execution_request(request, root=ROOT)
    assert result["status"] == "blocked"
    assert result["error"]["code"] == "schema_validation_failed"


def test_inbound_schema_validation_precedes_unsupported_mode_block():
    request = execution_request()
    request["mode"] = "dry-run"
    request["payload"]["inventedField"] = "must-not-be-accepted"
    result = adapter.process_execution_request(request, root=ROOT)
    assert result["status"] == "blocked"
    assert result["mode"] == "dry-run"
    assert result["error"]["code"] == "schema_validation_failed"


def test_action_chunk_is_blocked_when_adapter_is_unavailable():
    request = execution_request()
    request["payload"]["executionPlan"] = {
        "kind": "act_chunk",
        "planId": "plan-act-001",
        "adapterId": "startouch_action_chunk_adapter_v1",
        "bridgeRef": "web-control/server/startouch_bridge.py",
        "actionChunk": {
            "sequenceId": "sequence-act-001",
            "actionSpaceId": "startouch-j1-j6-rad-gripper-v1",
            "jointOrder": ["J1", "J2", "J3", "J4", "J5", "J6"],
            "jointUnit": "rad",
            "gripperUnit": "normalized_0_1",
            "steps": [
                {
                    "dtMs": 100,
                    "jointsRad": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                    "gripperNormalized": 1.0,
                }
            ],
        },
    }
    result = adapter.process_execution_request(request, root=ROOT)
    assert result["status"] == "blocked"
    assert result["error"]["code"] == "action_chunk_adapter_unavailable"


def test_dry_run_returns_success_with_zero_executed_steps_and_no_evidence():
    request = execution_request()
    request["mode"] = "dry-run"
    result = adapter.process_execution_request(request, root=ROOT, now_ms=1786890000200)
    assert result["status"] == "success"
    assert result["mode"] == "dry-run"
    assert result["payload"]["executedSteps"] == 0
    assert result["payload"]["hardwareFeedbackVerified"] is False
    assert result["payload"]["safetyEvent"] is False
    assert result["payload"]["bridgeEvidence"] == adapter._empty_bridge_evidence()


def test_real_without_estop_is_schema_blocked_and_real_with_estop_is_disabled():
    without_estop = execution_request()
    without_estop["mode"] = "real"
    blocked = adapter.process_execution_request(without_estop, root=ROOT)
    assert blocked["status"] == "blocked"
    assert blocked["error"]["code"] == "schema_validation_failed"

    with_estop = execution_request()
    with_estop["mode"] = "real"
    with_estop["payload"]["safety"]["physicalEStopReady"] = True
    disabled = adapter.process_execution_request(with_estop, root=ROOT)
    assert disabled["status"] == "blocked"
    assert disabled["error"]["code"] == "real_mode_disabled"
    assert disabled["payload"]["bridgeEvidence"]["commandCompleteCount"] == 0


@pytest.mark.parametrize("field", ["traceId", "candidateId", "decisionId", "targetId"])
def test_trusted_identity_mismatch_is_blocked(field):
    request = execution_request()
    expected = {
        "traceId": request["traceId"],
        "candidateId": request["payload"]["candidateId"],
        "decisionId": request["payload"]["decisionId"],
        "targetId": request["payload"]["targetId"],
    }
    expected[field] = f"different-{field}"
    result = adapter.process_execution_request(
        request,
        root=ROOT,
        expected_identity=expected,
    )
    assert result["status"] == "blocked"
    assert result["error"]["code"] == "identity_mismatch"
    assert result["payload"]["executedSteps"] == 0


@pytest.mark.parametrize(
    ("code", "message"),
    [
        ("bridge_connection_failed", "synthetic bridge connection failure"),
        ("can_fault", "synthetic CAN fault"),
        ("state_stale", "synthetic stale state"),
        ("bridge_timeout", "synthetic bridge timeout"),
    ],
)
def test_dry_run_fault_injection_fails_closed_without_hardware_evidence(code, message):
    request = execution_request()
    request["mode"] = "dry-run"

    def fail_probe(_root, _route):
        raise adapter.AdapterFailure(code, message)

    result = adapter.process_execution_request(
        request,
        root=ROOT,
        dry_run_probe=fail_probe,
    )
    assert result["status"] == "failure"
    assert result["error"]["code"] == code
    assert result["payload"]["executedSteps"] == 0
    assert result["payload"]["hardwareFeedbackVerified"] is False
    assert result["payload"]["bridgeEvidence"] == adapter._empty_bridge_evidence()


def test_duplicate_json_keys_are_rejected():
    with pytest.raises(adapter.DuplicateKeyError):
        adapter.loads_json_strict('{"mode":"simulate","mode":"real"}')


def test_explicit_missing_contract_schema_does_not_fall_back(monkeypatch, tmp_path):
    missing = tmp_path / "missing-schema.json"
    monkeypatch.setenv("THIRDHAND_CONTRACT_SCHEMA", str(missing))
    with pytest.raises(adapter.AdapterBlocked) as caught:
        adapter._contract_validator(ROOT)
    assert caught.value.code == "contract_schema_unavailable"


def test_input_request_is_not_mutated():
    request = execution_request()
    before = deepcopy(request)
    adapter.process_execution_request(request, root=ROOT)
    assert request == before
