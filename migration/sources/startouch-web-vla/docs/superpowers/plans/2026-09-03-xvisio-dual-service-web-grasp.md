# XVisio Dual-Service Web Grasp Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the web panel's D435 view with the remote XVisio recognition stream and add execution-locked step/manual and automatic grasp controls routed through the existing Startouch server.

**Architecture:** Port 3100 remains the XVisio RGB-D and perception owner; port 3000 owns the browser, safety authorization, and all robot commands. A new `XVisionClient` connects from 3000 to 3100, proxies two fixed MJPEG paths, forwards bounded selection commands, and publishes validated detection events to a new `GraspController` that supports step and automatic modes without automatic home or release.

**Tech Stack:** Node.js 18+, Express 4, `ws` 8, vanilla browser JavaScript/CSS, existing Startouch JSON-lines bridge, Node smoke tests.

**Spec:** `docs/superpowers/specs/2026-09-03-xvisio-dual-service-web-grasp-design.md`

## Global Constraints

- Preserve the existing explicit Startouch connection flow; page load and WebSocket reconnect must never connect or move the robot.
- Port 3100 must remain unable to send commands to CAN or the Startouch SDK.
- Browser messages may contain target IDs or left/right ordinals only, never trusted robot coordinates.
- Grasp execution requires a fresh server-side target, valid depth, stationary robot, approved physical hand-eye calibration, and explicit server execution enablement.
- The current calibration remains `pending`; deployed A/B controls must remain disabled until real validation passes.
- Automatic mode ends in `holding`; it must not issue `go_home` or open the gripper.
- Do not stage or overwrite pre-existing working-tree changes unrelated to the task.

---

## File Structure

- Create `web-control/server/xvision-client.js`: fixed-path HTTP MJPEG proxy, remote WebSocket lifecycle, event forwarding, and bounded bottle selection.
- Create `web-control/server/xvision-contract.js`: normalize and validate `thirdhand-va-detection-v2` events into display and trusted grasp targets.
- Create `web-control/server/grasp-controller.js`: isolated fail-closed step/automatic grasp state machine.
- Modify `web-control/server/config.js`: remote XVisio and grasp execution configuration.
- Modify `web-control/server/camera-bridge.js`: allow exact-key `select_bottle` commands for the 3100 bridge.
- Modify `web-control/server/proxy.js`: compose the remote client, status store, safety authorization, and grasp controller.
- Modify `web-control/server/grasp-authorization.js`: authorize the normalized grasp plan rather than browser coordinates.
- Modify `web-control/server/vision-status.js`: expose XVisio ordinals and selected/preview state while keeping execution fail-closed.
- Modify `web-control/web/index.html`: replace the dual D435/Lumos panel with one XVisio panel and A/B controls.
- Modify `web-control/web/js/main.js`: stream switching, target selection, and grasp-mode commands.
- Modify `web-control/web/css/style.css`: stable XVisio viewport, segmented controls, target rows, and state/action layout.
- Create focused Node smoke tests under `web-control/server/test/` for each new module and integration boundary.
- Modify `web-control/server/package.json`: include all new tests in `npm test`.
- Modify `web-control/README.md`: document dual-service startup and locked/unlocked behavior.

---

### Task 1: Remote XVisio Client and Fixed Stream Proxy

**Files:**
- Create: `web-control/server/xvision-client.js`
- Create: `web-control/server/test/xvision-client-smoke.js`
- Modify: `web-control/server/config.js`
- Modify: `web-control/server/package.json`

**Interfaces:**
- Produces: `new XVisionClient({ baseUrl, wsUrl, reconnectMs, requestTimeoutMs })`.
- Produces: `client.proxyMjpeg(upstreamPath, req, res)` for fixed server-selected paths.
- Produces: `client.selectBottle({ side, ordinal, requestId }) -> boolean`.
- Emits: `detection_result`, `vision_status`, `camera_status`, `vision_error`, `connection`.

- [ ] **Step 1: Write the failing remote-client test**

Create a local mock HTTP/WebSocket service. Assert that `/camera_lumos_vision` bytes stream through `proxyMjpeg`, `selectBottle` sends exactly `{cmd:'select_bottle',side:'left',ordinal:2,request_id:'req-1'}`, a detection event is emitted, arbitrary upstream paths throw, and disconnect schedules a bounded reconnect.

