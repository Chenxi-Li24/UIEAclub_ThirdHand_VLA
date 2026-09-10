from uiea_thirdhand_vla.orchestration.runtime.models import (
    Argument,
    EvidenceRef,
    Fact,
    Observation,
    Predicate,
    PredicateKind,
    SkillCall,
    Stage,
    Verdict,
)
from uiea_thirdhand_vla.orchestration.shadow.verification import (
    ModelDecision,
    RiskClass,
    ScriptedModelVerifier,
    VerificationMode,
    VerifierRouter,
)

EVIDENCE_ID = "sha256:" + "f" * 64
UNKNOWN_EVIDENCE_ID = "sha256:" + "a" * 64


def call() -> SkillCall:
    return SkillCall(
        step_id="pick-1",
        skill_id="tabletop.pick",
        contract_version="0.1.0",
        arguments=(Argument(name="target_id", value=7),),
    )


def observation(*, ready: bool | None = True) -> Observation:
    facts = ()
    if ready is not None:
        facts = (Fact(name="ready", value=ready, evidence_ids=(EVIDENCE_ID,)),)
    return Observation(
        episode_id="episode-verifier-router",
        snapshot_id="snapshot-1",
        sequence=1,
        monotonic_ns=100,
        source="fixture",
        source_version="1",
        facts=facts,
        evidence=(
            EvidenceRef(
                evidence_id=EVIDENCE_ID,
                kind="fixture",
                source="test",
                observed_monotonic_ns=100,
            ),
        ),
    )


def ready_predicate() -> tuple[Predicate, ...]:
    return (
        Predicate(
            predicate_id="ready",
            kind=PredicateKind.FACT_EQUALS,
            fact_name="ready",
            expected_value=True,
        ),
    )


def decision(
    verdict: Verdict,
    *,
    evidence_ids: tuple[str, ...] = (EVIDENCE_ID,),
) -> ModelDecision:
    return ModelDecision(
        verdict=verdict,
        reason_code=f"model_{verdict.value.lower()}",
        evidence_ids=evidence_ids,
        latency_ms=25.0,
        input_tokens=120,
        output_tokens=8,
        configured_cost_usd=0.002,
    )


def verify(router: VerifierRouter, stage: Stage, *, ready: bool | None = True):
    return router.verify(
        stage,
        ready_predicate(),
        call(),
        observation(ready=ready),
        None,
        100,
    )


def router(mode: VerificationMode, scripted) -> VerifierRouter:
    return VerifierRouter(
        mode=mode,
        model=ScriptedModelVerifier(tuple(scripted)),
        semantic_stages=(Stage.HANDOFF, Stage.TASK_GOAL),
        risk=RiskClass.MEDIUM,
        model_version="fixture-vlm-1",
        prompt_version="handoff-prompt-1",
    )


def test_rule_only_never_calls_model():
    verifier = router(VerificationMode.RULE_ONLY, (decision(Verdict.FAIL),))

    result = verify(verifier, Stage.HANDOFF)

    assert result.verdict is Verdict.PASS
    assert verifier.model_call_count == 0


def test_hard_rule_failure_dominates_and_skips_model():
    verifier = router(VerificationMode.ALWAYS_MODEL, (decision(Verdict.PASS),))

    result = verify(verifier, Stage.HANDOFF, ready=False)

    assert result.verdict is Verdict.FAIL
    assert verifier.model_call_count == 0


def test_model_failure_can_conservatively_veto_rule_pass():
    verifier = router(VerificationMode.ALWAYS_MODEL, (decision(Verdict.FAIL),))

    result = verify(verifier, Stage.EFFECT)

    assert result.verdict is Verdict.FAIL
    assert verifier.model_call_count == 1
    assert verifier.total_latency_ms == 25.0
    assert verifier.total_configured_cost_usd == 0.002
    assert result.results[-1].reason_code.startswith("model_response:sha256:")


def test_model_pass_cannot_override_missing_rule_evidence():
    verifier = router(VerificationMode.ALWAYS_MODEL, (decision(Verdict.PASS),))

    result = verify(verifier, Stage.EFFECT, ready=None)

    assert result.verdict is Verdict.UNKNOWN
    assert verifier.model_call_count == 1


def test_model_citation_outside_bundle_becomes_unknown():
    verifier = router(
        VerificationMode.ALWAYS_MODEL,
        (decision(Verdict.PASS, evidence_ids=(UNKNOWN_EVIDENCE_ID,)),),
    )

    result = verify(verifier, Stage.EFFECT)

    assert result.verdict is Verdict.UNKNOWN
    assert result.results[-1].reason_code == "model_evidence_not_in_bundle"


def test_timeout_becomes_unknown_and_is_counted():
    verifier = router(VerificationMode.ALWAYS_MODEL, (TimeoutError("slow model"),))

    result = verify(verifier, Stage.EFFECT)

    assert result.verdict is Verdict.UNKNOWN
    assert verifier.model_call_count == 1
    assert verifier.model_timeout_count == 1
    assert result.results[-1].reason_code == "model_timeout"


def test_hybrid_routes_only_semantic_or_rule_unknown_stages():
    verifier = router(
        VerificationMode.HYBRID,
        (decision(Verdict.PASS), decision(Verdict.UNKNOWN, evidence_ids=())),
    )

    effect = verify(verifier, Stage.EFFECT)
    handoff = verify(verifier, Stage.HANDOFF)
    unknown_precondition = verify(verifier, Stage.PRECONDITION, ready=None)

    assert effect.verdict is Verdict.PASS
    assert handoff.verdict is Verdict.PASS
    assert unknown_precondition.verdict is Verdict.UNKNOWN
    assert verifier.model_call_count == 2
    assert tuple(bundle.stage for bundle in verifier.model.calls) == (
        Stage.HANDOFF,
        Stage.PRECONDITION,
    )
