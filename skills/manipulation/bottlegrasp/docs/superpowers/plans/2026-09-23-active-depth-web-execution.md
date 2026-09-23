# Web-Triggered Active Depth Alignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a web-triggered automatic RGB-guided alignment session that uses J4-J6 first, falls back to J1-J3 only when wrist motion cannot improve alignment, and stops after acquiring valid registered depth.

**Architecture:** Web Gateway owns the visual-servo state machine and uses pure fisheye/FK planning with fresh Vision and Robot evidence. One protected execution client sends a new `vision.align.step` primitive to Robot Service, which independently validates and executes one bounded joint target. The browser starts/stops a session and renders status but never computes targets, holds the execution token, or directly commands joints.

**Tech Stack:** Node.js 24 CommonJS, `node:test`, JSON Schema/Ajv contracts, HTTP and `ws`, existing SEUCM/FK modules, existing launcher-generated runtime token. No new dependency.

**Spec:** `skills/manipulation/bottlegrasp/docs/superpowers/specs/2026-09-23-active-depth-web-execution-design.md`

## Global Constraints

- Vision Service `robotControlEnabled=false` is an ownership marker and must not block alignment.
- The operator must select a stable target and separately press **Start depth alignment**; selection alone never moves the robot.
- J4-J6 candidates are exhausted before J1-J3 are considered; joints from the two tiers never change in one primitive.
- J4-J6 limits: 2 degrees per step and 10 degrees cumulative per joint. J1-J3 limits: 1 degree per step and 5 degrees cumulative per joint.
- Predicted camera-center displacement is at most 5 mm per step and 20 mm from session start; the session is at most 20 completed steps and 90 seconds.
- Only authenticated loopback `/execution` may carry alignment primitives. Never use the manual `/ws` route as a fallback.
- No grasp, gripper, descent, placement, or automatic reverse command belongs to this feature.
- Automated tests and deployment must not initiate hardware motion. A live session begins only when the operator clicks the new Start control with the physical E-stop available.
- Do not commit, push, create a branch, or drop the pre-pull stash backups unless the user explicitly requests it.

## Review Focus

- An `arm_fallback` primitive with `wristExhausted:false`, mixed-tier deltas, or a delta over 1 degree must be rejected by Robot Service, not merely by Web Gateway (Task 1 test).
- A stop or execution-socket disconnect during an in-flight step must request software stop and end uncertain until correlated feedback arrives (Tasks 1 and 4 tests).
- Duplicate/decreasing vision frame IDs and target-ID switches must never count toward three-frame depth completion (Task 4 tests).
- Browser refresh/reconnect must render the server-owned session without creating a second session or leaking the token (Tasks 5 and 6 tests).
- A candidate that improves angle but exceeds camera displacement, cumulative joint budget, workspace bounds, or 20-step/90-second limits must not execute (Tasks 3 and 4 tests).

---

## File Map

- `platform/contracts/schemas/execution-primitive.schema.json`: discriminated `gripper.set` and `vision.align.step` contract.
- `services/robot/src/execution-gateway.js`: exact protected stop-control message and session interruption.
- `services/robot/src/robot-controller.js`: independent primitive validation, bounded joint execution, correlated completion and stop behavior.
- `apps/web/src/active-depth/execution-client.js`: token-protected loopback `/execution` client.
- `apps/web/src/active-depth/vision-client.js`: fresh observation plus runtime-evidence reader.
- `apps/web/src/active-depth/candidate.js`: deterministic wrist-first/arm-fallback candidate hierarchy.
- `apps/web/src/active-depth/coordinator.js`: one automatic alignment session and state machine.
- `apps/web/src/config.js`, `apps/launcher/src/service-config.js`: execution endpoint/token and mount configuration propagation.
- `apps/web/src/server.js`, `apps/web/src/robot-proxy.js`: HTTP API, status broadcasts, robot-state access and lifecycle wiring.
- `apps/web/public/index.html`, `apps/web/public/css/style.css`, `apps/web/public/js/main.js`: Start/Stop controls and session status.
- Focused `tests/node/robot_service/`, `tests/node/web/`, and `tests/node/launcher/` tests cover every boundary.

