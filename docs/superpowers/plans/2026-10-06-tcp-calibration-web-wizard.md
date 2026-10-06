# TCP Calibration Web Wizard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a simulated, Chinese-language web wizard that records canonical flange poses from port 3000, solves and independently validates a probe-pivot TCP, derives a measured grasp TCP, and safely manages pending/active/rollback artifacts without moving the robot.

**Architecture:** A pure Python SVD solver is wrapped by a bounded Node adapter. A focused Node state machine consumes only `CanonicalRobotWebSocketClient` snapshots, persists versioned evidence through an atomic artifact store, and is exposed through same-origin HTTP routes plus a standalone browser page. The real robot boundary permits state reads and `software_stop` only; every automated test uses synthetic states, fake WebSockets, and temporary directories.

**Tech Stack:** Node.js CommonJS and `node:test`, Python 3 with NumPy/OpenCV and `pytest`, existing `ws` and `yaml` packages, static HTML/CSS/JavaScript.

**Spec:** `docs/superpowers/specs/2026-10-06-tcp-calibration-web-wizard-design.md`

## Global Constraints

- Baseline is `7fdaabe77ce4b35ccee207be65bcdb758fd11a00`; all work stays on `feature/tcp-calibration-web-wizard-20261006` in the dedicated worktree.
- Do not modify or delete the original checkout's untracked `artifacts/`; do not push, merge, rewrite history, force-push, or run physical hardware.
- Do not add ROS, MoveIt, Ceres, a complete calibration framework, or new product dependencies.
- Robot state comes only from `ws://127.0.0.1:3000/ws` through `CanonicalRobotWebSocketClient`; the only command the calibration module may send is `{ "cmd": "software_stop" }`.
- Never send `move_l`, `servo`, `preset`, `gripper`, Home, automatic contact, or automatic verification motion.
- Normalize the SDK tool pose to `robot_flange` exactly once with the frame policy and `[0.17334, 0, 0] m` SDK transform; reject unprovable or double-normalized frames.
- Fit uses at least eight manual pivot contacts; validation uses at least three new contacts that never enter the fit.
- The caliper distance and explicit tool axis derive the grasp TCP exactly once; never hard-code 20 mm.
- Default output is an immutable pending artifact. Activation and rollback are explicit, versioned, atomic, and tested only against temporary roots.
- Keep bottle smoothing, approach distance, `forwardBackoffM`, grasp state machine, hand-eye calibration, camera calibration, and consumption of the measured TCP out of scope.
- Use the SciKit-Surgery BSD-3 project only as an independent formula/behavior reference; record provenance and do not copy large code blocks.

## Review Focus

- A valid-looking state with stale or decreasing producer time must fail sampling without mutating the session; Task 3 adds this test.
- Restart after a truncated current-session pointer must fail closed while preserving immutable evidence; Task 4 adds this test.
- Reuse of one request ID with a different body must return a conflict instead of replaying the first mutation; Task 5 adds this test.
- A Python child that hangs, overproduces output, or returns non-finite JSON must be terminated/rejected without advancing the stage; Task 2 adds this test.
- A browser restored into a newer server revision must display the server state and reject stale local actions; Task 6 adds this test.

---

### Task 1: Independent pivot reference fixtures and provenance

**Files:**
- Create: `tests/fixtures/tcp-calibration/reference-pivot.json`
- Create: `tests/python/tcp_calibration/test_reference_fixture.py`
- Create: `THIRD_PARTY_NOTICES.md`

**Interfaces:**
- Consumes: the algebraic system `R_i p_probe + t_i = p_fixed` from the spec.
- Produces: a deterministic JSON fixture with eight fit poses, three validation poses, expected probe/fixed points, 0.5/1/2/5 mm noise cases, and SciKit-Surgery-compatible one-step reference results.

- [ ] **Step 1: Write the fixture integrity test**

Add tests named `test_reference_fixture_recovers_known_probe_and_pivot`, `test_reference_fixture_has_independent_validation_set`, and `test_noise_cases_are_deterministic`. Reconstruct `A`/`b` independently in the test with NumPy, assert rank 6, exact-case error below `1e-9 m`, disjoint fit/validation IDs, and fixed seeded noise magnitudes.

- [ ] **Step 2: Run the integrity test and verify RED**

