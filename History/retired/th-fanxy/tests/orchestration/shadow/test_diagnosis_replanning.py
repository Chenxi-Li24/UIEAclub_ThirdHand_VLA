from pathlib import Path

import pytest

from uiea_thirdhand_vla.orchestration.runtime.models import (
    Argument,
    Plan,
    Predicate,
    PredicateKind,
    RunResult,
    RuntimeState,
    SkillCall,
)
from uiea_thirdhand_vla.orchestration.runtime.registry import SkillRegistry
from uiea_thirdhand_vla.orchestration.runtime.trace import MemoryTrace
from uiea_thirdhand_vla.orchestration.shadow.diagnosis import (
    DiagnosisProposal,
    FailureCause,
    FailureDiagnoser,
)
from uiea_thirdhand_vla.orchestration.shadow.replanning import (
    BoundedReplanner,
    ReplanContext,
    ReplanProposal,
)

ROOT = Path(__file__).resolve().parents[3]
PICK_PATH = ROOT / "configs" / "skills" / "tabletop_pick.yaml"
PLACE_PATH = ROOT / "configs" / "skills" / "tabletop_place.yaml"
EVIDENCE_ID = "sha256:" + "9" * 64
OTHER_EVIDENCE_ID = "sha256:" + "8" * 64


def stopped_result(
    *,
    stop_reason: str,
    stage_reason: str,
    event_type: str = "effect_result",
) -> RunResult:
    trace = MemoryTrace()
    trace.append(
        episode_id="episode-replan",
        step_id="place-1",
        attempt=0,
        event_type=event_type,
        state=RuntimeState.VERIFY_EFFECT,
        evidence_ids=(EVIDENCE_ID,),
        payload={"verdict": "FAIL", "reasons": [stage_reason]},
    )
    trace.append(
        episode_id="episode-replan",
        step_id="place-1",
        attempt=0,
        event_type="episode_stopped",
        state=RuntimeState.STOPPED,
        payload={"reason": stop_reason},
    )
    return RunResult(
        episode_id="episode-replan",
        final_state=RuntimeState.STOPPED,
        completed_steps=("pick-1",),
        dispatch_count=1,
        recovery_count=1,
        stop_reason=stop_reason,
        events=trace.events,
    )


@pytest.mark.parametrize(
    ("stop_reason", "stage_reason", "expected"),
    [
        ("precondition_not_passed", "observation_stale", FailureCause.STALE_OBSERVATION),
        ("precondition_not_passed", "identity_ambiguous", FailureCause.TARGET_AMBIGUOUS),
        ("precondition_not_passed", "object_state_unknown", FailureCause.TARGET_MISSING),
        ("precondition_not_passed", "depth_invalid", FailureCause.INVALID_DEPTH),
        ("retry_budget_exhausted", "fact_mismatch", FailureCause.BUDGET_EXHAUSTED),
        ("execution_timeout", "execution_timeout", FailureCause.EXECUTION_FAILURE),
        ("effect_not_passed", "model_timeout", FailureCause.MODEL_FAILURE),
        ("handoff_not_passed", "fact_mismatch", FailureCause.HANDOFF_FAILURE),
        ("task_goal_not_passed", "object_outside_region", FailureCause.TASK_GOAL_FAILURE),
    ],
)
def test_diagnoser_maps_trace_evidence_to_frozen_taxonomy(
    stop_reason: str,
    stage_reason: str,
    expected: FailureCause,
):
    diagnosis = FailureDiagnoser().diagnose(
        stopped_result(stop_reason=stop_reason, stage_reason=stage_reason)
    )

    assert diagnosis.cause is expected
    assert stage_reason in diagnosis.reason_codes
    assert diagnosis.evidence_ids == (EVIDENCE_ID,)
    assert diagnosis.suggestion_accepted is False


def test_inconsistent_model_diagnosis_is_rejected():
    result = stopped_result(
        stop_reason="precondition_not_passed",
        stage_reason="identity_ambiguous",
    )
    proposal = DiagnosisProposal(
        cause=FailureCause.EXECUTION_FAILURE,
        reason="model guessed execution failure",
        evidence_ids=(EVIDENCE_ID,),
    )

    diagnosis = FailureDiagnoser().diagnose(result, proposal)

    assert diagnosis.cause is FailureCause.TARGET_AMBIGUOUS
    assert diagnosis.suggested_cause is FailureCause.EXECUTION_FAILURE
    assert diagnosis.suggestion_accepted is False


