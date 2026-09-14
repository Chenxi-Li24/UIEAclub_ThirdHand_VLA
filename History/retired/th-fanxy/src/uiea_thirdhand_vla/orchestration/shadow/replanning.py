"""Exact-registry validation for one bounded remaining-plan proposal."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..runtime.models import CONTENT_ID_PATTERN, Plan, SkillCall
from ..runtime.registry import RegistryError, SkillRegistry
from ..runtime.trace import content_id
from .diagnosis import Diagnosis


class FrozenReplanModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


def _checked_ids(values: tuple[str, ...]) -> tuple[str, ...]:
    if any(CONTENT_ID_PATTERN.fullmatch(value) is None for value in values):
        raise ValueError("replan evidence IDs must be content-addressed")
    if len(values) != len(set(values)):
        raise ValueError("replan evidence IDs must be unique")
    return values


class ReplanContext(FrozenReplanModel):
    original_plan: Plan
    completed_steps: tuple[str, ...]
    failed_step_id: str = Field(min_length=1)
    diagnosis: Diagnosis
    remaining_replans: int = Field(ge=0, le=1)

    @model_validator(mode="after")
    def valid_history(self) -> ReplanContext:
        original_ids = tuple(step.step_id for step in self.original_plan.steps)
        if len(original_ids) != len(set(original_ids)):
            raise ValueError("original plan step IDs must be unique")
        if len(self.completed_steps) != len(set(self.completed_steps)):
            raise ValueError("completed step IDs must be unique")
        if original_ids[: len(self.completed_steps)] != self.completed_steps:
            raise ValueError("completed steps must be an original plan prefix")
        if self.failed_step_id not in original_ids:
            raise ValueError("failed step must belong to the original plan")
        if self.failed_step_id in self.completed_steps:
            raise ValueError("failed step cannot already be completed")
        return self


class ReplanProposal(FrozenReplanModel):
    steps: tuple[SkillCall, ...] = Field(min_length=1)
    rationale: str = Field(min_length=1)
    evidence_ids: tuple[str, ...]

    _validate_ids = field_validator("evidence_ids")(_checked_ids)


class ReplanDecision(FrozenReplanModel):
    accepted: bool
    reason: str = Field(min_length=1)
    plan: Plan | None = None
    remaining_replans: int = Field(ge=0, le=1)
    proposal_id: str


class BoundedReplanner:
    """Validate at most one remaining-plan replacement per episode."""

    def __init__(self, registry: SkillRegistry) -> None:
        self._registry = registry
        self._accepted_episodes: set[str] = set()

    def validate(
        self,
        context: ReplanContext,
        proposal: ReplanProposal,
    ) -> ReplanDecision:
        proposal_id = content_id(proposal)

        def reject(reason: str) -> ReplanDecision:
            return ReplanDecision(
                accepted=False,
                reason=reason,
                plan=None,
                remaining_replans=context.remaining_replans,
                proposal_id=proposal_id,
            )

        episode_id = context.original_plan.episode_id
        if episode_id in self._accepted_episodes:
            return reject("replan_already accepted_for_episode")
        if context.remaining_replans == 0:
            return reject("replan_budget_exhausted")
        if not set(proposal.evidence_ids).issubset(context.diagnosis.evidence_ids):
            return reject("replan evidence is not bound to the diagnosis")
        step_ids = tuple(step.step_id for step in proposal.steps)
        if len(step_ids) != len(set(step_ids)):
            return reject("replan step IDs must be unique; loop rejected")
        if set(step_ids).intersection(context.completed_steps):
            return reject("replan cannot reuse a completed step ID")
        signatures = tuple(
            content_id(
                {
                    "arguments": step.arguments,
                    "contract_version": step.contract_version,
                    "skill_id": step.skill_id,
                }
            )
            for step in proposal.steps
        )
        if len(signatures) != len(set(signatures)):
            return reject("replan repeated-Skill loop rejected")
        try:
            contracts = tuple(self._registry.validate_call(step) for step in proposal.steps)
        except RegistryError as exc:
            return reject(str(exc))
        previous_call = None
        if context.completed_steps:
            completed_id = context.completed_steps[-1]
            previous_call = next(
                step for step in context.original_plan.steps if step.step_id == completed_id
            )
        for index, call in enumerate(proposal.steps):
            if previous_call is not None:
                try:
                    previous_contract = self._registry.resolve(
                        previous_call.skill_id,
                        previous_call.contract_version,
                    )
                    previous_contract.readiness_for(call.skill_id)
                except (RegistryError, ValueError) as exc:
                    return reject(f"replan handoff invalid: {exc}")
            previous_call = call
            if contracts[index].skill_id != call.skill_id:
                return reject("replan registry contract mismatch")
        plan = Plan(
            episode_id=episode_id,
            task_goal=context.original_plan.task_goal,
            steps=proposal.steps,
        )
        self._accepted_episodes.add(episode_id)
        return ReplanDecision(
            accepted=True,
            reason="replan_accepted",
            plan=plan,
            remaining_replans=context.remaining_replans - 1,
            proposal_id=proposal_id,
        )


__all__ = [
    "BoundedReplanner",
    "ReplanContext",
    "ReplanDecision",
    "ReplanProposal",
]
