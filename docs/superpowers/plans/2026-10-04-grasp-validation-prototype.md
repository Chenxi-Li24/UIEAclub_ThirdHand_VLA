# Grasp Validation Prototype Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a simulation-only four-phase bottle-grasp prototype that generates and executes pregrasp, approach, grip, and lift commands without importing the production approval gate or validation-artifact path.

**Architecture:** Add a self-contained prototype package beside the production action modules. A pure plan builder converts explicit geometry into an immutable command plan, a simulator-only executor advances the plan through correlated acknowledgements, and a fixture-driven CLI prints a deterministic report without exposing any hardware option.

**Tech Stack:** Node.js 24, CommonJS, `node:test`, existing rigid-transform helper functions.

**Spec:** `docs/superpowers/specs/2026-10-04-grasp-validation-prototype-design.md`

## Global Constraints

- Work only on `Xavier/grasp-validation-prototype`, based on `origin/fanxy/bottle_grasp` at `7b8dc5813a2ce9dcc360d026325bd86d88641072`.
- Do not modify the production bottle-pick workflow, production action configuration, web routes, runtime profiles, or service startup paths.
- Do not import or instantiate Startouch, Robot Service, WebSocket, CAN, production workflow, or `execution_gate` code.
- The prototype accepts only an injected simulator adapter and stops after the lift phase.
- Approval and validation-artifact gates are intentionally absent; finite shape and rigid-transform checks remain mandatory input-contract checks.
- No new runtime dependency is allowed.

## Review Focus

- Aliased or reflected 4x4 transforms must be rejected before a plan is generated; Task 1 pins this with rigid-transform tests.
- Zero, negative, infinite, or `NaN` width and motion settings must fail with stable error codes; Task 1 exercises every numeric input class.
- Duplicate or mismatched simulated acknowledgements must not advance two phases; Task 2 tests correlation and idempotence.
- A simulator send failure must terminate the run as failed without emitting later commands; Task 2 tests the failure boundary.
- CLI arguments that resemble live execution or backend selection must be rejected before the fixture is read; Task 3 tests `--execute`, `--real`, `--backend`, and `--can`.

---

### Task 1: Pure prototype plan builder

**Files:**
- Create: `skills/manipulation/bottlegrasp/src/thirdhand_va/action/prototype/grasp_plan.js`
- Create: `skills/manipulation/bottlegrasp/tests/action/prototype/grasp_plan.test.js`

**Interfaces:**
- Consumes: `gripTargetToFlangePose(gripPose, flangeToGrip)` from `action/grasp/grip_transform.js`.
- Produces: `buildPrototypeGraspPlan(input) -> frozen plan`, where `input` contains `requestId`, `target.positionM`, `target.eulerRad`, `widthM`, `flangeToGrip`, `pregraspOffsetM`, `liftDistanceM`, and `linearSpeedMps`.
- Plan phases are exactly `pregrasp`, `approach`, `grip`, and `lift`; motion commands contain `position`, `euler`, and `time_sec`, while grip contains `position: 0`.

- [ ] **Step 1: Write failing geometry and ordering tests**

Add tests named:

- `builds an immutable pregrasp approach grip and lift plan`
- `converts the requested grip pose into a flange pose`

Assert that a target `[0.30, -0.20, 0.10]`, identity rotation, identity flange-to-grip transform, `pregraspOffsetM: 0.10`, and `liftDistanceM: 0.05` produce positions `[0.30, -0.20, 0.20]`, `[0.30, -0.20, 0.10]`, and `[0.30, -0.20, 0.15]` in that order, with a grip command between approach and lift. Assert the returned plan and nested commands are frozen.

- [ ] **Step 2: Run the focused tests and verify the new module is missing**

Run: `node --test tests/action/prototype/grasp_plan.test.js`

Expected: FAIL because `action/prototype/grasp_plan.js` does not exist.

- [ ] **Step 3: Implement `buildPrototypeGraspPlan(input)`**

Validate the exact input fields, call `gripTargetToFlangePose`, calculate pregrasp and lift along base-frame positive Z, calculate motion duration as Euclidean distance divided by `linearSpeedMps`, and deep-freeze the plan. Use stable `TypeError` messages: `prototype_request_id_invalid`, `prototype_target_invalid`, `prototype_width_invalid`, `prototype_motion_invalid`, and the existing rigid-transform errors.

