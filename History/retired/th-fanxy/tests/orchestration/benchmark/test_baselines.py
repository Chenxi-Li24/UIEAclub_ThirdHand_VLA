from pathlib import Path

from uiea_thirdhand_vla.orchestration.benchmark.baselines import BaselineKind
from uiea_thirdhand_vla.orchestration.benchmark.evaluator import BenchmarkEvaluator
from uiea_thirdhand_vla.orchestration.benchmark.models import (
    ScenarioFamily,
    load_manifest,
)
from uiea_thirdhand_vla.orchestration.runtime.models import RuntimeState

ROOT = Path(__file__).resolve().parents[3]
MANIFEST = ROOT / "configs" / "orchestration" / "benchmark_v1.yaml"
SKILLS = (
    ROOT / "configs" / "skills" / "tabletop_pick.yaml",
    ROOT / "configs" / "skills" / "tabletop_place.yaml",
)


def setup():
    manifest = load_manifest(MANIFEST)
    return manifest, BenchmarkEvaluator.from_skill_paths(SKILLS)


def family(manifest, value: ScenarioFamily):
    return next(case for case in manifest.cases if case.family is value)


def test_receipt_only_exposes_completed_receipt_effect_counterexample():
    manifest, evaluator = setup()

    run = evaluator.run(
        family(manifest, ScenarioFamily.EFFECT_FAIL), BaselineKind.RECEIPT_ONLY
    )

    assert run.false_advance_count >= 1
    assert run.false_effect_advance_count >= 1
    assert run.final_state is RuntimeState.DONE


def test_post_action_exposes_semantic_handoff_counterexample():
    manifest, evaluator = setup()

    run = evaluator.run(
        family(manifest, ScenarioFamily.HANDOFF_FAIL), BaselineKind.POST_ACTION
    )

    assert run.false_handoff_advance_count == 1


def test_rule_only_stops_safely_on_unresolved_semantic_unknown():
    manifest, evaluator = setup()

    run = evaluator.run(
        family(manifest, ScenarioFamily.EFFECT_UNKNOWN_EXHAUSTED),
        BaselineKind.RULE_ONLY,
    )

    assert run.final_state is RuntimeState.STOPPED
    assert run.false_advance_count == 0
    assert run.unknown_count > 0
    assert run.model_call_count == 0


def test_always_model_calls_every_gate_and_hybrid_is_event_triggered():
    manifest, evaluator = setup()
    clean = family(manifest, ScenarioFamily.CLEAN_SUCCESS)

    always = evaluator.run(clean, BaselineKind.ALWAYS_MODEL)
    hybrid = evaluator.run(clean, BaselineKind.HYBRID)

    assert always.model_call_count == always.semantic_gate_count
    assert always.model_call_count > 0
    assert hybrid.model_call_count == 0
    assert hybrid.model_call_count < always.model_call_count


def test_hybrid_never_advances_on_negative_truth():
    manifest, evaluator = setup()
    negative = tuple(
        case
        for case in manifest.cases
        if case.expectation.final_state is RuntimeState.STOPPED
    )

    runs = tuple(evaluator.run(case, BaselineKind.HYBRID) for case in negative)

    assert runs
    assert all(run.false_advance_count == 0 for run in runs)
    assert all(run.robot_execution_enabled is False for run in runs)


def test_all_five_baselines_terminate_for_all_cases():
    manifest, evaluator = setup()

    runs = tuple(
        evaluator.run(case, baseline)
        for case in manifest.cases
        for baseline in BaselineKind
    )

    assert len(runs) == 50
    assert {run.baseline for run in runs} == set(BaselineKind)
    assert all(run.can_execute_world is False for run in runs)
