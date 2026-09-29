# Dummy Person Follow Production Implementation Plan

> **For implementation:** Use `superpowers:executing-plans` in the current session, follow `superpowers:test-driven-development` task by task, and run `superpowers:verification-before-completion` before claiming any milestone complete.

**Goal:** Turn the current Dummy person-follow prototype into a modular, observable, production-shaped pipeline that uses the Lumos fisheye stream, stable session identity, locally calibrated visual control, and a fail-closed `31023 -> 3000` motion path without bypassing the official robot service.

**Architecture:** The vision service on `3100` owns image acquisition, SEUCM rectification, person detection, tracking/ReID, identity state, and observation provenance. Dummy consumes observations, owns the follow-session state machine and visual-Jacobian controller, and emits bounded motion proposals. The debug gateway on `31023` owns lease validation, proposal freshness, safety filtering, correlation, audit logging, and forwarding to the robot service on `3000`; only `3000` may call the vendor SDK/CAN path. Execution is stop-look-move-verify, with hold/stop as the default on uncertainty.

**Tech Stack:** Python 3, NumPy, OpenCV, ONNX Runtime or the repository-supported RTMDet runtime, BoT-SORT, OSNet ReID, `websockets`, Node.js 24, `ws`, JSON Schema, JSON Lines logging, `pytest`, Node test runner.

**Design reference:** `docs/superpowers/specs/2026-09-29-dummy-person-follow-production-design.md`

**Repository safety:** The deployed repository already contains uncommitted follow/gateway experiments. Adopt those files behind characterization tests. Do not reset, delete, or bundle unrelated user changes. Each commit below must stage only the named files.

---

## Task 1: Freeze the Existing Prototype as Characterization Tests

**Files:**
- Modify: `apps/dummy/tests/test_1023_gateway.py`
- Modify: `apps/dummy/tests/test_dume_touch_r1_follow_control.py`
- Modify: `apps/dummy/tests/test_person_lock_tracker.py`
- Create: `apps/dummy/tests/fixtures/person_follow_observations.jsonl`
- Create: `apps/dummy/tests/test_person_follow_existing_contract.py`

**Step 1: Write failing characterization tests**

Add tests that pin the currently relied-on behavior without endorsing the old architecture:

- `31023` accepts only service commands and bounded `move_joint`/`servo` commands.
- force, raw CAN, Cartesian bypass, malformed arrays, NaN/Inf, and unknown commands fail closed.
- the existing tracker emits target/lost observations with timestamps.
- the existing controller never changes more than the configured per-step bound.
- fixture replay is deterministic.

**Step 2: Run the tests and record the failures**

Run:

```bash
local/runtimes/python/bin/python -m pytest apps/dummy/tests/test_1023_gateway.py apps/dummy/tests/test_dume_touch_r1_follow_control.py apps/dummy/tests/test_person_lock_tracker.py apps/dummy/tests/test_person_follow_existing_contract.py -q
```

Expected: FAIL on malformed numeric payloads and missing stable observation fields.

**Step 3: Make only the minimum compatibility changes**

Patch the existing modules just enough to make the characterization boundary explicit. Do not yet add ReID or a new controller.

**Step 4: Re-run the focused suite**

Expected: PASS.

**Step 5: Commit**

```bash
git add apps/dummy/tests/test_1023_gateway.py apps/dummy/tests/test_dume_touch_r1_follow_control.py apps/dummy/tests/test_person_lock_tracker.py apps/dummy/tests/fixtures/person_follow_observations.jsonl apps/dummy/tests/test_person_follow_existing_contract.py apps/dummy/src/dummy/gateway_1023.py
git commit -m "test: characterize existing person follow prototype"
```

## Task 2: Add Shared Contracts and Structured JSONL Logging

**Files:**
- Create: `services/vision/python/person_follow/__init__.py`
- Create: `services/vision/python/person_follow/contracts.py`
- Create: `services/vision/python/person_follow/logging.py`
- Create: `apps/dummy/src/dummy/person_follow/__init__.py`
- Create: `apps/dummy/src/dummy/person_follow/contracts.py`
- Create: `apps/dummy/src/dummy/person_follow/logging.py`
- Create: `apps/dummy/tests/test_person_follow_contracts.py`
- Create: `apps/dummy/tests/test_person_follow_logging.py`