Run: `python -m pytest tests/python/tcp_calibration/test_reference_fixture.py -q`

Expected: FAIL because `reference-pivot.json` does not exist.

- [ ] **Step 3: Add the deterministic fixture and notice**

Generate the fixture once from explicit known transforms and commit the resulting JSON. Document the SciKit-Surgery URL, BSD-3-Clause license, access date `2026-10-06`, algebraic one-step influence, test-oracle use, and that no source code was copied.

- [ ] **Step 4: Run the integrity test and verify GREEN**

Run: `python -m pytest tests/python/tcp_calibration/test_reference_fixture.py -q`

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add THIRD_PARTY_NOTICES.md tests/fixtures/tcp-calibration/reference-pivot.json tests/python/tcp_calibration/test_reference_fixture.py
git commit -m "test: add TCP pivot calibration reference fixtures"
```

### Task 2: Pure pivot solver, contracts, and bounded adapter

**Files:**
- Create: `tools/tcp_calibration/__init__.py`
- Create: `tools/tcp_calibration/pivot_solver.py`
- Create: `tools/tcp_calibration/solve_tcp.py`
- Create: `apps/web/src/tcp-calibration/solver-adapter.js`
- Create: `tests/python/tcp_calibration/test_pivot_solver.py`
- Create: `tests/node/web/tcp-calibration-solver.test.js`
- Reference: `/home/nieqingcao/th0814/VA` branch `feature/measured-tcp-bottle-commissioning`, `PinZiZhuaQuSkill/src/thirdhand_va/action/calibration/tool_tcp.py`

**Interfaces:**
- Consumes: fixture from Task 1.
- Produces: Python `solve_pivot(fit_samples, thresholds) -> dict`, `validate_pivot(candidate, validation_samples, thresholds) -> dict`, `derive_grasp_tcp(T_flange_probe_tip, distance_m, tool_axis_flange) -> dict`; Node `runTcpSolver({python, script, request, timeoutMs, maximumOutputBytes}) -> Promise<object>`.

- [ ] **Step 1: Write failing pure-solver tests**

Cover exact recovery, the four deterministic noise cases, fewer than eight samples, duplicate orientations, single-axis/weak coverage, rank below 6, per-sample/RMS/max/worst diagnostics, and three validation samples excluded from the fit. Assert configuration values `fitRmsGreenM=0.002`, `fitMaximumGreenM=0.004`, `fitRmsMaximumM=0.003`, `fitMaximumM=0.005`, and `validationMaximumM=0.005` are reported rather than hidden constants.

- [ ] **Step 2: Run the solver tests and verify RED**

Run: `python -m pytest tests/python/tcp_calibration/test_pivot_solver.py -q`

Expected: collection FAIL because `tools.tcp_calibration.pivot_solver` is absent.

- [ ] **Step 3: Implement the pure solver and JSON CLI**

Use `numpy.linalg.lstsq`/SVD on stacked `[R_i, -I] [p_probe, p_fixed]^T = -t_i`; validate finite rigid transforms and unique IDs; expose rank/singular values/rotation-axis coverage and immutable input echoes. `derive_grasp_tcp` validates a finite non-negative measurement, bounded uncertainty, and an explicit normalized axis before applying the offset once.

- [ ] **Step 4: Run the Python solver tests and verify GREEN**

Run: `python -m pytest tests/python/tcp_calibration/test_pivot_solver.py -q`

Expected: all tests pass.

- [ ] **Step 5: Write failing Node adapter tests**

Test valid JSON round-trip plus timeout, output limit, nonzero exit, malformed JSON, non-finite token, unexpected schema, and preservation of session stage on adapter failure.

- [ ] **Step 6: Run the adapter test and verify RED**

Run: `node --test tests/node/web/tcp-calibration-solver.test.js`

Expected: FAIL because `solver-adapter.js` is absent.

- [ ] **Step 7: Implement the bounded child-process adapter**

Spawn the configured Python executable with `solve_tcp.py`, write one bounded JSON request to stdin, enforce timeout/output caps, require the exact result schema, and kill/reject the child on every protocol violation.

- [ ] **Step 8: Run focused tests and commit**

Run:

```bash
python -m pytest tests/python/tcp_calibration/test_pivot_solver.py -q
node --test tests/node/web/tcp-calibration-solver.test.js
```

Expected: all focused tests pass.

```bash
git add tools/tcp_calibration apps/web/src/tcp-calibration/solver-adapter.js tests/python/tcp_calibration/test_pivot_solver.py tests/node/web/tcp-calibration-solver.test.js
git commit -m "feat: port pure TCP solver and contracts"
```

### Task 3: Canonical port-3000 state source and calibration session

**Files:**
- Create: `apps/web/src/tcp-calibration/contracts.js`
- Create: `apps/web/src/tcp-calibration/robot-state-source.js`
- Create: `apps/web/src/tcp-calibration/session.js`
- Create: `tests/node/web/tcp-calibration-state-source.test.js`
- Create: `tests/node/web/tcp-calibration-session.test.js`
- Modify: `tools/frames/canonical_robot_client.js`
- Test: `tools/frames/test_canonical_robot_client.js`

**Interfaces:**
- Consumes: `CanonicalRobotWebSocketClient`, frame-policy ID, `runTcpSolver` from Task 2.
- Produces: `TcpCalibrationRobotStateSource`, whose public methods are `connect()`, `close()`, `snapshot()`, and `softwareStop()`; `TcpCalibrationSession`, whose `handle(command)` returns `{accepted, state|error}` with monotonically increasing `revision`.

- [ ] **Step 1: Write failing state-source tests**

Use a fake WebSocket to assert 173.34 mm normalization occurs once, output pose frame is `robot_flange`, policy/hash mismatch and already-normalized raw input produce no snapshot, disconnect marks state locked, and `softwareStop()` emits the only permitted command. Assert no test path can emit `move_l`, `servo`, `preset`, or `gripper`.

- [ ] **Step 2: Run state-source tests and verify RED**

Run: `node --test tests/node/web/tcp-calibration-state-source.test.js tools/frames/test_canonical_robot_client.js`

Expected: FAIL because the state source is absent or canonical metadata is incomplete.

- [ ] **Step 3: Implement exact canonical metadata and state source**

Expose an immutable normalized snapshot containing `TBaseFlange`, `poseFrame`, `framePolicyId`, `stateSequence`, `producerMonotonicNs`, freshness/health/stationary flags, and SDK-tool pose. Wrap the canonical client's existing send method with a state-source API that only constructs `software_stop`.

- [ ] **Step 4: Run state-source tests and verify GREEN**

Run the Step 2 command; expect all tests pass.

- [ ] **Step 5: Write failing session tests**

Cover Stage 0 confirmations and finite caliper data; at least eight unique fit samples; strict sequence/time increase; stale/moving/unhealthy/wrong-frame/wrong-policy rejection without revision change; duplicate and weakly separated poses; undo/delete/replacement; solver green/yellow/red transitions; three disjoint validation samples; validation maximum over 5 mm; distance/axis conversion once; abort terminality; and request-ID replay/conflict behavior at the session boundary.

- [ ] **Step 6: Run session tests and verify RED**

Run: `node --test tests/node/web/tcp-calibration-session.test.js`

Expected: FAIL because `session.js` and `contracts.js` are absent.

- [ ] **Step 7: Implement contracts and session state machine**

Define exact command schemas for `start`, `record_fit`, `delete_fit`, `solve`, `record_validation`, `derive`, and `abort`. Store fit and verification sets separately; inject clock, ID factory, robot source, solver, and thresholds; freeze returned status snapshots.

- [ ] **Step 8: Run focused tests and commit**

Run:

```bash
node --test tools/frames/test_frame_normalization.js tools/frames/test_canonical_robot_client.js tests/node/web/tcp-calibration-state-source.test.js tests/node/web/tcp-calibration-session.test.js
```

Expected: all focused tests pass.

```bash
git add tools/frames apps/web/src/tcp-calibration/contracts.js apps/web/src/tcp-calibration/robot-state-source.js apps/web/src/tcp-calibration/session.js tests/node/web/tcp-calibration-state-source.test.js tests/node/web/tcp-calibration-session.test.js
git commit -m "feat: add canonical 3000 robot-state calibration session"
```

### Task 4: Atomic pending, activation, and rollback artifacts

**Files:**
- Create: `apps/web/src/tcp-calibration/artifact-store.js`
- Create: `tests/node/web/tcp-calibration-artifacts.test.js`
- Create at runtime only: `configs/calibration/gripper-tcp.pending.json`
- Create at runtime only: versioned calibration files and `active-manifest.json` under a configured root

**Interfaces:**
- Consumes: finalized session snapshot from Task 3.
- Produces: `TcpCalibrationArtifactStore` methods `restoreSession()`, `saveSession(snapshot)`, `finalizePending(snapshot)`, `activate({candidateId, expectedActiveId})`, and `rollback({expectedActiveId})`.

- [ ] **Step 1: Write failing artifact tests**

Use temporary directories to assert owner-only atomic writes, canonical content hashes, immutable version files, pending pointer replacement, restart restoration, fail-closed truncated/current-pointer/hash mismatch, no production activation for unverified candidates, explicit active-version switch, previous-version preservation, rollback, expected-active compare-and-swap, and fsync/rename failure leaving the prior pointer intact.

- [ ] **Step 2: Run tests and verify RED**

Run: `node --test tests/node/web/tcp-calibration-artifacts.test.js`

Expected: FAIL because `artifact-store.js` is absent.

- [ ] **Step 3: Implement the artifact store**

Canonicalize JSON, hash without the hash field, write same-directory temporary files with mode `0600`, fsync and rename, and keep versioned targets append-only. Separate immutable evidence from replaceable current/pending/active pointers.

- [ ] **Step 4: Run tests and verify GREEN**

Run the Step 2 command; expect all tests pass.

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/tcp-calibration/artifact-store.js tests/node/web/tcp-calibration-artifacts.test.js
git commit -m "feat: add TCP calibration artifact activation and rollback"
```

