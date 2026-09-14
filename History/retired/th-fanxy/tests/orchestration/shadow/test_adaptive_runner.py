from pathlib import Path

from uiea_thirdhand_vla.orchestration.runtime.adapters import (
    FakeExecutor,
    ReplayObservationSource,
)
from uiea_thirdhand_vla.orchestration.runtime.models import (
    Argument,
    EvidenceRef,
    Fact,
    ObjectState,
    Observation,
    Plan,
    Predicate,
    PredicateKind,
    ReceiptStatus,
    RobotState,
    RuntimeState,
    SkillCall,
)
from uiea_thirdhand_vla.orchestration.runtime.monitors import (
    DeterministicStageVerifier,
)
from uiea_thirdhand_vla.orchestration.runtime.recovery import RecoveryManager
from uiea_thirdhand_vla.orchestration.runtime.registry import SkillRegistry
from uiea_thirdhand_vla.orchestration.runtime.trace import MemoryTrace
from uiea_thirdhand_vla.orchestration.shadow.adaptive_runner import (
    AdaptiveEpisodeRunner,
    ScriptedProposalProvider,
)
from uiea_thirdhand_vla.orchestration.shadow.diagnosis import FailureDiagnoser
from uiea_thirdhand_vla.orchestration.shadow.replanning import (
    BoundedReplanner,
    ReplanProposal,
)

ROOT = Path(__file__).resolve().parents[3]
PICK_PATH = ROOT / "configs" / "skills" / "tabletop_pick.yaml"
PLACE_PATH = ROOT / "configs" / "skills" / "tabletop_place.yaml"
EVIDENCE_ID = "sha256:" + "7" * 64


def arguments() -> tuple[Argument, ...]:
    return (
        Argument(name="target_id", value=7),
        Argument(name="destination_region", value="tray"),
    )


def skill_call(step_id: str, skill_id: str) -> SkillCall:
    return SkillCall(
        step_id=step_id,
        skill_id=skill_id,
        contract_version="0.1.0",
        arguments=arguments(),
    )


def plan(*steps: SkillCall) -> Plan:
    return Plan(
        episode_id="episode-adaptive",
        task_goal=(
            Predicate(
                predicate_id="goal.in_region",
                kind=PredicateKind.OBJECT_IN_REGION,
                object_arg="target_id",
                region_arg="destination_region",
            ),
        ),
        steps=tuple(steps),
    )


def single_pick_plan() -> Plan:
    return Plan(
        episode_id="episode-adaptive",
        task_goal=(
            Predicate(
                predicate_id="goal.held",
                kind=PredicateKind.ROBOT_HOLDS_OBJECT,
                object_arg="target_id",
            ),
        ),
        steps=(skill_call("pick-1", "tabletop.pick"),),
    )


def observation(
    sequence: int,
    *,
    held: int | None,
    facts: tuple[Fact, ...],
    regions: tuple[str, ...] = (),
) -> Observation:
    return Observation(
        episode_id="episode-adaptive",
        snapshot_id=f"snapshot-{sequence}",
        sequence=sequence,
        monotonic_ns=sequence * 10,
        source="fixture",
        source_version="1",
        objects=(
            ObjectState(
                identity_id=7,
                label="cup",
                visible=True,
                ambiguous=False,
                actionable=True,
                depth_valid=True,
                region_ids=regions,
                evidence_ids=(EVIDENCE_ID,),
            ),
        ),
        robot=RobotState(
            holding_known=True,
            held_object_id=held,
            evidence_ids=(EVIDENCE_ID,),
        ),
        facts=facts,
        evidence=(
            EvidenceRef(
                evidence_id=EVIDENCE_ID,
                kind="fixture",
                source="test",
                observed_monotonic_ns=sequence * 10,
            ),
        ),
    )


def fact(name: str, value: bool = True) -> Fact:
    return Fact(name=name, value=value, evidence_ids=(EVIDENCE_ID,))


def successful_pick_observations() -> tuple[Observation, Observation]:
    return (
        observation(1, held=None, facts=(fact("safety_clear"),)),
        observation(
            2,
            held=7,
            facts=(
                fact("safety_clear"),
                fact("object_follows_gripper"),
                fact("place_ready"),
            ),
        ),
    )