### Task 1: Protected alignment primitive

**Files:**
- Modify: `platform/contracts/schemas/execution-primitive.schema.json`
- Modify: `services/robot/src/execution-gateway.js`
- Modify: `services/robot/src/robot-controller.js`
- Modify: `tests/node/robot_service/execution-gateway.test.js`

**Interfaces:**
- Consumes: existing `thirdhand.execution-primitive.v1`, RobotController fresh joint state, joint limits, bridge `move_joint` and `softwareStop`.
- Produces: `vision.align.step` with `{sessionId, stableId, frameId, evidenceId, motionEpoch, tier, wristExhausted, startJointsDeg, targetJointsDeg, timeoutMs}`, exact stop control `{schema:'thirdhand.execution-control.v1',type:'execution.stop',sessionId,reason:'operator_stop'}`, and correlated `execution.status` messages.

- [ ] **Step 1: Write failing contract/controller tests.** Add a valid wrist primitive, valid fallback primitive, wrong-tier delta, fallback without `wristExhausted:true`, stale start joints, replay, joint-limit, second-in-flight, timeout, exact stop-control, malformed stop-control, and socket-close cases. The valid fixture is:

```js
const primitive = {
  schema: 'thirdhand.execution-primitive.v1', primitiveId: 'align-1',
  traceId: 'trace-1', taskId: 'active-depth:session-1',
  authorizationId: 'active-depth:session-1', planDigest: `sha256:${'a'.repeat(64)}`,
  operation: 'vision.align.step', parameters: {
    sessionId: 'session-1', stableId: 2, frameId: 41,
    evidenceId: `sha256:${'b'.repeat(64)}`, motionEpoch: 3,
    tier: 'wrist', wristExhausted: false,
    startJointsDeg: [0, 20, -30, 0, 0, 0],
    targetJointsDeg: [0, 20, -30, 0, 1, 0], timeoutMs: 3000,
  },
};
```

- [ ] **Step 2: Run red.** Run `node --test tests/node/robot_service/execution-gateway.test.js`; expect schema rejection for `vision.align.step`.
- [ ] **Step 3: Implement the schema union.** Keep top-level identity fields shared, then use `oneOf` for the existing exact `gripper.set` parameters and the exact alignment parameters. Enforce stable ID 1..5, six finite joint numbers, non-negative integer frame/motion epoch, SHA-256 evidence ID, and timeout 100..30000 ms.
- [ ] **Step 4: Implement RobotController alignment validation and stop control.** Dispatch by operation. Require stationary fresh state and start-joint agreement within 0.2 degrees. For `wrist`, require unchanged J1-J3 and absolute J4-J6 deltas <=2. For `arm_fallback`, require `wristExhausted===true`, unchanged J4-J6, and absolute J1-J3 deltas <=1. Reuse joint-limit validation, send one low-level `move_joint`, and complete only on correlated command completion plus matching stationary state. In `ExecutionGateway`, distinguish an exact `thirdhand.execution-control.v1` stop message before primitive validation, call `interruptSession(sessionId,'operator_stop')`, and reject unknown keys/types without motion.

```js
if (primitive.operation === 'vision.align.step') {
  const alignment = validateAlignmentStep(primitive.parameters, this.latestJointsDeg);
  if (!alignment.ok) return reply(failed(primitive, alignment.code));
  return this._executeAlignmentPrimitive(primitive, alignment, reply);
}
```

- [ ] **Step 5: Run green.** Run the focused test; expect every invalid primitive to produce a stable failure code and no bridge motion, while both valid tiers emit exactly one bounded `move_joint`.

### Task 2: Authenticated Web execution and Vision evidence clients

**Files:**
- Create: `apps/web/src/active-depth/execution-client.js`
- Create: `apps/web/src/active-depth/vision-client.js`
- Modify: `apps/web/src/config.js`
- Modify: `apps/launcher/src/service-config.js`
- Test: `tests/node/web/active-depth-clients.test.js`
- Modify: `tests/node/launcher/runtime-secrets.test.js`
- Modify: `tests/node/launcher/service-supervisor.test.js`