```js
const client = new XVisionClient({ baseUrl, wsUrl, reconnectMs: 10 });
assert.throws(() => client.proxyMjpeg('/arbitrary', req, res), /unsupported/i);
client.start();
assert.equal(client.selectBottle({ side: 'left', ordinal: 2, requestId: 'req-1' }), true);
assert.deepEqual(receivedCommand, {
  cmd: 'select_bottle', side: 'left', ordinal: 2, request_id: 'req-1',
});
```

- [ ] **Step 2: Run the test and verify RED**

Run: `cd web-control/server && node test/xvision-client-smoke.js`

Expected: FAIL with `Cannot find module '../xvision-client'`.

- [ ] **Step 3: Implement the minimal client**

Use `http`/`https` selected from the configured URL, `new URL(upstreamPath, baseUrl)`, a hard-coded path allowlist, request timeout, `Cache-Control: no-store`, and `req.on('close', () => upstream.destroy())`. Use `ws` for the remote event connection and emit only parsed JSON objects with recognized event types. Validate selection with:

```js
function normalizeSelection({ side, ordinal, requestId }) {
  if (!['left', 'right'].includes(side)) throw new TypeError('invalid selection side');
  if (!Number.isInteger(ordinal) || ordinal < 1 || ordinal > 32) {
    throw new TypeError('invalid selection ordinal');
  }
  return { cmd: 'select_bottle', side, ordinal, request_id: String(requestId) };
}
```

Add config:

```js
xvision: {
  enabled: process.env.XVISION_PROXY_ENABLED === '1',
  baseUrl: process.env.XVISION_SERVICE_URL || 'http://127.0.0.1:3100',
  wsUrl: process.env.XVISION_WS_URL || 'ws://127.0.0.1:3100/ws',
  reconnectMs: 2000,
  requestTimeoutMs: 2000,
},
```

- [ ] **Step 4: Run the focused test and verify GREEN**

Run: `cd web-control/server && node test/xvision-client-smoke.js`

Expected: `PASS remote XVisio client proxies fixed streams and validates selection`.

- [ ] **Step 5: Add the test to `package.json` and commit**

```bash
git add web-control/server/xvision-client.js web-control/server/test/xvision-client-smoke.js web-control/server/config.js web-control/server/package.json
git commit -m "feat(vision): add remote XVisio client"
```

---

### Task 2: XVisio Detection Contract and Selection Forwarding

**Files:**
- Create: `web-control/server/xvision-contract.js`
- Create: `web-control/server/test/xvision-contract-smoke.js`
- Modify: `web-control/server/camera-bridge.js`
- Modify: `web-control/server/vision-status.js`
- Modify: `web-control/server/test/vision-status-smoke.js`
- Modify: `web-control/server/package.json`

**Interfaces:**
- Produces: `normalizeXVisionEvent(event) -> { displayEvent, trustedTarget }`.
- Produces: `normalizeXVisionTarget(event, target) -> TrustedGraspTarget | null`.
- Extends: `CameraBridge.send({cmd:'select_bottle', side, ordinal, request_id})`.
- `TrustedGraspTarget` contains `id`, `selected`, `leftOrdinal`, `rightOrdinal`, `observedAtMs`, `previewId`, `calibrationId`, `graspM`, `pregraspM`, `retreatM`, `widthM`, and safety booleans.

- [ ] **Step 1: Write failing contract tests**

Use a real-shaped `thirdhand-va-detection-v2` fixture containing one selected target and top-level camera pose. Assert that the display target keeps `L1/R3`, while the trusted target takes robot coordinates only from `target.grasp_preview.grasp_xyz_m` and never from browser data or the camera-frame `event.pose.point_m`.

```js
const normalized = normalizeXVisionEvent(fixture);
assert.equal(normalized.displayEvent.objects[0].spatialLabel, 'L1/R3');
assert.deepEqual(normalized.trustedTarget.graspM, [0.555, 0.029, 0.294]);
assert.equal(normalized.trustedTarget.safetyApproved, false);
```

Add malformed fixtures for missing timestamps, non-finite vectors, duplicate selected targets, mismatched requested ordinals, and `grasp_preview.allowed !== true`; all must yield no trusted executable target.

- [ ] **Step 2: Run tests and verify RED**

Run: `cd web-control/server && node test/xvision-contract-smoke.js`

