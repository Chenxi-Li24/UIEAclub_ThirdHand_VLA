# Active Vision Robot Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After the dry-run plan passes, connect validated calibration and observation-pose evidence to a fail-closed active-view session that can perform explicitly approved, low-speed observation motions while keeping autonomous grasp execution disabled.

**Architecture:** The Python camera/vision process remains the authoritative perception and active-view session owner but cannot access Startouch or CAN. It emits evidence-bound move proposals; the Node control proxy independently authorizes and executes only a stored proposal identified by session/proposal IDs, then returns correlated motion events to Python. Enabling real observation motion requires both an environment request and a short-lived local approval artifact bound to exact calibration, catalog, robot-model, and safety-limit hashes; checked-in defaults remain disabled.

**Tech Stack:** Python 3.11, NumPy, PyYAML, pytest, Node.js 18+, Express, `ws`, Startouch bridge, Node smoke tests, existing web-control UI.

## Prerequisite

Every task in `docs/superpowers/plans/2026-08-06-active-vision-dry-run.md` must be complete, reviewed, and passing. The real-motion task at the end of this plan additionally requires the user's explicit approval in the active Codex conversation.

## Global Constraints

- The cameras are eye-in-hand and move together; D435 remains the only metric-depth source.
- No real motion is allowed until Lumos intrinsics, D435-to-Lumos, Lumos-to-flange, desktop, and full-chain validation meet the approved gates.
- Lumos validation requires median ≤1 px, P95 ≤2.5 px, and edge P95 ≤4 px.
- D435-to-Lumos validation requires target-board P95 ≤4 px and desktop-plane P95 ≤8 mm.
- Hand-eye/full-chain static-point P95 must be ≤10 mm.
- Coarse moves use only content-addressed, pre-taught observation poses and validated paths; missing coverage never falls back to arbitrary IK.
- Fine moves require valid D435 depth first and remain stop-and-look, lateral-only, ≤20 mm per step, ≤3 steps.
- First real validation uses speed scale ≤0.05 and requires operator confirmation before every observation move.
- Motion frames never update actionable 3D state; post-motion identity requires two high-quality confirmations and depth stability requires five new samples.
- Active-view observation motion and grasp motion are mutually exclusive.
- `robotExecutionEnabled` for grasp remains exactly `false` throughout this plan. Active-view success creates a grasp preview only; it does not approve or execute a grasp.
- Browser messages carry only identity, session, proposal, and confirmation IDs. Browser-provided joints, positions, Euler angles, deltas, safety booleans, or calibration IDs are ignored.
- Software stop does not replace the physical emergency stop. Any stop invalidates the current session and approval evidence.

## File Structure

- `web-control/server/vision_models/active_view_catalog.py`: loads and verifies live camera/table/catalog evidence.
- `scripts/vision/finalize_active_view_catalog.py`: converts captured poses into a content-addressed coverage catalog without moving hardware.
- `web-control/scripts/teach-active-view-pose.js`: reads one current pose through the existing web server and appends an unvalidated capture atomically; it sends no motion command.
- `scripts/vision/create_active_view_approval.py`: creates a short-lived, gitignored approval artifact bound to exact evidence after explicit user authorization.
- `web-control/server/camera_bridge.py`: owns validated bundles and the Python `ActiveViewSession`; still has no robot transport imports.
- `web-control/server/camera-bridge.js`: carries a narrow session-event protocol with no raw motion payload from Node to Python.
- `web-control/server/active-view-authorization.js`: independently validates proposals, live state, limits, hashes, and approval artifact.
- `web-control/server/active-view-controller.js`: owns trusted pending proposals and correlates Startouch request IDs.
- `web-control/server/active-view-audit-log.js`: writes canonical JSONL for every transition, proposal, authorization, command, completion, and cancellation.
- `web-control/server/proxy.js`: routes ID-only browser actions and supplies robot state to the controller/camera bridge.
- `web-control/web/camera-test.html`: active-view start/cancel/step-confirm controls and grasp preview; no coordinate editor.
- `scripts/vision/verify_active_view_control.py`: simulation and real staged evidence verifier.

