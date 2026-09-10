"""Frozen run records for five hardware-free benchmark references."""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import Field

from ..runtime.models import FrozenModel, RuntimeState, Stage, TraceEvent, Verdict
from .models import ScenarioFamily


class BaselineKind(str, Enum):
    RECEIPT_ONLY = "receipt_only"
    RULE_ONLY = "rule_only"
    POST_ACTION = "post_action"
    ALWAYS_MODEL = "always_model"
    HYBRID = "hybrid"


class AdvanceDecision(FrozenModel):
    step_id: str
    attempt: int = Field(ge=0)
    stage: Literal[Stage.EFFECT, Stage.HANDOFF, Stage.TASK_GOAL]
    verdict: Verdict
    truth: Verdict | None
    advanced: bool


class BenchmarkRun(FrozenModel):
    scenario_id: str
    family: ScenarioFamily
    condition: Literal["clean", "chained"]
    baseline: BaselineKind
    expected_final_state: RuntimeState
    final_state: RuntimeState
    completed_steps: tuple[str, ...]
    stop_reason: str | None
    dispatch_count: int = Field(ge=0)
    recovery_count: int = Field(ge=0)
    replan_count: int = Field(ge=0, le=1)
    model_call_count: int = Field(ge=0)
    model_timeout_count: int = Field(ge=0)
    deterministic_latency_ms: tuple[float, ...] = ()
    model_latency_ms: tuple[float, ...] = ()
    configured_cost_usd: float = Field(ge=0.0)
    decisions: tuple[AdvanceDecision, ...]
    events: tuple[TraceEvent, ...] = ()
    robot_execution_enabled: Literal[False] = False
    can_execute_world: Literal[False] = False

    @property
    def semantic_gate_count(self) -> int:
        return len(self.decisions)

    @property
    def unknown_count(self) -> int:
        return sum(item.verdict is Verdict.UNKNOWN for item in self.decisions)

    @property
    def false_advance_count(self) -> int:
        return sum(item.advanced and item.truth is not Verdict.PASS for item in self.decisions)

    @property
    def false_effect_advance_count(self) -> int:
        return self._false_count(Stage.EFFECT)

    @property
    def false_handoff_advance_count(self) -> int:
        return self._false_count(Stage.HANDOFF)

    @property
    def false_task_goal_advance_count(self) -> int:
        return self._false_count(Stage.TASK_GOAL)

    def _false_count(self, stage: Stage) -> int:
        return sum(
            item.stage is stage and item.advanced and item.truth is not Verdict.PASS
            for item in self.decisions
        )


__all__ = ["AdvanceDecision", "BaselineKind", "BenchmarkRun"]
