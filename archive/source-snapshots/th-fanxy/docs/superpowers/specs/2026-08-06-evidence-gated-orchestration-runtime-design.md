# Evidence-Gated Offline Orchestration Runtime Design

Date: 2026-08-06

Status: design approved; awaiting written-spec review before implementation planning

Scope: offline replay, read-only vision events, and a fake executor only

## 1. Decision

ThirdHand will add a contract-first orchestration runtime beside the existing deterministic state machine. The first delivery is an offline and shadow-mode research kernel. It may consume recorded observations or the existing read-only vision JSON, but it must not import, connect to, or command the Startouch SDK, CAN interface, robot bridge, or gripper bridge.

The runtime exists to test one research claim: a robot task should advance only when fresh evidence establishes both the current Skill's expected effect and the readiness conditions of the next Skill. A command receipt never establishes either condition.

### 1.1 Initial scaffold slice

Per the user's scope update, the immediate implementation stops at a runnable framework scaffold. It
includes the stable contracts, fake/replay ports, pick/place Skill files, deterministic core monitors,
bounded re-observation/retry, supervisor, trace, False Advance Rate, and representative safety tests.
The complete ten-case replay matrix, broad vision-event normalization, exhaustive error taxonomy,
and production hardening remain follow-on work under this design rather than blockers for the
initial scaffold.

## 2. Goals

The first delivery will:

1. represent plans, Skills, observations, receipts, verification decisions, recovery budgets, and trace events with strict immutable contracts;
2. run fixed typed plans through a deterministic evidence-gated supervisor;
3. separate command completion, expected effect, next-Skill readiness, and task success;
4. return `PASS`, `FAIL`, or `UNKNOWN` for every predicate and fail closed on missing or stale evidence;
5. support bounded re-observation and fake-execution retry without unbounded loops;
6. write an append-only, replayable trace with content-addressed evidence references;
7. adapt existing read-only REMIND-3D vision events without importing heavy vision models into the runtime;
8. calculate False Advance Rate and supporting orchestration metrics from a replay.

## 3. Non-goals

The first delivery will not:

- provide a Startouch, CAN, robot, gripper, ROS, or MoveIt adapter;
- execute any real or simulated physical motion outside the deterministic fake world;
- replace or modify the current `StateMachine` or `CentralControlUnit`;
- call an LLM, VLM, Grounding DINO, or learned robot policy;
- train RTMDet, DINO, REMIND, ACT, Diffusion Policy, or any other model;
- implement RoboHarness's Memory Bridge or automatic skill acquisition;
- accept model-generated Python or dynamically execute monitor code;
- treat a successful SDK-style receipt as proof of a world-state change;
- promote a single successful trace into a reviewed Skill.

These capabilities remain future adapters behind the contracts defined here.

## 4. Reuse of Existing Work

| Source | Reused mechanism | ThirdHand use | Deliberately not copied in phase one |
|---|---|---|---|
| OpenETA | one world-changing call followed by a fresh observation; host-owned interface; trusted receipts | supervisor sequencing, executor port, receipt contract, replay boundary | full OpenETA runtime and broad tool registry |
| RoboHarness | policy cards, capability boundaries, execution evidence | `PolicyVariant` metadata and later calibration fields | Memory Bridge and online policy evolution |
| Semantic Handoff | clean versus chained evaluation; next-Skill readiness distinct from local effect | separate effect and readiness verification and metrics | VLA checkpoints and multi-view VLM verifier |
| Code-as-Monitor | spatiotemporal constraints and compact deterministic monitors | typed predicate specifications evaluated by local code | runtime VLM code generation or arbitrary code execution |
| PLanAR and ProgPrompt | explicit preconditions, effects, assertions, and recovery branches | declarative Skill contracts and precheck/effect stages | PDDL planner and generated executable programs |
| DoReMi, REFLECT, and LERa | failure-triggered diagnosis and replanning | structured failure classes and future replanner port | phase-one VLM diagnosis and replanning |
| RTMDet-Ins | fast instance masks | existing read-only detector output is an evidence source | a second detector integration |
| DINO and REMIND | appearance descriptors, persistent identity, ambiguity-aware assignment | existing identity and provenance fields are preserved by the adapter | retraining or replacing the existing memory implementation |
| Grounding DINO | language-conditioned open-vocabulary detection | reserved on-demand observation adapter | permanent invocation in the main perception loop |