---

### Task 1: Validate Calibration and Build the Observation Catalog

**Files:**
- Create: `web-control/server/vision_models/active_view_catalog.py`
- Create: `web-control/server/tests/vision_models/test_active_view_catalog.py`
- Create: `scripts/vision/finalize_active_view_catalog.py`
- Create: `tests/vision_deployment/test_active_view_catalog.py`
- Create: `web-control/scripts/teach-active-view-pose.js`
- Create: `web-control/server/test/teach-active-view-pose-smoke.js`
- Modify: `web-control/server/package.json`
- Modify: `.gitignore`

**Interfaces:**
- `load_active_view_evidence(camera_path, table_path, catalog_path) -> ActiveViewEvidence` returns a verified `DualCameraCalibrationBundle`, `TablePlane`, tuple of `ObservationPose`, and aggregate `evidence_id`.
- `finalize_catalog(captures, evidence, output_path) -> dict` computes D435 inner-ROI footprints on the desktop and writes canonical atomic YAML/JSON.
- The teaching script accepts `--name`, `--server`, and `--output`; it records current joints/TCP only.

- [ ] **Step 1: Write failing audit and catalog tests**

```python
def test_catalog_is_bound_to_exact_calibration_and_validated_paths(tmp_path):
    evidence = load_active_view_evidence(
        valid_camera_bundle_path(tmp_path), valid_table_path(tmp_path), valid_catalog_path(tmp_path)
    )
    assert evidence.camera.calibration.validated is True
    assert evidence.table.validated is True
    assert evidence.poses[0].path_validation_id.startswith("sha256:")
    assert evidence.evidence_id.startswith("sha256:")


@pytest.mark.parametrize("mutation", [change_joint, change_coverage, change_calibration_id])
def test_catalog_content_or_provenance_change_is_rejected(tmp_path, mutation):
    path = valid_catalog_path(tmp_path)
    mutation(path)
    with pytest.raises(IdentityReplayFormatError, match="catalog|calibration|integrity"):
        load_active_view_evidence(valid_camera_bundle_path(tmp_path), valid_table_path(tmp_path), path)
```

The Node test must connect to a fake WebSocket server, return one `robot_state`, assert the capture is written atomically, and assert received commands are exactly `[{cmd:"status"}]` with no servo, preset, `move_l`, gripper, or grasp request.

- [ ] **Step 2: Verify tests fail**

Run: `PYTHONPATH=web-control/server pytest -q web-control/server/tests/vision_models/test_active_view_catalog.py tests/vision_deployment/test_active_view_catalog.py`

Run: `cd web-control/server && node test/teach-active-view-pose-smoke.js`

Expected: FAIL because the evidence loader and tools do not exist.

- [ ] **Step 3: Implement strict content-addressed evidence loading**

```python
@dataclass(frozen=True)
class ActiveViewEvidence:
    camera: DualCameraCalibrationBundle
    table: TablePlane
    poses: tuple[ObservationPose, ...]
    robot_model_id: str
    catalog_id: str
    evidence_id: str
```

Canonicalize JSON with sorted keys, compact separators, ASCII, and `allow_nan=False`. Verify source content hashes before constructing domain types. Enforce the exact calibration gates from Global Constraints, require at least one pose, unique IDs, convex coverage, six legal joints, allowed starts, and a path-validation record containing manual test date, maximum observed joint error, speed scale ≤0.05, and operator acknowledgment. Reject symlinks, remote URLs, files over 8 MiB, and paths outside the configured evidence directory.

- [ ] **Step 4: Implement catalog finalization geometry**

```python
corners = d435_inner_roi_rays(camera_bundle.d435, inner_roi_fraction=0.60)
t_base_from_d435 = (
    capture.t_base_from_flange
    @ camera_bundle.t_flange_from_lumos
    @ camera_bundle.t_lumos_from_d435
)
coverage_xy = intersect_rays_with_table(corners, t_base_from_d435, table)
```

