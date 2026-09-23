# Fisheye-Guided Wrist Depth Acquisition Offline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a deterministic, read-only J4–J6 aiming preview that starts from a fisheye RGB bearing and reports why a bottle cannot yet be moved into valid depth coverage.

**Architecture:** A pure SEUCM adapter converts the 640×480 bottle pixel and depth-ROI center to rays. Full wrist/flange forward kinematics plus the draft mount transform rank bounded joint candidates; without bottle range, the projected pixel is explicitly a rotation-only direction estimate, not a precise landing point. New observations are compared with that estimate rather than used for blind search. A fixture CLI displays the proposed motion and blockers but has no robot transport. A separately reviewed follow-up plan must extend the authenticated robot execution contract before any live joint motion.

**Tech Stack:** Node.js 24 CommonJS, `node:test`, existing URDF-derived Startouch kinematics, current Vision Service observation JSON. No new dependency.

**Spec:** `docs/superpowers/specs/2026-09-21-wrist-active-depth-acquisition-design.md`

## Global Constraints

- Phase 1 is read-only: no WebSocket robot commands, CAN, SDK motion, gripper action, or execution-token creation.
- Only J4–J6 may differ in a proposal; J1–J3 must remain identical.
- 640×480 depth ROI: `(203,149,428,319)`; native SEUCM pixel mapping: `u_native=2*u_stream`, `v_native=2*v_stream+160`.
- Candidate upper bounds: 2° per joint per step, 10° cumulative per wrist joint, 5 mm predicted camera-center displacement per step, 20 mm cumulative.
- Current mount transform is pending physical validation. An offline proposal must never be labeled executable or physically approved.
- Never move through the manual `/ws` route to evade the protected gateway. That gateway currently accepts only `gripper.set` and has no execution token.
- Do not commit or create a branch unless the user explicitly requests it.

## Review Focus

- A pixel outside 640×480 or outside the SEUCM domain returns an explicit invalid-ray result, not a NaN joint target (Task 1 test).
- A non-finite or wrong-length joint vector fails before FK arithmetic (Task 2 test).
- A target ID switch or stale observation produces no candidate (Task 4 test).
- A candidate with predicted camera displacement over 5 mm, even if pixel error improves, is rejected (Task 3 test).
- If every permitted wrist step fails to reduce angular error, report `not_reachable_by_wrist` rather than scanning joints; without target range, label any projected pixel as a rotation-only estimate (Task 3 tests).

---

## File map

- `apps/web/src/active-depth/fisheye.js`: one camera profile, native/stream mapping, SEUCM ray/project functions.
- `apps/web/src/active-depth/flange-pose.js`: reuse the existing URDF-derived origins and axes to compute full flange pose without changing the shared tool-position API.
- `apps/web/src/active-depth/candidate.js`: pure bounded wrist candidate planner and predicted camera displacement.
- `apps/web/src/active-depth/preview.js`: fail-closed assembly of a fresh selected target, model evidence, and candidate.
- `tools/active-depth/preview.js`: fixture-only CLI; it must not import robot-client or network code.
- Matching `tests/node/web/active-depth-*.test.js` files: one focused red/green cycle per component.

### Task 1: SEUCM stream-pixel bearing

**Files:** Create `apps/web/src/active-depth/fisheye.js`; test `tests/node/web/active-depth-fisheye.test.js`.

**Interfaces:** `streamPixelToRay([u,v]) -> {ok, ray?, reason?}` and `rayToStreamPixel([x,y,z]) -> {ok, pixel?, reason?}`. The profile is the checked-in Lumos SEUCM parameters `fx=392.5984802`, `fy=392.4404297`, `cx=637.3952637`, `cy=641.7739868`, `alpha=0.6799842119`, `beta=0.7471178174`, native 1280×1280. Match the Python `SeucmCamera` math in `/home/nieqingcao/th0814/ThirdHand-XVisio-handeye-web/web-control/server/vision/camera_models.py` and the crop in `services/vision/python/thirdhand_va/vision/nearfield_guard.py`.

- [x] **Step 1: Write failing tests.** Use hand-derived center and invalid-domain cases:

```js
const center = streamPixelToRay([637.3952637 / 2, (641.7739868 - 160) / 2]);
assert.equal(center.ok, true);
assert.ok(Math.abs(center.ray[0]) < 1e-10);
assert.ok(Math.abs(center.ray[1]) < 1e-10);
assert.ok(Math.abs(center.ray[2] - 1) < 1e-10);
assert.deepEqual(streamPixelToRay([-1, 240]), { ok: false, reason: 'pixel_out_of_frame' });
assert.equal(rayToStreamPixel(center.ray).ok, true);
```