**Step 1: Write failing contract and logging tests**

Test exact schema validation for `VisionObservation`, `MotionProposal`, `GatewayDecision`, and `VerificationResult`. Require these log fields on every event:

`timestamp_utc`, `monotonic_ns`, `level`, `component`, `event`, `run_id`, `session_id`, `frame_id`, `identity_id`, `proposal_id`, `request_id`, `state_before`, `state_after`, `reason_code`, `latency_ms`.

Test that absent context is represented by `null`, not by omitted keys, and that no frame image or embedding is logged by default.

**Step 2: Run tests to verify RED**

```bash
local/runtimes/python/bin/python -m pytest apps/dummy/tests/test_person_follow_contracts.py apps/dummy/tests/test_person_follow_logging.py -q
```

Expected: FAIL because modules do not exist.

**Step 3: Implement immutable dataclasses and one JSONL emitter**

Keep validation pure and dependency-light. Provide stable `reason_code` enums and correlation IDs. Mirror the wire contract between vision and Dummy, but keep each service's logging adapter local.

**Step 4: Run tests to verify GREEN**

Expected: PASS.

**Step 5: Commit**

```bash
git add services/vision/python/person_follow apps/dummy/src/dummy/person_follow apps/dummy/tests/test_person_follow_contracts.py apps/dummy/tests/test_person_follow_logging.py
git commit -m "feat: add person follow contracts and structured logs"
```

## Task 3: Implement SEUCM Virtual Pinhole Rectification

**Files:**
- Create: `services/vision/python/person_follow/camera_view.py`
- Create: `tests/python/vision/test_person_follow_camera_view.py`
- Create: `services/vision/config/person_follow.camera.example.json`

**Step 1: Write failing geometry tests**

Use synthetic rays and a checkerboard fixture to test:

- deterministic SEUCM-to-pinhole maps;
- configured ROI and output dimensions;
- optical-center consistency;
- calibration hash changes when parameters change;
- invalid or missing calibration fails closed.

**Step 2: Run tests to verify RED**

```bash
local/runtimes/python/bin/python -m pytest tests/python/vision/test_person_follow_camera_view.py -q
```

**Step 3: Implement rectification map generation and cached remap**

The module accepts calibrated intrinsics/SEUCM parameters and emits a `camera_view_id` plus `calibration_hash` for provenance. It must not invent camera parameters.

**Step 4: Verify GREEN and save a deterministic preview artifact**

Run the focused test and a non-live fixture render. Do not connect to the robot.

**Step 5: Commit**

```bash
git add services/vision/python/person_follow/camera_view.py services/vision/config/person_follow.camera.example.json tests/python/vision/test_person_follow_camera_view.py
git commit -m "feat: add calibrated fisheye virtual camera view"
```

## Task 4: Add RTMDet-Tiny Person Detection Adapter

**Files:**
- Create: `services/vision/python/person_follow/detector.py`
- Create: `tests/python/vision/test_person_follow_detector.py`
- Create: `tests/fixtures/vision/person_scene.jpg`
- Modify: `services/vision/requirements.txt`

**Step 1: Write failing adapter tests**

Test normalized detection output, person-class filtering, score/NMS thresholds, empty frames, model-load errors, and provenance fields (`model_id`, `model_sha256`, `inference_ms`). Use a fake backend for deterministic unit tests.

**Step 2: Verify RED**

```bash
local/runtimes/python/bin/python -m pytest tests/python/vision/test_person_follow_detector.py -q
```

**Step 3: Implement backend-neutral detector interface**

Prefer ONNX Runtime when a compatible RTMDet-tiny export is available. Keep model discovery explicit and return `MODEL_UNAVAILABLE` rather than silently falling back to the old detector.

**Step 4: Verify GREEN, then run one local model smoke test if weights exist**

The smoke test may be skipped with an explicit reason when weights are not installed; unit tests must still pass.