### Task 5: Same-origin HTTP API and Web gateway integration

**Files:**
- Create: `apps/web/src/tcp-calibration/routes.js`
- Modify: `apps/web/src/server.js`
- Modify: `apps/web/src/config.js`
- Create: `tests/node/web/tcp-calibration-api.test.js`
- Modify: `tests/node/web/server.test.js`

**Interfaces:**
- Consumes: session, state source, and artifact store from Tasks 3–4.
- Produces: `createTcpCalibrationRoutes({session, store, stateSource})` with `config()` and `handle(request, response, pathname)`; runtime config entry `tcpCalibration` and the specified `/api/tcp-calibration/*` endpoints.

- [ ] **Step 1: Write failing API tests**

Cover every method/path, exact request keys, body limit, same-origin mutation checks, session ID, expected revision, request ID replay, conflicting replay, stale revision, path sample ID validation, stable status codes, disconnected locking, best-effort software stop, pending-only default, explicit activate/rollback, and dependency injection that never opens a real socket.

- [ ] **Step 2: Run API tests and verify RED**

Run: `node --test tests/node/web/tcp-calibration-api.test.js`

Expected: FAIL because routes and gateway seam are absent.

- [ ] **Step 3: Implement focused routes and gateway seam**

Keep parsing, origin checks, exact schemas, and error mapping in `routes.js`. In `server.js`, construct the module only when configured, delegate matching paths before static serving, include availability in runtime config/health, and close the module during server shutdown.

