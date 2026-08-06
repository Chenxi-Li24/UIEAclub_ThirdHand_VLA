# Active-View Browser Dry-Run Demo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an interactive `camera-test.html?demo=1` workflow that demonstrates the completed active-view behavior without creating any camera, backend, robot, gripper, or network control connection.

**Architecture:** A standalone deterministic JavaScript state machine produces the same sanitized status shape consumed by the existing page. A small page transport selection feeds either the current live transport or the demo state machine into the unchanged renderer. A Python standard-library launcher serves only static assets on loopback.

**Tech Stack:** Browser JavaScript, Node.js `assert` smoke tests, Python 3 `http.server`, existing headless Edge browser smoke infrastructure.

## Global Constraints

- Demo mode is enabled only when the query parameter is exactly `demo=1`.
- Both execution locks remain false for every demo state.
- Demo mode creates no `WebSocket`, `fetch`, camera stream, Startouch, CAN, robot, or gripper connection.
- Browser commands contain identifiers only and each confirmation advances exactly one logical step.
- The terminal demo state is `grasp_preview`; no grasp execution control may exist.
- Normal live mode and its endpoints remain unchanged.

---

### Task 1: Deterministic demo state machine

**Files:**
- Create: `web-control/web/active-view-demo.js`
- Create: `web-control/server/test/active-view-demo-smoke.js`
- Modify: `web-control/server/package.json`

**Interfaces:**
- Produces: `createActiveViewDemo(): { snapshot(): object, send(command: object): object, subscribe(listener: Function): Function, cameraPanels: object }`
- Consumes: ID-only commands named `start_active_view`, `confirm_active_view_step`, and `cancel_active_view`.

- [ ] **Step 1: Write the failing state-machine test**

```javascript
const { createActiveViewDemo } = require('../../web/active-view-demo');
const demo = createActiveViewDemo();
assert.equal(demo.snapshot().activeView.control.phase, 'idle');
const started = demo.send({ cmd: 'start_active_view', identityId: 7 });
assert.equal(started.accepted, true);
assert.equal(demo.snapshot().activeView.control.phase, 'waiting_operator_confirmation');
const first = demo.snapshot().activeView.control;
demo.send({ cmd: 'confirm_active_view_step', sessionId: first.sessionId, proposalId: first.proposalId });
assert.equal(demo.snapshot().activeView.reports[0].stableSamples, 2);
const second = demo.snapshot().activeView.control;
demo.send({ cmd: 'confirm_active_view_step', sessionId: second.sessionId, proposalId: second.proposalId });
assert.equal(demo.snapshot().activeView.control.phase, 'grasp_preview');
assert.equal(demo.snapshot().robotExecutionEnabled, false);
assert.equal(demo.snapshot().activeViewExecutionEnabled, false);
```

- [ ] **Step 2: Run the test and verify RED**

Run: `cd web-control/server && node test/active-view-demo-smoke.js`

Expected: FAIL because `../../web/active-view-demo` does not exist.

- [ ] **Step 3: Implement the minimal UMD module**

Implement immutable cloned snapshots, fixed UUID-format session/proposal IDs, exact-key
validation, two confirmation stages, local cancellation, bounded rejection reasons, a
subscriber notification, and SVG data-URL camera panels. Export with `module.exports`
under Node and `window.ThirdHandActiveViewDemo` in the browser.

- [ ] **Step 4: Verify GREEN and register the test**

Run: `cd web-control/server && node test/active-view-demo-smoke.js`

Expected: `PASS active-view browser demo is deterministic and fail-closed`.

Add `test:active-view-demo` to `package.json` and include it in `npm test` before the
browser test.

- [ ] **Step 5: Commit Task 1**

```bash
git add web-control/web/active-view-demo.js web-control/server/test/active-view-demo-smoke.js web-control/server/package.json
git commit -m "feat(vision): add fail-closed active-view demo model"
```

### Task 2: Camera-test demo transport and interactive UI

**Files:**
- Modify: `web-control/web/camera-test.html`
- Create: `web-control/server/test/active-view-demo-browser-smoke.js`
- Modify: `web-control/server/package.json`

**Interfaces:**
- Consumes: `window.ThirdHandActiveViewDemo.createActiveViewDemo()` from Task 1.
- Produces: `camera-test.html?demo=1`, using the existing `render(status)` contract.