Require four valid forward intersections and preserve winding. The output starts `validated:false`; it becomes valid only when every path-validation record is present and the aggregate audit passes. Never infer a path-validation ID from pose geometry alone.

- [ ] **Step 5: Implement read-only pose capture**

Use the installed `ws` library, request current status, validate six joints and three-element TCP position/Euler values, and atomically append a named capture with timestamp and server URL. Refuse duplicate names, all-zero transient states, missing robot stability, and non-loopback servers unless `--allow-remote` is explicit. The script never imports or spawns the Startouch SDK.

- [ ] **Step 6: Test and commit**

```bash
PYTHONPATH=web-control/server pytest -q web-control/server/tests/vision_models/test_active_view_catalog.py tests/vision_deployment/test_active_view_catalog.py
cd web-control/server && node test/teach-active-view-pose-smoke.js && cd ../..
git add .gitignore web-control/server/vision_models/active_view_catalog.py web-control/server/tests/vision_models/test_active_view_catalog.py scripts/vision/finalize_active_view_catalog.py tests/vision_deployment/test_active_view_catalog.py web-control/scripts/teach-active-view-pose.js web-control/server/test/teach-active-view-pose-smoke.js web-control/server/package.json
git commit -m "feat(vision): audit active-view observation catalogs"
```

---

### Task 2: Supply Validated Robot Pose and Stationarity to Perception

**Files:**
- Modify: `web-control/server/camera_bridge.py`
- Modify: `web-control/server/camera-bridge.js`
- Modify: `web-control/server/proxy.js`
- Modify: `web-control/server/vision_models/online.py`
- Modify: `web-control/server/tests/vision_models/test_online.py`
- Modify: `tests/vision_deployment/test_online_camera_bridge_contract.py`

**Interfaces:**
- `CameraBridge.sendArmState(tcpPosition, tcpEuler, joints, velocities, stationary, observedAtNs)` forwards read-only state.
- Python `ArmPoseSample` gains `joints_deg`, `stationary`, and the sender's monotonic observation timestamp.
- `run_online_perception()` passes the verified calibration bundle and actual `arm_stationary` value instead of hard-coded `None/False`.

- [ ] **Step 1: Write failing time/stationarity tests**

```python
def test_arm_state_requires_sender_timestamp_and_explicit_stationarity():
    accepted = accepted_arm_state({
        "type": "arm_state",
        "tcp_position_m": [0.1, 0.0, 0.3],
        "tcp_euler_rad": [0.0, 0.0, 0.0],
        "joints_deg": [1, 2, 3, 4, 5, 6],
        "velocities_deg_s": [0, 0, 0, 0, 0, 0],
        "stationary": True,
        "monotonic_ns": 1_000_000,
    })
    assert accepted.stationary is True
    assert accepted.stamp.monotonic_ns == 1_000_000
```

Add rejection cases for missing/boolean numeric values, future/backward timestamps, `stationary:true` with velocity above the configured threshold, state older than 250 ms, calibration load failure, and calibration hash change during a running session.

- [ ] **Step 2: Verify tests fail**

Run: `PYTHONPATH=web-control/server pytest -q web-control/server/tests/vision_models/test_online.py tests/vision_deployment/test_online_camera_bridge_contract.py`

Expected: FAIL because arm state lacks the new provenance and online fusion remains deliberately disabled.

- [ ] **Step 3: Forward explicit state from the existing robot owner**

```javascript
const stationary = !motionActive && velocitiesDeg.every(value => Math.abs(value) <= 0.5);
cameraBridge.sendArmState(
  message.tcp_position_m, message.tcp_euler_rad, jointsDeg, velocitiesDeg,
  stationary, process.hrtime.bigint().toString()
);
```

Represent `monotonic_ns` as a decimal string across JSON to avoid JavaScript safe-integer truncation; parse it to Python `int` with length/range checks. Do not replace it with receipt time.

- [ ] **Step 4: Load validated evidence once and fail closed on change**