- [x] **Step 2: Run red.** `node --test tests/node/web/active-depth-fisheye.test.js`; expect missing module failure.
- [x] **Step 3: Implement.** Convert stream to native pixels; apply the SEUCM inverse `mx=(u-cx)/fx`, `my=(v-cy)/fy`, `r2=mx²+my²`, `mz=(1-beta*alpha²*r2)/(alpha*sqrt(1-(2*alpha-1)*beta*r2)+1-alpha)`, normalize `[mx,my,mz]`; reject invalid square-root/domain and non-finite values. Project with `distance=sqrt(beta*(x*x+y*y)+z*z)`, `denominator=alpha*distance+(1-alpha)*z`, `u=fx*x/denominator+cx`, `v=fy*y/denominator+cy`, then invert the crop mapping. Require positive denominator and a native pixel inside 1280×1280.
- [x] **Step 4: Run green and a parity sample.** Compare rays and round-trip pixels against the current Python camera model for center, four ROI corners, and a bottle pixel near `(562,327)`; require finite results and <0.25 px round-trip error. Run `node --test tests/node/web/active-depth-fisheye.test.js`.

### Task 2: Full flange pose for predicted camera motion

**Files:** Create `apps/web/src/active-depth/flange-pose.js`; test `tests/node/web/active-depth-fk.test.js`.

**Interfaces:** `forwardKinematicsFlangePose(jointsDeg) -> {positionM: [x,y,z], rotation: 3x3}`. Preserve `forwardKinematicsPosition(jointsDeg)` and its outputs. `cameraPose(flangePose, tFlangeCamera)` is owned by Task 3, not this module.

- [x] **Step 1: Write failing tests.** For six zero angles, verify the rotation is identity and the flange translation equals the sum of the six checked-in joint origins; reject `[0,0,0]`:

```js
const zero = forwardKinematicsFlangePose([0, 0, 0, 0, 0, 0]);
assert.deepEqual(zero.rotation, [[1,0,0],[0,1,0],[0,0,1]]);
assert.ok(Math.abs(zero.positionM[0] - 0.1275) < 1e-12);
assert.throws(() => forwardKinematicsFlangePose([0,0,0]), /six finite/);
```

- [x] **Step 2: Run red.** `node --test tests/node/web/active-depth-fk.test.js`; expect missing module/export failure.
- [x] **Step 3: Implement.** Import existing joint origins and axes into a focused full-pose module. Preserve the shared position function unchanged; test sampled full poses plus the existing tool offset against that function, without altering any joint convention.
- [x] **Step 4: Run green.** Run `node --test tests/node/web/active-depth-fk.test.js tests/node/web/arm-model-preview.test.js` and the full `npm run test:node` suite, which includes `language-chain.test.js`. Verify sampled poses against the existing URDF-derived FK; direct SDK/hardware pose validation remains a live-path prerequisite.

### Task 3: Deterministic bounded wrist proposal

**Files:** Create `apps/web/src/active-depth/candidate.js`; test `tests/node/web/active-depth-candidate.test.js`.

**Interfaces:** `planWristStep({targetPixel, jointsDeg, startJointsDeg, tFlangeCamera, poseForJoints, limits}) -> {ok, targetJointsDeg?, predictedPixel?, pixelEstimateKind?, angularErrorRad?, cameraShiftM?, reason?}`. `poseForJoints` defaults to Task 2's FK, but can be injected for deterministic tests. `pixelEstimateKind` is always `'rotation_only_bearing'` until valid target range is available; no exact landing-point claim is made. `limits` contains `jointLimitsDeg` (six `[min,max]` pairs), `maxStepDeg=2`, `maxCumulativeJointDeg=10`, `maxCameraStepM=0.005`, `maxCameraCumulativeM=0.02`. The caller supplies a read-only 4×4 mount transform; unapproved mount evidence is handled by Task 4.

- [x] **Step 1: Write failing tests.** Use an injected analytic pose model with identity flange rotation at zero and a Y-axis rotation of `jointsDeg[4]` at J5. Choose an off-center pixel and assert the signed step reduces angular error, J1–J3 stay exactly unchanged, `cameraShiftM <= 0.005`, and `pixelEstimateKind === 'rotation_only_bearing'`. In separate fixtures, add a 6 mm camera-origin jump for every nonzero wrist change and assert `camera_step_limit`; return an unchanged pose for all joints and assert `not_reachable_by_wrist`.