- [ ] **Step 1: Write the failing browser contract test**

The test serves `web-control/web` on loopback, opens `camera-test.html?demo=1` in
headless Edge, installs wrappers that count `fetch` and `WebSocket` construction before
page scripts execute, clicks the target and both confirmation buttons, and asserts:

```javascript
assert.equal(result.fetchCount, 0);
assert.equal(result.webSocketCount, 0);
assert.equal(result.phase, 'grasp_preview');
assert.match(result.preview, /仅预览，不能执行抓取/);
assert.equal(result.confirmations, 2);
assert.equal(result.hasGraspExecutionButton, false);
assert.match(result.banner, /纯浏览器模拟/);
```

- [ ] **Step 2: Run the test and verify RED**

Run: `cd web-control/server && node test/active-view-demo-browser-smoke.js`

Expected: FAIL because the page currently calls `fetch` and creates `WebSocket` and has
no demo banner.

- [ ] **Step 3: Implement transport selection**

Load `active-view-demo.js`, add a hidden demo banner and synthetic-panel styling, select
demo mode with `new URLSearchParams(location.search).get('demo') === '1'`, and route
`sendCommand`, `refresh`, initialization, and camera panels through the demo object.
Live mode retains `/api/vision/status`, `/ws`, `/camera_lumos_vision`, and `/camera`.

- [ ] **Step 4: Verify demo and live browser tests**

Run:

```bash
cd web-control/server
node test/active-view-demo-browser-smoke.js
LUMOS_TEST_PORT=43110 VOICE_TEST_PORT=43111 EDGE_DEBUG_PORT=49237 node test/browser-smoke.js
```

Expected: both commands exit zero, demo reaches `grasp_preview`, live test retains all
existing PASS checks.

- [ ] **Step 5: Commit Task 2**

```bash
git add web-control/web/camera-test.html web-control/server/test/active-view-demo-browser-smoke.js web-control/server/package.json
git commit -m "feat(web): expose interactive active-view dry run"
```

### Task 3: Loopback-only demo launcher and final verification

**Files:**
- Create: `scripts/vision/start_active_view_demo.sh`
- Create: `tests/vision_deployment/test_active_view_demo_launcher.py`

**Interfaces:**
- Produces: `bash scripts/vision/start_active_view_demo.sh [--port PORT]`, printing `http://127.0.0.1:PORT/camera-test.html?demo=1`.
- Consumes: Python 3 standard-library `http.server` and `web-control/web` static assets only.

- [ ] **Step 1: Write the failing launcher contract test**

```python
def test_launcher_is_loopback_static_and_actuator_free():
    source = LAUNCHER.read_text(encoding="utf-8")
    assert "--bind 127.0.0.1" in source
    assert "web-control/web" in source
    assert "camera-test.html?demo=1" in source
    for forbidden in ("proxy.js", "camera_bridge", "startouch", "can0", "robot", "gripper"):
        assert forbidden not in source.lower()
```

- [ ] **Step 2: Run the test and verify RED**

Run: `pytest tests/vision_deployment/test_active_view_demo_launcher.py -q`

Expected: FAIL because the launcher does not exist.

- [ ] **Step 3: Implement the minimal launcher**

Validate a numeric port in `[1024, 65535]`, resolve the repository root relative to the
script, print the exact demo URL and safety message, then `exec python3 -m http.server
"$port" --bind 127.0.0.1 --directory "$root/web-control/web"`.

- [ ] **Step 4: Run focused and full verification**

Run:

```bash
bash -n scripts/vision/start_active_view_demo.sh
pytest tests/vision_deployment/test_active_view_demo_launcher.py -q
cd web-control/server && VOICE_TEST_PORT=43111 LUMOS_TEST_PORT=43110 LUMOS_PROXY_TEST_PORT=43220 LUMOS_UPSTREAM_TEST_PORT=43221 EDGE_DEBUG_PORT=49237 npm test
```

Expected: syntax check exits zero, launcher tests pass, and all Node/browser checks pass.

- [ ] **Step 5: Commit Task 3**

```bash
git add scripts/vision/start_active_view_demo.sh tests/vision_deployment/test_active_view_demo_launcher.py
git commit -m "feat(vision): launch active-view demo safely"
```