def adaptive_observations() -> tuple[Observation, ...]:
    pick_pre, pick_post = successful_pick_observations()
    unknown_place = tuple(
        observation(sequence, held=7, facts=(fact("safety_clear"),))
        for sequence in (3, 4, 5)
    )
    resolved_place_pre = observation(
        6,
        held=7,
        facts=(fact("safety_clear"), fact("destination_known")),
    )
    place_post = observation(
        7,
        held=None,
        facts=(fact("safety_clear"),),
        regions=("tray",),
    )
    return (pick_pre, pick_post, *unknown_place, resolved_place_pre, place_post)


def runner(observations, statuses, proposals) -> AdaptiveEpisodeRunner:
    registry = SkillRegistry.from_paths((PICK_PATH, PLACE_PATH))
    return AdaptiveEpisodeRunner(
        registry=registry,
        observations=ReplayObservationSource(tuple(observations)),
        executor=FakeExecutor(tuple(statuses)),
        recovery=RecoveryManager(),
        verifier=DeterministicStageVerifier(),
        trace=MemoryTrace(),
        diagnoser=FailureDiagnoser(),
        replanner=BoundedReplanner(registry),
        proposal_provider=ScriptedProposalProvider(tuple(proposals)),
        replan_budget=1,
    )


def retry_place_proposal(skill_id: str = "tabletop.place") -> ReplanProposal:
    return ReplanProposal(
        steps=(skill_call("place-retry-1", skill_id),),
        rationale="retry remaining place after a fresh observation",
        evidence_ids=(),
    )


def test_successful_episode_does_not_request_replan():
    pick_pre, pick_post = successful_pick_observations()
    result = runner(
        (pick_pre, pick_post),
        (ReceiptStatus.COMPLETED,),
        (),
    ).run(single_pick_plan())

    assert result.final_state is RuntimeState.DONE
    assert result.accepted_replans == 0
    assert result.diagnosis_count == 0
    assert result.dispatch_count == 1


def test_one_valid_remaining_plan_resumes_without_redispatching_completed_pick():
    result = runner(
        adaptive_observations(),
        (ReceiptStatus.COMPLETED, ReceiptStatus.COMPLETED),
        (retry_place_proposal(),),
    ).run(
        plan(
            skill_call("pick-1", "tabletop.pick"),
            skill_call("place-1", "tabletop.place"),
        )
    )

    assert result.final_state is RuntimeState.DONE
    assert result.completed_steps == ("pick-1", "place-retry-1")
    assert result.dispatch_count == 2
    assert result.accepted_replans == 1
    assert result.diagnosis_count == 1
    assert result.model_call_count == 0
    event_types = tuple(event.event_type for event in result.events)
    assert event_types.count("command_dispatched") == 2
    assert "diagnosis" in event_types
    assert "replan_decision" in event_types
    assert tuple(event.sequence for event in result.events) == tuple(range(len(result.events)))


def test_rejected_proposal_stops_without_additional_dispatch():
    result = runner(
        adaptive_observations(),
        (ReceiptStatus.COMPLETED,),
        (retry_place_proposal("tabletop.unknown"),),
    ).run(
        plan(
            skill_call("pick-1", "tabletop.pick"),
            skill_call("place-1", "tabletop.place"),
        )
    )

    assert result.final_state is RuntimeState.STOPPED
    assert result.dispatch_count == 1
    assert result.accepted_replans == 0
    assert result.stop_reason is not None
    assert "unknown Skill" in result.stop_reason


def test_absent_proposal_fails_closed_after_diagnosis():
    result = runner(
        adaptive_observations(),
        (ReceiptStatus.COMPLETED,),
        (),
    ).run(
        plan(
            skill_call("pick-1", "tabletop.pick"),
            skill_call("place-1", "tabletop.place"),
        )
    )

    assert result.final_state is RuntimeState.STOPPED
    assert result.dispatch_count == 1
    assert result.diagnosis_count == 1
    assert result.accepted_replans == 0
    assert result.stop_reason == "no_replan_proposal"