def arguments() -> tuple[Argument, ...]:
    return (
        Argument(name="target_id", value=7),
        Argument(name="destination_region", value="tray"),
    )


def skill_call(step_id: str, skill_id: str, version: str = "0.1.0") -> SkillCall:
    return SkillCall(
        step_id=step_id,
        skill_id=skill_id,
        contract_version=version,
        arguments=arguments(),
    )


def original_plan() -> Plan:
    return Plan(
        episode_id="episode-replan",
        task_goal=(
            Predicate(
                predicate_id="goal.in_region",
                kind=PredicateKind.OBJECT_IN_REGION,
                object_arg="target_id",
                region_arg="destination_region",
            ),
        ),
        steps=(
            skill_call("pick-1", "tabletop.pick"),
            skill_call("place-1", "tabletop.place"),
        ),
    )


def context(*, budget: int = 1) -> ReplanContext:
    diagnosis = FailureDiagnoser().diagnose(
        stopped_result(
            stop_reason="handoff_not_passed",
            stage_reason="fact_mismatch",
        )
    )
    return ReplanContext(
        original_plan=original_plan(),
        completed_steps=("pick-1",),
        failed_step_id="place-1",
        diagnosis=diagnosis,
        remaining_replans=budget,
    )


def proposal(
    *steps: SkillCall,
    evidence_ids: tuple[str, ...] = (EVIDENCE_ID,),
) -> ReplanProposal:
    return ReplanProposal(
        steps=tuple(steps),
        rationale="retry remaining place through an exact registered Skill",
        evidence_ids=evidence_ids,
    )


def replanner() -> BoundedReplanner:
    return BoundedReplanner(SkillRegistry.from_paths((PICK_PATH, PLACE_PATH)))


def test_valid_replan_preserves_goal_and_consumes_single_budget():
    decision = replanner().validate(
        context(),
        proposal(skill_call("place-retry-1", "tabletop.place")),
    )

    assert decision.accepted is True
    assert decision.remaining_replans == 0
    assert decision.plan is not None
    assert decision.plan.episode_id == original_plan().episode_id
    assert decision.plan.task_goal == original_plan().task_goal
    assert tuple(step.step_id for step in decision.plan.steps) == ("place-retry-1",)
    assert decision.proposal_id.startswith("sha256:")


@pytest.mark.parametrize(
    ("candidate", "reason"),
    [
        (skill_call("unknown-1", "tabletop.unknown"), "unknown Skill"),
        (skill_call("place-2", "tabletop.place", "0.2.0"), "version"),
        (skill_call("pick-1", "tabletop.place"), "completed step"),
    ],
)
def test_replanner_rejects_unregistered_version_or_completed_step(candidate, reason: str):
    decision = replanner().validate(context(), proposal(candidate))

    assert decision.accepted is False
    assert reason in decision.reason
    assert decision.plan is None
    assert decision.remaining_replans == 1


def test_replanner_rejects_duplicate_loop_and_unbound_evidence():
    duplicate = skill_call("place-loop", "tabletop.place")
    duplicate_decision = replanner().validate(context(), proposal(duplicate, duplicate))
    evidence_decision = replanner().validate(
        context(),
        proposal(
            skill_call("place-retry-1", "tabletop.place"),
            evidence_ids=(OTHER_EVIDENCE_ID,),
        ),
    )

    assert duplicate_decision.accepted is False
    assert "unique" in duplicate_decision.reason or "loop" in duplicate_decision.reason
    assert evidence_decision.accepted is False
    assert "evidence" in evidence_decision.reason


def test_replanner_cannot_accept_twice_for_one_episode():
    service = replanner()
    first = service.validate(
        context(),
        proposal(skill_call("place-retry-1", "tabletop.place")),
    )
    second = service.validate(
        context(),
        proposal(skill_call("place-retry-2", "tabletop.place")),
    )

    assert first.accepted is True
    assert second.accepted is False
    assert "already accepted" in second.reason


def test_zero_replan_budget_fails_closed():
    decision = replanner().validate(
        context(budget=0),
        proposal(skill_call("place-retry-1", "tabletop.place")),
    )

    assert decision.accepted is False
    assert decision.reason == "replan_budget_exhausted"
    assert decision.remaining_replans == 0