- [ ] **Step 4: Add failing malformed-input tests**

For each vector field, width, offset, lift distance, and speed, test zero where prohibited plus negative, `NaN`, and infinity. Test an aliased transform, a reflected transform, and a non-4x4 transform. Assert the stable error message and that no partial plan is returned.

- [ ] **Step 5: Run Task 1 tests**

Run: `node --test tests/action/prototype/grasp_plan.test.js`

Expected: all Task 1 tests PASS.

- [ ] **Step 6: Commit Task 1**

```bash
git add skills/manipulation/bottlegrasp/src/thirdhand_va/action/prototype/grasp_plan.js \
  skills/manipulation/bottlegrasp/tests/action/prototype/grasp_plan.test.js
git commit -m "feat: add prototype grasp plan builder"
```

### Task 2: Simulator-only prototype executor

**Files:**
- Create: `skills/manipulation/bottlegrasp/src/thirdhand_va/action/prototype/simulator.js`
- Create: `skills/manipulation/bottlegrasp/src/thirdhand_va/action/prototype/executor.js`
- Create: `skills/manipulation/bottlegrasp/tests/action/prototype/executor.test.js`

**Interfaces:**
- Consumes: the frozen plan returned by `buildPrototypeGraspPlan(input)`.
- Produces: `new PrototypeGraspExecutor({ simulator, idFactory })`, with `start(plan)`, `ack(event)`, and `snapshot()` methods.
- Produces: `new PrototypeSimulator({ onCommand })`, with `send(command)` and `commands` for deterministic tests and CLI reporting.
- Every emitted command has `request_id: <plan.requestId>:<phase>` and `source: prototype_grasp_validation`.

- [ ] **Step 1: Write failing happy-path and correlation tests**

Assert that `start(plan)` emits only `pregrasp`; each matching `{ type: 'command_complete', request_id, reached: true }` acknowledgement emits exactly the next phase; and the lift acknowledgement produces `status: 'complete'` with exactly four recorded commands.

Also assert that a duplicate acknowledgement is idempotent and a mismatched request ID returns `handled: false` without advancing.

- [ ] **Step 2: Run the focused tests and verify the executor is missing**

Run: `node --test tests/action/prototype/executor.test.js`

Expected: FAIL because the prototype executor modules do not exist.

- [ ] **Step 3: Implement `PrototypeSimulator`**

Store frozen copies of accepted commands, invoke the optional `onCommand` callback, and return `true`. Do not import any production adapter.

- [ ] **Step 4: Implement `PrototypeGraspExecutor`**

Use one in-flight command at a time. Reject a second `start` with `prototype_session_active`. Treat `reached !== true` or a simulator `send()` result other than `true` as terminal `failed`; never emit later phases after failure. Keep duplicate completed acknowledgement IDs in a set so they cannot advance the state twice.

- [ ] **Step 5: Add failing send and acknowledgement failure tests**

Test simulator send failure on `approach`, a correlated completion with `reached: false`, an acknowledgement received while idle, and calling `start` twice. Assert terminal status and exact command count in each case.

- [ ] **Step 6: Run Task 2 tests**

Run: `node --test tests/action/prototype/executor.test.js`

Expected: all Task 2 tests PASS.

- [ ] **Step 7: Commit Task 2**

```bash
git add skills/manipulation/bottlegrasp/src/thirdhand_va/action/prototype/simulator.js \
  skills/manipulation/bottlegrasp/src/thirdhand_va/action/prototype/executor.js \
  skills/manipulation/bottlegrasp/tests/action/prototype/executor.test.js
git commit -m "feat: simulate prototype grasp execution"
```

### Task 3: Fixture CLI and isolation proof

**Files:**
- Create: `skills/manipulation/bottlegrasp/scripts/action/prototype_grasp_validation.js`
- Create: `skills/manipulation/bottlegrasp/tests/fixtures/action/prototype-grasp.json`
- Create: `skills/manipulation/bottlegrasp/tests/action/prototype/prototype_cli.test.js`
- Modify: `skills/manipulation/bottlegrasp/README.md`

