# Hybrid Verifier, Diagnosis, and Replanning Design

Status: approved by delegated user authority on 2026-08-07.

## Purpose

Extend the offline/shadow runtime with a calibrated verifier router, structured failure diagnosis,
and bounded replanning. Rules remain authoritative for hard safety and geometry; a VLM is an
optional semantic judge and may return only `PASS`, `FAIL`, or `UNKNOWN` with cited evidence.

## Boundaries

- Model code never receives an executor, SDK object, device path, or capability to modify files.
- Runtime core remains network-free. Optional model transports live under `orchestration/shadow`.
- The default and CI path uses scripted responses. Optional HTTP transport is disabled unless an
  explicit configuration enables one allow-listed endpoint.
- A model cannot override a deterministic hard `FAIL`, invent evidence IDs, introduce an
  unregistered Skill, change a contract version, increase a budget, or issue a command.

## Components

### Evidence bundle

`EvidenceBundle` contains the query, stage, current and previous snapshot IDs, selected object,
deterministic predicate results, allowed labels, risk class, model/prompt versions, and a bounded
set of evidence references. Raw images are represented by checked local references and hashes; the
core trace never embeds unbounded binary data.

### Verifier port and router

`VerifierPort.verify(bundle) -> VerifierDecision` is implemented by:

- `ScriptedVerifier` for replay and tests;
- `JsonHttpVerifier` for an optional OpenAI-compatible or other structured JSON endpoint through an
  injected transport;
- `RuleOnlyVerifier` for the baseline.

`VerifierRouter` chooses among rule-only, always-model, and event-triggered hybrid modes. It routes
to a model only for semantic predicates, rule `UNKNOWN`, evidence conflict, or configured
handoff/task-goal checks. Timeouts, invalid JSON, missing citations, unexpected labels, and model
errors return `UNKNOWN`. Model `PASS` is ignored when a hard rule has failed.

### Diagnosis

`FailureDiagnoser` maps trace evidence into a frozen taxonomy:

- stale or missing observation;
- target missing, ambiguous, or identity-lost;
- invalid depth or calibration;
- precondition, execution, effect, handoff, or task-goal failure;
- model timeout or malformed result;
- exhausted retry, re-observation, world-change, or replan budget.

A scripted/model diagnosis is accepted only if its cause is allowed by the observed reason codes.
Otherwise the deterministic cause is retained and the mismatch is traced.

### Bounded replanning

`BoundedReplanner.propose(context) -> ReplanDecision` may reorder or replace only remaining plan
steps using exact-version Skills already present in the registry. It cannot change completed steps,
task goal, evidence, safety facts, executor kind, or budgets. The validator rejects loops,
duplicate step IDs, missing handoff rules, unknown arguments, and proposals beyond the replan
budget. The default maximum is one accepted replan per episode.

## Supervisor Integration

The supervisor receives optional verifier, diagnosis, and replanner ports. Existing deterministic
behavior is unchanged when they are absent. Every routed model call, response hash, final decision,
diagnosis, rejected proposal, accepted replan, and budget delta is appended to the trace.

Recovery order is fixed:

1. re-observe without dispatch;
2. retry the same fake/shadow Skill when allowed;
3. try an explicitly registered policy variant in dry-run;
4. request one bounded replan;
5. stop.

No step can advance on `UNKNOWN`.

## Acceptance

1. Rule-only, always-model, and hybrid modes share the same typed inputs and outputs.
2. A model cannot override hard failure or advance without cited evidence.
3. Invalid, timed-out, or contradictory responses become `UNKNOWN` and terminate within budget.
4. Accepted replans contain only registered exact-version Skills and preserve completed history.
5. Replay produces deterministic trace events and counts verifier calls, timeouts, diagnoses,
   replans, latency, and configured cost.
