"""
Message builders for the ThirdHand Policy module.

Every value produced here conforms to ``contracts/schema.json``. The Policy
module only speaks two message types (plus ``service.error``):

* inbound  ``policy.action.request``  (orchestrator -> policy)
* outbound ``policy.action.result``   (policy -> orchestrator)
* error    ``service.error``          (stage=policy)

Action space is fixed by the contract: ``startouch-j1-j6-rad-gripper-v1``,
joints in **radians**, order J1..J6, gripper ``0=closed 1=open``.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

SCHEMA_VERSION = "1.0"
COMPONENT_POLICY = "policy"
COMPONENT_ORCHESTRATOR = "orchestrator"

ACTION_SPACE_ID = "startouch-j1-j6-rad-gripper-v1"
JOINT_ORDER = ["J1", "J2", "J3", "J4", "J5", "J6"]
JOINT_COUNT = 6

FIXED_BASELINE = "fixed_baseline"
FAKE_ACT = "fake_act"
LEROBOT_ACT = "lerobot_act"
ALLOWED_POLICY_KINDS = (FIXED_BASELINE, FAKE_ACT, LEROBOT_ACT)

#: The fixed waypoint plan only ever runs the A -> B first half of the existing
#: ``home_transit_ab`` demonstration. The second half (B -> A) is forbidden.
ROUTE_STATES = [
    "OPEN_GRIPPER_READY",
    "MOVE_HOME_START",
    "APPROACH_A_UP",
    "DESCEND_TO_A_PICK",
    "ADAPTIVE_GRASP_A",
    "LIFT_A",
    "TRANSFER_A_UP_TO_B_UP",
    "DESCEND_TO_B",
    "RELEASE_AT_B",
    "LIFT_AFTER_RELEASE_B",
    "RETURN_B_UP_TO_HOME",
]

FIXED_ADAPTER_ID = "startouch_fixed_waypoint_adapter_v1"
ACT_CHUNK_ADAPTER_ID = "startouch_action_chunk_adapter_v1"
BRIDGE_REF = "web-control/server/startouch_bridge.py"
FIXED_CONFIG_REF = "configs/tasks/fixed_pick_place.yaml"


def new_id(prefix: str) -> str:
    """Return a schema-valid identifier (``^[A-Za-z0-9][A-Za-z0-9._:-]*$``)."""
    return f"{prefix}-{uuid.uuid4().hex}"


def now_ms() -> int:
    return int(time.time() * 1000)


def make_action_step(dt_ms: int, joints_rad, gripper_normalized: float) -> dict[str, Any]:
    """Build one ``actionStep``: {dtMs, jointsRad[6], gripperNormalized}."""
    values = [float(value) for value in joints_rad]
    if len(values) != JOINT_COUNT:
        raise ValueError(f"jointsRad must have {JOINT_COUNT} values, got {len(values)}")
    return {
        "dtMs": int(dt_ms),
        "jointsRad": values,
        "gripperNormalized": float(gripper_normalized),
    }


def make_action_chunk(steps: list[dict[str, Any]], *, sequence_id: str | None = None) -> dict[str, Any]:
    return {
        "sequenceId": sequence_id or new_id("seq"),
        "actionSpaceId": ACTION_SPACE_ID,
        "jointOrder": list(JOINT_ORDER),
        "jointUnit": "rad",
        "gripperUnit": "normalized_0_1",
        "steps": steps,
    }


def make_act_chunk_plan(
    steps: list[dict[str, Any]], *, plan_id: str | None = None, sequence_id: str | None = None
) -> dict[str, Any]:
    """Build an ``act_chunk`` execution plan (for the ``lerobot_act`` kind)."""
    return {
        "kind": "act_chunk",
        "planId": plan_id or new_id("plan"),
        "adapterId": ACT_CHUNK_ADAPTER_ID,
        "bridgeRef": BRIDGE_REF,
        "actionChunk": make_action_chunk(steps, sequence_id=sequence_id),
    }


def make_fixed_waypoint_plan(*, plan_id: str | None = None) -> dict[str, Any]:
    """Build the ``fixed_waypoint_a_to_b`` execution plan (for ``fixed_baseline``)."""
    return {
        "kind": "fixed_waypoint_a_to_b",
        "planId": plan_id or new_id("plan"),
        "adapterId": FIXED_ADAPTER_ID,
        "bridgeRef": BRIDGE_REF,
        "configRef": FIXED_CONFIG_REF,
        "sourceWorkflow": "home_transit_ab",
        "sourceZoneId": "pick_zone_a",
        "destinationZoneId": "drop_zone_b",
        "routeStates": list(ROUTE_STATES),
        "cycles": 1,
        "confirmEachStep": True,
        "speedScale": 0.15,
    }


def build_policy_action_result(
    request: dict[str, Any],
    *,
    status: str,
    policy_id: str,
    policy_version: str,
    kind: str,
    checkpoint: str | None,
    execution_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a ``policy.action.result`` message echoing the request context."""
    payload: dict[str, Any] = {
        "candidateId": request["payload"]["candidateId"],
        "targetId": request["payload"]["target"]["targetId"],
        "frameId": request["payload"]["target"]["frameId"],
        "policy": {
            "id": policy_id,
            "version": policy_version,
            "kind": kind,
            "checkpoint": checkpoint,
        },
    }
    if execution_plan is not None:
        payload["executionPlan"] = execution_plan

    return {
        "schemaVersion": SCHEMA_VERSION,
        "type": "policy.action.result",
        "messageId": new_id("msg"),
        "replyTo": request.get("messageId"),
        "sessionId": request.get("sessionId"),
        "traceId": request.get("traceId"),
        "ts": now_ms(),
        "source": COMPONENT_POLICY,
        "target": COMPONENT_ORCHESTRATOR,
        "mode": request.get("mode", "dry-run"),
        "status": status,
        "payload": payload,
    }


def build_service_error(
    request: dict[str, Any],
    *,
    code: str,
    message: str,
    retryable: bool = False,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a ``service.error`` message (stage=policy)."""
    return {
        "schemaVersion": SCHEMA_VERSION,
        "type": "service.error",
        "messageId": new_id("msg"),
        "replyTo": request.get("messageId"),
        "sessionId": request.get("sessionId"),
        "traceId": request.get("traceId"),
        "ts": now_ms(),
        "source": COMPONENT_POLICY,
        "target": COMPONENT_ORCHESTRATOR,
        "mode": request.get("mode", "dry-run"),
        "status": "failure",
        "payload": {"stage": "policy"},
        "error": {
            "code": code,
            "message": message,
            "retryable": retryable,
            "details": details or {},
        },
    }
