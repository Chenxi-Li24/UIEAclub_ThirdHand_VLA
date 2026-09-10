"""One-source-of-truth metrics for benchmark runs and baseline summaries."""

from __future__ import annotations

import math

from pydantic import Field

from ..runtime.models import FrozenModel, RuntimeState
from .baselines import BaselineKind, BenchmarkRun
from .models import ScenarioCase, ScenarioFamily


def nearest_rank(values: tuple[float, ...], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile * len(ordered)))
    return float(ordered[rank - 1])


class RunMetricsV2(FrozenModel):
    scenario_id: str
    family: ScenarioFamily
    condition: str
    baseline: BaselineKind
    final_state: RuntimeState
    advance_count: int = Field(ge=0)
    false_advance_count: int = Field(ge=0)
    false_effect_advance_count: int = Field(ge=0)
    false_handoff_advance_count: int = Field(ge=0)
    false_task_goal_advance_count: int = Field(ge=0)
    false_advance_rate: float = Field(ge=0.0, le=1.0)
    episode_success: bool
    safe_stop: bool
    false_abort: bool
    unknown_count: int = Field(ge=0)
    recovery_count: int = Field(ge=0)
    recovery_success: bool
    replan_count: int = Field(ge=0)
    dispatch_count: int = Field(ge=0)
    model_call_count: int = Field(ge=0)
    model_timeout_count: int = Field(ge=0)
    deterministic_latency_p50_ms: float = Field(ge=0.0)
    deterministic_latency_p95_ms: float = Field(ge=0.0)
    model_latency_p50_ms: float = Field(ge=0.0)
    model_latency_p95_ms: float = Field(ge=0.0)
    configured_cost_usd: float = Field(ge=0.0)
    robot_execution_enabled: bool
    can_execute_world: bool


class BaselineSummary(FrozenModel):
    baseline: BaselineKind
    run_count: int = Field(ge=0)
    advance_count: int = Field(ge=0)
    false_advance_count: int = Field(ge=0)
    false_effect_advance_count: int = Field(ge=0)
    false_handoff_advance_count: int = Field(ge=0)
    false_task_goal_advance_count: int = Field(ge=0)
    false_advance_rate: float = Field(ge=0.0, le=1.0)
    episode_success_count: int = Field(ge=0)
    episode_success_rate: float = Field(ge=0.0, le=1.0)
    safe_stop_count: int = Field(ge=0)
    safe_stop_rate: float = Field(ge=0.0, le=1.0)
    false_abort_count: int = Field(ge=0)
    false_abort_rate: float = Field(ge=0.0, le=1.0)
    unknown_count: int = Field(ge=0)
    recovery_episode_count: int = Field(ge=0)
    recovery_success_count: int = Field(ge=0)
    recovery_success_rate: float = Field(ge=0.0, le=1.0)
    replan_count: int = Field(ge=0)
    replan_rate: float = Field(ge=0.0, le=1.0)
    dispatch_count: int = Field(ge=0)
    model_call_count: int = Field(ge=0)
    model_timeout_count: int = Field(ge=0)
    deterministic_latency_p50_ms: float = Field(ge=0.0)
    deterministic_latency_p95_ms: float = Field(ge=0.0)
    model_latency_p50_ms: float = Field(ge=0.0)
    model_latency_p95_ms: float = Field(ge=0.0)
    configured_cost_usd: float = Field(ge=0.0)
    clean_run_count: int = Field(ge=0)
    chained_run_count: int = Field(ge=0)
    clean_false_advance_rate: float = Field(ge=0.0, le=1.0)
    chained_false_advance_rate: float = Field(ge=0.0, le=1.0)
    chained_minus_clean_false_advance_rate: float = Field(ge=-1.0, le=1.0)
    robot_execution_enabled: bool


def compute_run_metrics(
    case: ScenarioCase | None,
    run: BenchmarkRun,
) -> RunMetricsV2:
    expected = run.expected_final_state if case is None else case.expectation.final_state
    false_count = run.false_advance_count
    advances = sum(item.advanced for item in run.decisions)
    correct_outcome = run.final_state is expected and false_count == 0
    return RunMetricsV2(
        scenario_id=run.scenario_id,
        family=run.family,
        condition=run.condition,
        baseline=run.baseline,
        final_state=run.final_state,
        advance_count=advances,
        false_advance_count=false_count,
        false_effect_advance_count=run.false_effect_advance_count,
        false_handoff_advance_count=run.false_handoff_advance_count,
        false_task_goal_advance_count=run.false_task_goal_advance_count,
        false_advance_rate=false_count / advances if advances else 0.0,
        episode_success=(
            expected is RuntimeState.DONE
            and run.final_state is RuntimeState.DONE
            and false_count == 0
        ),
        safe_stop=(
            expected is RuntimeState.STOPPED
            and run.final_state is RuntimeState.STOPPED
            and false_count == 0
        ),
        false_abort=expected is RuntimeState.DONE and run.final_state is RuntimeState.STOPPED,
        unknown_count=run.unknown_count,
        recovery_count=run.recovery_count,
        recovery_success=run.recovery_count > 0 and correct_outcome,
        replan_count=run.replan_count,
        dispatch_count=run.dispatch_count,
        model_call_count=run.model_call_count,
        model_timeout_count=run.model_timeout_count,
        deterministic_latency_p50_ms=nearest_rank(run.deterministic_latency_ms, 0.50),
        deterministic_latency_p95_ms=nearest_rank(run.deterministic_latency_ms, 0.95),
        model_latency_p50_ms=nearest_rank(run.model_latency_ms, 0.50),
        model_latency_p95_ms=nearest_rank(run.model_latency_ms, 0.95),
        configured_cost_usd=run.configured_cost_usd,
        robot_execution_enabled=False,
        can_execute_world=False,
    )


