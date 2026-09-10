# Active Vision Full Completion Implementation Plan

> **For Codex:** Execute this plan task-by-task with the `superpowers:executing-plans` and `superpowers:test-driven-development` workflows. Do not enable physical motion merely because software tests pass.

**Goal:** Deliver a modular, evidence-gated dual-camera workflow in which Lumos finds and tracks a tabletop object, the robot may move through validated observation poses to bring it into the D435 central depth region, D435 produces a stable 3D grasp preview, and a separate authorized controller can execute a correlated grasp sequence.

**Architecture:** Keep pure geometry and perception independent from robot transport. Exchange immutable typed records between identity, active-view, grasp-preview, authorization, and execution modules. Browser commands carry only server-issued IDs; calibration matrices, robot joints, grasp coordinates, and safety decisions remain server-owned. The commissioning web page is a presentation/client layer over those contracts and does not implement algorithms.

**Technology:** Python 3.11, NumPy, OpenCV, pytest; Node.js CommonJS, WebSocket, built-in node:test; existing RTMDet/DINO/REMIND adapters; existing StarTouch bridge and web-control server.

---

## Non-negotiable boundaries

- `web-control/server/vision/`: pure, deterministic vision/geometry/state modules. No sockets, robot commands, or environment-variable reads.
- `web-control/server/vision_models/`: camera/model adapters and composition only. No robot commands.
- `web-control/server/*.js`: authorization, orchestration, transport, audit, and sanitization. No OpenCV/NumPy geometry.
- `web-control/web/`: rendering and ID-only user actions. No coordinates, joint vectors, or client-authored safety flags.
- Active-view movement and grasp movement use different authorization artifacts, controllers, timeouts, and audit events.
- A grasp preview is never an execution command. A target can remain visually selected while grasp execution is locked.
- Calibration evidence, observation-pose evidence, model acceptance, depth stability, workspace checks, and operator acknowledgement fail closed.

## Completion gates

1. All Python and Node unit/integration tests pass.
2. Runtime loads `camera.json` and `table.json` from the validated foundation without manual environment edits.
3. The live page shows both camera streams and requested overlays in no-motion mode.
4. Observation-pose catalog exists and passes strict evidence validation before active-view execution can unlock.
5. Grasp preview exposes contour, persistent ID, base-frame 3D point, target state, grasp point, and allowed/blocked reasons.
6. Every robot and gripper step is correlated to a session ID and request ID; stale or mismatched completions cannot advance the sequence.
7. Physical active-view/grasp execution remains disabled until the operator confirms E-stop access, clear workspace, correct target, and low-speed test conditions.

---

### Task 1: Bind validated foundation evidence into runtime preflight

**Files:**
- Modify: `web-control/server/config.js`
- Modify: `web-control/server/vision_models/camera_bridge.py`
- Modify: `scripts/vision/start_dual_camera_online.sh`
- Create: `web-control/server/vision-runtime-preflight.js`
- Test: `web-control/test/vision-runtime-preflight.test.js`
- Test: `tests/vision_deployment/test_camera_bridge.py`

**Step 1: Write failing Node tests**

Cover repository-relative default resolution for:

- `data/calibration/active-view-foundation/camera.json`
- `data/calibration/active-view-foundation/table.json`
- `data/calibration/active-view-foundation/observation-catalog.json`

Assert that camera/table absence is fatal for online active-view, catalog absence locks motion but still permits live perception, and explicit environment overrides win over defaults.

**Step 2: Run the focused Node test and verify failure**

Run: `node --test web-control/test/vision-runtime-preflight.test.js`

**Step 3: Implement the preflight module and configuration defaults**

Return a frozen result with `perceptionReady`, `activeViewReady`, `graspReady`, `evidencePaths`, and stable blocker codes. Do not read calibration JSON in multiple server modules; centralize path/existence checks here and let the Python evidence loader validate contents.

**Step 4: Write failing Python bridge tests**

Assert that validated foundation evidence replaces placeholder table/camera values, missing catalog produces a controlled `active_view_catalog_unavailable` condition, and malformed evidence never falls back to placeholder execution geometry.

**Step 5: Implement bridge behavior and safe launcher defaults**