**Step 5: Commit**

```bash
git add services/vision/python/person_follow/detector.py services/vision/requirements.txt tests/python/vision/test_person_follow_detector.py tests/fixtures/vision/person_scene.jpg
git commit -m "feat: add RTMDet person detector adapter"
```

## Task 5: Add BoT-SORT Tracking and OSNet Session Identity

**Files:**
- Create: `services/vision/python/person_follow/tracker.py`
- Create: `services/vision/python/person_follow/reid.py`
- Create: `services/vision/python/person_follow/identity.py`
- Create: `tests/python/vision/test_person_follow_tracker.py`
- Create: `tests/python/vision/test_person_follow_identity.py`

**Step 1: Write failing sequence tests**

Cover stable track IDs across short occlusion, crossing people, target disappearance, re-entry, wrong-person rejection, ambiguity, ReID timeout, and a new session invalidating old identity state.

**Step 2: Verify RED**

```bash
local/runtimes/python/bin/python -m pytest tests/python/vision/test_person_follow_tracker.py tests/python/vision/test_person_follow_identity.py -q
```

**Step 3: Implement adapters and the identity state machine**

States: `UNBOUND`, `ACQUIRING`, `LOCKED`, `AMBIGUOUS`, `LOST`, `REACQUIRING`, `STOPPED`. Detection geometry may propose candidates; only session identity can authorize the tracked subject.

**Step 4: Verify GREEN and fixture replay determinism**

Expected: the same ordered observations produce identical identity transitions and reason codes.

**Step 5: Commit**

```bash
git add services/vision/python/person_follow/tracker.py services/vision/python/person_follow/reid.py services/vision/python/person_follow/identity.py tests/python/vision/test_person_follow_tracker.py tests/python/vision/test_person_follow_identity.py
git commit -m "feat: add tracked session identity for person follow"
```

## Task 6: Assemble the Vision Pipeline and Expose It on Port 3100

**Files:**
- Create: `services/vision/python/person_follow/pipeline.py`
- Create: `services/vision/python/person_follow/worker.py`
- Modify: `services/vision/src/camera-process.js`
- Modify: `services/vision/src/server.js`
- Modify: `services/vision/src/config.js`
- Create: `tests/python/vision/test_person_follow_pipeline.py`
- Modify: `tests/node/vision_service/camera-process.test.js`
- Modify: `tests/node/vision_service/server.test.js`

**Step 1: Write failing pipeline/API tests**

Require `/api/vision/person-follow/status`, session start/stop, and an observation stream carrying schema version, frame timestamp, camera view/calibration IDs, detector/tracker/ReID provenance, target box/center, confidence, identity state, and latency.

**Step 2: Verify RED**

```bash
local/runtimes/python/bin/python -m pytest tests/python/vision/test_person_follow_pipeline.py -q
node --test tests/node/vision_service/camera-process.test.js tests/node/vision_service/server.test.js
```

**Step 3: Implement worker supervision and API integration**

The existing `3100` health/status endpoints remain compatible. Worker exit, stale frames, model failure, or schema mismatch must publish an unhealthy state and stop observations.

**Step 4: Verify GREEN and live read-only camera smoke test**

The live smoke test may read Lumos frames and logs only; no robot commands.

**Step 5: Commit**

```bash
git add services/vision/python/person_follow services/vision/src tests/python/vision/test_person_follow_pipeline.py tests/node/vision_service
git commit -m "feat: serve identity-aware person observations on 3100"
```

## Task 7: Implement Follow Session Ownership and State Machine

**Files:**
- Create: `apps/dummy/src/dummy/person_follow/session.py`
- Create: `apps/dummy/tests/test_person_follow_session.py`
- Modify: `apps/dummy/src/dummy/director.py`

**Step 1: Write failing session tests**

Cover one active owner, lease expiry, explicit stop, stale observation, lost/ambiguous identity, reconnect, session replacement, and emergency stop. Required states: `IDLE`, `ACQUIRING`, `LOCKED`, `HOLDING`, `MOVING`, `VERIFYING`, `LOST`, `STOPPING`, `STOPPED`, `FAULT`.

