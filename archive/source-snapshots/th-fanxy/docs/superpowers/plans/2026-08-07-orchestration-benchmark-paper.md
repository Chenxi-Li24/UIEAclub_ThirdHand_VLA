# Orchestration Benchmark and Paper Artifacts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a deterministic ten-scenario benchmark, five baselines, research metrics, and reproducible paper-ready tables for the evidence-gated orchestration claim.

**Architecture:** A strict benchmark manifest references compact replay bundles and independent ground truth. Baseline policies run through a hardware-free evaluator. Canonical run records feed one metrics/report layer that emits JSONL, CSV, JSON, Markdown, LaTeX, and a reproducibility report.

**Tech Stack:** Python 3.10+, Pydantic v2, standard-library csv/json/hash/statistics/path, pytest, Ruff.

## Global Constraints

- No hardware, camera, network, model download, or subprocess access.
- Every scenario and baseline terminates within explicit budgets.
- Ground truth is independent from runtime decisions; missing truth makes an advance false.
- Canonical decisions and metrics are deterministic; wall time is not part of equality checks.
- Reports must state that results are replay/shadow evidence, not autonomous real-robot trials.

---

### Task 1: Benchmark Manifest and Ten Scenario Fixtures

**Files:**
- Create: `src/uiea_thirdhand_vla/orchestration/benchmark/__init__.py`
- Create: `src/uiea_thirdhand_vla/orchestration/benchmark/models.py`
- Create: `configs/orchestration/benchmark_v1.yaml`
- Create: `tests/fixtures/orchestration/benchmark/*.json`
- Test: `tests/orchestration/benchmark/test_manifest.py`

**Interfaces:**
- Produces: `ScenarioExpectation`, `ScenarioCase`, `BenchmarkManifest`.
- Produces: `load_manifest(path: Path) -> BenchmarkManifest` and `load_case(path: Path) -> ScenarioCase`.

- [ ] **Step 1: Write failing manifest tests**

Require exactly the ten named scenario families, unique IDs, local regular fixture paths, content
hashes, typed replay bundles, independent expected outcome/count bounds/failure category, and
explicit `robot_execution_enabled=false`.

- [ ] **Step 2: Verify failure**

Run: `.venv/bin/pytest -q tests/orchestration/benchmark/test_manifest.py`

Expected: FAIL because benchmark modules and fixtures are absent.

- [ ] **Step 3: Implement strict loading and add all ten fixtures**

Create fixtures for success, effect fail, effect unknown resolved/exhausted, handoff fail/unknown
resolved, stale post-observation, ambiguous identity, invalid depth/calibration, and timeout retry
ending in task-goal failure. Each fixture includes exact receipt/observation sequences and expected
dispatch/recovery bounds.

- [ ] **Step 4: Verify and commit**

Run: `.venv/bin/pytest -q tests/orchestration/benchmark/test_manifest.py`

Expected: PASS with ten cases loaded.

```bash
git add src/uiea_thirdhand_vla/orchestration/benchmark configs/orchestration/benchmark_v1.yaml tests/fixtures/orchestration/benchmark tests/orchestration/benchmark/test_manifest.py
git commit -m "test(orchestration): define ten-case shadow benchmark"
```

---

### Task 2: Five Hardware-Free Baselines

**Files:**
- Create: `src/uiea_thirdhand_vla/orchestration/benchmark/baselines.py`
- Create: `src/uiea_thirdhand_vla/orchestration/benchmark/evaluator.py`
- Test: `tests/orchestration/benchmark/test_baselines.py`

**Interfaces:**
- Produces: `BaselineKind` values `receipt_only`, `rule_only`, `post_action`, `always_model`, `hybrid`.
- Produces: `BenchmarkEvaluator.run(case: ScenarioCase, baseline: BaselineKind) -> BenchmarkRun`.

- [ ] **Step 1: Write failing baseline counterexample tests**

Assert receipt-only falsely advances after a completed receipt/effect failure; post-action falsely
advances through failed handoff; rule-only is safe but can stop on semantic unknown; always-model
records every eligible model call; hybrid never advances on negative truth and uses fewer calls on
rule-sufficient cases.

- [ ] **Step 2: Verify failure**

Run: `.venv/bin/pytest -q tests/orchestration/benchmark/test_baselines.py`

Expected: FAIL because baselines are absent.

- [ ] **Step 3: Implement isolated baseline evaluators**

Run safe baselines through `EvidenceGatedSupervisor` plus scripted verifiers. Implement unsafe
receipt/post-action references only as pure trace evaluators over the same bundle; they receive no
executor object and cannot write command previews.

- [ ] **Step 4: Verify and commit**

Run: `.venv/bin/pytest -q tests/orchestration/benchmark/test_baselines.py`

Expected: PASS.

```bash
git add src/uiea_thirdhand_vla/orchestration/benchmark tests/orchestration/benchmark/test_baselines.py
git commit -m "feat(orchestration): add shadow benchmark baselines"
```

