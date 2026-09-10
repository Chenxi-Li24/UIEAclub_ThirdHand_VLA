"""
Core handler: ``policy.action.request`` -> ``policy.action.result``.

The handler is a pure function (no HTTP) so it can be unit-tested directly and
wrapped by any transport. It follows the Policy-owner boundary in
``policy/policy.md``: validate the authorized target, pick an allowed policy
kind, produce an execution plan, and validate the outbound result.

``act_chunk`` (``lerobot_act`` / ``fake_act``) is only produced when the
independent ``startouch_action_chunk_adapter_v1`` is registered/available;
otherwise the Policy falls back to ``fixed_baseline`` or fails closed -- it never
emits an ``act_chunk`` that the Robot module cannot execute.
"""

from __future__ import annotations

import logging
from typing import Any

from . import messages
from .policies import PolicyError, fake_act_plan, fixed_baseline_plan, lerobot_act_plan
from .schema import validate_message

LOG = logging.getLogger(__name__)

_PRODUCERS = {
    messages.FIXED_BASELINE: fixed_baseline_plan,
    messages.FAKE_ACT: fake_act_plan,
    messages.LEROBOT_ACT: lerobot_act_plan,
}


def handle_policy_action_request(request: dict[str, Any], config: dict[str, Any] | None = None) -> dict:
    """Handle one ``policy.action.request`` and return a contract-valid message."""
    config = config or {}

    if request.get("type") != "policy.action.request":
        return messages.build_service_error(
            request,
            code="bad_request",
            message="expected type 'policy.action.request'",
        )

    payload = request.get("payload") or {}

    target_error = _validate_target(payload)
    if target_error:
        return messages.build_service_error(
            request,
            code="target_not_authorized",
            message=target_error,
        )

    if payload.get("actionSpaceId") != messages.ACTION_SPACE_ID:
        return messages.build_service_error(
            request,
            code="incompatible_action_space",
            message=f"actionSpaceId must be {messages.ACTION_SPACE_ID}",
        )

    errors = validate_message(request)
    if errors:
        return messages.build_service_error(
            request,
            code="bad_request",
            message="; ".join(errors[:5]),
        )

    kind = _choose_kind(payload.get("allowedPolicyKinds") or [], config)
    if kind is None:
        return messages.build_service_error(
            request,
            code="policy_unavailable",
            message="no allowed policy kind is available on this host",
        )

    try:
        plan, meta = _PRODUCERS[kind](payload, config)
    except PolicyError as exc:
        return messages.build_service_error(
            request,
            code=exc.code,
            message=exc.message,
            retryable=exc.retryable,
        )

    result = messages.build_policy_action_result(
        request,
        status="ready",
        policy_id=meta["id"],
        policy_version=meta["version"],
        kind=meta["kind"],
        checkpoint=meta["checkpoint"],
        execution_plan=plan,
    )

    out_errors = validate_message(result)
    if out_errors:
        # Never emit an invalid result; this is an internal bug, not a fake success.
        LOG.error("generated an invalid policy.action.result: %s", out_errors)
        return messages.build_service_error(
            request,
            code="internal",
            message="generated result failed schema validation",
        )
    return result


def _validate_target(payload: dict[str, Any]) -> str | None:
    """Validate the authorized target references (fail closed, per policy.md).

    The Policy only plans motion for a unique, Vision-authorized Coke target:
    ``uniqueTarget``/``authorized`` must be true and the target must carry the
    matching ``targetId``/``frameId``/``maskRef`` plus a ``robotStateRef``.
    """
    target = payload.get("target")
    if not isinstance(target, dict):
        return "payload.target is missing"
    if target.get("label") != "coke_bottle":
        return "target.label must be 'coke_bottle' (refusing non-Coke targets)"
    if target.get("uniqueTarget") is not True:
        return "target.uniqueTarget must be true (unique authorized Coke target required)"
    if target.get("authorized") is not True:
        return "target.authorized must be true"
    for key in ("targetId", "frameId", "maskRef"):
        if not target.get(key):
            return f"target.{key} is missing"
    if not payload.get("robotStateRef"):
        return "payload.robotStateRef is missing"
    return None


def _choose_kind(allowed: list[str], config: dict[str, Any]) -> str | None:
    """Choose the first *allowed* policy kind that is actually available.

    ``act_chunk`` (``lerobot_act`` / ``fake_act``) is gated on the independent
    ``startouch_action_chunk_adapter_v1`` being registered/available; without it
    the Policy only offers ``fixed_baseline``, or fails closed.
    """
    act_adapter_available = bool(config.get("act_chunk_adapter_available", False))

    available: list[str] = []
    if act_adapter_available and config.get("checkpoint"):
        available.append(messages.LEROBOT_ACT)
    available.append(messages.FIXED_BASELINE)
    if act_adapter_available and config.get("enable_fake", True):
        available.append(messages.FAKE_ACT)

    for kind in available:
        if kind in allowed:
            return kind
    return None