def _rate(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def aggregate_metrics(metrics: tuple[RunMetricsV2, ...]) -> tuple[BaselineSummary, ...]:
    summaries: list[BaselineSummary] = []
    for baseline in BaselineKind:
        group = tuple(item for item in metrics if item.baseline is baseline)
        if not group:
            continue
        advances = sum(item.advance_count for item in group)
        false_advances = sum(item.false_advance_count for item in group)
        successes = sum(item.episode_success for item in group)
        safe_stops = sum(item.safe_stop for item in group)
        false_aborts = sum(item.false_abort for item in group)
        recovery_group = tuple(item for item in group if item.recovery_count > 0)
        recovery_successes = sum(item.recovery_success for item in recovery_group)
        clean = tuple(item for item in group if item.condition == "clean")
        chained = tuple(item for item in group if item.condition == "chained")
        clean_advances = sum(item.advance_count for item in clean)
        chained_advances = sum(item.advance_count for item in chained)
        clean_rate = _rate(sum(item.false_advance_count for item in clean), clean_advances)
        chained_rate = _rate(
            sum(item.false_advance_count for item in chained), chained_advances
        )
        deterministic_latencies = tuple(
            value
            for item in group
            for value in (
                item.deterministic_latency_p50_ms,
                item.deterministic_latency_p95_ms,
            )
            if value > 0
        )
        model_latencies = tuple(
            value
            for item in group
            for value in (item.model_latency_p50_ms, item.model_latency_p95_ms)
            if value > 0
        )
        summaries.append(
            BaselineSummary(
                baseline=baseline,
                run_count=len(group),
                advance_count=advances,
                false_advance_count=false_advances,
                false_effect_advance_count=sum(
                    item.false_effect_advance_count for item in group
                ),
                false_handoff_advance_count=sum(
                    item.false_handoff_advance_count for item in group
                ),
                false_task_goal_advance_count=sum(
                    item.false_task_goal_advance_count for item in group
                ),
                false_advance_rate=_rate(false_advances, advances),
                episode_success_count=successes,
                episode_success_rate=_rate(successes, len(group)),
                safe_stop_count=safe_stops,
                safe_stop_rate=_rate(safe_stops, len(group)),
                false_abort_count=false_aborts,
                false_abort_rate=_rate(false_aborts, len(group)),
                unknown_count=sum(item.unknown_count for item in group),
                recovery_episode_count=len(recovery_group),
                recovery_success_count=recovery_successes,
                recovery_success_rate=_rate(recovery_successes, len(recovery_group)),
                replan_count=sum(item.replan_count for item in group),
                replan_rate=_rate(sum(item.replan_count for item in group), len(group)),
                dispatch_count=sum(item.dispatch_count for item in group),
                model_call_count=sum(item.model_call_count for item in group),
                model_timeout_count=sum(item.model_timeout_count for item in group),
                deterministic_latency_p50_ms=nearest_rank(
                    deterministic_latencies, 0.50
                ),
                deterministic_latency_p95_ms=nearest_rank(
                    deterministic_latencies, 0.95
                ),
                model_latency_p50_ms=nearest_rank(model_latencies, 0.50),
                model_latency_p95_ms=nearest_rank(model_latencies, 0.95),
                configured_cost_usd=round(
                    sum(item.configured_cost_usd for item in group), 6
                ),
                clean_run_count=len(clean),
                chained_run_count=len(chained),
                clean_false_advance_rate=clean_rate,
                chained_false_advance_rate=chained_rate,
                chained_minus_clean_false_advance_rate=chained_rate - clean_rate,
                robot_execution_enabled=False,
            )
        )
    return tuple(summaries)


__all__ = [
    "BaselineSummary",
    "RunMetricsV2",
    "aggregate_metrics",
    "compute_run_metrics",
    "nearest_rank",
]