Expected: FAIL with `Cannot find module '../xvision-contract'`.

- [ ] **Step 3: Implement normalization and exact-key selection**

Normalize display-only fields separately from trusted motion evidence. Require exactly one selected target for a trusted target. Extend `COMMAND_KEYS` and the allowlist in `camera-bridge.js`:

```js
select_bottle: ['cmd', 'side', 'ordinal', 'request_id'],
```

Update `VisionStatusStore` so XVisio targets expose `leftOrdinal`, `rightOrdinal`, `spatialLabel`, `selected`, `depthValidRatio`, `graspWidthM`, `previewIdShort`, and blocker strings, but continue returning `robotExecutionEnabled: false` unless the composing server explicitly provides an enabled state.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `cd web-control/server && node test/xvision-contract-smoke.js && node test/vision-status-smoke.js`

Expected: both scripts print `PASS` and exit 0.

- [ ] **Step 5: Commit the contract boundary**

```bash
git add web-control/server/xvision-contract.js web-control/server/test/xvision-contract-smoke.js web-control/server/camera-bridge.js web-control/server/vision-status.js web-control/server/test/vision-status-smoke.js web-control/server/package.json
git commit -m "feat(vision): normalize remote grasp evidence"
```

---

### Task 3: Fail-Closed A/B Grasp Controller

**Files:**
- Create: `web-control/server/grasp-controller.js`
- Create: `web-control/server/test/grasp-controller-smoke.js`
- Modify: `web-control/server/grasp-authorization.js`
- Modify: `web-control/server/test/grasp-authorization-smoke.js`
- Modify: `web-control/server/package.json`

**Interfaces:**
- Produces: `new GraspController({ authorize, sendRobot, now, emitStatus })`.
- Produces: `select(target)`, `start(mode)`, `advance()`, `onRobotComplete(event)`, `onRobotError(reason)`, `cancel(reason)`, and `snapshot()`.
- Modes: `step` and `auto`.
- Phases: `idle`, `target_selected`, `preview_ready`, `hover`, `descend`, `close`, `lift`, `holding`, `aborted`.

- [ ] **Step 1: Write failing controller tests**

Test with real callback functions that record sent commands. Required assertions:

```js
controller.select(target);
controller.start('step');
assert.deepEqual(sent.map(item => item.phase), ['hover']);
controller.onRobotComplete({ command: 'move_l' });
assert.equal(controller.snapshot().phase, 'preview_ready');
controller.advance();
assert.deepEqual(sent.map(item => item.phase), ['hover', 'descend']);
```

For `auto`, simulate completions and assert command phases are exactly `hover`, `descend`, `close`, `lift`, ending in `holding`. Assert no command contains `go_home` or an open-gripper position. Add stale evidence, preview-ID change, send failure, motion error, and cancel cases; each must stop further commands and enter `aborted`.

- [ ] **Step 2: Run tests and verify RED**

Run: `cd web-control/server && node test/grasp-controller-smoke.js`

Expected: FAIL with `Cannot find module '../grasp-controller'`.

- [ ] **Step 3: Extend authorization for complete plans**

`authorizeGrasp` must require `executionEnabled`, robot connected/idle/fresh, exactly one trusted target, `actionable`, `calibrationValidated`, `depthValid`, `identityConfirmed`, `armStationary`, `safetyApproved`, `previewAllowed`, fresh observation, finite `pregraspM`/`graspM`/`retreatM`, a finite width in `[0.012, 0.080]`, and matching preview/calibration IDs. Return a frozen plan copied from trusted data.

- [ ] **Step 4: Implement the minimal controller**

The controller owns the task evidence and calls authorization before every phase. Map phases to server-owned robot commands:

```js
hover   -> { cmd: 'move_l', position: plan.pregraspM, euler: plan.euler }
descend -> { cmd: 'move_l', position: plan.graspM,    euler: plan.euler }
close   -> { cmd: 'gripper', position: widthToNormalized(plan.widthM) }
lift    -> { cmd: 'move_l', position: plan.retreatM,  euler: plan.euler }
```

Do not implement home, release, placement, retry, or recovery motion.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run: `cd web-control/server && node test/grasp-authorization-smoke.js && node test/grasp-controller-smoke.js`

Expected: both scripts print `PASS` and exit 0.