**Step 2: Verify RED**

```bash
local/runtimes/python/bin/python -m pytest apps/dummy/tests/test_person_follow_session.py -q
```

**Step 3: Implement deterministic state transitions**

Every transition emits a structured log with `state_before`, `state_after`, and `reason_code`. No state except `LOCKED`/`VERIFYING` may authorize a proposal.

**Step 4: Verify GREEN**

**Step 5: Commit**

```bash
git add apps/dummy/src/dummy/person_follow/session.py apps/dummy/src/dummy/director.py apps/dummy/tests/test_person_follow_session.py
git commit -m "feat: add fail-closed person follow session state machine"
```

## Task 8: Replace Pixel Gain with a Measured Local Visual Jacobian

**Files:**
- Create: `apps/dummy/src/dummy/person_follow/jacobian.py`
- Create: `apps/dummy/src/dummy/person_follow/controller.py`
- Create: `apps/dummy/src/dummy/person_follow/calibration.py`
- Create: `apps/dummy/tests/test_person_follow_jacobian.py`
- Create: `apps/dummy/tests/test_person_follow_controller.py`
- Create: `apps/dummy/configs/person_follow_calibration.example.yaml`

**Step 1: Write failing numerical tests**

Use synthetic calibration samples with a known Jacobian to test least-squares estimation, conditioning checks, calibration hash, damped pseudoinverse, deadband, per-axis bounds, joint limits, saturation, and refusal to act on stale/mismatched calibration.

**Step 2: Verify RED**

```bash
local/runtimes/python/bin/python -m pytest apps/dummy/tests/test_person_follow_jacobian.py apps/dummy/tests/test_person_follow_controller.py -q
```

**Step 3: Implement calibration and controller**

Compute `delta_q = -lambda * J_damped_pinv * e`, then apply deadband, joint selection, velocity/step bounds, and safety envelopes. Keep the old proportional controller only as an explicitly disabled compatibility adapter; production mode must refuse to start without valid measured calibration.

**Step 4: Verify GREEN**

**Step 5: Commit**

```bash
git add apps/dummy/src/dummy/person_follow apps/dummy/tests/test_person_follow_jacobian.py apps/dummy/tests/test_person_follow_controller.py apps/dummy/configs/person_follow_calibration.example.yaml
git commit -m "feat: add calibrated local visual Jacobian controller"
```

## Task 9: Introduce Typed Motion Proposals and Post-Move Verification

**Files:**
- Create: `apps/dummy/src/dummy/person_follow/proposal.py`
- Create: `apps/dummy/src/dummy/person_follow/verifier.py`
- Create: `apps/dummy/tests/test_person_follow_proposal.py`
- Create: `apps/dummy/tests/test_person_follow_verifier.py`
- Modify: `apps/dummy/src/dummy/dume_touch_r1_follow.py`

**Step 1: Write failing proposal/verifier tests**

Require session/identity/calibration hashes, source observation timestamp, expiry, expected error reduction, bounded joint delta, and unique proposal ID. Verification must accept only fresh same-identity observations and detect no-progress, reversed progress, oscillation, target loss, and timeout.

**Step 2: Verify RED**

```bash
local/runtimes/python/bin/python -m pytest apps/dummy/tests/test_person_follow_proposal.py apps/dummy/tests/test_person_follow_verifier.py -q
```

**Step 3: Implement stop-look-move-verify primitives**

One proposal authorizes one bounded move. No streaming burst is allowed before verification completes.

**Step 4: Verify GREEN and update old follow tests**

Update `test_dume_touch_r1_follow_control.py` so it asserts typed proposals instead of raw pixel-gain joint commands.

**Step 5: Commit**

```bash
git add apps/dummy/src/dummy/person_follow apps/dummy/src/dummy/dume_touch_r1_follow.py apps/dummy/tests/test_person_follow_proposal.py apps/dummy/tests/test_person_follow_verifier.py apps/dummy/tests/test_dume_touch_r1_follow_control.py
git commit -m "feat: add bounded proposals and visual verification"
```