Initialize `ActiveViewEvidence` before model processing. Pass its camera bundle to `OnlinePerceptionEngine` only when integrity verification succeeds. Surface `calibration_unavailable` or `calibration_changed` on any error; never hot-reload a different calibration into an active session.

- [ ] **Step 5: Run fusion and bridge suites**

Run: `PYTHONPATH=web-control/server pytest -q web-control/server/tests/vision web-control/server/tests/vision_models tests/vision_deployment/test_online_camera_bridge_contract.py`

Expected: PASS; validated synthetic stationary data can produce 3D observations, moving/stale data cannot.

- [ ] **Step 6: Commit**

```bash
git add web-control/server/camera_bridge.py web-control/server/camera-bridge.js web-control/server/proxy.js web-control/server/vision_models/online.py web-control/server/tests/vision_models/test_online.py tests/vision_deployment/test_online_camera_bridge_contract.py
git commit -m "feat(vision): bind online fusion to stationary robot state"
```

---

### Task 3: Narrow Session Protocol Between Node and Python

**Files:**
- Modify: `web-control/server/camera_bridge.py`
- Modify: `web-control/server/camera-bridge.js`
- Modify: `web-control/server/vision/active_view_session.py`
- Modify: `web-control/server/tests/vision/test_active_view_session.py`
- Modify: `tests/vision_deployment/test_online_camera_bridge_contract.py`

**Interfaces:**
- Node-to-Python command allowlist adds only `active_view_start`, `active_view_motion_started`, `active_view_motion_completed`, `active_view_motion_failed`, `active_view_cancel`, and `active_view_operator_confirmed`.
- Commands carry IDs/timestamps only; they cannot carry joints, Cartesian positions, Euler angles, deltas, or safety booleans.
- Python emits `active_view_state` and `active_view_move_proposal` events with `session_id`, `proposal_id`, target identity, evidence IDs, expiry, and the trusted proposal payload.

- [ ] **Step 1: Write failing protocol tests**

```python
@pytest.mark.parametrize("command", [
    {"type": "active_view_start", "session_id": "s1", "identity_id": 7},
    {"type": "active_view_motion_completed", "session_id": "s1", "request_id": "r1"},
    {"type": "active_view_cancel", "session_id": "s1"},
])
def test_session_commands_accept_ids_only(command):
    assert accepted_command_type(command) == command["type"]


def test_session_command_with_coordinates_is_rejected():
    assert accepted_command_type({
        "type": "active_view_start", "session_id": "s1", "identity_id": 7,
        "position": [0.1, 0.2, 0.3]
    }) is None
```

Add tests for bounded ID lengths, invalid UUIDs, old/wrong session events, duplicate completion, operator confirmation of a different proposal, cancel during every non-terminal phase, and JSON events forcing grasp execution false.

- [ ] **Step 2: Verify tests fail**

Run: `PYTHONPATH=web-control/server pytest -q web-control/server/tests/vision/test_active_view_session.py tests/vision_deployment/test_online_camera_bridge_contract.py`

Expected: FAIL because the bridge accepts no active-view session events.

- [ ] **Step 3: Implement schema-specific parsing**

```python
SESSION_COMMAND_KEYS = {
    "active_view_start": {"type", "session_id", "identity_id"},
    "active_view_motion_started": {"type", "session_id", "proposal_id", "request_id"},
    "active_view_motion_completed": {"type", "session_id", "request_id"},
    "active_view_motion_failed": {"type", "session_id", "request_id", "reason"},
    "active_view_cancel": {"type", "session_id"},
    "active_view_operator_confirmed": {"type", "session_id", "proposal_id"},
}
```

Require exact key sets and validated scalar values. Route events through the pure state machine. Session transitions run on one owning thread/queue so camera and stdin threads cannot race.

- [ ] **Step 4: Emit evidence-bound proposals**

Generate a random server-side `proposal_id`, store its full immutable proposal in the Python session, and serialize it once. Motion events must match the stored proposal/request IDs. Proposal expiry or a new conflicting observation invalidates it and emits an aborted state.

- [ ] **Step 5: Run protocol, session, and no-hardware tests**