**Interfaces:**
- Consumes: `buildPrototypeGraspPlan`, `PrototypeGraspExecutor`, and `PrototypeSimulator` from Tasks 1 and 2.
- Produces: CLI `node scripts/action/prototype_grasp_validation.js --fixture FILE`.
- Produces: one JSON object with `schema: thirdhand-prototype-grasp-report-v1`, `status`, `plan`, `commands`, and `finalState`.

- [ ] **Step 1: Write failing CLI happy-path test**

Spawn the CLI with `tests/fixtures/action/prototype-grasp.json`. Assert exit code 0, valid JSON output, four commands in exact phase order, `status: complete`, and no stderr.

- [ ] **Step 2: Write failing forbidden-option tests**

For `--execute`, `--real`, `--backend`, and `--can`, assert exit code 2 and `prototype_hardware_option_forbidden`. Use a missing fixture path in these cases to prove argument rejection happens before fixture access.

- [ ] **Step 3: Run the CLI tests and verify the script is missing**

Run: `node --test tests/action/prototype/prototype_cli.test.js`

Expected: FAIL because the CLI does not exist.

- [ ] **Step 4: Implement the fixture and CLI**

Parse only `--fixture FILE`; reject unknown arguments. Read and parse the fixture, build the plan, start the executor, and feed it one correlated successful simulated acknowledgement per emitted command until terminal. Print only the final report JSON to stdout. On input or execution error, print one JSON error to stderr and exit 2.

- [ ] **Step 5: Add source-isolation test**

Read every `.js` file under `src/thirdhand_va/action/prototype/` and the CLI. Assert none contains `startouch`, `robot_ws_client`, `robot_client_factory`, `execution_gate`, `workflow`, `ws://`, `can0`, or `child_process` as a module or runtime reference.

- [ ] **Step 6: Document the prototype command and boundary**

Add a README section that shows the exact fixture command, labels the result simulation-only, lists the four phases, and states that the prototype is not wired into the production service or hardware adapters.

- [ ] **Step 7: Run focused and regression verification**

Run:

```bash
cd skills/manipulation/bottlegrasp
node --test tests/action/prototype/*.test.js
node --test tests/action/grasp/grip_transform.test.js \
  tests/action/grasp/lift_only_plan.test.js
node scripts/action/prototype_grasp_validation.js \
  --fixture tests/fixtures/action/prototype-grasp.json
cd ../../../
npm run test:node
git diff --check
```

Expected: all focused tests and 132 root Node tests PASS; the CLI prints a complete four-command report; `git diff --check` is silent.

- [ ] **Step 8: Record the known baseline limitation**

Do not claim the bottle skill's entire `npm test` suite is green. Report the seven pre-existing Startouch process-client timeouts separately; rerun the focused non-hardware tests changed by this prototype.

- [ ] **Step 9: Commit Task 3**

```bash
git add skills/manipulation/bottlegrasp/scripts/action/prototype_grasp_validation.js \
  skills/manipulation/bottlegrasp/tests/fixtures/action/prototype-grasp.json \
  skills/manipulation/bottlegrasp/tests/action/prototype/prototype_cli.test.js \
  skills/manipulation/bottlegrasp/README.md
git commit -m "feat: add simulated grasp validation CLI"
```

### Task 4: Whole-branch review and handoff

**Files:**
- Review only; modify files only to address verified findings.

**Interfaces:**
- Consumes: all deliverables from Tasks 1–3.
- Produces: a reviewed branch with verification evidence and no uncommitted changes.

- [ ] **Step 1: Review the branch diff against the spec**

Run: `git diff origin/fanxy/bottle_grasp...HEAD`

Check phase ordering, input contracts, command correlation, simulator-only isolation, README claims, and absence of production wiring.

- [ ] **Step 2: Run final verification**

Repeat Task 3 Step 7 from a clean working tree.

Expected: the same focused and root Node results pass with no generated tracked files.

- [ ] **Step 3: Confirm branch state**

Run: `git status --short --branch`

Expected: clean `Xavier/grasp-validation-prototype` branch, ahead of `origin/fanxy/bottle_grasp` only by the design, plan, and implementation commits.