The launcher must default to real camera/model input with `VISION_ACTIVE_VIEW_EXECUTION_ENABLED=0` and `VISION_GRASP_EXECUTION_ENABLED=0`. Add an explicit `--enable-motion`/environment gate only for the later physical acceptance step.

**Step 6: Verify**

Run:

```bash
node --test web-control/test/vision-runtime-preflight.test.js
/home/nieqingcao/miniconda3/envs/thirdhand-remind3d/bin/python -m pytest tests/vision_deployment/test_camera_bridge.py -q
```

**Step 7: Commit**

```bash
git add web-control/server/config.js web-control/server/vision-runtime-preflight.js web-control/server/vision_models/camera_bridge.py scripts/vision/start_dual_camera_online.sh web-control/test/vision-runtime-preflight.test.js tests/vision_deployment/test_camera_bridge.py
git commit -m "feat(vision): bind validated foundation evidence"
```

---

### Task 2: Complete observation-pose commissioning without coupling it to motion

**Files:**
- Modify: `web-control/scripts/teach-active-view-pose.js`
- Modify: `scripts/vision/finalize_active_view_catalog.py`
- Create: `web-control/server/observation-catalog-service.js`
- Create: `web-control/test/observation-catalog-service.test.js`
- Modify: `tests/vision_deployment/test_active_view_catalog.py`
- Create: `docs/vision/observation-pose-commissioning.md`

**Step 1: Write failing catalog-service tests**

Assert capture records contain a generated pose ID, timestamp, joint vector, TCP transform, source robot state, and foundation evidence IDs. Reject capture while the robot is moving or status is stale. Accept no browser-supplied joints or transforms.

**Step 2: Verify failure**

Run: `node --test web-control/test/observation-catalog-service.test.js`

**Step 3: Implement read-only pose capture service**

The service may read robot status and persist a capture manifest; it must not send robot commands. Make persistence atomic and append-only. Expose sanitized summaries for the webpage.

**Step 4: Write failing finalization tests**

Cover duplicate IDs, foundation mismatch, invalid joint limits, insufficient table coverage, missing start-pose/path-validation records, speed scale above `0.05`, operator acknowledgement false, and stale validation timestamps.

**Step 5: Implement strict finalization and documentation**

Produce `data/calibration/active-view-foundation/observation-catalog.json` only when every selected pose has validated coverage and path evidence. Document the exact low-speed, E-stop, clear-workspace procedure; keep it as the only manual phase in this task.

**Step 6: Verify**

Run:

```bash
node --test web-control/test/observation-catalog-service.test.js
/home/nieqingcao/miniconda3/envs/thirdhand-remind3d/bin/python -m pytest tests/vision_deployment/test_active_view_catalog.py -q
```

**Step 7: Commit**

```bash
git add web-control/scripts/teach-active-view-pose.js web-control/server/observation-catalog-service.js web-control/test/observation-catalog-service.test.js scripts/vision/finalize_active_view_catalog.py tests/vision_deployment/test_active_view_catalog.py docs/vision/observation-pose-commissioning.md
git commit -m "feat(vision): add observation pose commissioning"
```

---

### Task 3: Add a pure top-down grasp-preview algorithm

**Files:**
- Create: `web-control/server/vision/grasp_geometry.py`
- Create: `tests/vision_deployment/test_grasp_geometry.py`
- Modify: `web-control/server/vision/active_view_types.py`

**Step 1: Write failing pure-geometry tests**

Use synthetic registered point clouds and masks to cover:

- robust interior grasp pixel selection instead of bounding-box center;
- base-frame point and object height derived through calibrated transforms/table plane;
- planar PCA yaw with deterministic axis sign;
- minimum point count, depth MAD, temporal stability, gripper-width, table-clearance, central-D435-ROI, and workspace rejection;
- immutable output with stable blocker codes;
- no imports from camera, socket, robot, or web modules.

**Step 2: Verify failure**

Run: `/home/nieqingcao/miniconda3/envs/thirdhand-remind3d/bin/python -m pytest tests/vision_deployment/test_grasp_geometry.py -q`

**Step 3: Implement typed records and planner**