- [ ] **Step 4: Run focused gateway tests and verify GREEN**

Run:

```bash
node --test tests/node/web/tcp-calibration-api.test.js tests/node/web/server.test.js tests/node/web/grasp-gateway.test.js
```

Expected: all focused tests pass and existing grasp routes remain unchanged.

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/tcp-calibration/routes.js apps/web/src/server.js apps/web/src/config.js tests/node/web/tcp-calibration-api.test.js tests/node/web/server.test.js
git commit -m "feat: add TCP calibration HTTP API and artifact store"
```

### Task 6: Chinese task-gated calibration wizard

**Files:**
- Create: `apps/web/public/tcp-calibration.html`
- Create: `apps/web/public/js/tcp-calibration.js`
- Create: `apps/web/public/css/tcp-calibration.css`
- Modify: `apps/web/public/index.html`
- Create: `tests/node/web/tcp-calibration-ui.test.js`

**Interfaces:**
- Consumes: runtime config and HTTP API from Task 5.
- Produces: standalone “TCP标定” page with stages 0–6, safe server-state restoration, and no direct WebSocket or filesystem access.

- [ ] **Step 1: Write failing static/UI contract tests**

Assert Chinese stage labels and safety copy; main-page entry; no direct `ws://`, SDK, CAN, motion command, timer reward, or camera dependency; disabled controls before each gate; fit/validation separation; diagnostic fields; three-transform comparison; pending/activate/rollback confirmations; disconnect lock; server revision rendering; and stale local revision rejection after refresh.

