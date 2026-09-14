import csv
import json
from pathlib import Path

from uiea_thirdhand_vla.orchestration.benchmark.baselines import BaselineKind
from uiea_thirdhand_vla.orchestration.benchmark.evaluator import BenchmarkEvaluator
from uiea_thirdhand_vla.orchestration.benchmark.metrics import (
    aggregate_metrics,
    compute_run_metrics,
)
from uiea_thirdhand_vla.orchestration.benchmark.models import (
    ScenarioFamily,
    load_manifest,
)
from uiea_thirdhand_vla.orchestration.benchmark.report import ReportWriter

ROOT = Path(__file__).resolve().parents[3]
MANIFEST = ROOT / "configs" / "orchestration" / "benchmark_v1.yaml"
SKILLS = (
    ROOT / "configs" / "skills" / "tabletop_pick.yaml",
    ROOT / "configs" / "skills" / "tabletop_place.yaml",
)
RUN_COLUMNS = [
    "scenario_id",
    "family",
    "condition",
    "baseline",
    "final_state",
    "advance_count",
    "false_advance_count",
    "false_effect_advance_count",
    "false_handoff_advance_count",
    "false_task_goal_advance_count",
    "false_advance_rate",
    "episode_success",
    "safe_stop",
    "false_abort",
    "unknown_count",
    "recovery_count",
    "replan_count",
    "dispatch_count",
    "model_call_count",
    "model_timeout_count",
    "deterministic_latency_p50_ms",
    "deterministic_latency_p95_ms",
    "model_latency_p50_ms",
    "model_latency_p95_ms",
    "configured_cost_usd",
    "robot_execution_enabled",
    "can_execute_world",
]


def all_data():
    manifest = load_manifest(MANIFEST)
    evaluator = BenchmarkEvaluator.from_skill_paths(SKILLS)
    runs = tuple(
        evaluator.run(case, baseline)
        for case in manifest.cases
        for baseline in BaselineKind
    )
    case_by_id = {case.scenario_id: case for case in manifest.cases}
    metrics = tuple(compute_run_metrics(case_by_id[run.scenario_id], run) for run in runs)
    return manifest, runs, metrics


def metric(metrics, family: ScenarioFamily, baseline: BaselineKind):
    return next(
        item
        for item in metrics
        if item.family is family and item.baseline is baseline
    )


def test_metrics_separate_false_effect_handoff_and_task_goal_advances():
    _, _, metrics = all_data()

    effect = metric(metrics, ScenarioFamily.EFFECT_FAIL, BaselineKind.RECEIPT_ONLY)
    handoff = metric(metrics, ScenarioFamily.HANDOFF_FAIL, BaselineKind.POST_ACTION)
    goal = metric(
        metrics, ScenarioFamily.TIMEOUT_RETRY_GOAL_FAIL, BaselineKind.RECEIPT_ONLY
    )

    assert effect.false_effect_advance_count >= 1
    assert handoff.false_handoff_advance_count == 1
    assert goal.false_task_goal_advance_count == 1


def test_metrics_capture_success_safe_stop_abort_unknown_cost_and_latency():
    _, _, metrics = all_data()

    clean = metric(metrics, ScenarioFamily.CLEAN_SUCCESS, BaselineKind.HYBRID)
    stopped = metric(metrics, ScenarioFamily.HANDOFF_FAIL, BaselineKind.HYBRID)
    unknown = metric(
        metrics, ScenarioFamily.EFFECT_UNKNOWN_EXHAUSTED, BaselineKind.HYBRID
    )
    always = metric(metrics, ScenarioFamily.CLEAN_SUCCESS, BaselineKind.ALWAYS_MODEL)

    assert clean.episode_success is True
    assert stopped.safe_stop is True
    assert clean.false_abort is False
    assert unknown.unknown_count > 0
    assert always.model_call_count > 0
    assert always.model_latency_p95_ms == 25.0
    assert always.configured_cost_usd > 0


def test_aggregation_reports_counts_rates_and_clean_chained_delta():
    _, _, metrics = all_data()

    summaries = aggregate_metrics(metrics)
    hybrid = next(item for item in summaries if item.baseline is BaselineKind.HYBRID)

    assert hybrid.run_count == 10
    assert hybrid.false_advance_count == 0
    assert hybrid.false_advance_rate == 0.0
    assert hybrid.recovery_episode_count > 0
    assert 0.0 <= hybrid.recovery_success_rate <= 1.0
    assert hybrid.clean_run_count == 3
    assert hybrid.chained_run_count == 7
    assert hybrid.chained_minus_clean_false_advance_rate == 0.0


def test_report_writer_emits_deterministic_machine_and_paper_formats(tmp_path):
    _, runs, _ = all_data()

    first = ReportWriter().write(tmp_path / "first", runs)
    second = ReportWriter().write(tmp_path / "second", runs)

    assert first.artifacts == second.artifacts
    required = {
        "runs.jsonl",
        "runs.csv",
        "summary.csv",
        "metrics.json",
        "table.md",
        "table.tex",
        "reproducibility.json",
        "failure-gallery.md",
        "LIMITATIONS.md",
    }
    assert {item.path for item in first.artifacts} == required
    with (tmp_path / "first" / "runs.csv").open(encoding="utf-8", newline="") as stream:
        assert next(csv.reader(stream)) == RUN_COLUMNS
    metrics_payload = json.loads(
        (tmp_path / "first" / "metrics.json").read_text(encoding="utf-8")
    )
    assert len(metrics_payload["runs"]) == 50
    assert len(metrics_payload["summaries"]) == 5
    limitations = (tmp_path / "first" / "LIMITATIONS.md").read_text(encoding="utf-8")
    assert "replay/shadow" in limitations
    assert "real-robot" in limitations
    assert "robot_execution_enabled=false" in limitations
