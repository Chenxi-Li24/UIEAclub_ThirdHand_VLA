# Live Camera Test Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `/camera-test.html` show the real Lumos and D435 streams immediately, with a bounded optional Lumos overlay switch that never replaces a working raw stream with a stalled overlay.

**Architecture:** A focused UMD module owns only Lumos raw/overlay selection and timeout behavior. The existing page selects real raw streams in live mode, uses the selector for the optional overlay, and leaves its status renderer and synthetic demo transport separate. A controlled real-browser test serves actual image responses and verifies stream selection plus first-viewport layout.

**Tech Stack:** Browser JavaScript, Node.js `assert`, Express, Chrome DevTools Protocol, existing headless Edge infrastructure.

## Global Constraints

- Normal mode defaults to same-origin `/camera_lumos` and `/camera`.
- A stalled or failed `/camera_lumos_vision` probe never replaces raw Lumos.
- `?demo=1` creates no raw, overlay, API, or WebSocket request.
- Both execution locks remain false; no robot or gripper command is added.
- Lumos and D435 must both intersect the first 1440×1000 desktop viewport.
- Existing ID-only active-view commands remain unchanged.

---

### Task 1: Bounded Lumos stream selector

**Files:**
- Create: `web-control/web/live-camera-streams.js`
- Create: `web-control/server/test/live-camera-streams-smoke.js`
- Modify: `web-control/server/package.json`

**Interfaces:**
- Produces: `createLumosStreamSelector(options)` with `useRaw()`, `tryOverlay()`, `destroy()`, and `mode()`.
- Consumes: `rawUrl`, `overlayUrl`, `applySource(url)`, `report(status)`, `createProbe()`, `schedule(fn, milliseconds)`, `cancelSchedule(handle)`, and `timeoutMs`.

- [ ] **Step 1: Write the failing selector behavior test**

```javascript
const { createLumosStreamSelector } = require('../../web/live-camera-streams');
let visible = null;
let status = null;
let timeout;
const probes = [];
const selector = createLumosStreamSelector({
  rawUrl: '/camera_lumos', overlayUrl: '/camera_lumos_vision',
  applySource: value => { visible = value; }, report: value => { status = value; },
  createProbe: () => { const probe = {}; probes.push(probe); return probe; },
  schedule: callback => { timeout = callback; return 1; }, cancelSchedule: () => {},
  timeoutMs: 2500,
});
selector.useRaw();
assert.equal(visible, '/camera_lumos');
selector.tryOverlay();
timeout();
assert.equal(visible, '/camera_lumos');
assert.equal(status, 'overlay_unavailable');
selector.tryOverlay();
probes[1].onload();
assert.equal(visible, '/camera_lumos_vision');
selector.useRaw();
assert.equal(visible, '/camera_lumos');
```

- [ ] **Step 2: Run and verify RED**

Run: `cd web-control/server && node test/live-camera-streams-smoke.js`

Expected: FAIL because `../../web/live-camera-streams` does not exist.

- [ ] **Step 3: Implement the minimal selector**

Use an internal generation counter so late `load`/`error` callbacks from an older probe
cannot change the visible source. `tryOverlay()` reports `checking_overlay`, starts one
probe and one timeout, applies the overlay only on the current probe's `load`, and reports
`overlay_unavailable` on error/timeout without changing the raw source. `useRaw()` and
`destroy()` invalidate the current generation and clear its timer/probe.

- [ ] **Step 4: Verify GREEN and register the test**

Run: `cd web-control/server && node test/live-camera-streams-smoke.js`

Expected: `PASS Lumos stream selector preserves raw video on overlay failure`.

Add `test:live-camera-streams` to `package.json` and the aggregate `npm test` chain.

- [ ] **Step 5: Commit Task 1**

```bash
git add web-control/web/live-camera-streams.js web-control/server/test/live-camera-streams-smoke.js web-control/server/package.json
git commit -m "feat(web): select Lumos overlay without hiding raw video"
```

### Task 2: Live-first page, desktop layout, and real-browser verification

**Files:**
- Modify: `web-control/web/camera-test.html`
- Create: `web-control/server/test/live-camera-page-browser-smoke.js`
- Modify: `web-control/server/test/lumos-proxy-smoke.js`
- Modify: `tests/web/test_web_ui_security.py`
- Modify: `web-control/server/package.json`

**Interfaces:**
- Consumes: `window.ThirdHandLiveCameraStreams.createLumosStreamSelector()` from Task 1.
- Produces: live-first `/camera-test.html`; button `#lumos-overlay-toggle`; status `#lumos-stream-status`.

- [ ] **Step 1: Write the failing live-browser test**

Serve the production web directory plus controlled endpoints: raw Lumos and D435 return
valid SVG images; overlay returns 503 until the test toggles `overlayReady=true`; status
returns a complete safe snapshot. Open normal `/camera-test.html` in headless Edge and
assert literal outcomes:

```javascript
assert.match(result.lumosSource, /\/camera_lumos$/);
assert.match(result.d435Source, /\/camera$/);
assert.equal(result.lumosVisibleInViewport, true);
assert.equal(result.d435VisibleInViewport, true);
// failed overlay attempt
assert.match(result.lumosSource, /\/camera_lumos$/);
assert.equal(result.overlayStatus, '算法叠加不可用，继续显示原始画面');
// working overlay, then return to raw
assert.match(overlaySource, /\/camera_lumos_vision/);
assert.match(returnedRawSource, /\/camera_lumos$/);
```

- [ ] **Step 2: Run and verify RED**

Run: `cd web-control/server && node test/live-camera-page-browser-smoke.js`

Expected: FAIL because the current page defaults to `/camera_lumos_vision`, lacks the
toggle, and stacks D435 below the first viewport.

- [ ] **Step 3: Implement live-first page behavior**

Set Lumos `data-stream="/camera_lumos"` and `data-overlay-stream="/camera_lumos_vision"`;
keep D435 `data-stream="/camera"`. Load `live-camera-streams.js`. In live mode create the
selector with a 2500 ms timeout and wire the overlay button/status. Hide the control in
demo mode. Change desktop camera grid to two columns with 16:9 feeds and stack only under
900 px. Preserve the existing renderer and ID-only command objects exactly.

- [ ] **Step 4: Update route/security contracts and verify all browser modes**

Update static route contracts to expect raw defaults and deferred `src`. Register
`test:live-camera-page-browser`. Run:

```bash
cd web-control/server
node test/live-camera-page-browser-smoke.js
ACTIVE_VIEW_DEMO_TEST_PORT=43330 ACTIVE_VIEW_DEMO_DEBUG_PORT=49438 node test/active-view-demo-browser-smoke.js
LUMOS_TEST_PORT=43310 VOICE_TEST_PORT=43311 EDGE_DEBUG_PORT=49437 node test/browser-smoke.js
```

Expected: live raw streams are above the fold, overlay failure/success paths pass, demo
has zero network/control transport, and the existing browser suite exits zero.

- [ ] **Step 5: Verify against local cameras and commit Task 2**

Open `http://127.0.0.1:3100/camera-test.html` in headless Edge, capture
`/tmp/thirdhand-live-camera-test.png`, and visually confirm both panels contain real image
content. Then run the full Python and Node suites and commit:

```bash
git add web-control/web/camera-test.html web-control/server/test/live-camera-page-browser-smoke.js web-control/server/test/lumos-proxy-smoke.js tests/web/test_web_ui_security.py web-control/server/package.json
git commit -m "fix(web): show real cameras before vision overlays"
```