The orchestration runtime is new project code, but its semantics are intentionally built from these established mechanisms. The paper contribution is not the existence of a Skill registry. It is the evidence- and risk-sensitive decision to advance, re-observe, recover, or stop at Skill boundaries.

## 5. Package Boundary

New runtime code will live under:

```text
src/uiea_thirdhand_vla/orchestration/runtime/
    __init__.py
    models.py
    ports.py
    registry.py
    supervisor.py
    monitors.py
    recovery.py
    trace.py
    metrics.py
    adapters/
        __init__.py
        fake_executor.py
        replay_observation.py
        vision_event.py
```

Configuration and tests will live under:

```text
configs/skills/tabletop_pick.yaml
configs/skills/tabletop_place.yaml
scripts/orchestration/run_shadow_replay.py
tests/orchestration/runtime/
tests/fixtures/orchestration/
```

The existing `orchestration/state_machine.py`, `orchestration/central_control.py`, `web-control/server/startouch_bridge.py`, and vision implementation remain unchanged. The runtime may consume serialized vision events, but `src/.../runtime` must not import from `web-control`.

## 6. Stable Contracts

Contracts use Pydantic v2 models configured as frozen with unknown fields forbidden. JSON serialization must reject NaN and infinity. IDs and enumerations are stable strings; poses always carry frame, units, timestamp, and calibration identity.

### 6.1 Evidence and observation

`EvidenceRef` contains:

- `evidence_id`: `sha256:<64 lowercase hex characters>`;
- `kind`: frame, depth summary, identity, robot state, receipt, predicate, or annotation;
- `source`: producer identity;
- `observed_monotonic_ns`;
- an episode-relative `artifact_path` or inline deterministic payload metadata. Absolute paths,
  parent traversal, and symlink escapes are rejected.

`ObservationSnapshot` contains:

- episode and snapshot IDs;
- monotonically increasing sequence and time;
- source and source version;
- zero or more `ObjectObservation` records;
- optional `RobotObservation` and task facts;
- calibration, detector, descriptor, and identity-memory versions when available;
- evidence references supporting every populated fact.

An absent fact is unknown. It is never replaced with a default success value.

### 6.2 Plan and Skill

`TypedPlan` contains an explicit tuple of task-goal predicates and an ordered tuple of
`SkillCall` values. Each call binds a `skill_id`, exact contract version, typed arguments, and
logical step ID.

`SkillContract` contains:

- identity and semantic version;
- risk class and allowed executor kinds;
- typed inputs with units, frame, range, and freshness requirements;
- precondition predicates;
- invariants;
- expected-effect predicates;
- next-Skill-indexed handoff-readiness predicates;
- policy variants and capability metadata;
- execution, observation, and verification timeouts;
- re-observation, retry, and logical world-change budgets.

Phase-one Skill files allow only `executor_kind: fake`.

### 6.3 Command and verification

`CommandRequest` is derived by the host from a validated SkillCall. Planner-provided values cannot change safety limits or executor kind.

`CommandReceipt` reports accepted, completed, rejected, failed, or timed out, with correlation ID, timestamps, and executor evidence. `completed` means only that the fake command lifecycle ended.

`PredicateResult` contains:

- `PASS`, `FAIL`, or `UNKNOWN`;
- predicate ID and evaluated value;
- reason code;
- evidence IDs;
- observation snapshot ID;
- monitor identity and version.

`VerificationResult` groups predicate results for exactly one stage: precondition, invariant, effect, handoff, or task goal. A hard `FAIL` dominates. All predicates must pass for the stage to pass. Any remaining case is `UNKNOWN`.

## 7. Ports and Components

### 7.1 Plan source

The phase-one `PlanSource` reads a fixed validated plan fixture. There is no natural-language planner. A future LLM planner must return the same `TypedPlan` and will receive no executor handle.

### 7.2 Skill registry

The registry loads YAML contracts by explicit path, validates them once, rejects duplicate `(skill_id, version)` pairs, and resolves each call to an exact version. It does not silently choose the newest version.

### 7.3 Observation source

`ObservationSource.next_snapshot(after_sequence, deadline)` returns a strictly newer snapshot or a structured exhaustion/timeout result. The supervisor, rather than an adapter, decides whether freshness is sufficient.

### 7.4 Executor

