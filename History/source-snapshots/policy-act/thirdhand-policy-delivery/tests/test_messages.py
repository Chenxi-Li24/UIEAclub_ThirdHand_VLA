"""Tests for the Policy message builders (unit-level, no schema round-trip)."""

import pytest

from thirdhand_policy import messages


def _request(**overrides):
    request = {
        "schemaVersion": "1.0",
        "type": "policy.action.request",
        "messageId": "msg-req-1",
        "replyTo": None,
        "sessionId": "sess-1",
        "traceId": "trace-1",
        "ts": 1700000000000,
        "source": "orchestrator",
        "target": "policy",
        "mode": "dry-run",
        "payload": {
            "candidateId": "cand-1",
            "target": {
                "targetId": "tgt-1",
                "label": "coke_bottle",
                "confidence": 0.95,
                "bbox": {"format": "xyxy", "coordinateSpace": "pixel", "values": [10, 20, 30, 40]},
                "maskRef": "mask-1",
                "frameId": "frame-1",
                "uniqueTarget": True,
                "authorized": True,
            },
            "robotStateRef": "state-1",
            "actionSpaceId": "startouch-j1-j6-rad-gripper-v1",
            "allowedPolicyKinds": ["fixed_baseline", "fake_act"],
        },
    }
    request.update(overrides)
    return request


def test_make_action_step_rejects_wrong_joint_count():
    with pytest.raises(ValueError):
        messages.make_action_step(100, [0.0, 0.0, 0.0], 0.5)


def test_make_fixed_waypoint_plan_route_is_a_to_b_only():
    plan = messages.make_fixed_waypoint_plan()
    assert plan["kind"] == "fixed_waypoint_a_to_b"
    assert plan["sourceZoneId"] == "pick_zone_a"
    assert plan["destinationZoneId"] == "drop_zone_b"
    assert plan["routeStates"][0] == "OPEN_GRIPPER_READY"
    assert plan["routeStates"][-1] == "RETURN_B_UP_TO_HOME"
    assert len(plan["routeStates"]) == 11


def test_build_result_preserves_trace_and_reply():
    request = _request()
    result = messages.build_policy_action_result(
        request,
        status="ready",
        policy_id="fixed_baseline",
        policy_version="1.0",
        kind="fixed_baseline",
        checkpoint=None,
        execution_plan=messages.make_fixed_waypoint_plan(),
    )
    assert result["type"] == "policy.action.result"
    assert result["traceId"] == "trace-1"
    assert result["replyTo"] == "msg-req-1"
    assert result["source"] == "policy"
    assert result["target"] == "orchestrator"
    assert result["payload"]["candidateId"] == "cand-1"
    assert result["payload"]["targetId"] == "tgt-1"
    assert result["payload"]["frameId"] == "frame-1"