- [ ] **Step 6: Commit the controller**

```bash
git add web-control/server/grasp-controller.js web-control/server/test/grasp-controller-smoke.js web-control/server/grasp-authorization.js web-control/server/test/grasp-authorization-smoke.js web-control/server/package.json
git commit -m "feat(robot): add staged and automatic grasp controller"
```

---

### Task 4: Compose Dual Services in the Port 3000 Server

**Files:**
- Modify: `web-control/server/proxy.js`
- Create: `web-control/server/test/xvision-proxy-integration-smoke.js`
- Modify: `web-control/server/package.json`

**Interfaces:**
- Consumes: `XVisionClient`, `normalizeXVisionEvent`, `GraspController`.
- Adds browser commands: `select_vision_target`, `start_grasp`, `advance_grasp`, `cancel_grasp`.
- Adds HTTP streams: `/camera/xvisio/vision`, `/camera/xvisio/raw`.
- Broadcasts: normalized `detection_result`, `vision_connection`, and `grasp_task_status`.

- [ ] **Step 1: Write the failing integration test**

Start a mock 3100 service and a simulated 3000 server. Assert fixed stream bytes arrive, detection events appear on the browser WebSocket, selection is forwarded, browser-supplied coordinates are ignored, and `start_grasp` is rejected with `robot_execution_disabled` while the current lock is active.

```js
browser.send(JSON.stringify({
  cmd: 'start_grasp', mode: 'auto', id: 7,
  position_m: [999, 999, 999],
}));
assert.equal(result.accepted, false);
assert.equal(result.reason, 'robot_execution_disabled');
assert.equal(robotCommands.length, 0);
```

- [ ] **Step 2: Run the integration test and verify RED**

Run: `cd web-control/server && node test/xvision-proxy-integration-smoke.js`

Expected: FAIL because the fixed stream route or browser command is missing.

- [ ] **Step 3: Integrate the client and controller**

When `config.xvision.enabled` is true, do not start the local `CameraBridge`; start `XVisionClient` instead. Feed normalized detections to `VisionStatusStore`, update the trusted-target map, and broadcast display events. Forward only validated target selection to 3100. Replace the old global `graspState`, `startGrasp`, and `advanceGrasp` with `GraspController`.

Robot command dispatch must retain existing bridge serialization and generate server request IDs. Set `motionActive` for Cartesian moves; completion/error events must return to the controller. `software_stop`, robot disconnect, visual disconnect, and stale target events cancel the task.

- [ ] **Step 4: Run the integration test and verify GREEN**

Run: `cd web-control/server && node test/xvision-proxy-integration-smoke.js`

Expected: `PASS port 3000 safely composes remote XVisio and simulated Startouch`.

- [ ] **Step 5: Commit the server composition**

```bash
git add web-control/server/proxy.js web-control/server/test/xvision-proxy-integration-smoke.js web-control/server/package.json
git commit -m "feat(web): bridge remote vision to grasp control"
```

---

### Task 5: Replace the D435 Panel with XVisio A/B Controls

**Files:**
- Modify: `web-control/web/index.html`
- Modify: `web-control/web/js/main.js`
- Modify: `web-control/web/css/style.css`
- Modify: `web-control/server/test/browser-smoke.js`
- Create: `web-control/server/test/xvision-browser-smoke.js`
- Modify: `web-control/server/package.json`

**Interfaces:**
- Consumes HTTP: `/camera/xvisio/vision`, `/camera/xvisio/raw`, `/api/vision/status`.
- Sends WebSocket commands containing IDs/ordinals only.
- Consumes WebSocket: `detection_result`, `vision_connection`, `grasp_task_status`.

- [ ] **Step 1: Write failing browser tests**

Assert the page contains one XVisio image, defaults to recognition mode, switches to raw mode, renders `L1/R3`, sends a bounded selection command, presents `step` and `auto` modes, and disables all motion buttons for a locked target. Assert no D435 label, duplicate Lumos image, browser coordinate, `go_home`, or automatic release control remains in the panel flow.

- [ ] **Step 2: Run browser tests and verify RED**

Run: `cd web-control/server && node test/xvision-browser-smoke.js`

Expected: FAIL because the XVisio panel and controls are absent.

- [ ] **Step 3: Implement the panel markup and styles**

