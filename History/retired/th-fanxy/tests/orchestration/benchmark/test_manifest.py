import hashlib
from pathlib import Path

from uiea_thirdhand_vla.orchestration.benchmark.models import (
    ScenarioFamily,
    load_case,
    load_manifest,
)

ROOT = Path(__file__).resolve().parents[3]
MANIFEST = ROOT / "configs" / "orchestration" / "benchmark_v1.yaml"


def test_manifest_loads_exactly_ten_unique_scenario_families():
    manifest = load_manifest(MANIFEST)

    assert len(manifest.cases) == 10
    assert len({case.scenario_id for case in manifest.cases}) == 10
    assert {case.family for case in manifest.cases} == set(ScenarioFamily)
    assert manifest.robot_execution_enabled is False
    assert all(case.robot_execution_enabled is False for case in manifest.cases)


def test_manifest_hashes_regular_local_typed_fixtures():
    manifest = load_manifest(MANIFEST)

    for entry, case in zip(manifest.entries, manifest.cases, strict=True):
        fixture = (MANIFEST.parent / entry.fixture).resolve()
        assert fixture.is_file()
        assert not fixture.is_symlink()
        actual = "sha256:" + hashlib.sha256(fixture.read_bytes()).hexdigest()
        assert entry.content_id == actual
        assert load_case(fixture) == case
        assert case.replay.plan.episode_id == case.scenario_id
        assert case.replay.ground_truth


def test_expectations_have_bounded_counts_and_independent_labels():
    manifest = load_manifest(MANIFEST)

    for case in manifest.cases:
        expected = case.expectation
        assert expected.dispatch_min <= expected.dispatch_max
        assert expected.recovery_min <= expected.recovery_max
        assert expected.replan_min <= expected.replan_max <= 1
        labels = {(item.step_id, item.attempt) for item in case.replay.ground_truth}
        assert len(labels) == len(case.replay.ground_truth)


def test_matrix_includes_clean_and_chained_conditions():
    manifest = load_manifest(MANIFEST)

    conditions = {case.condition for case in manifest.cases}

    assert conditions == {"clean", "chained"}
