# Voice and Model Action Control Chain Design

- Date: 2026-09-13
- Status: Phase 0-2 implemented; isolated browser acceptance complete; external 9983 cutover and hardware acceptance pending
- Initial delivery scope: launcher ownership, plan/authorization chain, and gripper open/close

## 1. Problem Statement

The formal Ubuntu project previously had three disconnected pieces:

- Speech Service can emit `intent.candidate` messages such as `gripper.open`.
- The browser can display the candidate and simulate it locally.
- Robot Service can execute deterministic `cmd` messages through `/ws`.

That gap is now implemented for `gripper.open` and `gripper.close`: the browser has a dedicated Plan Channel, Orchestrator owns the proposal lifecycle, and Robot Service exposes a token-authenticated loopback `/execution` route. The manual Robot allowlist remains unchanged. Wider arm motion, visual picking, policy models, and AI-originated software stop remain fail-closed.

The implementation has passed contract, replay, launcher ownership, service isolation, disconnect interruption, feedback-timeout, unexpected-joint-motion, full simulated-chain, and isolated browser acceptance tests. The browser run verified candidate-to-plan conversion, visible pinch risk, no motion before confirmation, one confirmed primitive, completion from fresh feedback, and clean shutdown with an active vision stream. It has not replaced the currently running external services and has not received hardware-motion acceptance.

## 2. Goals

- Convert text, voice, or model suggestions into auditable task plans.
- Show plan steps, target evidence, risks, and simulation before authorization.
- Require one authorization for one exact physical plan revision.
- Preserve stable target identity from observation through execution.
- Keep Robot Service as the only owner of Startouch SDK and `can0`.
- Keep Speech and foundational Vision online after one launcher command.
- Support VLA, ACT, and Diffusion Policy as interchangeable Policy Skills.
- Verify success from real Robot Service feedback, not from command delivery alone.

## 3. Non-Goals

- Software stop is not a hardware emergency stop and does not replace physical power isolation.
- Models and LLMs do not send robot commands directly.
- This phase does not enable automatic bottle picking, active view, joint motion, or Home commands.
- Historical source is not imported dynamically and is not treated as a runtime dependency.
- Starting services must not connect the SDK, enable motors, home, or move the arm.

## 4. Chosen Architecture

The project will use a centralized orchestration chain rather than restoring execution inside the old Web proxy.

```text
Browser :9983
  |-- /voice  ------> Speech Service :3004
  |-- /vision -----> Vision Service :3100
  |-- /plan  ------> Orchestrator :3200
  `-- /ws ---------> Robot Service :3000

Speech / Text / Model suggestion
              |
              v
         Orchestrator
              |
              v
Skill Registry -> TaskPlan -> Authorization -> Task Engine
      |                                      |
      +--> Vision / Model / Supervisor       v
                                        Robot Service
                                              |
                                              v
                                            can0