Add `TopDownGraspPreview` and `GraspPreviewEvidence`. Compute preview point, yaw, estimated width, pregrasp/grasp/retreat points, uncertainty, D435 pixel, Lumos pixel, and `allowed`/`blockers`. Keep gripper/TCP approach policy injectable through a frozen config.

**Step 4: Add temporal accumulator tests and implementation**

Require five stable samples, median deviation no more than `10 mm`, and per-axis MAD no more than `5 mm`. Bind samples to persistent target ID plus active-view session/evidence ID; reset on identity or evidence change.

**Step 5: Verify**

Run: `/home/nieqingcao/miniconda3/envs/thirdhand-remind3d/bin/python -m pytest tests/vision_deployment/test_grasp_geometry.py -q`

**Step 6: Commit**

```bash
git add web-control/server/vision/grasp_geometry.py web-control/server/vision/active_view_types.py tests/vision_deployment/test_grasp_geometry.py
git commit -m "feat(vision): add calibrated top down grasp previews"
```

---

### Task 4: Integrate preview into perception events and overlays

**Files:**
- Modify: `web-control/server/vision_models/online.py`
- Modify: `web-control/server/vision_models/visualization.py`
- Modify: `web-control/server/vision_models/active_view_online.py`
- Modify: `web-control/server/vision_models/camera_bridge.py`
- Modify: `web-control/server/vision-status.js`
- Test: `tests/vision_deployment/test_online_perception.py`
- Test: `tests/vision_deployment/test_visualization.py`
- Test: `web-control/test/vision-status.test.js`

**Step 1: Write failing event-contract tests**

Require each target event to expose a sanitized `grasp_preview` containing preview ID, evidence ID, target ID, frame, 3D point, image point, state, allowed flag, and blockers. Coordinates originate only from Python perception output.

**Step 2: Write failing visualization tests**

Assert overlay includes contour, persistent ID, base-frame XYZ, target/handoff state, grasp crosshair, and allowed/blocked label. Missing preview must render a visible reason rather than a fabricated point.

**Step 3: Implement explicit planner composition**

Inject the grasp-preview planner into the online engine. Pass registered depth/mask/calibration results through a typed boundary. Do not make the visualizer calculate geometry. Keep `robot_execution=false` until Node authorization/execution gates pass.

**Step 4: Implement strict Node sanitization**

Reject malformed preview payloads and preserve fail-closed blockers. Do not flatten untrusted fields into the authorization structure without validation.

**Step 5: Verify**

Run:

```bash
/home/nieqingcao/miniconda3/envs/thirdhand-remind3d/bin/python -m pytest tests/vision_deployment/test_online_perception.py tests/vision_deployment/test_visualization.py -q
node --test web-control/test/vision-status.test.js
```

**Step 6: Commit**

```bash
git add web-control/server/vision_models/online.py web-control/server/vision_models/visualization.py web-control/server/vision_models/active_view_online.py web-control/server/vision_models/camera_bridge.py web-control/server/vision-status.js tests/vision_deployment/test_online_perception.py tests/vision_deployment/test_visualization.py web-control/test/vision-status.test.js
git commit -m "feat(vision): publish grasp previews and overlays"
```

---

### Task 5: Replace inline grasp sequencing with correlated authorization and execution

**Files:**
- Create: `web-control/server/grasp-execution-controller.js`
- Create: `web-control/server/grasp-audit-log.js`
- Modify: `web-control/server/grasp-authorization.js`
- Modify: `web-control/server/startouch_bridge.py`
- Modify: `web-control/server/proxy.js`
- Test: `web-control/test/grasp-authorization.test.js`
- Create: `web-control/test/grasp-execution-controller.test.js`
- Modify: `tests/vision_deployment/test_startouch_bridge.py`

**Step 1: Write failing authorization tests**

Require a short-lived server-issued approval artifact bound to preview ID, target ID, identity epoch, active-view evidence ID, calibration evidence IDs, robot start pose, operator acknowledgement, and expiry. Any mismatch, stale target, blocker, or model/calibration/catalog failure rejects execution.

**Step 2: Write failing controller tests**

Cover hover, descend, close, lift, retreat/home, and release as an explicit finite-state machine. Verify one in-flight step, exact request-ID matching, command-name matching, timeouts, cancellation, robot fault, disconnect, stale completion, and duplicate completion. A mismatched completion must never advance state.