The only implementation is `FakeExecutor`. It consumes scripted outcomes and returns deterministic receipts. It exposes no networking, SDK, subprocess, CAN, or robot imports. Its executor kind is immutable and equal to `fake`.

### 7.5 Monitors

The deterministic monitor set supports:

- observation freshness and sequence progression;
- calibration and model-version consistency;
- target identity equality and ambiguity rejection;
- visibility and actionable-state checks;
- valid depth and bounded pose uncertainty;
- position delta and region membership;
- gripper/held-object facts when supplied by a fake observation;
- task-specific Boolean and bounded numeric facts.

The read-only vision adapter accepts an already serialized local JSON object or JSONL record. It
does not perform network access. It rejects an event unless `robot_execution_enabled` is explicitly
`false`, and can establish only facts present in current vision output. Missing robot, gripper,
attachment, or task facts remain unknown.

### 7.6 Recovery manager

The Recovery Manager is a deterministic policy over failure class and remaining budgets. Phase one permits only:

1. `REOBSERVE` for stale, missing, conflicting, or unknown evidence;
2. `RETRY_SAME_FAKE` for configured reversible fake failures after a fresh precheck;
3. `STOP` when a hard failure is not retryable or any budget is exhausted.

No execution retry inherits a previous `PASS`; every new attempt returns to a fresh observation and
precheck. `REOBSERVE` performs no dispatch: it obtains a newer snapshot and resumes only the
blocked precheck, effect, handoff, or task-goal verifier.

### 7.7 Trace and metrics

The trace writer appends canonical JSON Lines. Every event contains episode ID, step ID, attempt, monotonic and wall timestamps, event type, correlation ID, component versions, and evidence references. A write or serialization failure stops the episode.

The replay runner reconstructs supervisor input from the trace/fixture without invoking live cameras or executors. Injected clock and ID providers make fixture replays deterministic.

Metrics include:

- task completion and pass-at-one;
- effect, handoff, and task-goal `PASS/FAIL/UNKNOWN` counts;
- recovery attempts and budget exhaustion;
- observation and stage latency from trace timestamps;
- false abort count when fixture ground truth marks a state valid;
- False Advance Rate: the fraction of transitions to the next Skill or `DONE` for which fixture
  ground truth marks the required effect, readiness, or task goal false or unknown. The report also
  includes numerator and eligible-transition count; when no eligible transition occurs, the rate is
  reported as zero with count zero rather than as evidence of safety.

## 8. Supervisor Data Flow

The state sequence is:

```text
IDLE
  -> LOAD_PLAN
  -> OBSERVE_PRE
  -> PRECHECK
  -> DISPATCH
  -> AWAIT_RECEIPT
  -> OBSERVE_POST
  -> VERIFY_EFFECT
  -> VERIFY_HANDOFF      # skipped only when there is no next Skill
  -> VERIFY_TASK_GOAL    # required before DONE on the final Skill
  -> ADVANCE or DONE
```

Any recoverable stage may enter `RECOVER`. A retry returns to `OBSERVE_PRE`; a re-observation
obtains a newer snapshot and resumes the blocked verifier without dispatch. Any non-recoverable
failure enters `STOPPED`. `DONE` and `STOPPED` are terminal.

Phase one has no continuous physical execution interval. Contract invariants are therefore checked
with the preconditions immediately before fake dispatch and again against the fresh post-dispatch
snapshot. Continuous invariant monitoring belongs to the separately gated real-executor project.

The following invariants are enforced:

1. no dispatch occurs before plan validation and precondition `PASS`;
2. at most one command is outstanding;
3. a post-command observation sequence must be newer than the pre-command sequence;
4. a receipt cannot satisfy an effect, readiness, or task-goal predicate;
5. the next Skill is unreachable unless effect and handoff both pass;
6. `DONE` is unreachable unless the final effect and task goal pass;
7. `UNKNOWN` never advances the plan;
8. all retry, re-observation, and logical world-change budgets decrease monotonically;
9. every state transition is traced before the next side-effect-like fake dispatch;
10. executor kinds other than `fake` are rejected during plan validation.

## 9. Pick and Place Contracts

The phase-one `tabletop.pick` contract requires a fresh, unambiguous target identity and valid evidence before dispatch. Its expected effect requires evidence that the requested object is held or follows the gripper in the fake/replay world. A mere gripper-close receipt does not pass.