## Task 10: Refactor 31023 into a Lease-Bound Safety Gateway to 3000

**Files:**
- Create: `apps/dummy/src/dummy/gateway/protocol.py`
- Create: `apps/dummy/src/dummy/gateway/ownership.py`
- Create: `apps/dummy/src/dummy/gateway/policy.py`
- Create: `apps/dummy/src/dummy/gateway/robot_3000.py`
- Create: `apps/dummy/src/dummy/gateway/audit.py`
- Create: `apps/dummy/src/dummy/gateway/server.py`
- Modify: `apps/dummy/apps/run_1023_gateway.py`
- Modify: `apps/dummy/src/dummy/gateway_1023.py`
- Create: `apps/dummy/tests/test_gateway_protocol.py`
- Create: `apps/dummy/tests/test_gateway_ownership.py`
- Create: `apps/dummy/tests/test_gateway_robot_3000.py`
- Modify: `apps/dummy/tests/test_1023_gateway.py`

**Step 1: Write failing gateway tests**

Test loopback binding, single-owner lease, heartbeat expiry, proposal expiry, schema validation, replay rejection, correlation IDs, upstream timeout, disconnect, 3000 error propagation, software stop, and absolute prohibition on vendor SDK/CAN imports.

**Step 2: Verify RED**

```bash
local/runtimes/python/bin/python -m pytest apps/dummy/tests/test_gateway_protocol.py apps/dummy/tests/test_gateway_ownership.py apps/dummy/tests/test_gateway_robot_3000.py apps/dummy/tests/test_1023_gateway.py -q
```

**Step 3: Implement split gateway modules**

Bind `127.0.0.1:31023`; connect only to `ws://127.0.0.1:3000/ws`. Forward only policy-approved commands, attach `source=dummy_1023_gateway`, and emit an audit event for accept, reject, timeout, upstream response, and stop.

**Step 4: Verify GREEN and static bypass check**

Run:

```bash
rg -n "can0|python-can|socketcan|startouch_bridge|vendor" apps/dummy/src/dummy/gateway apps/dummy/apps/run_1023_gateway.py
```

Expected: no gateway-side CAN/vendor SDK implementation or import.

**Step 5: Commit**

```bash
git add apps/dummy/src/dummy/gateway apps/dummy/src/dummy/gateway_1023.py apps/dummy/apps/run_1023_gateway.py apps/dummy/tests/test_gateway_*.py apps/dummy/tests/test_1023_gateway.py
git commit -m "feat: harden 31023 gateway as the sole path to 3000"
```

## Task 11: Wire the End-to-End Dummy Follow Runner

**Files:**
- Create: `apps/dummy/src/dummy/person_follow/gateway_client.py`
- Create: `apps/dummy/src/dummy/person_follow/runtime.py`
- Modify: `apps/dummy/apps/run_dume_follow_touch_r1.py`
- Modify: `apps/dummy/configs/dum_e_touch_r1.yaml`
- Create: `apps/dummy/tests/test_person_follow_runtime.py`
- Create: `apps/dummy/tests/test_person_follow_gateway_client.py`

**Step 1: Write failing orchestration tests**

Use fake `3100`, `31023`, and `3000` endpoints to cover acquire, lock, propose, move, verify, repeat, stop, identity loss, stale frame, gateway denial, upstream timeout, and clean shutdown. Assert causal IDs are preserved across all logs.

**Step 2: Verify RED**

```bash
local/runtimes/python/bin/python -m pytest apps/dummy/tests/test_person_follow_runtime.py apps/dummy/tests/test_person_follow_gateway_client.py -q
```

**Step 3: Implement orchestration with dependency injection**

The runner reads observations from `3100`, sends typed proposals only to `31023`, and never opens `3000` directly. Configuration names all URLs, timeouts, limits, model/calibration paths, and log output explicitly.

**Step 4: Verify GREEN and assert no direct motion path**

Add a test that fails if the production runner is configured with `3000` as its gateway target.

**Step 5: Commit**

