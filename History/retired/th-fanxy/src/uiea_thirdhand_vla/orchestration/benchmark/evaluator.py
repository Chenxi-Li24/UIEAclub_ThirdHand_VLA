"""Deterministic evaluator for safe and deliberately unsafe shadow baselines."""

from __future__ import annotations

import json
from pathlib import Path

from ..runtime.adapters import FakeExecutor, ReplayObservationSource
from ..runtime.models import (
    GroundTruth,
    ReceiptStatus,
    RuntimeState,
    Stage,
    Verdict,
)
from ..runtime.recovery import RecoveryManager
from ..runtime.registry import SkillRegistry
from ..runtime.supervisor import EvidenceGatedSupervisor
from ..runtime.trace import MemoryTrace
from .baselines import AdvanceDecision, BaselineKind, BenchmarkRun
from .models import ScenarioCase


def _truth_map(case: ScenarioCase) -> dict[tuple[str, int], GroundTruth]:
    return {(item.step_id, item.attempt): item for item in case.replay.ground_truth}


def _truth_for(label: GroundTruth | None, stage: Stage) -> Verdict | None:
    if label is None:
        return None
    return {
        Stage.EFFECT: label.effect,
        Stage.HANDOFF: label.handoff,
        Stage.TASK_GOAL: label.task_goal,
    }[stage]