```js
const result = planWristStep({ targetPixel: [562, 327], jointsDeg: [0,0,0,0,0,0],
  startJointsDeg: [0,0,0,0,0,0], tFlangeCamera: identity4,
  poseForJoints: joints => ({ positionM: [0,0,0], rotation: yRotation(joints[4]) }),
  limits: testLimits });
assert.equal(result.ok, true);
assert.deepEqual(result.targetJointsDeg.slice(0, 3), [0,0,0]);
assert.equal(result.pixelEstimateKind, 'rotation_only_bearing');
assert.ok(result.angularErrorRad < initialAngularErrorRad);
```
- [x] **Step 2: Run red.** `node --test tests/node/web/active-depth-candidate.test.js`; expect planner export missing or candidate assertions to fail.
- [x] **Step 3: Implement.** Derive target and ROI-center rays with Task 1. Enumerate deterministic signed J4/J5/J6 candidates at 2°, 1°, 0.5°, and 0.25° within the configured bounds. Compose `R_base_camera=R_base_flange*R_flange_camera` and `p_base_camera=p_base_flange+R_base_flange*p_flange_camera`; rotate the current target bearing through base into each proposed camera pose, without pretending a range-free ray compensates camera translation. Reject joint-limit, per-step/cumulative rotation, and per-step/cumulative camera-shift violations before ranking. Choose the lowest angular-error strict improvement with fixed J4/J5/J6 tie order; never add exploratory motion for an unrankable direction. Return `pixelEstimateKind:'rotation_only_bearing'` on a proposal.
- [x] **Step 4: Run green.** Run candidate tests and a recorded fixture that starts with pixel `(562,327)`; output a bounded proposal or a specific blocker, never a motion command.

### Task 4: Fail-closed offline preview and correction evidence

**Files:** Create `apps/web/src/active-depth/preview.js`, `tools/active-depth/preview.js`; test `tests/node/web/active-depth-preview.test.js`.

**Interfaces:** `buildActiveDepthPreview({observation, robotSnapshot, mount, previousStep, nowMs}) -> {mode:'offline', executable:false, targetId, targetPixel, roi, proposal, blockers}`. `observation` uses Vision Service fields `frameId`, `observedAtMs`, `selectedStableId`, and `targets[*].centroid_xy`; `robotSnapshot` includes `jointsDeg`, `observedAtMs`, `stateName`. `mount` includes `matrix_4x4`, `camera_mount_id`, `registration_id`, `physical_validation.status`. `previousStep` includes `targetId`, `predictedPixel`, `beforePixel`, `completedAtMs`. A fixture CLI accepts `--fixture <json>` and `--target-id 1..5`, prints the result, and exits 2 for blockers. It must not accept `--execute`.

- [x] **Step 1: Write failing tests.** Use literal fixtures with matching and switched stable IDs, stale timestamps (>300 ms), missing joint state, and a prior step whose observed pixel moved away from the predicted direction. Assert the latter yields `response_inconsistent`, no next proposal, and `executable:false`. Assert the CLI rejects `--execute` without importing a robot adapter.

```js
const result = buildActiveDepthPreview({ observation: {
  frameId: 42, observedAtMs: 1000, selectedStableId: 2,
  targets: [{ stable_id: 2, centroid_xy: [570, 327] }],
}, robotSnapshot: { jointsDeg: [0,0,0,0,0,0], observedAtMs: 1000, stateName: 'IDLE' },
mount: pendingMount, previousStep: { targetId: 2, beforePixel: [562,327],
  predictedPixel: [550,327], completedAtMs: 900 }, nowMs: 1100 });
assert.equal(result.executable, false);
assert.ok(result.blockers.includes('response_inconsistent'));
assert.equal(result.proposal, null);
```
- [x] **Step 2: Run red.** `node --test tests/node/web/active-depth-preview.test.js`; expect missing preview/CLI behavior.
- [x] **Step 3: Implement.** Reject `nowMs-observedAtMs>300` for either vision or robot, require `stateName==='IDLE'`, match the selected stable ID to exactly one target, and validate camera/registration IDs against `mount` when present. Require six finite joint values and a 4×4 finite homogeneous matrix. For a pending mount, show an illustrative candidate but include `mount_unverified`; always set `executable:false`. Compare `(observed-before)·(predicted-before)` and stop with `response_inconsistent` when it is nonpositive; also reject target switch or no progress. The CLI calls only `readFileSync`, `JSON.parse`, and `buildActiveDepthPreview`; unknown flags, especially `--execute`, exit 2 before any preview.
- [x] **Step 4: Run green and full relevant suite.** Run new tests, `node --test tests/node/web/*active-depth*.test.js`, and `npm run test:node` from the project root. Report existing unrelated failures separately; do not repair them as part of this feature.

## Handoff to live motion

This plan ends with a deterministic offline preview. A live-motion plan is required before sending J4–J6 commands: the current authenticated `thirdhand.execution-primitive.v1` contract and `services/robot/src/robot-controller.js` implement `gripper.set` only. That follow-up must define a new bounded joint primitive, authorization/evidence binding, correlated completion, disconnect/stop semantics, and operator-confirmed one-step control; it must never reuse the unauthenticated manual route. Live commissioning remains blocked until the mount/FK model and physical area clearance are validated.