When followed by `tabletop.place`, pick handoff readiness additionally requires the same held object identity, a known destination, and a state marked suitable for the place policy. This allows `EFFECT_PASS + HANDOFF_FAIL` as a first-class outcome.

The `tabletop.place` expected effect requires the object to be inside the requested target region and
no longer held. The plan's final task-goal predicates repeat the task-level object-region relation
using a fresh observation. They are evaluated separately even when they share evidence with the
place effect.

## 10. Error Model

Errors use stable reason codes grouped as:

- plan: invalid schema, unknown Skill, version mismatch, invalid units/frame;
- observation: exhausted replay, timeout, stale sequence, invalid provenance, calibration mismatch;
- grounding: target missing, identity ambiguous, identity changed;
- execution: rejected, failed, timed out, malformed receipt;
- verification: precondition/effect/handoff/task-goal fail or unknown;
- recovery: retry not allowed, re-observation exhausted, world-change budget exhausted;
- infrastructure: trace failure, adapter exception, internal invariant violation.

Invalid plans stop before dispatch. Missing or conflicting evidence becomes `UNKNOWN`. A monitor exception becomes a traced verifier error and cannot produce `PASS`. Internal invariant or trace failures stop the episode. No generic exception path advances the plan.

## 11. Testing Strategy

### 11.1 Unit tests

- strict schema validation, immutability, finite numbers, frames, units, and content IDs;
- registry duplicate/version rejection;
- tri-state monitor aggregation;
- freshness and identity checks;
- recovery budget monotonicity and termination;
- canonical trace serialization, event ordering, and hash stability;
- metric calculations, especially False Advance Rate.

### 11.2 Integration replays

Fixtures cover:

1. successful pick-to-place with fresh evidence;
2. completed receipt followed by failed pick effect;
3. passed pick effect followed by failed place readiness;
4. unknown effect followed by re-observation and pass;
5. stale post-command observation;
6. target identity swap or ambiguity;
7. fake timeout followed by one permitted retry;
8. repeated unknown evidence ending in budget exhaustion;
9. passed place effect but failed task goal;
10. malformed vision event and trace-write failure.

Every negative fixture asserts that the supervisor never reaches the next Skill or `DONE` incorrectly.

### 11.3 Isolation tests

- importing the runtime succeeds without CUDA, cameras, web services, or robot SDKs;
- runtime source contains no import of `startouch_bridge`, CAN packages, or Startouch SDK modules;
- phase-one registry rejects every executor kind except `fake`;
- tests perform no network access and use no hardware device path;
- the existing state machine and web-control stack remain behaviorally untouched.

## 12. Acceptance Criteria

### 12.1 Initial scaffold acceptance

The immediate scaffold is complete when:

1. pick and place contracts load through an exact-version fake-only registry;
2. a deterministic pick-place replay reaches `DONE` only through effect, handoff, and task-goal gates;
3. representative effect failure and handoff failure replays cannot advance;
4. an unknown verdict can consume one re-observation without causing another dispatch;
5. trace output records state transitions, receipts, verdicts, recovery, and the final result;
6. False Advance Rate is calculated for the representative replays;
7. runtime tests and Ruff pass without importing or invoking Startouch/CAN/hardware/network code.

### 12.2 Full phase-one acceptance

The first delivery is complete when:

1. both Skill YAML files validate and round-trip deterministically;
2. all ten integration replay cases terminate within their configured budgets;
3. successful replay reaches `DONE` only after effect, handoff, and task-goal evidence passes;
4. negative fixtures produce zero false advances;
5. a completed receipt with failed or unknown effect never advances;
6. replaying the same fixture produces the same transition sequence, verdicts, reason codes, and metrics;
7. every decision references evidence and can be reconstructed from the JSONL trace;
8. the runtime imports and tests without the vision-model environment or hardware stack;
9. the full relevant pytest suite, Ruff checks on new Python files, and `git diff --check` pass;
10. no Startouch/CAN adapter or real execution path exists in the delivered runtime.

## 13. Follow-on Gates

Later subprojects require separate specifications and approval:

1. calibrated VLM verifier and risk-sensitive routing;
2. Grounding DINO on-demand observation fallback;
3. learned policy or multiple policy variants and capability calibration;
4. RoboHarness-style bridge-state retrieval;
5. shadow consumption of live robot state;
6. any Startouch executor adapter or real motion.

Real motion remains forbidden until offline replay, calibration, hardware acceptance, human approval, and a separate safety design all pass.