Run: `PYTHONPATH=web-control/server pytest -q web-control/server/tests/vision/test_active_view_session.py web-control/server/tests/vision/test_no_hardware_dependencies.py tests/vision_deployment/test_online_camera_bridge_contract.py`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add web-control/server/camera_bridge.py web-control/server/camera-bridge.js web-control/server/vision/active_view_session.py web-control/server/tests/vision/test_active_view_session.py tests/vision_deployment/test_online_camera_bridge_contract.py
git commit -m "feat(vision): add active-view session protocol"
```

---

### Task 4: Independent Motion Authorization and Trusted Controller

**Files:**
- Create: `web-control/server/active-view-authorization.js`
- Create: `web-control/server/active-view-controller.js`
- Create: `web-control/server/active-view-audit-log.js`
- Create: `web-control/server/test/active-view-authorization-smoke.js`
- Create: `web-control/server/test/active-view-controller-smoke.js`
- Create: `web-control/server/test/active-view-audit-log-smoke.js`
- Modify: `web-control/server/config.js`
- Modify: `web-control/server/package.json`
- Create: `scripts/vision/create_active_view_approval.py`
- Create: `tests/vision_deployment/test_active_view_approval.py`

**Interfaces:**
- `authorizeActiveViewMove({requested, approval, proposal, robot, session, nowMs, limits}) -> {approved, reason, command?}`.
- `ActiveViewController` stores one trusted pending proposal and exposes ID-only `begin`, `confirm`, `cancel`, `onRobotEvent`, and `onVisionEvent` methods.
- `ActiveViewAuditLog.append(event)` writes canonical newline-delimited JSON with an increasing local sequence.
- `create_active_view_approval.py` creates an atomic artifact expiring within 8 hours and bound to evidence IDs and exact limits.

- [ ] **Step 1: Write failing authorization tests**

```javascript
assert.deepEqual(authorizeActiveViewMove({
  requested: false, approval, proposal, robot, session, nowMs: 1000, limits
}), { approved: false, reason: 'active_view_execution_disabled' });