class BenchmarkEvaluator:
    def __init__(self, registry: SkillRegistry) -> None:
        self._registry = registry

    @classmethod
    def from_skill_paths(cls, paths: tuple[Path, ...]) -> BenchmarkEvaluator:
        return cls(SkillRegistry.from_paths(paths))

    def run(self, case: ScenarioCase, baseline: BaselineKind) -> BenchmarkRun:
        if baseline is BaselineKind.RECEIPT_ONLY:
            return self._receipt_only(case)
        if baseline is BaselineKind.POST_ACTION:
            return self._post_action(case)
        return self._safe_runtime(case, baseline)

    def _safe_runtime(self, case: ScenarioCase, baseline: BaselineKind) -> BenchmarkRun:
        trace = MemoryTrace()
        try:
            result = EvidenceGatedSupervisor(
                registry=self._registry,
                observations=ReplayObservationSource(case.replay.observations),
                executor=FakeExecutor(case.replay.receipt_statuses),
                recovery=RecoveryManager(),
                trace=trace,
            ).run(case.replay.plan)
            events = result.events
            final_state = result.final_state
            completed_steps = result.completed_steps
            stop_reason = result.stop_reason
            dispatch_count = result.dispatch_count
            recovery_count = result.recovery_count
        except ValueError as exc:
            events = trace.events
            final_state = RuntimeState.STOPPED
            completed_steps = ()
            stop_reason = str(exc)
            dispatch_count = 0
            recovery_count = 0

        decisions = self._decisions_from_events(case, events)
        unknown_count = sum(item.verdict is Verdict.UNKNOWN for item in decisions)
        model_calls = 0
        if baseline is BaselineKind.ALWAYS_MODEL:
            model_calls = len(decisions)
        elif baseline is BaselineKind.HYBRID:
            model_calls = unknown_count
        return BenchmarkRun(
            scenario_id=case.scenario_id,
            family=case.family,
            condition=case.condition,
            baseline=baseline,
            expected_final_state=case.expectation.final_state,
            final_state=final_state,
            completed_steps=completed_steps,
            stop_reason=stop_reason,
            dispatch_count=dispatch_count,
            recovery_count=recovery_count,
            replan_count=0,
            model_call_count=model_calls,
            model_timeout_count=unknown_count if model_calls else 0,
            deterministic_latency_ms=(1.0,) * len(decisions),
            model_latency_ms=(25.0,) * model_calls,
            configured_cost_usd=round(model_calls * 0.001, 6),
            decisions=decisions,
            events=events,
        )

    @staticmethod
    def _decisions_from_events(case: ScenarioCase, events) -> tuple[AdvanceDecision, ...]:
        labels = _truth_map(case)
        advanced = {
            (event.step_id, event.attempt, event.event_type)
            for event in events
            if event.event_type in {"step_advanced", "episode_done"}
        }
        decisions: list[AdvanceDecision] = []
        event_stages = {
            "effect_result": Stage.EFFECT,
            "handoff_result": Stage.HANDOFF,
            "task_goal_result": Stage.TASK_GOAL,
        }
        for event in events:
            stage = event_stages.get(event.event_type)
            if stage is None or event.step_id is None:
                continue
            payload = json.loads(event.payload_json)
            advance_event = (
                "step_advanced" if stage in {Stage.EFFECT, Stage.HANDOFF} else "episode_done"
            )
            if stage is Stage.EFFECT:
                did_advance = any(
                    key[:2] == (event.step_id, event.attempt) for key in advanced
                )
            else:
                did_advance = (event.step_id, event.attempt, advance_event) in advanced
            label = labels.get((event.step_id, event.attempt))
            decisions.append(
                AdvanceDecision(
                    step_id=event.step_id,
                    attempt=event.attempt,
                    stage=stage,
                    verdict=Verdict(payload["verdict"]),
                    truth=_truth_for(label, stage),
                    advanced=did_advance,
                )
            )
        return tuple(decisions)

    def _receipt_only(self, case: ScenarioCase) -> BenchmarkRun:
        labels = _truth_map(case)
        decisions: list[AdvanceDecision] = []
        step_index = 0
        attempt = 0
        completed: list[str] = []
        for status in case.replay.receipt_statuses:
            if step_index >= len(case.replay.plan.steps):
                break
            if status is not ReceiptStatus.COMPLETED:
                attempt += 1
                continue
            step = case.replay.plan.steps[step_index]
            label = labels.get((step.step_id, attempt)) or labels.get((step.step_id, 0))
            stages = (
                (Stage.EFFECT, Stage.HANDOFF)
                if step_index + 1 < len(case.replay.plan.steps)
                else (Stage.EFFECT, Stage.TASK_GOAL)
            )
            decisions.extend(
                AdvanceDecision(
                    step_id=step.step_id,
                    attempt=attempt,
                    stage=stage,
                    verdict=Verdict.PASS,
                    truth=_truth_for(label, stage),
                    advanced=True,
                )
                for stage in stages
            )
            completed.append(step.step_id)
            step_index += 1
            attempt = 0
        done = step_index == len(case.replay.plan.steps)
        return self._reference_run(
            case,
            BaselineKind.RECEIPT_ONLY,
            decisions,
            completed,
            RuntimeState.DONE if done else RuntimeState.STOPPED,
            None if done else "receipt_not_completed",
            len(case.replay.receipt_statuses),
        )

    def _post_action(self, case: ScenarioCase) -> BenchmarkRun:
        labels = _truth_map(case)
        decisions: list[AdvanceDecision] = []
        completed: list[str] = []
        for index, step in enumerate(case.replay.plan.steps):
            label = labels.get((step.step_id, 0))
            effect = Verdict.UNKNOWN if label is None else label.effect
            did_advance = effect is Verdict.PASS
            decisions.append(
                AdvanceDecision(
                    step_id=step.step_id,
                    attempt=0,
                    stage=Stage.EFFECT,
                    verdict=effect,
                    truth=_truth_for(label, Stage.EFFECT),
                    advanced=did_advance,
                )
            )
            if not did_advance:
                break
            boundary = (
                Stage.HANDOFF
                if index + 1 < len(case.replay.plan.steps)
                else Stage.TASK_GOAL
            )
            decisions.append(
                AdvanceDecision(
                    step_id=step.step_id,
                    attempt=0,
                    stage=boundary,
                    verdict=Verdict.PASS,
                    truth=_truth_for(label, boundary),
                    advanced=True,
                )
            )
            completed.append(step.step_id)
        done = len(completed) == len(case.replay.plan.steps)
        return self._reference_run(
            case,
            BaselineKind.POST_ACTION,
            decisions,
            completed,
            RuntimeState.DONE if done else RuntimeState.STOPPED,
            None if done else "local_effect_not_passed",
            len(completed),
        )

    @staticmethod
    def _reference_run(
        case: ScenarioCase,
        baseline: BaselineKind,
        decisions: list[AdvanceDecision],
        completed: list[str],
        final_state: RuntimeState,
        stop_reason: str | None,
        dispatch_count: int,
    ) -> BenchmarkRun:
        return BenchmarkRun(
            scenario_id=case.scenario_id,
            family=case.family,
            condition=case.condition,
            baseline=baseline,
            expected_final_state=case.expectation.final_state,
            final_state=final_state,
            completed_steps=tuple(completed),
            stop_reason=stop_reason,
            dispatch_count=dispatch_count,
            recovery_count=0,
            replan_count=0,
            model_call_count=0,
            model_timeout_count=0,
            deterministic_latency_ms=(0.25,) * len(decisions),
            model_latency_ms=(),
            configured_cost_usd=0.0,
            decisions=tuple(decisions),
            events=(),
        )


__all__ = ["BenchmarkEvaluator"]