```bash
git add apps/dummy/src/dummy/person_follow apps/dummy/apps/run_dume_follow_touch_r1.py apps/dummy/configs/dum_e_touch_r1.yaml apps/dummy/tests/test_person_follow_runtime.py apps/dummy/tests/test_person_follow_gateway_client.py
git commit -m "feat: wire Dummy person follow through 31023"
```

## Task 12: Add Offline Replay and Safety Fault Injection

**Files:**
- Create: `apps/dummy/apps/replay_person_follow.py`
- Create: `apps/dummy/tests/fixtures/person_follow_crossing.jsonl`
- Create: `apps/dummy/tests/fixtures/person_follow_loss.jsonl`
- Create: `apps/dummy/tests/fixtures/person_follow_stale.jsonl`
- Create: `apps/dummy/tests/test_person_follow_replay.py`
- Modify: `apps/dummy/tests/test_offline.py`

**Step 1: Write failing replay assertions**

Define acceptance metrics for lock continuity, wrong-person switches, stop latency in frames, controller error reduction, gateway rejection, and deterministic state/log output.

**Step 2: Verify RED**

```bash
local/runtimes/python/bin/python -m pytest apps/dummy/tests/test_person_follow_replay.py apps/dummy/tests/test_offline.py -q
```

**Step 3: Implement replay CLI and fault injector**

Support dropped frames, delayed frames, duplicated proposal IDs, 3100 disconnect, 31023 disconnect, 3000 timeout, identity ambiguity, and controller no-progress. Replay must never connect to real ports.

**Step 4: Verify GREEN and save the summary JSON**

The CLI exits non-zero when any safety metric fails.

**Step 5: Commit**

```bash
git add apps/dummy/apps/replay_person_follow.py apps/dummy/tests/fixtures apps/dummy/tests/test_person_follow_replay.py apps/dummy/tests/test_offline.py
git commit -m "test: add deterministic person follow safety replay"
```

## Task 13: Integrate Services Without Motion and Verify Ports

**Files:**
- Create: `scripts/person_follow/check_stack.ps1`
- Create: `scripts/person_follow/check_stack.sh`
- Create: `docs/runbooks/dummy-person-follow.md`
- Modify: `README.md`

**Step 1: Write a read-only stack checker**

Check exact listeners and health:

- vision service: `127.0.0.1:3100`;
- debug gateway: `127.0.0.1:31023`;
- robot service: `127.0.0.1:3000`;
- no expected dependency on `3001`;
- 31023 upstream equals 3000;
- Dummy production runner upstream equals 31023.

**Step 2: Run focused and full automated suites**

```bash
local/runtimes/python/bin/python -m pytest apps/dummy/tests tests/python/vision -q
node --test tests/node/vision_service/*.test.js tests/node/robot_service/*.test.js
```

Expected: PASS.

**Step 3: Start the stack in dry-run mode**

Use read-only camera observations and a fake 3000 adapter. Verify structured logs and causal IDs without sending a physical command.

**Step 4: Run the checker and fault drills**

Stop each service in turn and confirm the follow state becomes `HOLDING`, `STOPPED`, or `FAULT` and no further proposal is forwarded.

**Step 5: Commit**

```bash
git add scripts/person_follow docs/runbooks/dummy-person-follow.md README.md
git commit -m "docs: add person follow deployment and safety runbook"
```

## Task 14: Perform Explicitly Gated On-Site Calibration

**Files:**
- Modify: `apps/dummy/apps/calibrate_touch_r1_gimbal.py`
- Create: `apps/dummy/configs/person_follow_calibration.yaml`
- Create: `artifacts/person_follow/calibration-report.json`
- Create: `apps/dummy/tests/test_calibration_report.py`

**Step 1: Stop and obtain the user's live confirmation**

Before any physical motion, report the exact joints, maximum perturbation, pose, stop control, ports, and expected duration. Do not continue on silence.

**Step 2: Validate stationary safety conditions**

Confirm clear workspace, connected robot state through `3000`, active 31023 lease, fresh 3100 frames, correct identity session, and reachable software stop.

**Step 3: Run bounded excitation through `31023 -> 3000` only**