**Step 3: Extend bridge correlation under tests**

Add `request_id` to gripper commands/progress/completion while retaining compatibility for manual non-session use. Test that set-gripper completion echoes the originating request ID.

**Step 4: Implement controller, authorization, and append-only audit**

Move all old `startGrasp`/`advanceGrasp` logic out of `proxy.js`. The proxy should only route validated ID-only commands and bridge events. The execution controller accepts a server-owned preview snapshot and generates robot requests internally.

**Step 5: Verify**

Run:

```bash
node --test web-control/test/grasp-authorization.test.js web-control/test/grasp-execution-controller.test.js
/home/nieqingcao/miniconda3/envs/thirdhand-remind3d/bin/python -m pytest tests/vision_deployment/test_startouch_bridge.py -q
```

**Step 6: Commit**

```bash
git add web-control/server/grasp-execution-controller.js web-control/server/grasp-audit-log.js web-control/server/grasp-authorization.js web-control/server/startouch_bridge.py web-control/server/proxy.js web-control/test/grasp-authorization.test.js web-control/test/grasp-execution-controller.test.js tests/vision_deployment/test_startouch_bridge.py
git commit -m "refactor(control): isolate correlated grasp execution"
```

---

### Task 6: Build the modular active-vision commissioning and test webpage

**Files:**
- Create: `web-control/web/active-vision.html`
- Create: `web-control/web/css/active-vision.css`
- Create: `web-control/web/js/active-vision-client.js`
- Create: `web-control/web/js/active-vision-renderer.js`
- Create: `web-control/web/js/active-vision-actions.js`
- Create: `web-control/server/active-vision-api.js`
- Modify: `web-control/server/proxy.js`
- Create: `web-control/test/active-vision-api.test.js`
- Create: `web-control/test/active-vision-page.test.js`

**Step 1: Write failing API and static-page tests**

Require endpoints/messages for sanitized runtime preflight, calibration evidence, catalog status, model acceptance, Lumos overlay stream, D435/depth status, targets, active-view sessions, grasp preview, execution state, and audit tail. Browser actions may send only target/session/pose/preview/approval IDs.

**Step 2: Verify failure**

Run: `node --test web-control/test/active-vision-api.test.js web-control/test/active-vision-page.test.js`

**Step 3: Implement server API module**

Keep API routing separate from `proxy.js`. Validate all message schemas, apply rate limits to capture/authorization commands, and return stable blocker codes plus Chinese display text.

**Step 4: Implement the page in separate client/render/action modules**

The page must show:

- Lumos live/overlay panel with object contour, ID, XYZ, state, grasp point, grasp permission;
- D435 RGB/depth/central-ROI panel and stable-sample counter;
- selected target and Lumos→D435 handoff state machine;
- calibration, observation catalog, model, camera, robot, and safety gates;
- observation-pose capture/finalization status;
- active-view proposal/approval/execution status;
- grasp preview/approval/execution status;
- audit timeline and explicit no-motion/simulator/real-motion badge.

The renderer consumes state only. The actions module emits ID-only commands only. CSS/UI must remain usable at laptop and narrow split-screen widths.

**Step 5: Verify**

Run: `node --test web-control/test/active-vision-api.test.js web-control/test/active-vision-page.test.js`

**Step 6: Commit**

```bash
git add web-control/web/active-vision.html web-control/web/css/active-vision.css web-control/web/js/active-vision-client.js web-control/web/js/active-vision-renderer.js web-control/web/js/active-vision-actions.js web-control/server/active-vision-api.js web-control/server/proxy.js web-control/test/active-vision-api.test.js web-control/test/active-vision-page.test.js
git commit -m "feat(web): add modular active vision console"
```

---

### Task 7: Add task-checkpoint acceptance and keep it evidence-gated

**Files:**
- Create: `web-control/server/vision/model_acceptance.py`
- Create: `scripts/vision/validate_task_checkpoint.py`
- Create: `tests/vision_deployment/test_model_acceptance.py`
- Modify: `web-control/server/vision_models/online.py`
- Modify: `configs/vision/remind3d.yaml`
- Create: `docs/vision/model-acceptance.md`

**Step 1: Write failing acceptance tests**