- [ ] **Step 2: Run UI tests and verify RED**

Run: `node --test tests/node/web/tcp-calibration-ui.test.js`

Expected: FAIL because the page and assets are absent.

- [ ] **Step 3: Implement the standalone page and controller**

Render stages from server status, use same-origin `fetch`, send exact session/revision/request IDs, make red/yellow/green diagnostics accessible by text as well as color, show suggested orientation coverage without scoring speed, and require explicit confirmations for derive/finalize/activate/rollback.

- [ ] **Step 4: Run UI and static-serving tests and verify GREEN**

Run:

```bash
node --test tests/node/web/tcp-calibration-ui.test.js tests/node/web/server.test.js tests/node/web/grasp-ui.test.js
```

Expected: all focused tests pass.

- [ ] **Step 5: Commit**

```bash
git add apps/web/public/tcp-calibration.html apps/web/public/js/tcp-calibration.js apps/web/public/css/tcp-calibration.css apps/web/public/index.html tests/node/web/tcp-calibration-ui.test.js
git commit -m "feat: add Chinese TCP calibration wizard UI"
```

### Task 7: Simulated end-to-end workflow, operator docs, and final verification

**Files:**
- Create: `tests/node/web/tcp-calibration-e2e.test.js`
- Create: `tools/tcp_calibration/demo_simulated.js`
- Create: `docs/hardware/tcp-calibration-web-wizard.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: complete API/UI/session/solver/store implementation.
- Produces: deterministic stage 0–6 demonstration against a fake port-3000 WebSocket and temporary artifact root; operator/developer documentation and recovery commands.

- [ ] **Step 1: Write the failing end-to-end test**

Drive start, eight fit contacts, solve, three separate validation contacts, grasp-TCP derivation, pending finalization, simulated activation, restart restoration, and rollback. Assert every outbound fake-robot message is exactly `software_stop`, fit and validation IDs remain disjoint, active artifacts are content-valid, and no repository production config is touched.

- [ ] **Step 2: Run E2E test and verify RED**

Run: `node --test tests/node/web/tcp-calibration-e2e.test.js`

Expected: FAIL until the simulation harness wires the complete workflow.

- [ ] **Step 3: Implement the simulation harness and documentation**

Document prerequisites, page URL, seven stages, physical operator responsibilities, manual-only contact, emergency stop, artifact locations, pending versus active semantics, rollback, simulation command, original/feature/recovery branches, and explicit statement that software completion is not physical TCP calibration or grasp approval.

- [ ] **Step 4: Run focused and full verification**

Run:

```bash
node --test tests/node/web/tcp-calibration-*.test.js
python -m pytest tests/python/tcp_calibration -q
npm run test:node
npm run test:python
git diff --check
git status --short --branch
```

Expected: all new tests pass; Node full suite remains green. Report the pre-existing Python collection failure by exact test/module if it remains; do not hide or relabel it.

- [ ] **Step 5: Run simulated demonstration**

Run: `node tools/tcp_calibration/demo_simulated.js --artifact-root "$(mktemp -d)"`

Expected: prints stages 0–6, candidate/active/rollback IDs, zero motion commands, and exits 0.

- [ ] **Step 6: Commit**

```bash
git add tests/node/web/tcp-calibration-e2e.test.js tools/tcp_calibration/demo_simulated.js docs/hardware/tcp-calibration-web-wizard.md README.md
git commit -m "test: add end-to-end simulated TCP calibration workflow"
```

- [ ] **Step 7: Documentation-only final commit if provenance or recovery changed during implementation**

Only if verification required documentation corrections, commit those exact files with:

```bash
git commit -m "docs: document TCP calibration safety and rollback"
```

Otherwise skip this commit rather than creating an empty or artificial change.

## Completion report

Report the original HEAD, recovery branch, feature branch, worktree, every commit hash, third-party reference/license, complete test commands and outcomes, unchanged baseline failures, page URL, simulation command, restoration commands, and all remaining physical operator steps. Explicitly state that no real robot connection, motion, contact, activation, or bottle grasp was performed.