Collect positive/negative small perturbations for authorized pan/tilt/body joints, return to baseline between samples, and stop immediately on target loss, limit approach, no visual response, or user stop.

**Step 4: Fit and validate the local Jacobian**

Reject ill-conditioned fits. Save sample counts, residuals, operating pose/range, calibration/model/camera hashes, and timestamp. Run held-out directional checks at reduced step size.

**Step 5: Test the report and commit only calibration artifacts**

```bash
local/runtimes/python/bin/python -m pytest apps/dummy/tests/test_calibration_report.py -q
git add apps/dummy/apps/calibrate_touch_r1_gimbal.py apps/dummy/configs/person_follow_calibration.yaml artifacts/person_follow/calibration-report.json apps/dummy/tests/test_calibration_report.py
git commit -m "calibrate: measure Touch R1 visual Jacobian"
```

## Task 15: Run Gated On-Site Acceptance Without Merging into 3000

**Files:**
- Create: `artifacts/person_follow/acceptance-report.json`
- Create: `artifacts/person_follow/acceptance-events.jsonl`
- Modify: `docs/runbooks/dummy-person-follow.md`

**Step 1: Obtain a second explicit live confirmation**

State the configured per-step joint bounds, timeout, identity, software-stop command, and that 31023 remains a separate gateway.

**Step 2: Run staged acceptance**

Run in this order, stopping between stages:

1. stationary detection/identity lock;
2. one bounded proposal and verify;
3. five stop-look-move-verify cycles;
4. short occlusion and correct reacquisition;
5. distractor crossing and wrong-person rejection;
6. operator stop;
7. simulated 3100/31023/3000 failure.

**Step 3: Evaluate hard acceptance criteria**

The report must show zero direct SDK/CAN calls outside 3000, zero wrong-person executed moves, zero executed stale/replayed proposals, bounded joint deltas, verified error reduction, and fail-closed behavior for every injected fault.

**Step 4: Run the full regression suite**

```bash
local/runtimes/python/bin/python -m pytest -q
npm run test:node
```

Expected: PASS. Record exact counts and durations in the report.

**Step 5: Commit the acceptance evidence**

```bash
git add artifacts/person_follow/acceptance-report.json artifacts/person_follow/acceptance-events.jsonl docs/runbooks/dummy-person-follow.md
git commit -m "test: record person follow on-site acceptance"
```

## Task 16: Prepare, But Do Not Perform, the Final 3000 Merge

**Files:**
- Create: `docs/superpowers/plans/2026-09-29-person-follow-3000-merge.md`

**Step 1: Inspect the accepted 31023 boundary**

List protocol, ownership, policy, audit, and upstream adapter responsibilities. Identify which pieces belong inside `services/robot` and which remain in Dummy/vision.

**Step 2: Write a separate merge plan**

Include API compatibility, feature flag, rollback, migration tests, service restart order, and restoration of the standalone gateway.

**Step 3: Stop for explicit user approval**

Do not copy code into `services/robot`, change port ownership, disable 31023, or restart production 3000 until the user explicitly approves that merge plan.

**Step 4: Commit only the plan**

```bash
git add docs/superpowers/plans/2026-09-29-person-follow-3000-merge.md
git commit -m "docs: plan approved person follow merge into 3000"
```

---

## Completion Criteria Before the 3000 Merge Decision

- The deployed path is exactly `Lumos -> 3100 -> Dummy -> 31023 -> 3000 -> vendor SDK -> can0 -> Touch R1`.
- No Dummy, vision, or 31023 module directly imports or drives CAN/vendor motion code.
- Every observation, proposal, gateway decision, robot response, and verification result is correlated in JSONL logs.
- Session identity survives short occlusion and fails closed on ambiguity or wrong-person risk.
- Production control uses a measured, versioned local visual Jacobian; raw pixel proportional gain is disabled.
- Every physical move is bounded, single-step, lease-bound, fresh, and visually verified before another move.
- Offline replay, fault injection, service integration, and on-site acceptance suites pass with saved evidence.
- The standalone 31023 gateway remains enabled until the user explicitly approves merging its validated behavior into 3000.