---

### Task 3: Research Metrics and Deterministic Reports

**Files:**
- Create: `src/uiea_thirdhand_vla/orchestration/benchmark/metrics.py`
- Create: `src/uiea_thirdhand_vla/orchestration/benchmark/report.py`
- Test: `tests/orchestration/benchmark/test_metrics_report.py`

**Interfaces:**
- Produces: `RunMetricsV2`, `BaselineSummary`, `compute_run_metrics`, `aggregate_metrics`.
- Produces: `ReportWriter.write(output_dir: Path, runs: tuple[BenchmarkRun, ...]) -> ReportIndex`.

- [ ] **Step 1: Write failing metric/report tests**

Verify effect/handoff/task-goal false advances, episode success, safe stop, false abort, unknown,
recovery/replan rate, dispatch/model/timeout counts, latency percentiles, configured cost, and
clean/chained paired deltas. Golden-test CSV column order, canonical JSON, Markdown and LaTeX rows,
hashes, and limitations text.

- [ ] **Step 2: Verify failure**

Run: `.venv/bin/pytest -q tests/orchestration/benchmark/test_metrics_report.py`

Expected: FAIL because metrics/report modules are absent.

- [ ] **Step 3: Implement one-source-of-truth aggregation**

Compute all formats from frozen `BenchmarkRun` records. Sort by scenario and baseline. Use explicit
zero-denominator behavior, population counts beside rates, nearest-rank percentiles, and canonical
float serialization. Put timestamps outside hashed reproducibility content.

- [ ] **Step 4: Verify and commit**

Run: `.venv/bin/pytest -q tests/orchestration/benchmark/test_metrics_report.py`

Expected: PASS.

```bash
git add src/uiea_thirdhand_vla/orchestration/benchmark tests/orchestration/benchmark/test_metrics_report.py
git commit -m "feat(orchestration): compute paper benchmark metrics"
```

---

### Task 4: Benchmark CLI and Checked Paper Artifacts

**Files:**
- Create: `scripts/orchestration/run_benchmark.py`
- Create: `docs/experiments/orchestration-shadow-v1/README.md`
- Create: `docs/experiments/orchestration-shadow-v1/LABELING.md`
- Create: `docs/experiments/orchestration-shadow-v1/LIMITATIONS.md`
- Generate: `artifacts/orchestration-shadow-v1/*`
- Test: `tests/orchestration/benchmark/test_benchmark_cli.py`

**Interfaces:**
- CLI: `--manifest`, `--skills`, `--output-dir`, repeated `--baseline`.

- [ ] **Step 1: Write failing end-to-end and repeatability tests**

Run all ten scenarios and five baselines twice into separate temporary directories. Assert 50 run
records, identical canonical traces/metrics/tables, zero proposed-hybrid false advances on negative
truth, exposed unsafe-baseline counterexamples, and all required output files.

- [ ] **Step 2: Verify failure**

Run: `.venv/bin/pytest -q tests/orchestration/benchmark/test_benchmark_cli.py`

Expected: FAIL because the CLI and artifacts are absent.

- [ ] **Step 3: Implement CLI, documentation, and generate checked outputs**

The CLI validates paths and manifest hashes before running. It writes one trace per run plus
`runs.csv`, `summary.csv`, `metrics.json`, `table.md`, `table.tex`, `reproducibility.json`,
`failure-gallery.md`, and `LIMITATIONS.md`. Generate the checked artifact directory using the CLI,
not handwritten values.

- [ ] **Step 4: Run full scoped verification**

Run:

```bash
.venv/bin/pytest -q tests/orchestration
.venv/bin/ruff check src/uiea_thirdhand_vla/orchestration scripts/orchestration tests/orchestration
.venv/bin/python scripts/orchestration/run_benchmark.py \
  --manifest configs/orchestration/benchmark_v1.yaml \
  --skills configs/skills/tabletop_pick.yaml configs/skills/tabletop_place.yaml \
  --output-dir artifacts/orchestration-shadow-v1 \
  --baseline receipt_only --baseline rule_only --baseline post_action \
  --baseline always_model --baseline hybrid
git diff --check -- src/uiea_thirdhand_vla/orchestration scripts/orchestration tests/orchestration configs/orchestration docs/experiments artifacts/orchestration-shadow-v1
```

Expected: all scoped tests and Ruff pass; the CLI reports 50 runs and real execution disabled.

- [ ] **Step 5: Commit**

```bash
git add src/uiea_thirdhand_vla/orchestration/benchmark scripts/orchestration/run_benchmark.py configs/orchestration/benchmark_v1.yaml tests/orchestration/benchmark tests/fixtures/orchestration/benchmark docs/experiments/orchestration-shadow-v1 artifacts/orchestration-shadow-v1
git commit -m "feat(orchestration): deliver reproducible shadow benchmark"
```