```

Manual page controls continue to use `/ws`. AI-originated physical actions use `/plan`; they never send `skill.candidate` to Robot Service directly.

Default network allocation is:

| Component | Bind | Port or route |
|---|---|---|
| Web Gateway | LAN address | `9983` |
| Robot Service | loopback | `3000` |
| Speech Service | loopback | `3004` |
| Vision Service | loopback | `3100` |
| Orchestrator | loopback | `3200` |
| Supervisor | loopback | `3201` |
| Model Service | loopback | `3202` |

All ports remain profile-configurable. The browser reaches internal services only through allowlisted Web Gateway routes.

## 5. Alternatives Considered

### 5.1 Candidate executor inside Robot Service

This is faster for two gripper commands, but it mixes intent lifecycle, user authorization, and hardware execution. It makes later VLA, supervision, and multi-step tasks harder to audit. It is rejected as the target design.

### 5.2 Restore the historical Web Proxy executor

The historical implementation contains useful reference behavior, but it gives the Web process too much execution responsibility and relies on old process boundaries. It is rejected. Individual validation and lifecycle rules may be adapted into formal modules with new tests.

### 5.3 Centralized Orchestrator, Authorization, and Task Engine

This adds two internal boundaries but gives every input source the same safety path. It is selected because it scales from gripper actions to supervised picking and policy models without giving models hardware authority.

## 6. Component Responsibilities

### 6.1 `apps/orchestrator`

- Exposes a loopback HTTP/WebSocket service on default port `3200`.
- Accepts intent candidates from the browser.
- Resolves candidate intent to a registered Skill operation.
- Queries service, device, model, and target readiness.
- Produces a validated TaskPlan and human-readable risk summary.
- Never owns devices and never executes robot commands.

### 6.2 `platform/task_engine`

- Owns task states: `proposed`, `awaiting_authorization`, `authorized`, `running`, `completed`, `failed`, `interrupted`, and `expired`.
- Atomically advances steps and records inputs, outputs, timestamps, and reasons.
- Requires valid authorization before the first physical step.
- Stops on uncertain results; it never guesses a recovery action or automatically retries motion.

### 6.3 `platform/authorization`

- Binds authorization to `taskId`, `planId`, `planRevision`, `targetRef`, authorized operations, expiry, and a canonical plan digest.
- Consumes an authorization exactly once.
- Rejects replay, expiry, plan mutation, target mutation, or operation escalation.
- Revokes all pending authorizations when Robot state, target evidence, or relevant service readiness becomes invalid.

The existing `thirdhand.task-authorization.v1` schema is the baseline. A versioned schema extension is required for canonical digest and consumption metadata; existing v1 messages must continue to fail closed when those guarantees are required.

### 6.4 `services/robot`

- Remains the sole Startouch SDK and `can0` owner.
- Accepts only typed, validated execution primitives from Task Engine and existing manual `cmd` messages from the page.
- Applies joint limits, speed constraints, fresh-state checks, command mutual exclusion, and all-zero protection.
- Reports accepted, started, completed, interrupted, failed, or uncertain results.
- Confirms gripper success from real gripper feedback within tolerance and timeout.

### 6.5 `services/vision`

- Owns RGB-D acquisition, detection, depth validity, stable target identity, and pose revisions.
- Publishes target evidence without robot authority.
- Keeps stable identity separate from display order such as “first bottle”.

### 6.6 `services/supervisor`

- Observes the locked target, current plan, Robot state, and scene revision.
- Emits warnings or stop requests for target loss, stale depth, unexpected scene change, or execution deviation.
- Cannot produce replacement motion and cannot access `can0`.

### 6.7 `services/model`

- Loads VLA, ACT, and Diffusion Policy adapters from project-local environments.
- Returns candidate trajectories with model identity, version, confidence, and failure reason.
- Does not call Robot Service. Every candidate is validated and authorized through Task Engine.

### 6.8 `skills`

- Describes capability, inputs, outputs, dependencies, risk, and Worker entrypoint.
- A manifest does not grant hardware authority.
- A Skill is available only when its Worker, required service, device, model, and calibration are ready.

## 7. Stable Target Identity

Vision Service owns the live target record. `platform/contracts/TargetRef` carries the stable reference across process boundaries.

Required evidence for physical object tasks is:

```text
targetRef, class, label, confidence
frameRef, frameSequence, lastSeenAt
poseRevision, sceneRevision
bbox, depth validity, camera-space pose
calibration revision and optional base-space pose
```

TaskPlan stores `targetRef`; Authorization binds the same value and pose revision. Before every target-dependent physical step, Task Engine asks Vision and Supervisor to revalidate it. Missing target, changed identity, invalid depth, stale observation, changed pose revision beyond tolerance, or changed calibration revokes authorization.

Gripper-only commands do not require an object TargetRef. They use a reserved non-object reference such as `robot:gripper`, so the existing TaskPlan and Authorization contracts remain explicit rather than using null.

## 8. Protocol Flow

### 8.1 Candidate creation

Speech emits `intent.candidate`. The browser displays the text but forwards the candidate to `/plan`, not `/ws`. Orchestrator validates schema, candidate ID, trace ID, allowed intent, and Skill availability.

### 8.2 Plan proposal

Orchestrator returns `plan.proposed` containing a validated `thirdhand.task-plan.v1`, readiness snapshot, preview data, canonical digest, expiry, and risk summary. The browser must not synthesize missing server fields.

### 8.3 Authorization

The operator confirms the exact displayed revision. The browser sends `authorization.grant` with plan identity and digest. Authorization Service verifies current readiness and creates a one-use grant. Confirmation is rejected if the plan or readiness snapshot has changed.

### 8.4 Execution

Task Engine atomically consumes the grant and emits `execution.started`. It invokes the Skill Worker, which submits typed primitives to Robot Service. Robot Service applies current safety checks independently and may still reject an authorized action.

### 8.5 Completion

Robot Service requires both command completion and fresh state feedback. Task Engine emits a `thirdhand.skill-result.v1` with `completed`, `failed`, or `interrupted`, plus structured reason and evidence. The browser and Speech Service report that result; they do not infer success locally.

## 9. Initial Gripper Operations

The first physical operations are `gripper.open` and `gripper.close` only.

```text
intent.candidate
-> plan.proposed: gripper.set(positionPercent)
-> local 3D preview and pinch-risk summary
-> authorization.grant
-> one-use authorization consumption
-> Robot Service gripper primitive
-> real position feedback and timeout verification
-> SkillResult
```

The TaskPlan must contain the exact requested percentage, timeout, allowed tolerance, and no arm motion step. The Robot Service clamps only within the declared hardware range; a changed value creates a new plan revision and requires new authorization.

## 10. Software Stop

`safety.stop.request` is the sole AI-originated operation allowed to bypass normal confirmation. It is routed with highest priority directly to Robot Service through an explicit stop-only gateway path. It cannot be converted into motion, cannot resume a task, and revokes all pending authorizations.

The page must continue to state that software stop depends on browser, network, processes, the operating system, and CAN. Independent hardware emergency stop or physical power isolation remains required.

## 11. Process Ownership and Startup

Automation is blocked while launcher state reports external or stale service ownership. The launcher must own exactly one process for each configured service and refuse duplicate ports.

The launcher will not silently adopt an external process. Phase 0 provides an explicit operator restart procedure: verify no motion, revoke authorization, disconnect the Startouch SDK, stop only the identified project processes, verify required ports are clear, and then start the profile under launcher ownership. A PID is considered owned only when its process-start marker and command hash match recorded state.

The `manual-control` profile will eventually start, in dependency order:

```text
robot -> speech -> vision -> model gateway -> supervisor -> orchestrator -> web
```

Speech and foundational Vision remain online after startup. Policy models may load on Skill demand or through a dedicated prewarm profile. Robot Service starts disconnected from the SDK and does not enable or move hardware until the operator explicitly connects it.

## 12. Failure and Recovery Semantics

| Condition | Required behavior |
|---|---|
| Robot feedback older than configured threshold, initially 500 ms | Reject or interrupt physical execution |
| Plan expired, changed, replayed, or already consumed | Reject authorization or execution |
| Target, depth, scene, pose, or calibration becomes invalid | Revoke authorization and interrupt before the next step |
| Browser disconnects before execution | Do not start the task |
| Browser disconnects during execution | Supervisor requests software stop; report result as uncertain until Robot confirms |
| Skill, model, or service crashes | Stop advancing steps; request software stop if motion is active |
| Robot command result is uncertain | Report failed or interrupted; never retry automatically |
| Software stop cannot be confirmed | Instruct the operator to use hardware emergency stop or physical power isolation |

Every failure response includes a stable code, human-readable message, trace ID, task ID, and available evidence.

## 13. Browser Changes

- Replace the disabled `robotChannel` candidate path with a dedicated Plan Channel connected to `/plan`.
- Keep existing manual controls on `/ws`.
- Route Robot execution events and Task Engine results to `VoiceControl` through an explicit adapter.
- Replace “3000 control channel not connected” with component-specific readiness, such as “Orchestrator unavailable” or “Robot state stale”.
- Disable confirmation unless plan validation, preview, authorization readiness, Robot readiness, and required target evidence are current.
- Clear pending candidates on disconnect, plan revision change, target change, timeout, stop, or completed result.

## 14. Security and Safety Invariants

- Only Robot Service accesses `can0`.
- Browser confirmation is not trusted without server-side authorization validation.
- Authorization is exact, expiring, one-use, and non-transferable.
- Unknown message types, Skill IDs, operations, schema versions, or additional fields fail closed.
- History is a migration source only and is never added to runtime search paths.
- Model output is untrusted input and must pass schema, bounds, timing, workspace, and readiness checks.
- Startup, reconnect, page refresh, model load, and service recovery never trigger motion.

## 15. Testing Strategy

### 15.1 Unit tests

- Canonical plan digest and schema validation.
- Authorization binding, expiry, replay prevention, and atomic consumption.
- Task state transitions and fail-closed invalid transitions.
- Gripper intent mapping, range, tolerance, and timeout.

### 15.2 Service tests

- Orchestrator candidate validation and unavailable-Skill errors.
- Robot Service accepts only authorized execution primitives while preserving manual command compatibility.
- Supervisor invalidates stale target or Robot state without direct hardware access.
- Web proxy preserves protocol and rejects undeclared routes.

### 15.3 Browser tests

- Voice candidate becomes a plan and cannot execute before click.
- One click yields one grant and one execution request.
- Refresh, double-click, reconnect, stale state, and changed plan cannot replay an action.
- Final UI success requires a real SkillResult.

### 15.4 Hardware acceptance

- Begin with simulation and a fake Robot backend.
- Perform read-only CAN and gripper-state checks.
- With the work area clear and hardware emergency stop reachable, authorize one low-risk open operation, then one close operation without an object between the fingers.
- Verify requested target, actual feedback, timeout behavior, stop behavior, and no arm joint movement.

## 16. Implementation Phases

### Phase 0: Process ownership

Make launcher state authoritative, adopt or safely replace externally started services, prevent duplicate port ownership, and add status tests. No automation is enabled in this phase.

### Phase 1: Plan and authorization foundation

Implement Orchestrator transport, Task Engine, Authorization, versioned contract extensions, Web `/plan` proxy, and browser Plan Channel. Candidate execution remains disabled until the full phase passes tests.

### Phase 2: Gripper open and close

Implement the gripper Skill Worker and authorized Robot primitive, connect browser confirmation and results, and complete simulation plus hardware acceptance. This is the first enabled AI-originated physical action.

### Phase 3: Existing manual intents

Migrate joint steps, directional control, Home, and software-stop routing without weakening plan binding.

### Phase 4: Supervised object manipulation

Complete stable target, depth, calibration, Supervisor, pick-and-place, and execution evidence.

### Phase 5: Policy models and active view

Add VLA, ACT, Diffusion Policy Workers and Active View after their service, asset, calibration, and safety dependencies are measurable.

### Phase 6: History cleanup

Delete each historical source subtree only after its mapping is closed, formal tests pass, no runtime references remain, provenance is retained, and the replacement has a recoverable Git commit or backup.

## 17. Initial Acceptance Criteria

The initial delivery is complete only when:

- all configured services are uniquely launcher-owned and `thirdhand status` is accurate;
- the browser uses `/plan` for candidates and `/ws` only for manual Robot control;
- gripper open/close require one exact, expiring, one-use authorization;
- refresh, reconnect, timeout, mutation, and duplicate confirmation cannot execute a second action;
- Robot Service independently rejects stale state, conflicting motion, invalid range, and unknown operations;
- reported success includes fresh real gripper feedback and no arm joint motion;
- software stop remains available and is explicitly distinguished from hardware emergency stop;
- Node, Python, browser, simulation, and approved hardware acceptance tests pass;
- no formal runtime code imports from `History/` or external old project directories.

## 18. Risks

| Risk | Mitigation |
|---|---|
| Historical executor is copied wholesale | Adapt behavior into new boundaries with tests; never import History at runtime |
| Duplicate or stale service ownership | Complete Phase 0 before enabling actions |
| Candidate replay or double confirmation | Atomic one-use authorization bound to canonical plan digest |
| Stale Robot state or target evidence | Freshness checks in Task Engine, Supervisor, and Robot Service |
| Invalid depth or hand-eye calibration | Block object motion until evidence and calibration revision are valid |
| Accidental zero-pose or unrelated arm movement | Explicit primitive allowlist, no arm steps in gripper plans, existing all-zero guard |
| Model produces unsafe trajectory | Treat as untrusted candidate and apply deterministic validation before authorization |
| Software stop is mistaken for emergency stop | Persistent UI warning and hardware acceptance procedure requiring physical E-stop access |

## 19. Design Decision

The approved target is the centralized Orchestrator, Task Engine, Authorization, Supervisor, Model Service, Skill Registry, and sole Robot Service execution chain. The first implementation milestone covers process ownership plus the complete gripper open/close path. No broader robot motion becomes AI-executable during that milestone.

## 20. Verified Implementation Record

Implemented paths include `apps/orchestrator`, `platform/authorization`, `platform/task_engine`, `skills/manipulation/gripper-control`, Robot `/execution`, Web `/plan`, browser `PlanChannel`, and Launcher-managed execution-token rotation. The isolated simulation verifies one primitive only after an exact grant, fresh feedback within 2%, and no arm-joint delta above 0.5°. Browser acceptance used the isolated `gripper-plan-simulation` profile on ports `19983`, `13200`, and `13000`; it did not open `can0` or stop the existing `9983`, `3000`, `3004`, and `3100` services.

Pending gates are an explicitly approved cutover from the current external `9983` stack to the Launcher-managed profile and a separately authorized hardware acceptance consisting only of one open and one close command with an empty gripper. Supervisor, stable RGB-D target binding, bottle picking, Model Service, VLA, ACT, Diffusion Policy, active view, and AI-originated software stop remain deferred.