**Interfaces:**
- Produces: `ExecutionClient({endpoint, tokenFile}).execute(primitive) -> Promise<terminalStatus>`, `.stop(sessionId)`, `.close()`; `VisionClient({baseUrl}).snapshot(stableId) -> Promise<{observation,runtimeEvidence}>`.
- Consumed by: Task 4 coordinator.

- [ ] **Step 1: Write failing tests.** Use local fake HTTP/WS servers. Assert the execution client sends the 64-hex token only in the upgrade header, correlates by primitive ID, rejects mismatched IDs, times out, requests software stop, and never exposes the token in `publicStatus()` or thrown errors. Assert VisionClient merges `/api/vision/observation` with `/api/vision/status.runtimeEvidence`, rejects mismatched target IDs and non-increasing frames, and does not interpret `robotControlEnabled:false` as a blocker.
- [ ] **Step 2: Run red.** Run `node --test tests/node/web/active-depth-clients.test.js tests/node/launcher/runtime-secrets.test.js tests/node/launcher/service-supervisor.test.js`; expect missing clients/config.
- [ ] **Step 3: Implement strict clients.** Validate loopback URLs, token file mode/content, response sizes and JSON shapes. Keep one execution socket and one primitive in flight. On timeout/close, attempt `{type:'execution.stop', sessionId}` on the protected socket and reject with `execution_uncertain`.

```js
const result = await visionClient.snapshot(stableId);
// result.observation remains vision-owned and may say robotControlEnabled:false.
// result.runtimeEvidence supplies camera_mount_id and registration_id.
```

- [ ] **Step 4: Propagate runtime configuration.** Add `ROBOT_EXECUTION_WS_URL` (default `ws://127.0.0.1:3000/execution`), `ROBOT_EXECUTION_TOKEN_FILE`, and `ACTIVE_DEPTH_MOUNT_FILE`. The launcher must pass the same `prepareExecutionToken()` path to Robot and Web services without logging its contents.
- [ ] **Step 5: Run green.** Re-run all Task 2 tests; inspect captured child environments and WS headers to prove identical token path and no token value leakage.

### Task 3: Wrist-first candidate hierarchy

**Files:**
- Modify: `apps/web/src/active-depth/candidate.js`
- Modify: `tests/node/web/active-depth-candidate.test.js`

**Interfaces:**
- Produces: `planAlignmentStep(input) -> {ok,tier,wristExhausted,targetJointsDeg,predictedPixel,pixelEstimateKind,angularErrorRad,initialAngularErrorRad,cameraShiftM,cameraCumulativeM,jointDeltasDeg,reason?}`.
- Keeps: `planWristStep(input)` as a compatibility wrapper for existing offline tests.

- [ ] **Step 1: Write failing hierarchy tests.** Inject analytic FK poses. Assert a wrist improvement wins even when an arm candidate scores better; arm fallback occurs only when every wrist candidate is invalid/non-improving or wrist cumulative budget is exhausted; fallback never changes J4-J6; and no candidate is returned over joint/camera/workspace/session bounds.

```js
const result = planAlignmentStep({ ...fixture, completedSteps: 3, elapsedMs: 1200 });
assert.equal(result.tier, 'wrist');
assert.deepEqual(result.targetJointsDeg.slice(0, 3), fixture.jointsDeg.slice(0, 3));
```

- [ ] **Step 2: Run red.** Run `node --test tests/node/web/active-depth-candidate.test.js`; expect missing `planAlignmentStep`.
- [ ] **Step 3: Implement deterministic tiers.** Factor one `rankTier(indices, stepSizes)` helper. Wrist indices `[3,4,5]` use `[2,1,0.5,0.25]`; fallback indices `[0,1,2]` use `[1,0.5,0.25]`. Apply configured joint limits, per-tier cumulative limits, 5 mm step/20 mm cumulative camera displacement, 20 steps, 90 seconds, and strict 0.001 rad improvement. Return `wristExhausted:true` only after evaluating all wrist candidates.
- [ ] **Step 4: Run green.** Run candidate and FK/fisheye tests; expect deterministic repeated output for identical input.