const accepted = authorizeActiveViewMove({
  requested: true, approval, proposal, robot, session, nowMs: 1000, limits
});
assert.equal(accepted.approved, true);
assert.deepEqual(accepted.command.joints_rad, proposal.jointsDeg.map(degreesToRadians));
```

Add explicit rejects for missing/expired approval, evidence mismatch, wrong session/identity/proposal, proposal age over 200 ms, robot disconnected/moving, stale state, grasp active, joint bounds, all-zero accidental target, speed scale over 0.05, refinement over 20 mm, nonzero optical-axis refinement, more than three refinements, browser-injected coordinates, and an already active motion.

Add an audit-log test that writes two events, restarts the writer, verifies the sequence continues, verifies every line contains finite JSON, rejects records above 64 KiB, and confirms session/proposal/request/evidence IDs and rejection reasons are retained.

- [ ] **Step 2: Verify tests fail**

Run: `cd web-control/server && node test/active-view-authorization-smoke.js && node test/active-view-controller-smoke.js`

Run: `cd ../.. && pytest -q tests/vision_deployment/test_active_view_approval.py`

Expected: FAIL because the modules do not exist.

- [ ] **Step 3: Implement two-factor enablement**

```javascript
activeView: {
  requested: process.env.ACTIVE_VIEW_EXECUTION_ENABLED === '1',
  approvalFile: process.env.ACTIVE_VIEW_APPROVAL_FILE || '',
  auditLog: process.env.ACTIVE_VIEW_AUDIT_LOG ||
    path.resolve(__dirname, '../../artifacts/vision/active-view-control/events.jsonl'),
  maxSpeedScale: 0.05,
  maxTranslationM: 0.020,
  maxRotationRad: 5 * Math.PI / 180,
  requireStepConfirmation: true,
}
```

An environment request alone never authorizes motion. Load and canonicalize the approval artifact, verify its content hash, expiry ≤8 hours, evidence IDs, limits, and `operator_acknowledged:true`. Keep approval artifacts below the gitignored runtime directory and never commit them.

- [ ] **Step 4: Implement trusted proposal ownership and correlation**

```javascript
confirm({ sessionId, proposalId }) {
  if (!this.pending || this.pending.sessionId !== sessionId || this.pending.proposalId !== proposalId) {
    return { approved: false, reason: 'proposal_not_pending' };
  }
  const decision = authorizeActiveViewMove(this._authorizationInput());
  if (!decision.approved) return decision;
  const requestId = randomUUID();
  this.inFlight = { sessionId, proposalId, requestId };
  this.pending = null;
  return { ...decision, requestId };
}
```

Only `command_complete` or `error` with the exact request ID may finish the move. A software stop, disconnect, new evidence ID, grasp start, or timeout clears both pending and in-flight state and sends a cancel/failure event to Python.

- [ ] **Step 5: Implement append-only audit evidence**

```javascript
append(event) {
  const record = sanitizeAuditRecord({
    ...event,
    sequence: this.nextSequence,
    writtenAtMs: Date.now(),
  });
  const line = `${canonicalJson(record)}\n`;
  if (Buffer.byteLength(line) > 65536) throw new TypeError('audit record exceeds 64 KiB');
  fs.appendFileSync(this.path, line, { encoding: 'utf8', mode: 0o600 });
  this.nextSequence += 1;
}
```

The controller appends before and after every state-changing action. Failure to write a pre-motion audit record rejects the motion; a later logging failure aborts the session and never sends a follow-up movement.

- [ ] **Step 6: Run authorization/controller/audit tests and existing grasp tests**

Run: `cd web-control/server && npm test`

Expected: PASS; grasp authorization remains unchanged and disabled.

- [ ] **Step 7: Commit**

```bash
git add web-control/server/active-view-authorization.js web-control/server/active-view-controller.js web-control/server/active-view-audit-log.js web-control/server/test/active-view-authorization-smoke.js web-control/server/test/active-view-controller-smoke.js web-control/server/test/active-view-audit-log-smoke.js web-control/server/config.js web-control/server/package.json scripts/vision/create_active_view_approval.py tests/vision_deployment/test_active_view_approval.py
git commit -m "feat(control): authorize active-view moves independently"
```

---

### Task 5: Proxy Integration, Mutual Exclusion, and ID-Only UI

**Files:**
- Modify: `web-control/server/proxy.js`
- Modify: `web-control/server/vision-status.js`
- Modify: `web-control/server/test/vision-status-smoke.js`
- Modify: `web-control/server/test/browser-smoke.js`
- Modify: `web-control/web/camera-test.html`
- Modify: `tests/web/test_web_ui_security.py`

**Interfaces:**
- Browser commands: `start_active_view {identityId}`, `confirm_active_view_step {sessionId, proposalId}`, and `cancel_active_view {sessionId}`.
- Server messages: sanitized `active_view_state` and `active_view_move_ready`; the browser never receives trusted joints/deltas.
- `GET /api/vision/status` continues to report both execution gates separately.

- [ ] **Step 1: Write failing proxy/UI security tests**

```python
def test_camera_page_sends_ids_only_for_active_view():
    source = CAMERA_PAGE.read_text(encoding="utf-8")
    assert "start_active_view" in source
    assert "confirm_active_view_step" in source
    for forbidden in ("jointsDeg", "deltaBaseM", "tcp_position", "euler", "safetyApproved"):
        assert forbidden not in source
```

Extend Node smoke coverage so a browser start request for an unknown/stale identity is rejected, extra coordinate keys are ignored/rejected, step confirmation uses the server-held proposal, cancellation invalidates it, grasp requests are refused while an active-view session exists, and active-view starts are refused while `graspState` or `motionActive` is set.

- [ ] **Step 2: Verify tests fail**

Run: `pytest -q tests/web/test_web_ui_security.py`

Run: `cd web-control/server && npm test`

Expected: FAIL because the proxy and UI do not implement the session controls.

- [ ] **Step 3: Integrate exact events without broadening generic servo**

```javascript
case 'start_active_view':
  activeView.begin({ identityId: Number(message.identityId), targets: visionStatus.trustedTargets() });
  break;
