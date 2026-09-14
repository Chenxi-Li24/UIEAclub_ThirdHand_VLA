#!/usr/bin/env python3
"""Generate the checked synthetic benchmark cases and content-hashed manifest."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

from uiea_thirdhand_vla.orchestration.benchmark.models import (
    FailureCategory,
    ScenarioCase,
    ScenarioExpectation,
    ScenarioFamily,
)
from uiea_thirdhand_vla.orchestration.runtime.models import (
    Argument,
    EvidenceRef,
    Fact,
    GroundTruth,
    ObjectState,
    Observation,
    Plan,
    Predicate,
    PredicateKind,
    ReceiptStatus,
    ReplayBundle,
    RobotState,
    RuntimeState,
    SkillCall,
    Verdict,
)

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "tests" / "fixtures" / "orchestration" / "benchmark"
MANIFEST = ROOT / "configs" / "orchestration" / "benchmark_v1.yaml"


def arguments() -> tuple[Argument, ...]:
    return (
        Argument(name="target_id", value=7),
        Argument(name="destination_region", value="tray"),
    )


def call(step: str, skill: str) -> SkillCall:
    return SkillCall(
        step_id=step,
        skill_id=skill,
        contract_version="0.1.0",
        arguments=arguments(),
    )


def region_goal() -> Predicate:
    return Predicate(
        predicate_id="goal.object_in_tray",
        kind=PredicateKind.OBJECT_IN_REGION,
        object_arg="target_id",
        region_arg="destination_region",
    )


def plan(episode_id: str, *, two_steps: bool, held_goal: bool = False) -> Plan:
    goal = (
        Predicate(
            predicate_id="goal.object_held",
            kind=PredicateKind.ROBOT_HOLDS_OBJECT,
            object_arg="target_id",
        )
        if held_goal
        else region_goal()
    )
    steps = (call("pick-1", "tabletop.pick"),)
    if two_steps:
        steps += (call("place-1", "tabletop.place"),)
    return Plan(episode_id=episode_id, task_goal=(goal,), steps=steps)


def observation(
    episode_id: str,
    sequence: int,
    *,
    held: int | None,
    holding_known: bool = True,
    ambiguous: bool = False,
    depth_valid: bool = True,
    regions: tuple[str, ...] = (),
    facts: dict[str, bool] | None = None,
) -> Observation:
    digit = format(sequence % 16, "x")
    evidence_id = "sha256:" + digit * 64
    return Observation(
        episode_id=episode_id,
        snapshot_id=f"{episode_id}-snapshot-{sequence}",
        sequence=sequence,
        monotonic_ns=sequence * 10,
        source="synthetic-benchmark",
        source_version="1.0.0",
        objects=(
            ObjectState(
                identity_id=7,
                label="cup",
                visible=True,
                ambiguous=ambiguous,
                actionable=not ambiguous and depth_valid,
                depth_valid=depth_valid,
                region_ids=regions,
                evidence_ids=(evidence_id,),
            ),
        ),
        robot=RobotState(
            holding_known=holding_known,
            held_object_id=held,
            evidence_ids=(evidence_id,),
        ),
        facts=tuple(
            Fact(name=name, value=value, evidence_ids=(evidence_id,))
            for name, value in sorted((facts or {}).items())
        ),
        evidence=(
            EvidenceRef(
                evidence_id=evidence_id,
                kind="synthetic_grounded_state",
                source="benchmark-generator",
                observed_monotonic_ns=sequence * 10,
            ),
        ),
    )


def pre(episode_id: str, sequence: int = 1, **changes) -> Observation:
    return observation(
        episode_id,
        sequence,
        held=None,
        facts={"safety_clear": True},
        **changes,
    )


def pick_post(
    episode_id: str,
    sequence: int = 2,
    *,
    holding_known: bool = True,
    held: int | None = 7,
    following: bool | None = True,
    place_ready: bool | None = True,
) -> Observation:
    facts = {"safety_clear": True}
    if following is not None:
        facts["object_follows_gripper"] = following
    if place_ready is not None:
        facts["place_ready"] = place_ready
    return observation(
        episode_id,
        sequence,
        held=held,
        holding_known=holding_known,
        facts=facts,
    )


def place_pre(episode_id: str, sequence: int) -> Observation:
    return observation(
        episode_id,
        sequence,
        held=7,
        facts={"safety_clear": True, "destination_known": True},
    )


def place_post(episode_id: str, sequence: int) -> Observation:
    return observation(
        episode_id,
        sequence,
        held=None,
        regions=("tray",),
        facts={"safety_clear": True},
    )


def truth(
    step_id: str,
    *,
    attempt: int = 0,
    effect: Verdict,
    handoff: Verdict = Verdict.UNKNOWN,
    goal: Verdict = Verdict.UNKNOWN,
) -> GroundTruth:
    return GroundTruth(
        step_id=step_id,
        attempt=attempt,
        effect=effect,
        handoff=handoff,
        task_goal=goal,
    )


def case(
    family: ScenarioFamily,
    *,
    observations: tuple[Observation, ...],
    receipts: tuple[ReceiptStatus, ...],
    ground_truth: tuple[GroundTruth, ...],
    two_steps: bool,
    held_goal: bool,
    final_state: RuntimeState,
    dispatch: tuple[int, int],
    recovery: tuple[int, int],
    failure: FailureCategory,
    condition: str,
) -> ScenarioCase:
    episode_id = family.value
    return ScenarioCase(
        schema_version="1.0.0",
        scenario_id=episode_id,
        family=family,
        condition=condition,
        robot_execution_enabled=False,
        replay=ReplayBundle(
            plan=plan(episode_id, two_steps=two_steps, held_goal=held_goal),
            observations=observations,
            receipt_statuses=receipts,
            ground_truth=ground_truth,
        ),
        expectation=ScenarioExpectation(
            final_state=final_state,
            dispatch_min=dispatch[0],
            dispatch_max=dispatch[1],
            recovery_min=recovery[0],
            recovery_max=recovery[1],
            replan_min=0,
            replan_max=0,
            failure_category=failure,
        ),
    )


def build_cases() -> tuple[ScenarioCase, ...]:
    cases: list[ScenarioCase] = []

    episode = ScenarioFamily.CLEAN_SUCCESS.value
    cases.append(
        case(
            ScenarioFamily.CLEAN_SUCCESS,
            observations=(
                pre(episode),
                pick_post(episode),
                place_pre(episode, 3),
                place_post(episode, 4),
            ),
            receipts=(ReceiptStatus.COMPLETED, ReceiptStatus.COMPLETED),
            ground_truth=(
                truth("pick-1", effect=Verdict.PASS, handoff=Verdict.PASS),
                truth("place-1", effect=Verdict.PASS, goal=Verdict.PASS),
            ),
            two_steps=True,
            held_goal=False,
            final_state=RuntimeState.DONE,
            dispatch=(2, 2),
            recovery=(0, 0),
            failure=FailureCategory.NONE,
            condition="clean",
        )
    )

    episode = ScenarioFamily.EFFECT_FAIL.value
    cases.append(
        case(
            ScenarioFamily.EFFECT_FAIL,
            observations=(pre(episode), pick_post(episode, held=None, following=False)),
            receipts=(ReceiptStatus.COMPLETED,),
            ground_truth=(truth("pick-1", effect=Verdict.FAIL),),
            two_steps=False,
            held_goal=True,
            final_state=RuntimeState.STOPPED,
            dispatch=(1, 1),
            recovery=(1, 1),
            failure=FailureCategory.EFFECT,
            condition="clean",
        )
    )

    episode = ScenarioFamily.EFFECT_UNKNOWN_RESOLVED.value
    cases.append(
        case(
            ScenarioFamily.EFFECT_UNKNOWN_RESOLVED,
            observations=(
                pre(episode),
                pick_post(episode, holding_known=False, held=None),
                pick_post(episode, 3),
            ),
            receipts=(ReceiptStatus.COMPLETED,),
            ground_truth=(truth("pick-1", effect=Verdict.PASS, goal=Verdict.PASS),),
            two_steps=False,
            held_goal=True,
            final_state=RuntimeState.DONE,
            dispatch=(1, 1),
            recovery=(1, 1),
            failure=FailureCategory.NONE,
            condition="clean",
        )
    )

    episode = ScenarioFamily.EFFECT_UNKNOWN_EXHAUSTED.value
    cases.append(
        case(
            ScenarioFamily.EFFECT_UNKNOWN_EXHAUSTED,
            observations=(
                pre(episode),
                pick_post(episode, holding_known=False, held=None),
                pick_post(episode, 3, holding_known=False, held=None),
                pick_post(episode, 4, holding_known=False, held=None),
            ),
            receipts=(ReceiptStatus.COMPLETED,),
            ground_truth=(truth("pick-1", effect=Verdict.UNKNOWN),),
            two_steps=False,
            held_goal=True,
            final_state=RuntimeState.STOPPED,
            dispatch=(1, 1),
            recovery=(4, 4),
            failure=FailureCategory.UNKNOWN,
            condition="chained",
        )
    )

    episode = ScenarioFamily.HANDOFF_FAIL.value
    cases.append(
        case(
            ScenarioFamily.HANDOFF_FAIL,
            observations=(pre(episode), pick_post(episode, place_ready=False)),
            receipts=(ReceiptStatus.COMPLETED,),
            ground_truth=(
                truth("pick-1", effect=Verdict.PASS, handoff=Verdict.FAIL),
                truth("place-1", effect=Verdict.UNKNOWN),
            ),
            two_steps=True,
            held_goal=False,
            final_state=RuntimeState.STOPPED,
            dispatch=(1, 1),
            recovery=(0, 0),
            failure=FailureCategory.HANDOFF,
            condition="chained",
        )
    )

    episode = ScenarioFamily.HANDOFF_UNKNOWN_RESOLVED.value
    cases.append(
        case(
            ScenarioFamily.HANDOFF_UNKNOWN_RESOLVED,
            observations=(
                pre(episode),
                pick_post(episode, place_ready=None),
                pick_post(episode, 3),
                place_pre(episode, 4),
                place_post(episode, 5),
            ),
            receipts=(ReceiptStatus.COMPLETED, ReceiptStatus.COMPLETED),
            ground_truth=(
                truth("pick-1", effect=Verdict.PASS, handoff=Verdict.PASS),
                truth("place-1", effect=Verdict.PASS, goal=Verdict.PASS),
            ),
            two_steps=True,
            held_goal=False,
            final_state=RuntimeState.DONE,
            dispatch=(2, 2),
            recovery=(1, 1),
            failure=FailureCategory.NONE,
            condition="chained",
        )
    )

    episode = ScenarioFamily.STALE_POST_OBSERVATION.value
    cases.append(
        case(
            ScenarioFamily.STALE_POST_OBSERVATION,
            observations=(pre(episode), pick_post(episode, 1)),
            receipts=(ReceiptStatus.COMPLETED,),
            ground_truth=(truth("pick-1", effect=Verdict.UNKNOWN),),
            two_steps=False,
            held_goal=True,
            final_state=RuntimeState.STOPPED,
            dispatch=(0, 0),
            recovery=(0, 0),
            failure=FailureCategory.OBSERVATION_ORDER,
            condition="chained",
        )
    )

    episode = ScenarioFamily.AMBIGUOUS_IDENTITY.value
    cases.append(
        case(
            ScenarioFamily.AMBIGUOUS_IDENTITY,
            observations=(pre(episode, ambiguous=True),),
            receipts=(ReceiptStatus.COMPLETED,),
            ground_truth=(truth("pick-1", effect=Verdict.UNKNOWN),),
            two_steps=False,
            held_goal=True,
            final_state=RuntimeState.STOPPED,
            dispatch=(0, 0),
            recovery=(0, 0),
            failure=FailureCategory.IDENTITY,
            condition="chained",
        )
    )

    episode = ScenarioFamily.INVALID_DEPTH_CALIBRATION.value
    cases.append(
        case(
            ScenarioFamily.INVALID_DEPTH_CALIBRATION,
            observations=(pre(episode, depth_valid=False),),
            receipts=(ReceiptStatus.COMPLETED,),
            ground_truth=(truth("pick-1", effect=Verdict.UNKNOWN),),
            two_steps=False,
            held_goal=True,
            final_state=RuntimeState.STOPPED,
            dispatch=(0, 0),
            recovery=(0, 0),
            failure=FailureCategory.GEOMETRY,
            condition="chained",
        )
    )

    episode = ScenarioFamily.TIMEOUT_RETRY_GOAL_FAIL.value
    cases.append(
        case(
            ScenarioFamily.TIMEOUT_RETRY_GOAL_FAIL,
            observations=(pre(episode), pre(episode, 2), pick_post(episode, 3)),
            receipts=(ReceiptStatus.TIMED_OUT, ReceiptStatus.COMPLETED),
            ground_truth=(
                truth("pick-1", attempt=0, effect=Verdict.UNKNOWN),
                truth("pick-1", attempt=1, effect=Verdict.PASS, goal=Verdict.FAIL),
            ),
            two_steps=False,
            held_goal=False,
            final_state=RuntimeState.STOPPED,
            dispatch=(2, 2),
            recovery=(1, 1),
            failure=FailureCategory.EXECUTION_AND_GOAL,
            condition="chained",
        )
    )
    return tuple(cases)


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    entries = []
    for item in build_cases():
        path = OUTPUT / f"{item.scenario_id}.json"
        text = json.dumps(
            item.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        ) + "\n"
        path.write_text(text, encoding="utf-8")
        entries.append(
            {
                "scenario_id": item.scenario_id,
                "family": item.family.value,
                "fixture": f"../../tests/fixtures/orchestration/benchmark/{path.name}",
                "content_id": "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest(),
            }
        )
    manifest = {
        "schema_version": "1.0.0",
        "benchmark_id": "orchestration-shadow-v1",
        "robot_execution_enabled": False,
        "entries": entries,
    }
    MANIFEST.write_text(
        yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    print(f"generated {len(entries)} cases and {MANIFEST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
