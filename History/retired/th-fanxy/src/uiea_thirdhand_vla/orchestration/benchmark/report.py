"""Deterministic machine-readable and paper-ready benchmark reports."""

from __future__ import annotations

import csv
import hashlib
import io
from pathlib import Path

from pydantic import Field

from ..runtime.models import FrozenModel
from ..runtime.trace import canonical_json, content_id
from .baselines import BenchmarkRun
from .metrics import RunMetricsV2, aggregate_metrics, compute_run_metrics

RUN_COLUMNS = (
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
)

SUMMARY_COLUMNS = (
    "baseline",
    "run_count",
    "advance_count",
    "false_advance_count",
    "false_advance_rate",
    "false_effect_advance_count",
    "false_handoff_advance_count",
    "false_task_goal_advance_count",
    "episode_success_count",
    "episode_success_rate",
    "safe_stop_count",
    "safe_stop_rate",
    "false_abort_count",
    "false_abort_rate",
    "unknown_count",
    "recovery_episode_count",
    "recovery_success_count",
    "recovery_success_rate",
    "replan_count",
    "replan_rate",
    "dispatch_count",
    "model_call_count",
    "model_timeout_count",
    "deterministic_latency_p50_ms",
    "deterministic_latency_p95_ms",
    "model_latency_p50_ms",
    "model_latency_p95_ms",
    "configured_cost_usd",
    "clean_run_count",
    "chained_run_count",
    "clean_false_advance_rate",
    "chained_false_advance_rate",
    "chained_minus_clean_false_advance_rate",
    "robot_execution_enabled",
)

LIMITATIONS = """# Limitations

These are deterministic replay/shadow experiments, not autonomous real-robot trials.
No camera, robot SDK, CAN interface, network model, or physical actuator was used.
The fixtures are synthetic counterexamples and do not establish manipulation success in the wild.
Configured model latency and cost are accounting constants, not measured service performance.
The supported claim is limited to advancement safety in this checked tabletop replay matrix.

Safety invariant: `robot_execution_enabled=false` and `can_execute_world=false`.
"""


class ReportArtifact(FrozenModel):
    path: str = Field(min_length=1)
    content_id: str = Field(min_length=1)


class ReportIndex(FrozenModel):
    run_count: int = Field(ge=0)
    artifacts: tuple[ReportArtifact, ...]
    robot_execution_enabled: bool = False


def _csv_text(rows: tuple[dict, ...], columns: tuple[str, ...]) -> str:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({column: row[column] for column in columns})
    return stream.getvalue()


def _run_row(metric: RunMetricsV2) -> dict:
    row = metric.model_dump(mode="json")
    row.pop("recovery_success")
    return row


class ReportWriter:
    def write(
        self,
        output_dir: Path,
        runs: tuple[BenchmarkRun, ...],
        *,
        provenance: dict | None = None,
    ) -> ReportIndex:
        output_dir = Path(output_dir)
        if output_dir.is_symlink() or (output_dir.exists() and not output_dir.is_dir()):
            raise ValueError("report output must be a non-symlink directory")
        output_dir.mkdir(parents=True, exist_ok=True)
        ordered_runs = tuple(sorted(runs, key=lambda run: (run.scenario_id, run.baseline.value)))
        metrics = tuple(compute_run_metrics(None, run) for run in ordered_runs)
        summaries = aggregate_metrics(metrics)

        run_lines = "".join(canonical_json(run) + "\n" for run in ordered_runs)
        run_rows = tuple(_run_row(item) for item in metrics)
        summary_rows = tuple(item.model_dump(mode="json") for item in summaries)
        metrics_payload = {
            "schema_version": "1.0.0",
            "run_count": len(runs),
            "robot_execution_enabled": False,
            "can_execute_world": False,
            "runs": tuple(item.model_dump(mode="json") for item in metrics),
            "summaries": summary_rows,
        }
        files = {
            "runs.jsonl": run_lines,
            "runs.csv": _csv_text(run_rows, RUN_COLUMNS),
            "summary.csv": _csv_text(summary_rows, SUMMARY_COLUMNS),
            "metrics.json": canonical_json(metrics_payload) + "\n",
            "table.md": self._markdown_table(summaries),
            "table.tex": self._latex_table(summaries),
            "reproducibility.json": canonical_json(
                {
                    "schema_version": "1.0.0",
                    "run_count": len(runs),
                    "canonical_runs_id": content_id(ordered_runs),
                    "decision_schema": "evidence-gated-orchestration-v1",
                    "provenance": provenance or {},
                    "robot_execution_enabled": False,
                    "can_execute_world": False,
                }
            )
            + "\n",
            "failure-gallery.md": self._failure_gallery(metrics),
            "LIMITATIONS.md": LIMITATIONS,
        }
        artifacts: list[ReportArtifact] = []
        for name in sorted(files):
            text = files[name]
            (output_dir / name).write_text(text, encoding="utf-8", newline="\n")
            artifacts.append(
                ReportArtifact(
                    path=name,
                    content_id="sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest(),
                )
            )
        return ReportIndex(
            run_count=len(runs),
            artifacts=tuple(artifacts),
            robot_execution_enabled=False,
        )

    @staticmethod
    def _markdown_table(summaries) -> str:
        lines = [
            "# Orchestration Shadow Benchmark",
            "",
            "| Baseline | Runs | False advances | FAR | Success | Safe stops | "
            "Model calls | Cost (USD) |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
        lines.extend(
            f"| {item.baseline.value} | {item.run_count} | "
            f"{item.false_advance_count} | {item.false_advance_rate:.3f} | "
            f"{item.episode_success_count} | {item.safe_stop_count} | "
            f"{item.model_call_count} | {item.configured_cost_usd:.3f} |"
            for item in summaries
        )
        lines.extend(
            [
                "",
                "Replay/shadow evidence only; robot_execution_enabled=false.",
            ]
        )
        return "\n".join(lines) + "\n"

    @staticmethod
    def _latex_table(summaries) -> str:
        lines = [
            r"\begin{tabular}{lrrrrrr}",
            r"\toprule",
            r"Baseline & Runs & False adv. & FAR & Success & Safe stop & Model calls \\",
            r"\midrule",
        ]
        for item in summaries:
            name = item.baseline.value.replace("_", r"\_")
            lines.append(
                f"{name} & {item.run_count} & {item.false_advance_count} & "
                f"{item.false_advance_rate:.3f} & {item.episode_success_count} & "
                f"{item.safe_stop_count} & {item.model_call_count} " + r"\\"
            )
        lines.extend([r"\bottomrule", r"\end{tabular}"])
        return "\n".join(lines) + "\n"

    @staticmethod
    def _failure_gallery(metrics: tuple[RunMetricsV2, ...]) -> str:
        failures = tuple(
            item
            for item in metrics
            if item.false_advance_count > 0 or item.false_abort
        )
        lines = [
            "# Failure Gallery",
            "",
            "Counterexamples are replay-only and never dispatched to hardware.",
            "",
        ]
        if not failures:
            lines.append("No false advances or false aborts in the selected runs.")
        else:
            lines.extend(
                f"- `{item.scenario_id}` / `{item.baseline.value}`: "
                f"false_advances={item.false_advance_count}, "
                f"false_abort={str(item.false_abort).lower()}"
                for item in failures
            )
        return "\n".join(lines) + "\n"


__all__ = ["ReportArtifact", "ReportIndex", "ReportWriter", "RUN_COLUMNS"]