Require a signed-by-content evidence record containing model/config hashes, dataset manifest hash, label scope, precision/recall or per-class pass criteria, ID continuity score, timestamp, and failure reasons. A stock COCO checkpoint is not automatically task validated.

**Step 2: Implement offline/live-replay evaluator**

Generate deterministic JSON evidence from captured labeled scenes. Runtime validation must compare current hashes and requested labels to the accepted record. Unsupported/unmeasured classes remain blocked while accepted classes may proceed.

**Step 3: Verify and document**

Run: `/home/nieqingcao/miniconda3/envs/thirdhand-remind3d/bin/python -m pytest tests/vision_deployment/test_model_acceptance.py -q`

Document how to collect/label a small controlled tabletop acceptance set and how rejection affects only execution, not visualization.

**Step 4: Commit**

```bash
git add web-control/server/vision/model_acceptance.py scripts/vision/validate_task_checkpoint.py tests/vision_deployment/test_model_acceptance.py web-control/server/vision_models/online.py configs/vision/remind3d.yaml docs/vision/model-acceptance.md
git commit -m "feat(vision): gate task models with acceptance evidence"
```

---

### Task 8: Full no-motion verification, then controlled physical acceptance

**Files:**
- Create: `scripts/vision/verify_active_vision_stack.sh`
- Create: `tests/vision_deployment/test_active_vision_end_to_end.py`
- Modify: `docs/vision/README.md`

**Step 1: Add a deterministic end-to-end replay test**

Replay a target entering Lumos only, becoming assigned a persistent ID, receiving an observation-pose proposal, transitioning into the D435 central ROI, accumulating five stable depth samples, producing a grasp preview, and remaining execution-locked without approval. Then verify a simulated authorized run completes only on matched command IDs.

**Step 2: Implement one verification entry point**

The script must run focused Python tests, Node tests, evidence preflight, replay integration, live dual-camera no-motion smoke test, WebSocket/page health checks, and a bounded soak test. It must print evidence paths and explicit blockers.

**Step 3: Run full software verification**

Run:

```bash
bash scripts/vision/verify_active_vision_stack.sh
```

Keep robot/CAN movement and grasp disabled. Confirm both real camera frames are fresh and the page displays the required overlays.

**Step 4: Physical active-view acceptance gate**

Proceed only after the operator confirms:

- E-stop is reachable and tested;
- workspace and cable path are clear;
- a soft, non-hazardous test object is the selected target;
- gripper approach area is clear;
- observation pose/path evidence is complete;
- speed scale is at most `0.05`;
- first run uses per-step confirmation and no automatic grasp.

Validate one observation move and return-to-start. Record request IDs, actual-vs-commanded pose, closest clearance observation, camera freshness, D435 central ratio, and depth stability.

**Step 5: Physical grasp acceptance gate**

Only after the active-view move passes, execute one preview-only approach, retreat, then one low-force grasp with per-step confirmation. Verify target identity/evidence remain unchanged and all controller transitions correlate exactly.

**Step 6: Final verification and commit**

Run the complete verification script again, archive sanitized audit/evidence output, update `docs/vision/README.md`, then commit:

```bash
git add scripts/vision/verify_active_vision_stack.sh tests/vision_deployment/test_active_vision_end_to_end.py docs/vision/README.md
git commit -m "test(vision): verify modular active vision stack"
```

---

## Rollback and safety behavior

- Software failures stop the current state machine, revoke approvals, and retain audit data.
- Camera staleness, identity changes, calibration/catalog/model evidence changes, robot faults, and bridge disconnects invalidate the current preview and approval.
- The system never retries physical motion automatically after a timeout or fault.
- No test or webpage action rewrites calibration evidence.
- Observation-pose capture is read-only; finalization writes a new evidence artifact and never mutates robot state.

## Final handoff artifacts

- Validated foundation: `data/calibration/active-view-foundation/camera.json`, `table.json`
- Validated observation poses: `data/calibration/active-view-foundation/observation-catalog.json`
- Model acceptance evidence under `data/vision/model-acceptance/`
- Append-only active-view/grasp audit under configured runtime evidence directory
- Operator/test page: `/active-vision.html`
- One-command verification: `bash scripts/vision/verify_active_vision_stack.sh`