case 'confirm_active_view_step':
  activeView.confirm({ sessionId: String(message.sessionId), proposalId: String(message.proposalId) });
  break;
case 'cancel_active_view':
  activeView.cancel({ sessionId: String(message.sessionId), reason: 'operator_cancelled' });
  break;
```

Reject extra keys before dispatch. Do not route active-view movement through the public `servo` handler. The controller sends the already-authorized command directly to the existing Startouch bridge and registers its exact request ID.

- [ ] **Step 4: Render controls and grasp preview safely**

Enable Start only for a fresh confirmed identity. Show proposal pose name, maximum step, evidence IDs shortened for display, and exact blockers. Require a click for every move during first validation. `GRASP_PREVIEW` displays target geometry and reasons but has no grasp-execution button because `robotExecutionEnabled` remains false.

- [ ] **Step 5: Run browser, Node, and web suites**

Run: `cd web-control/server && npm test`

Run: `cd ../.. && pytest -q tests/web`

Expected: PASS, including no dynamic `innerHTML` and no browser coordinate authority.

- [ ] **Step 6: Commit**

```bash
git add web-control/server/proxy.js web-control/server/vision-status.js web-control/server/test/vision-status-smoke.js web-control/server/test/browser-smoke.js web-control/web/camera-test.html tests/web/test_web_ui_security.py
git commit -m "feat(web): control active-view sessions by ID"
```

---

### Task 6: Simulation, Fault Injection, and Soak Verification

**Files:**
- Create: `scripts/vision/verify_active_view_control.py`
- Create: `tests/vision_deployment/test_active_view_control.py`
- Modify: `scripts/vision/start_dual_camera_online.sh`
- Modify: `docs/vision_research/REMIND3D_DEPLOYMENT_RESULTS.md`

**Interfaces:**
- `evaluate_active_view_control(events, expected_evidence_id, real_motion_allowed=False) -> dict` produces deterministic acceptance evidence.
- The verifier supports `--base-url`, `--duration-seconds`, `--output`, `--expected-evidence-id`, and `--simulation-only`.

- [ ] **Step 1: Write failing simulation and failure-injection tests**

```python
def test_simulated_session_reaches_grasp_preview_without_grasp_command():
    report = evaluate_active_view_control(simulated_success_events(), EVIDENCE_ID)
    assert report["passed"] is True
    assert report["observation_moves"] == 2
    assert report["grasp_commands"] == 0
    assert report["max_translation_m"] <= 0.020


@pytest.mark.parametrize("events,reason", [
    (identity_switch_events(), "identity"),
    (stale_depth_events(), "stale"),
    (wrong_request_id_events(), "request"),
    (disconnect_events(), "disconnect"),
    (approval_expiry_events(), "approval"),
])
def test_faults_abort_without_followup_motion(events, reason):
    report = evaluate_active_view_control(events, EVIDENCE_ID)
    assert report["passed"] is False
    assert reason in "\n".join(report["errors"]).lower()
    assert report["commands_after_abort"] == 0
