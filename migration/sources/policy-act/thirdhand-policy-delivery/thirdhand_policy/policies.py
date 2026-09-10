"""
Policy implementations: turn a ``policy.action.request`` payload into an
execution plan (``fixedWaypointPlan`` or ``actChunkPlan``).

Three kinds are supported:

* ``fixed_baseline`` -- reuse the existing Startouch A/B waypoints (no model).
* ``fake_act`` -- deterministic act_chunk for integration tests (no model).
* ``lerobot_act`` -- load a trained LeRobot ACT checkpoint and emit a chunk.
"""

from __future__ import annotations

from typing import Any

from . import messages


class PolicyError(Exception):
    """A policy failure that maps to ``service.error`` (never a fake success)."""

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


#: Safe resting joints (radians) used by ``fake_act`` when no state is resolved.
_FAKE_JOINTS_RAD = [0.0, 0.2, -0.8, 0.0, 0.0, 0.0]


def fixed_baseline_plan(payload: dict[str, Any], config: dict[str, Any]) -> tuple[dict, dict]:
    """Return the fixed ``pick_zone_a -> drop_zone_b`` waypoint plan."""
    plan = messages.make_fixed_waypoint_plan()
    meta = {
        "id": "fixed_baseline",
        "version": "1.0",
        "kind": messages.FIXED_BASELINE,
        "checkpoint": None,
    }
    return plan, meta


def fake_act_plan(payload: dict[str, Any], config: dict[str, Any]) -> tuple[dict, dict]:
    """Return a deterministic act_chunk (open gripper over ``fake_steps`` steps)."""
    steps_count = int(config.get("fake_steps", 3))
    dt_ms = int(config.get("dt_ms", 100))
    steps = []
    for index in range(steps_count):
        gripper = index / max(1, steps_count - 1)  # 0 (closed) -> 1 (open)
        steps.append(messages.make_action_step(dt_ms, _FAKE_JOINTS_RAD, gripper))
    plan = messages.make_act_chunk_plan(steps)
    meta = {
        "id": "fake_act",
        "version": "1.0",
        "kind": messages.FAKE_ACT,
        "checkpoint": None,
    }
    return plan, meta


def lerobot_act_plan(payload: dict[str, Any], config: dict[str, Any]) -> tuple[dict, dict]:
    """Run the trained LeRobot ACT policy and emit an ``act_chunk`` plan."""
    checkpoint = config.get("checkpoint")
    if not checkpoint:
        raise PolicyError("checkpoint_missing", "no ACT checkpoint is configured")

    steps = _run_act(checkpoint, payload, config)

    plan = messages.make_act_chunk_plan(steps)
    meta = {
        "id": "lerobot_act",
        "version": str(config.get("policy_version", "1.0")),
        "kind": messages.LEROBOT_ACT,
        "checkpoint": checkpoint,
    }
    return plan, meta


def _run_act(checkpoint: str, payload: dict[str, Any], config: dict[str, Any]) -> list[dict]:
    """Load the ACT policy and convert its chunk into ``actionStep`` dicts.

    This is the LeRobot boundary: it lazy-imports torch/lerobot so the service
    starts and serves ``fixed_baseline``/``fake_act`` even on hosts without a
    GPU. It also rejects a checkpoint whose action space is not
    ``startouch-j1-j6-rad-gripper-v1`` rather than silently reusing it.
    """
    try:
        from .act_runner import run_action_chunk
    except ImportError as exc:  # torch / lerobot not installed on this host
        raise PolicyError("lerobot_unavailable", f"lerobot/torch unavailable: {exc}") from exc

    try:
        return run_action_chunk(checkpoint=checkpoint, payload=payload, config=config)
    except PolicyError:
        raise
    except Exception as exc:  # model load or inference failure
        raise PolicyError("policy_inference_failed", str(exc)) from exc