### Task 4: Automatic active-depth coordinator

**Files:**
- Create: `apps/web/src/active-depth/coordinator.js`
- Test: `tests/node/web/active-depth-coordinator.test.js`

**Interfaces:**
- Consumes: Task 2 clients, Task 3 `planAlignmentStep`, `getRobotState()`, mount artifact.
- Produces: `start(stableId)`, `stop(sessionId)`, `status()`, `close()`, and EventEmitter event `status` carrying immutable `active_depth.status` payloads.

- [ ] **Step 1: Write failing state-machine tests.** Use deterministic fake clients and clock. Cover explicit start, duplicate start, selected-ID mismatch, three increasing depth-valid frames, invalid-frame counter reset, decreasing/duplicate frame rejection, wrist then fallback, correlated execution completion, target switch, no progress, 20-step and 90-second limits, operator stop, timeout, and close during motion.

```js
await coordinator.start(2);
assert.equal(coordinator.status().phase, 'observing');
vision.push(depthFrame(41, true));
vision.push(depthFrame(42, true));
vision.push(depthFrame(43, true));
assert.equal(coordinator.status().phase, 'depth_acquired');
assert.equal(execution.sent.length, 0);
```

- [ ] **Step 2: Run red.** Run `node --test tests/node/web/active-depth-coordinator.test.js`; expect missing coordinator.
- [ ] **Step 3: Implement the state machine.** Serialize transitions through one promise chain. Freeze session start joints/camera pose and target identity. Poll only after execution completion and stationary state. Require new frame IDs and compare observed SEUCM angular error against the pre-step value; stop on less than 0.001 rad improvement. Every terminal path cancels timers and emits one final immutable status.
- [ ] **Step 4: Implement stop semantics.** Stop is idempotent. If no primitive is in flight, terminate `stopped`; otherwise call protected stop and wait for correlated completion, using `uncertain` on loss/timeout. `close()` follows the same path before closing clients.
- [ ] **Step 5: Run green.** Run coordinator tests; expect no unhandled timers, no command after any terminal state, and at most one primitive in flight.

### Task 5: Web Gateway API and status broadcast

**Files:**
- Modify: `apps/web/src/robot-proxy.js`
- Modify: `apps/web/src/server.js`
- Modify: `tests/node/web/server.test.js`
- Test: `tests/node/web/active-depth-api.test.js`

**Interfaces:**
- Adds: `RobotProxy.getRobotState()`, existing `broadcast(message)` reuse.
- Adds HTTP: `POST /api/active-depth/start`, `POST /api/active-depth/stop`, `GET /api/active-depth/status`.

- [ ] **Step 1: Write failing API tests.** Inject a fake coordinator. Verify exact JSON body keys, stable ID 1..5, 16 KiB body limit, 202 start, 409 active, 200 idempotent stop, status readback, coordinator event broadcast to all browsers, refresh readback, and no token/config secret in any response.
- [ ] **Step 2: Run red.** Run `node --test tests/node/web/active-depth-api.test.js tests/node/web/server.test.js`; expect 404 routes.
- [ ] **Step 3: Implement dependency injection and routes.** `createWebGateway(options)` accepts or constructs clients/coordinator. Parse bounded JSON exactly, delegate state, map stable coordinator reasons to HTTP statuses, and broadcast `active_depth.status`. Add active-depth readiness—not the vision ownership flag—to `/health` and `/api/runtime-config`.

```js
if (request.method === 'POST' && pathname === '/api/active-depth/start') {
  const body = await readJson(request, 16 * 1024);
  return writeCoordinatorResult(response, await coordinator.start(body.stableId));
}
```

- [ ] **Step 4: Wire lifecycle.** Start coordinator dependencies after server construction; on gateway close call `await coordinator.close()` before terminating Robot/Vision proxies. Expose the same background Robot state already maintained by `LanguageUpstreamBridge`; do not create a second manual `/ws` command path.
- [ ] **Step 5: Run green.** Run API/server/vision-proxy/language-chain tests; expect routes and existing proxies to coexist.

### Task 6: Browser controls and status rendering

