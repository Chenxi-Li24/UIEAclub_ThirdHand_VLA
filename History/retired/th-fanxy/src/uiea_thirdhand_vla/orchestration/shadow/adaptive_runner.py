"""Outer bounded loop for diagnosis and one validated shadow replan."""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from ..runtime.models import Plan, RunResult, RuntimeState, TraceEvent
from ..runtime.ports import Executor, ObservationSource, StageVerifier
from ..runtime.recovery import RecoveryManager
from ..runtime.registry import SkillRegistry
from ..runtime.supervisor import EvidenceGatedSupervisor
from ..runtime.trace import MemoryTrace
from .diagnosis import FailureDiagnoser
from .replanning import (
    BoundedReplanner,
    ReplanContext,
    ReplanDecision,
    ReplanProposal,
)


class ProposalProvider(Protocol):
    def propose(self, context: ReplanContext) -> ReplanProposal | None:
        """Return one bounded remaining-plan proposal or decline."""


class ScriptedProposalProvider:
    def __init__(self, proposals: tuple[ReplanProposal | None, ...]) -> None:
        self._proposals = proposals
        self._cursor = 0
        self._calls: list[ReplanContext] = []

    @property
    def calls(self) -> tuple[ReplanContext, ...]:
        return tuple(self._calls)

    def propose(self, context: ReplanContext) -> ReplanProposal | None:
        self._calls.append(context)
        if self._cursor >= len(self._proposals):
            return None
        proposal = self._proposals[self._cursor]
        self._cursor += 1
        return proposal


class AdaptiveRunResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    episode_id: str
    final_state: RuntimeState
    completed_steps: tuple[str, ...]
    dispatch_count: int = Field(ge=0)
    recovery_count: int = Field(ge=0)
    model_call_count: int = Field(ge=0)
    diagnosis_count: int = Field(ge=0)
    accepted_replans: int = Field(ge=0, le=1)
    stop_reason: str | None = None
    events: tuple[TraceEvent, ...]


