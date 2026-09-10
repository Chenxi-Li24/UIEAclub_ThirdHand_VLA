# Orchestration Benchmark and Paper Artifact Design

Status: approved by delegated user authority on 2026-08-07.

## Purpose

Turn the runtime into a reproducible offline research instrument. The benchmark measures whether
effect and next-Skill readiness evidence prevent false advancement under clean and chained states;
it does not claim real-robot results.

## Scenario Matrix

Ten deterministic episode families are checked in as compact JSON fixtures:

1. clean Pick-to-Place success;
2. completed receipt but Pick effect failure;
3. Pick effect unknown, then resolved by re-observation;
4. Pick effect unknown until re-observation budget exhaustion;
5. Pick effect pass but Place handoff failure;
6. handoff unknown, then resolved by re-observation;
7. stale or rolled-back post-action observation;
8. ambiguous or lost target identity;
9. invalid metric depth or calibration evidence;
10. execution timeout followed by bounded retry and terminal task-goal failure.

Each family contains a typed plan, ordered observations, scripted receipts, independent ground
truth, expected terminal state, expected dispatch/recovery/replan bounds, and failure category.
Fixtures are synthetic or derived from explicitly included checked events; private live images are
not copied into the benchmark.

## Baselines

- `receipt_only`: deliberately unsafe reference that advances on completed receipts;
- `rule_only`: deterministic monitors;
- `post_action`: verifies local effect but not handoff readiness;
- `always_model`: sends every eligible semantic decision to a scripted/model verifier;
- `hybrid`: hard rules plus event-triggered semantic verification and bounded recovery.

All baselines consume the same scenario contract. Unsafe baselines run only in a separate benchmark
simulator and never through an executor capable of side effects.

## Metrics

Primary:

- False Advance Rate, separated into effect, handoff, and task-goal false advances;
- episode success and safe-stop rate;
- false abort rate and unresolved `UNKNOWN` rate;
- recovery success and replan acceptance rate.

Secondary:

- dispatches, re-observations, retries, replans, verifier calls and timeouts;
- deterministic and model latency distributions;
- configured token/call cost;
- paired per-scenario deltas between clean and chained initial states.

Missing ground truth counts as unsafe for an advance. Hardware execution is always false and is
reported in every result.

## Runner and Outputs

One CLI validates a manifest, runs every scenario and baseline, and writes:

- per-run canonical JSONL traces;
- `runs.csv` and `summary.csv`;
- a machine-readable `metrics.json`;
- a Markdown and LaTeX table suitable for the paper;
- a reproducibility report containing commit, configuration, fixture and prompt hashes;
- a failure gallery index and explicit limitations section.

Repeated runs with the same inputs must produce identical decisions and metrics; wall-clock fields
are kept outside the canonical comparison payload.

## Paper Claim Boundary

The supported claim is: evidence-gated effect and semantic-handoff verification reduces false
advancement in a low-cost tabletop manipulation replay benchmark under bounded cost and recovery.
The benchmark cannot support claims about autonomous real-robot success, learned-policy quality, or
general household manipulation until separately approved real trials exist.

## Acceptance

1. All ten scenario families terminate within declared budgets.
2. Negative ground-truth episodes show zero false advances for the proposed hybrid runtime.
3. The unsafe receipt-only and post-action baselines expose the intended counterexamples.
4. Repeated runs produce identical decision sequences, metrics, and table values.
5. The runner writes complete JSONL, CSV, JSON, Markdown, LaTeX, reproducibility, and limitation
   artifacts without hardware, camera, network, or model downloads.
