"""Tests for the Policy handler, validating every result against schema.json."""

import json
from pathlib import Path

import pytest

from thirdhand_policy.handler import handle_policy_action_request
from thirdhand_policy.schema import load_schema

try:
    from jsonschema import Draft202012Validator
except ImportError:  # pragma: no cover
    Draft202012Validator = None

ROOT = Path(__file__).resolve().parents[1]


def _validator():
    return Draft202012Validator(load_schema()) if Draft202012Validator is not None else None


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


def _assert_schema_valid(message: dict) -> None:
    validator = _validator()
    if validator is None:
        return  # jsonschema not installed; skip full validation
    errors = list(validator.iter_errors(message))
    assert not errors, f"message violates schema: {errors[0].json_path}: {errors[0].message}"


def test_fixed_baseline_returns_valid_result():
    request = _request()
    result = handle_policy_action_request(request, {"enable_fake": False})
    assert result["type"] == "policy.action.result"
    assert result["status"] == "ready"
    assert result["payload"]["policy"]["kind"] == "fixed_baseline"
    assert result["payload"]["executionPlan"]["kind"] == "fixed_waypoint_a_to_b"
    _assert_schema_valid(result)


def test_fake_act_returns_valid_result():
    request = _request()
    request["payload"]["allowedPolicyKinds"] = ["fake_act"]
    result = handle_policy_action_request(
        request, {"enable_fake": True, "act_chunk_adapter_available": True}
    )
    assert result["status"] == "ready"
    assert result["payload"]["policy"]["kind"] == "fake_act"
    plan = result["payload"]["executionPlan"]
    assert plan["kind"] == "act_chunk"
    steps = plan["actionChunk"]["steps"]
    assert len(steps) == 3
    assert plan["actionChunk"]["jointUnit"] == "rad"
    assert plan["actionChunk"]["gripperUnit"] == "normalized_0_1"
    _assert_schema_valid(result)


def test_wrong_type_returns_service_error():
    request = _request(type="vision.target.request")
    result = handle_policy_action_request(request)
    assert result["type"] == "service.error"
    assert result["payload"]["stage"] == "policy"
    _assert_schema_valid(result)


def test_incompatible_action_space_returns_error():
    request = _request()
    request["payload"]["actionSpaceId"] = "some-other-space-v1"
    result = handle_policy_action_request(request)
    assert result["type"] == "service.error"
    assert result["error"]["code"] == "incompatible_action_space"
    _assert_schema_valid(result)


def test_no_allowed_kind_returns_error():
    request = _request()
    request["payload"]["allowedPolicyKinds"] = ["lerobot_act"]  # no checkpoint -> unavailable
    result = handle_policy_action_request(request, {"enable_fake": False})
    assert result["type"] == "service.error"
    assert result["error"]["code"] == "policy_unavailable"
    _assert_schema_valid(result)


def test_missing_traceid_rejected():
    request = _request()
    del request["traceId"]
    result = handle_policy_action_request(request)
    assert result["type"] == "service.error"
    assert result["error"]["code"] == "bad_request"


def test_lerobot_act_without_checkpoint_falls_back_to_fixed_baseline():
    request = _request()
    request["payload"]["allowedPolicyKinds"] = ["lerobot_act", "fixed_baseline"]
    result = handle_policy_action_request(request, {"enable_fake": False})
    # checkpoint missing but fixed_baseline is allowed and available -> ready via fixed
    assert result["status"] == "ready"
    assert result["payload"]["policy"]["kind"] == "fixed_baseline"


def test_act_chunk_falls_back_to_fixed_baseline_when_adapter_unavailable():
    request = _request()
    request["payload"]["allowedPolicyKinds"] = ["fake_act", "fixed_baseline"]
    result = handle_policy_action_request(request, {})
    # startouch_action_chunk_adapter_v1 not registered -> act_chunk is not offered
    assert result["status"] == "ready"
    assert result["payload"]["policy"]["kind"] == "fixed_baseline"
    assert result["payload"]["executionPlan"]["kind"] == "fixed_waypoint_a_to_b"


def test_act_chunk_fails_closed_when_adapter_unavailable_and_fixed_not_allowed():
    request = _request()
    request["payload"]["allowedPolicyKinds"] = ["fake_act"]
    result = handle_policy_action_request(request, {})
    assert result["type"] == "service.error"
    assert result["error"]["code"] == "policy_unavailable"


def test_unauthorized_target_rejected():
    request = _request()
    request["payload"]["target"]["authorized"] = False
    result = handle_policy_action_request(request, {})
    assert result["type"] == "service.error"
    assert result["error"]["code"] == "target_not_authorized"


def test_non_unique_target_rejected():
    request = _request()
    request["payload"]["target"]["uniqueTarget"] = False
    result = handle_policy_action_request(request, {})
    assert result["type"] == "service.error"
    assert result["error"]["code"] == "target_not_authorized"


def test_non_coke_label_rejected():
    request = _request()
    request["payload"]["target"]["label"] = "pepsi_bottle"
    result = handle_policy_action_request(request, {})
    assert result["type"] == "service.error"
    assert result["error"]["code"] == "target_not_authorized"


def test_generic_bottle_label_rejected():
    request = _request()
    request["payload"]["target"]["label"] = "bottle"
    result = handle_policy_action_request(request, {})
    assert result["type"] == "service.error"
    assert result["error"]["code"] == "target_not_authorized"


def test_handler_does_not_embed_images_or_tensors():
    request = _request()
    result = handle_policy_action_request(request)
    text = json.dumps(result, ensure_ascii=False)
    assert len(text) < 5000  # plans are references + small numeric steps, never binary


@pytest.mark.parametrize("key", ["targetId", "frameId", "maskRef"])
def test_missing_target_field_rejected(key):
    request = _request()
    del request["payload"]["target"][key]
    result = handle_policy_action_request(request, {})
    assert result["type"] == "service.error"
    assert result["error"]["code"] == "target_not_authorized"
    assert "executionPlan" not in result


def test_missing_robot_state_ref_rejected():
    request = _request()
    del request["payload"]["robotStateRef"]
    result = handle_policy_action_request(request, {})
    assert result["type"] == "service.error"
    assert result["error"]["code"] == "target_not_authorized"
    assert "executionPlan" not in result


def test_lerobot_act_without_checkpoint_rejected():
    request = _request()
    request["payload"]["allowedPolicyKinds"] = ["lerobot_act"]
    result = handle_policy_action_request(request, {"enable_fake": False})
    assert result["type"] == "service.error"
    assert result["error"]["code"] == "policy_unavailable"
    assert "executionPlan" not in result


def test_internal_policy_error_returns_service_error_without_plan(monkeypatch):
    from thirdhand_policy import handler as handler_module
    from thirdhand_policy.policies import PolicyError

    def _boom(payload, config):
        raise PolicyError("internal_policy_error", "simulated policy crash")

    monkeypatch.setitem(handler_module._PRODUCERS, "fixed_baseline", _boom)
    request = _request()
    request["payload"]["allowedPolicyKinds"] = ["fixed_baseline"]
    result = handle_policy_action_request(request, {})
    assert result["type"] == "service.error"
    assert result["error"]["code"] == "internal_policy_error"
    assert "executionPlan" not in result