class AdaptiveEpisodeRunner:
    """Resume a stopped episode only through one registry-validated proposal."""

    def __init__(
        self,
        *,
        registry: SkillRegistry,
        observations: ObservationSource,
        executor: Executor,
        recovery: RecoveryManager,
        verifier: StageVerifier,
        trace: MemoryTrace,
        diagnoser: FailureDiagnoser,
        replanner: BoundedReplanner,
        proposal_provider: ProposalProvider,
        replan_budget: int,
    ) -> None:
        if replan_budget not in (0, 1):
            raise ValueError("replan_budget must be zero or one")
        self._registry = registry
        self._observations = observations
        self._executor = executor
        self._recovery = recovery
        self._verifier = verifier
        self._trace = trace
        self._diagnoser = diagnoser
        self._replanner = replanner
        self._proposal_provider = proposal_provider
        self._initial_replan_budget = replan_budget

    def run(self, plan: Plan) -> AdaptiveRunResult:
        original_plan = plan
        current_plan = plan
        completed: list[str] = []
        dispatch_count = 0
        recovery_count = 0
        diagnosis_count = 0
        accepted_replans = 0
        remaining_replans = self._initial_replan_budget

        while True:
            segment = EvidenceGatedSupervisor(
                registry=self._registry,
                observations=self._observations,
                executor=self._executor,
                recovery=self._recovery,
                trace=self._trace,
                verifier=self._verifier,
            ).run(current_plan)
            dispatch_count += segment.dispatch_count
            recovery_count += segment.recovery_count
            for step_id in segment.completed_steps:
                if step_id not in completed:
                    completed.append(step_id)
            if segment.final_state is RuntimeState.DONE:
                return self._result(
                    original_plan,
                    RuntimeState.DONE,
                    completed,
                    dispatch_count,
                    recovery_count,
                    diagnosis_count,
                    accepted_replans,
                    None,
                )

            diagnosis = self._diagnoser.diagnose(segment)
            diagnosis_count += 1
            failed_step_id, attempt = self._failure_location(segment)
            self._trace.append(
                episode_id=original_plan.episode_id,
                step_id=failed_step_id,
                attempt=attempt,
                event_type="diagnosis",
                state=RuntimeState.RECOVER,
                evidence_ids=diagnosis.evidence_ids,
                payload={
                    "cause": diagnosis.cause.value,
                    "reason_codes": diagnosis.reason_codes,
                    "suggestion_accepted": diagnosis.suggestion_accepted,
                },
            )
            if remaining_replans == 0:
                return self._result(
                    original_plan,
                    RuntimeState.STOPPED,
                    completed,
                    dispatch_count,
                    recovery_count,
                    diagnosis_count,
                    accepted_replans,
                    "replan_budget_exhausted",
                )
            context = ReplanContext(
                original_plan=original_plan,
                completed_steps=tuple(completed),
                failed_step_id=failed_step_id,
                diagnosis=diagnosis,
                remaining_replans=remaining_replans,
            )
            try:
                proposal = self._proposal_provider.propose(context)
            except Exception as exc:  # Proposal generation is optional and fail-closed.
                return self._result(
                    original_plan,
                    RuntimeState.STOPPED,
                    completed,
                    dispatch_count,
                    recovery_count,
                    diagnosis_count,
                    accepted_replans,
                    f"replan_provider_error:{type(exc).__name__}",
                )
            if proposal is None:
                self._append_replan_decision(
                    original_plan,
                    failed_step_id,
                    attempt,
                    None,
                    "no_replan_proposal",
                )
                return self._result(
                    original_plan,
                    RuntimeState.STOPPED,
                    completed,
                    dispatch_count,
                    recovery_count,
                    diagnosis_count,
                    accepted_replans,
                    "no_replan_proposal",
                )
            decision = self._replanner.validate(context, proposal)
            self._append_replan_decision(
                original_plan,
                failed_step_id,
                attempt,
                decision,
                decision.reason,
            )
            if not decision.accepted or decision.plan is None:
                return self._result(
                    original_plan,
                    RuntimeState.STOPPED,
                    completed,
                    dispatch_count,
                    recovery_count,
                    diagnosis_count,
                    accepted_replans,
                    decision.reason,
                )
            accepted_replans += 1
            remaining_replans = decision.remaining_replans
            current_plan = decision.plan

    @staticmethod
    def _failure_location(segment: RunResult) -> tuple[str, int]:
        for event in reversed(segment.events):
            if event.step_id is not None:
                return event.step_id, event.attempt
        raise ValueError("stopped episode has no failed step")

    def _append_replan_decision(
        self,
        plan: Plan,
        step_id: str,
        attempt: int,
        decision: ReplanDecision | None,
        reason: str,
    ) -> None:
        self._trace.append(
            episode_id=plan.episode_id,
            step_id=step_id,
            attempt=attempt,
            event_type="replan_decision",
            state=RuntimeState.RECOVER,
            payload={
                "accepted": False if decision is None else decision.accepted,
                "proposal_id": None if decision is None else decision.proposal_id,
                "reason": reason,
                "remaining_replans": (
                    0 if decision is None else decision.remaining_replans
                ),
            },
        )

    def _result(
        self,
        plan: Plan,
        final_state: RuntimeState,
        completed: list[str],
        dispatch_count: int,
        recovery_count: int,
        diagnosis_count: int,
        accepted_replans: int,
        stop_reason: str | None,
    ) -> AdaptiveRunResult:
        return AdaptiveRunResult(
            episode_id=plan.episode_id,
            final_state=final_state,
            completed_steps=tuple(completed),
            dispatch_count=dispatch_count,
            recovery_count=recovery_count,
            model_call_count=int(getattr(self._verifier, "model_call_count", 0)),
            diagnosis_count=diagnosis_count,
            accepted_replans=accepted_replans,
            stop_reason=stop_reason,
            events=self._trace.events,
        )


__all__ = [
    "AdaptiveEpisodeRunner",
    "AdaptiveRunResult",
    "ProposalProvider",
    "ScriptedProposalProvider",
]