```

- [ ] **Step 2: Verify tests fail**

Run: `pytest -q tests/vision_deployment/test_active_view_control.py`

Expected: FAIL because the verifier does not exist.

- [ ] **Step 3: Implement deterministic event evaluation**

Require legal state order, exact session/proposal/request correlation, two post-motion identity confirmations, five post-motion depth samples, no movement above configured bounds, no grasp command, and both evidence hashes unchanged. Record abort-reason histogram, maximum motion, settling time, identity changes, depth stability, and execution-gate samples.

- [ ] **Step 4: Run the complete simulation gate**

Run: `PYTHONPATH=web-control/server pytest -q web-control/server/tests/vision web-control/server/tests/vision_models tests/vision_deployment tests/web`

Run: `cd web-control/server && npm test`

Run: `cd ../.. && python -m py_compile scripts/vision/verify_active_view_control.py && git diff --check`

Expected: all commands exit 0. Run a 30-minute simulated soak with real active-view execution disabled; require zero unexpected session transitions, zero stale accepted proposals, and zero grasp commands.

- [ ] **Step 5: Record simulation evidence and commit**

```bash
git add scripts/vision/verify_active_view_control.py tests/vision_deployment/test_active_view_control.py scripts/vision/start_dual_camera_online.sh docs/vision_research/REMIND3D_DEPLOYMENT_RESULTS.md
git commit -m "test(control): verify active-view motion sessions"
```

---

### Task 7: Staged Real Observation-Motion Validation

**Files:**
- Runtime only: `artifacts/vision/active-view-control/approval.json` (gitignored)
- Runtime only: `artifacts/vision/active-view-control/events.jsonl` (gitignored)
- Runtime only: `artifacts/vision/active-view-control/readiness.json` (gitignored)
- Modify after evidence exists: `docs/vision_research/REMIND3D_DEPLOYMENT_RESULTS.md`

**Interfaces:**
- Produces evidence for observation motion only. It does not enable or execute grasp motion.

- [ ] **Step 1: Stop and request explicit user authorization**

Present the exact calibration/catalog/evidence hashes, proposed observation poses, maximum 0.05 speed scale, 20 mm refinement cap, physical emergency-stop requirement, cleared workspace requirement, and fake-target setup. Do not proceed until the user explicitly approves the first real observation movement in the current conversation.

- [ ] **Step 2: Confirm physical prerequisites without changing state**

Read the current robot/camera status, exact port/PID ownership, CAN lock owner, joint/TCP state, calibration hashes, catalog hash, and approval absence. Ask the user to confirm the physical emergency stop is reachable, the table workspace is clear, and a safe fake target is present. Do not infer these physical facts from software status.

- [ ] **Step 3: Create the short-lived approval artifact**

Run `scripts/vision/create_active_view_approval.py` with the approved evidence IDs, speed 0.05, translation 0.020 m, rotation 0°, three-step maximum, and an expiry no more than 8 hours away. Inspect its canonical content and hash. Set `ACTIVE_VIEW_EXECUTION_ENABLED=1` and `ACTIVE_VIEW_APPROVAL_FILE` only for the exact owned control process; leave grasp execution false.

- [ ] **Step 4: Validate one pre-taught coarse observation move**

Start from its cataloged allowed pose, lock a fake target, inspect the pending proposal, obtain the per-step UI confirmation, and execute one pre-taught joint move. Require exact request completion, joint error within the catalog threshold, stop-and-look settle, two same-identity observations, and no unexpected command. Cancel and stop on any discrepancy.

- [ ] **Step 5: Validate one bounded lateral refinement**

Only after valid D435 depth exists, confirm one refinement with norm ≤20 mm and zero optical-axis component. Require exact completion and five new stable depth samples. Do not run a second refinement until the first evidence is reviewed; then increase only up to the three-step design maximum.

- [ ] **Step 6: Exercise fail-closed cases**

With the robot stationary between cases, test operator cancel, stale proposal, target identity loss, D435 interruption, and approval expiry. Each must produce zero follow-up motion and invalidate the session. Do not induce CAN loss or physical collision as a test.

- [ ] **Step 7: Run a bounded real soak and disable execution**

Run repeated observation-only sessions for the approved duration with per-step confirmation. Save event evidence, then remove/expire the approval artifact and restart the exact owned process with `ACTIVE_VIEW_EXECUTION_ENABLED=0`. Verify both active-view and grasp execution are false.

- [ ] **Step 8: Document results and commit only documentation**

```bash
git add docs/vision_research/REMIND3D_DEPLOYMENT_RESULTS.md
git commit -m "docs: record active-view motion validation"
```

Record exact evidence hashes, motion counts, maximum error/step, identity continuity, depth improvement, abort tests, approval expiry, and the final disabled state. Do not claim grasp readiness; dynamic grasp planning and real grasp execution require a separate reviewed specification and explicit user authorization.