Use one fixed-aspect-ratio viewport, two segmented controls (`识别/原始`, `分步/自动`), selectable target rows, compact preview metrics, phase status, primary action, next-step action, and cancel action. Use the repository's existing button styles and keep controls within the drawer width at desktop and mobile sizes.

- [ ] **Step 4: Implement browser state handling**

Default `#xvision-feed` to `/camera/xvisio/vision`, retain bounded reconnect backoff, and render target labels from server-provided `spatialLabel`. A target click sends only:

```js
ws.send({ cmd: 'select_vision_target', side, ordinal });
```

Start/advance/cancel commands contain mode and target ID only. Button enablement derives from server `grasp_task_status` and target blockers; client-side state never overrides a server rejection.

- [ ] **Step 5: Run focused browser tests and verify GREEN**

Run: `cd web-control/server && node test/xvision-browser-smoke.js && node test/browser-smoke.js`

Expected: both scripts print `PASS` and exit 0.

- [ ] **Step 6: Commit the UI**

```bash
git add web-control/web/index.html web-control/web/js/main.js web-control/web/css/style.css web-control/server/test/browser-smoke.js web-control/server/test/xvision-browser-smoke.js web-control/server/package.json
git commit -m "feat(web): add XVisio grasp controls"
```

---

### Task 6: Documentation, Full Verification, and Ubuntu Simulation Deployment

**Files:**
- Modify: `web-control/README.md`
- Modify: `web-control/.env.example`
- Modify: `web-control/scripts/start_ubuntu.sh`
- Test: all `web-control/server/test/*.js`

**Interfaces:**
- Documents `XVISION_PROXY_ENABLED`, `XVISION_SERVICE_URL`, `XVISION_WS_URL`, and `VISION_ROBOT_EXECUTION_ENABLED`.
- Keeps execution disabled in checked-in defaults.

- [ ] **Step 1: Write the failing runtime configuration test**

Extend the runtime smoke test to require documented dual-service environment variables and to assert the default execution flag is false.

- [ ] **Step 2: Run the runtime test and verify RED**

Run: `cd web-control/server && node test/runtime-endpoints-smoke.js`

Expected: FAIL because the new environment variables are not documented or exported.

- [ ] **Step 3: Update startup and documentation**

Document that 3100 starts first with `STARTOUCH_SIMULATE=1`, then 3000 starts with remote vision enabled. Keep this checked-in default:

```bash
XVISION_PROXY_ENABLED=1
XVISION_SERVICE_URL=http://127.0.0.1:3100
XVISION_WS_URL=ws://127.0.0.1:3100/ws
VISION_ROBOT_EXECUTION_ENABLED=0
```

Explain that setting the last value to 1 is insufficient unless the live target also carries approved calibration and safety evidence.

- [ ] **Step 4: Run the complete local suite**

Run: `cd web-control/server && npm test`

Expected: all Node smoke tests pass with exit 0.

- [ ] **Step 5: Review the diff before deployment**

Run: `git diff --check && git status --short && git diff --stat HEAD~5..HEAD`

Expected: no whitespace errors; only planned files and preserved pre-existing changes are present.

- [ ] **Step 6: Deploy to Ubuntu without restarting the real port 3000 service**

Copy the reviewed files to `/home/nieqingcao/arm/UIEAclub_ThirdHand_VLA`, install no new packages, and run `npm test` there. Restart only the simulated/visual 3100 service and verify:

```bash
curl -fsS http://127.0.0.1:3100/api/vision/status
curl --max-time 3 http://127.0.0.1:3100/camera_lumos_vision -o /tmp/xvision.mjpeg
```

Expected: model online, XVisio roles reported, and non-empty MJPEG bytes. Do not restart the real 3000 service until the operator explicitly approves the interruption because SDK cleanup can depower the arm.

- [ ] **Step 7: Commit documentation and runtime configuration**

```bash
git add web-control/README.md web-control/.env.example web-control/scripts/start_ubuntu.sh web-control/server/test/runtime-endpoints-smoke.js
git commit -m "docs: describe dual-service XVisio startup"
```

- [ ] **Step 8: Perform the operator-approved real-service restart and locked-state check**

After explicit approval, restart port 3000 with remote XVisio enabled and execution disabled. Verify the recognition feed, target selection, both grasp modes, and server-side rejection while calibration is pending. No real motion is part of this step.

