"""Evidence-cited conservative verifier routing for shadow episodes."""

from __future__ import annotations

from enum import Enum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..runtime.models import (
    CONTENT_ID_PATTERN,
    Observation,
    Predicate,
    PredicateResult,
    SkillCall,
    Stage,
    StageResult,
    Verdict,
)
from ..runtime.monitors import DeterministicStageVerifier
from ..runtime.trace import content_id


class VerificationMode(str, Enum):
    RULE_ONLY = "rule_only"
    ALWAYS_MODEL = "always_model"
    HYBRID = "hybrid"


class RiskClass(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class FrozenVerificationModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)


def _checked_ids(values: tuple[str, ...]) -> tuple[str, ...]:
    if any(CONTENT_ID_PATTERN.fullmatch(value) is None for value in values):
        raise ValueError("evidence IDs must be content-addressed")
    if len(values) != len(set(values)):
        raise ValueError("evidence IDs must be unique")
    return values


class EvidenceBundle(FrozenVerificationModel):
    episode_id: str = Field(min_length=1)
    step_id: str = Field(min_length=1)
    stage: Stage
    snapshot_id: str = Field(min_length=1)
    previous_snapshot_id: str | None = None
    predicate_ids: tuple[str, ...] = Field(min_length=1)
    deterministic: StageResult
    evidence_ids: tuple[str, ...]
    risk: RiskClass
    model_version: str = Field(min_length=1)
    prompt_version: str = Field(min_length=1)

    _validate_ids = field_validator("evidence_ids")(_checked_ids)


class ModelDecision(FrozenVerificationModel):
    verdict: Verdict
    reason_code: str = Field(min_length=1)
    evidence_ids: tuple[str, ...]
    latency_ms: float = Field(ge=0.0)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    configured_cost_usd: float = Field(ge=0.0)

    _validate_ids = field_validator("evidence_ids")(_checked_ids)


class ModelVerifier(Protocol):
    def verify(self, bundle: EvidenceBundle) -> ModelDecision:
        """Return a strict model judgment or raise a bounded transport error."""


class ScriptedModelVerifier:
    """Finite model stand-in whose real bundle inputs remain inspectable."""

    def __init__(self, responses: tuple[ModelDecision | Exception, ...]) -> None:
        self._responses = responses
        self._cursor = 0
        self._calls: list[EvidenceBundle] = []

    @property
    def calls(self) -> tuple[EvidenceBundle, ...]:
        return tuple(self._calls)

    def verify(self, bundle: EvidenceBundle) -> ModelDecision:
        self._calls.append(bundle)
        if self._cursor >= len(self._responses):
            raise RuntimeError("scripted model responses exhausted")
        response = self._responses[self._cursor]
        self._cursor += 1
        if isinstance(response, Exception):
            raise response
        return response


class VerifierRouter:
    """Combine hard deterministic gates with optional conservative model checks."""

    def __init__(
        self,
        *,
        mode: VerificationMode,
        model: ModelVerifier,
        semantic_stages: tuple[Stage, ...],
        risk: RiskClass,
        model_version: str,
        prompt_version: str,
    ) -> None:
        if not model_version or not prompt_version:
            raise ValueError("model and prompt versions must be non-empty")
        self.mode = mode
        self.model = model
        self.semantic_stages = frozenset(semantic_stages)
        self.risk = risk
        self.model_version = model_version
        self.prompt_version = prompt_version
        self._rules = DeterministicStageVerifier()
        self.model_call_count = 0
        self.model_timeout_count = 0
        self.total_latency_ms = 0.0
        self.total_configured_cost_usd = 0.0

    def verify(
        self,
        stage: Stage,
        predicates: tuple[Predicate, ...],
        call: SkillCall,
        observation: Observation,
        previous: Observation | None,
        now_ns: int,
    ) -> StageResult:
        deterministic = self._rules.verify(
            stage,
            predicates,
            call,
            observation,
            previous,
            now_ns,
        )
        if deterministic.verdict is Verdict.FAIL or not self._should_route(
            stage, deterministic.verdict
        ):
            return deterministic
        evidence_ids = tuple(
            dict.fromkeys(
                [
                    *(item.evidence_id for item in observation.evidence),
                    *(
                        evidence_id
                        for result in deterministic.results
                        for evidence_id in result.evidence_ids
                    ),
                ]
            )
        )
        bundle = EvidenceBundle(
            episode_id=observation.episode_id,
            step_id=call.step_id,
            stage=stage,
            snapshot_id=observation.snapshot_id,
            previous_snapshot_id=None if previous is None else previous.snapshot_id,
            predicate_ids=tuple(predicate.predicate_id for predicate in predicates),
            deterministic=deterministic,
            evidence_ids=evidence_ids,
            risk=self.risk,
            model_version=self.model_version,
            prompt_version=self.prompt_version,
        )
        self.model_call_count += 1
        try:
            decision = self.model.verify(bundle)
        except TimeoutError:
            self.model_timeout_count += 1
            return self._with_unknown(
                deterministic,
                observation,
                "model_timeout",
            )
        except Exception as exc:  # Model adapters fail closed at this boundary.
            return self._with_unknown(
                deterministic,
                observation,
                f"model_error:{type(exc).__name__}",
            )
        self.total_latency_ms += decision.latency_ms
        self.total_configured_cost_usd += decision.configured_cost_usd
        if not set(decision.evidence_ids).issubset(bundle.evidence_ids):
            return self._with_unknown(
                deterministic,
                observation,
                "model_evidence_not_in_bundle",
            )
        if decision.verdict is not Verdict.UNKNOWN and not decision.evidence_ids:
            return self._with_unknown(
                deterministic,
                observation,
                "model_evidence_missing",
            )
        decision_id = content_id(
            {
                "bundle": content_id(bundle),
                "decision": decision,
                "model_version": self.model_version,
                "prompt_version": self.prompt_version,
            }
        )
        model_result = PredicateResult(
            predicate_id=f"model.{stage.value}",
            verdict=decision.verdict,
            reason_code=f"model_response:{decision_id}",
            evidence_ids=decision.evidence_ids,
            snapshot_id=observation.snapshot_id,
            observed_value=decision.verdict.value,
        )
        return StageResult.aggregate(stage, (*deterministic.results, model_result))

    def _should_route(self, stage: Stage, verdict: Verdict) -> bool:
        if self.mode is VerificationMode.RULE_ONLY:
            return False
        if self.mode is VerificationMode.ALWAYS_MODEL:
            return True
        return stage in self.semantic_stages or verdict is Verdict.UNKNOWN

    @staticmethod
    def _with_unknown(
        deterministic: StageResult,
        observation: Observation,
        reason: str,
    ) -> StageResult:
        result = PredicateResult(
            predicate_id=f"model.{deterministic.stage.value}",
            verdict=Verdict.UNKNOWN,
            reason_code=reason,
            evidence_ids=(),
            snapshot_id=observation.snapshot_id,
        )
        return StageResult.aggregate(
            deterministic.stage,
            (*deterministic.results, result),
        )


__all__ = [
    "EvidenceBundle",
    "ModelDecision",
    "ModelVerifier",
    "RiskClass",
    "ScriptedModelVerifier",
    "VerificationMode",
    "VerifierRouter",
]