**Files:**
- Modify: `apps/web/public/index.html`
- Modify: `apps/web/public/css/style.css`
- Modify: `apps/web/public/js/main.js`
- Modify: `tests/node/web/arm-model-preview.test.js`
- Test: `tests/node/web/active-depth-ui.test.js`

**Interfaces:**
- Browser calls same-origin APIs from Task 5 and consumes `active_depth.status` from existing Robot WebSocket.

- [ ] **Step 1: Write failing DOM/source tests.** Assert unique Start/Stop IDs, Start disabled without selected stable target or during active session, Stop enabled only during non-terminal session, no automatic start on target selection, Chinese terminal messages, and no direct `move_joint`, `/execution`, token, or FK logic in browser code.
- [ ] **Step 2: Run red.** Run `node --test tests/node/web/active-depth-ui.test.js tests/node/web/arm-model-preview.test.js`; expect missing controls/handlers.
- [ ] **Step 3: Add accessible markup and styling.** Place controls in `sec-xvision`. Add status rows for phase, target, depth, current→predicted pixel, joint delta, camera shift, steps and reason. Preserve existing stream selector and grasp controls. Use existing button/chip visual language and responsive drawer layout.
- [ ] **Step 4: Implement browser behavior.** Maintain one `activeDepthStatus`; read status on page startup/reconnect, POST start only from explicit click with selected stable ID, POST stop with server session ID, and render every WS update. Use `navigator.sendBeacon` only for stop on page hide if a session is active; server timeouts remain authoritative.

```js
startButton.addEventListener('click', () => requestActiveDepth('/api/active-depth/start', {
  stableId: this.selectedVisionTarget.stableId,
}));
```

- [ ] **Step 5: Run green.** Run UI and existing web tests. Inspect the served page with the fake coordinator through `9983` and verify reconnect/status restoration without starting a second session.

### Task 7: Integrated verification and deployment readiness

**Files:**
- Modify: `tools/active-depth/README.md`
- Modify: `docs/OPERATIONS.md`
- Modify: `tests/node/web/active-depth-api.test.js`
- Modify: `tests/node/robot_service/execution-gateway.test.js`

**Interfaces:** Documents the exact launcher command, UI flow, observable status, stop procedure, token file, and hardware commissioning gate.

- [ ] **Step 1: Add one end-to-end simulated test.** Launch fake Vision and Robot execution services plus Web Gateway, select target 2, POST start, return one wrist rejection/no-improvement path followed by a valid fallback step, then three valid increasing depth frames. Assert terminal `depth_acquired`, exactly two bounded primitives at most (according to fixture), no gripper command, and no browser token exposure.
- [ ] **Step 2: Run red before completing integration wiring.** Run the new named test and verify it fails at the first missing boundary rather than from malformed fixtures.
- [ ] **Step 3: Complete documentation.** State that `robotControlEnabled:false` is expected for Vision, define all phases/reasons and limits, explain physical E-stop and empty swept-workspace requirements, and document that service startup does not start alignment.
- [ ] **Step 4: Run focused and full verification.** Run:

```sh
node --test tests/node/robot_service/execution-gateway.test.js
node --test tests/node/web/active-depth-*.test.js tests/node/web/server.test.js tests/node/web/arm-model-preview.test.js
npm run test:node
```

Expected: all commands exit 0. If an unrelated pre-existing test fails, record the exact name/output and do not modify unrelated code.

- [ ] **Step 5: Start services without starting alignment.** Use the normal launcher so Robot, Vision, and Web receive the shared token path. Verify `/health`, `/api/vision/status`, `/api/active-depth/status`, and the `9983` page. Do not press Start or send a primitive during deployment verification; report that hardware commissioning remains operator-triggered.

## Hardware Commissioning Handoff

After software verification, the first live session requires the operator at the machine with the physical E-stop reachable and the swept workspace empty. Start with a visible target already close to the depth ROI. Observe one wrist step and one fallback step separately against predicted pixel direction before allowing the loop to continue. Any unexpected link motion, target switch, wrong pixel direction, depth regression, or stop uncertainty ends commissioning; do not automatically retry, reverse, grasp, or place.
