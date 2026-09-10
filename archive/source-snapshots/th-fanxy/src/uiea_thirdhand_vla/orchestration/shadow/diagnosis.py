"""Deterministic, evidence-bound failure diagnosis for stopped episodes."""

from __future__ import annotations

import json
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..runtime.models import CONTENT_ID_PATTERN, RunResult, RuntimeState


class FailureCause(str, Enum):
    STALE_OBSERVATION = "stale_observation"
    TARGET_MISSING = "target_missing"
    TARGET_AMBIGUOUS = "target_ambiguous"
    IDENTITY_LOST = "identity_lost"
    INVALID_DEPTH = "invalid_depth_or_calibration"
    PRECONDITION_FAILURE = "precondition_failure"
    INVARIANT_FAILURE = "invariant_failure"
    EXECUTION_FAILURE = "execution_failure"
    EFFECT_FAILURE = "effect_failure"
    HANDOFF_FAILURE = "handoff_failure"
    TASK_GOAL_FAILURE = "task_goal_failure"
    MODEL_FAILURE = "model_failure"
    BUDGET_EXHAUSTED = "budget_exhausted"
    UNKNOWN = "unknown"


class FrozenDiagnosisModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


def _checked_ids(values: tuple[str, ...]) -> tuple[str, ...]:
    if any(CONTENT_ID_PATTERN.fullmatch(value) is None for value in values):
        raise ValueError("diagnosis evidence IDs must be content-addressed")
    if len(values) != len(set(values)):
        raise ValueError("diagnosis evidence IDs must be unique")
    return values


class DiagnosisProposal(FrozenDiagnosisModel):
    cause: FailureCause
    reason: str = Field(min_length=1)
    evidence_ids: tuple[str, ...]

    _validate_ids = field_validator("evidence_ids")(_checked_ids)


class Diagnosis(FrozenDiagnosisModel):
    cause: FailureCause
    reason_codes: tuple[str, ...] = Field(min_length=1)
    evidence_ids: tuple[str, ...]
    suggested_cause: FailureCause | None = None
    suggestion_accepted: bool = False
    rationale: str = Field(min_length=1)

    _validate_ids = field_validator("evidence_ids")(_checked_ids)


def _candidate_causes(tokens: tuple[str, ...]) -> tuple[FailureCause, ...]:
    joined = " ".join(tokens).lower()
    candidates: list[FailureCause] = []

    def add(condition: bool, cause: FailureCause) -> None:
        if condition and cause not in candidates:
            candidates.append(cause)

    add("budget_exhausted" in joined, FailureCause.BUDGET_EXHAUSTED)
    add("model_" in joined or "malformed_result" in joined, FailureCause.MODEL_FAILURE)
    add("observation_stale" in joined or "clock_before" in joined, FailureCause.STALE_OBSERVATION)
    add("ambiguous" in joined, FailureCause.TARGET_AMBIGUOUS)
    add("identity_lost" in joined or "identity_inactive" in joined, FailureCause.IDENTITY_LOST)
    add(
        "object_state_unknown" in joined or "target_missing" in joined,
        FailureCause.TARGET_MISSING,
    )
    add("depth_" in joined or "calibration" in joined, FailureCause.INVALID_DEPTH)
    add("execution_" in joined, FailureCause.EXECUTION_FAILURE)
    add("handoff_not_passed" in joined, FailureCause.HANDOFF_FAILURE)
    add("task_goal_not_passed" in joined, FailureCause.TASK_GOAL_FAILURE)
    add("effect_not_passed" in joined or "effect_fail" in joined, FailureCause.EFFECT_FAILURE)
    add("invariant_not_passed" in joined, FailureCause.INVARIANT_FAILURE)
    add("precondition_not_passed" in joined, FailureCause.PRECONDITION_FAILURE)
    if not candidates:
        candidates.append(FailureCause.UNKNOWN)
    return tuple(candidates)


class FailureDiagnoser:
    """Classify a stopped trace without inventing unavailable causes."""

    def diagnose(
        self,
        result: RunResult,
        proposal: DiagnosisProposal | None = None,
    ) -> Diagnosis:
        if result.final_state is not RuntimeState.STOPPED:
            raise ValueError("failure diagnosis requires a stopped episode")
        reasons: list[str] = []
        evidence_ids: list[str] = []
        for event in result.events:
            if event.event_type.endswith("_result"):
                try:
                    payload = json.loads(event.payload_json)
                except json.JSONDecodeError:
                    payload = {}
                event_reasons = payload.get("reasons", ())
                if isinstance(event_reasons, list):
                    reasons.extend(str(reason) for reason in event_reasons)
                evidence_ids.extend(event.evidence_ids)
        if result.stop_reason:
            reasons.append(result.stop_reason)
        reason_codes = tuple(dict.fromkeys(reasons or ["unknown_failure"]))
        cited = tuple(dict.fromkeys(evidence_ids))
        candidates = _candidate_causes(reason_codes)
        accepted = bool(
            proposal is not None
            and proposal.cause in candidates
            and set(proposal.evidence_ids).issubset(cited)
        )
        cause = proposal.cause if accepted and proposal is not None else candidates[0]
        rationale = (
            "model diagnosis matched deterministic reason codes and cited evidence"
            if accepted
            else "deterministic diagnosis retained from trace reason codes"
        )
        return Diagnosis(
            cause=cause,
            reason_codes=reason_codes,
            evidence_ids=cited,
            suggested_cause=None if proposal is None else proposal.cause,
            suggestion_accepted=accepted,
            rationale=rationale,
        )


__all__ = [
    "Diagnosis",
    "DiagnosisProposal",
    "FailureCause",
    "FailureDiagnoser",
]
