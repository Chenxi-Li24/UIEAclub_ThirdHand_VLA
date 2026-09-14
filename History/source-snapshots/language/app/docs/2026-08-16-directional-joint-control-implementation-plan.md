# Directional Joint Control 9982/3003 Implementation Plan

> Implementation target: only the copied integration tree at
> `/home/nieqingcao/th0814/thirdhand-language9981/language-sync-20260814-221750`.
> Do not edit, restart, or deploy formal 3000/3001 or the accepted 9981/3002 runtime.

**Goal:** Add bilingual natural-language directional primitives that create confirmation-gated candidates, preview a bounded joint target, and—only after a later explicit hardware-test authorization—send one correlated command through formal 3000, which remains the sole SDK/CAN owner.

**Architecture:** Voice 3003 maps Chinese or English text to a new `directional_joint_control@1` candidate. Web 9982 validates and previews that candidate. A dedicated Node orchestrator computes the full six-joint target from fresh formal-3000 state, checks mechanical limits and lift semantics, then sends one `servo` request through the existing loopback `LanguageUpstreamBridge`. The directional real-control flag starts disabled. Existing `manual_joint_control@1`, Coke Skill handoff, right-side controls, formal 3000/3001, and 9981/3002 remain unchanged.

**Fixed mappings:** Default magnitude is 20 degrees. Explicit magnitudes are preserved. `turn.left/right` change J1 `+/-`; `lift.up/down` change J2/J3 `(+,-)/(-,+)` atomically; `wrist.pitch.up/down` change J4 `-/+`; `wrist.yaw.left/right` change J5 `+/-`; `wrist.roll.clockwise/counterclockwise` change J6 `+/-`. Speed scale is always 0.05.

---

## Task 1: Add the independent directional contract

**Files:**
- Create: `contracts/directional_joint_control.schema.json`
- Create: `contracts/directional_joint_control.skill.json`
- Create: `contracts/examples/directional_joint_control.positive.json`
- Create: `contracts/examples/directional_joint_control.negative.json`
- Create: `contracts/validate_directional.py`
- Test: `contracts/validate_directional.py`

1. Write the validator and fixtures first so validation fails while the schema/manifest are absent.
2. Define only the ten approved action names and a positive finite `deltaDeg`; reject joint arrays, speed, trajectories, Cartesian values, and additional properties.
3. Require `candidateId`, `traceId`, source text, 120-second expiry, and `requiresConfirmation:true`.
4. Define the fixed mapping table, speed `0.05`, state freshness `500ms`, joint tolerance `1 degree`, no automatic retry, and preview-only deployment default in the manifest.
5. Run `python contracts/validate_directional.py`; expect all positive cases accepted and all negative cases rejected.
6. Run the existing manual and Coke contract validators to prove their semantics were not changed.

## Task 2: Add bilingual Language-to-candidate mapping

**Files:**
- Modify: `thirdhand-voice/voice_agent.py`
- Modify: `thirdhand-voice/voice_bridge.py`
- Create: `thirdhand-voice/test_directional_language_contract.py`
- Test: `thirdhand-voice/test_language_contract.py`

1. Add failing tests for every directional action, default `20`, explicit positive magnitude, candidate skill, TTL, confirmation requirement, and absence of joints/speed/trajectory fields.
2. Add prompt/tool-contract tests containing paired Chinese and English examples such as `向左转` / `turn left`, `抬高` / `raise up`, and `rotate clockwise`.
3. Add one `directional_joint_control(action, delta_deg=20)` Claude tool whose enum is the ten contract actions. Keep degree sign out of the LLM: the action determines the sign in Node; `delta_deg` is a positive magnitude only.
4. Update the bilingual system prompt: unspecified magnitude means 20; explicit magnitude is preserved; vague intensifiers without a number require clarification; never generate joint arrays, speed, or arbitrary multi-joint motion.
5. Map the tool result to a `directional_joint_control@1` candidate in `VoiceBridge._candidate_from_action`.
6. Run the new and existing Voice unit tests without calling Claude or exposing credentials.

## Task 3: Implement deterministic target calculation and lift semantic verification

**Files:**
- Create: `web-control/server/startouch-forward-kinematics.js`
- Create: `web-control/server/directional-joint-control.js`
- Create: `web-control/server/test/startouch-forward-kinematics-smoke.js`
- Create: `web-control/server/test/directional-joint-control-smoke.js`

1. Write failing FK fixture tests using the checked-in six-joint URDF chain and the existing `0.15584m` end-effector offset. Cover zero pose and representative J2/J3 combinations previously cross-checked with the Python model.
2. Implement dependency-free rigid-transform FK for position only; keep joint origins/axes documented as copied from the checked-in URDF.
3. Write failing directional tests for all ten mappings, custom magnitude, exact six-joint target, mechanical-limit rejection, stale/disconnected/non-IDLE rejection, preview-disabled execution, candidate expiry, trace mismatch, replay, and fixed speed.
4. For `lift.up/down`, reject unless the FK displacement has the requested base-frame Z sign and `abs(dz) >= sqrt(dx^2 + dy^2)`. This prevents repeated 20-degree commands from silently becoming mostly horizontal.
5. Implement a dedicated `DirectionalJointOrchestrator`. It must use one full `move_joint` command, verify all changed joints after matching completion plus fresh IDLE state, never retry, and request software stop on timeout/disconnect/uncertain failure.
6. Keep `ManualJointOrchestrator` unchanged except for minimal shared routing if required; directional candidates must not be treated as manual or Coke candidates.

## Task 4: Permit only validated atomic directional commands through the existing 3000 forwarder

**Files:**
- Modify: `web-control/server/language-upstream-bridge.js`
- Modify: `web-control/server/test/language-upstream-bridge-smoke.js`

1. Add a failing test showing an ordinary two-joint command remains rejected.
2. Add a failing test showing a command marked with the internal directional authorization metadata is accepted only when it changes exactly J2 and J3 with equal opposite magnitudes; single-axis directional mappings remain accepted through the normal path.
3. Validate authorization metadata against the target before sending; strip internal metadata from the formal-3000 `servo` message.
4. Keep the existing one-in-flight correlation, formal request matching, state freshness, IDLE, speed-safety, and final six-axis feedback checks.
5. Re-run the existing upstream suite to prove arbitrary multi-joint forwarding is still rejected.

## Task 5: Wire proxy configuration without enabling real directional motion

**Files:**
- Modify: `web-control/server/config.js`
- Modify: `web-control/server/proxy.js`
- Modify: `web-control/server/package.json`
- Create: `web-control/server/test/directional-proxy-wiring-smoke.js`

1. Add `DIRECTIONAL_CONTROL_ENABLED` and `DIRECTIONAL_REAL_CONTROL` as separate flags. The first exposes candidates/preview; the second authorizes hardware dispatch and defaults false.
2. Instantiate the directional orchestrator with the same formal-3000 state source, command sender, software stop, joint limits, speed scale, and request correlation used by existing Language control.
3. Route `directional_joint_control@1` candidates and matching decisions to the directional orchestrator; route all existing candidates exactly as before.
4. Feed upstream bridge events to both orchestrators, but only the orchestrator owning the matching request may consume them.
5. On browser disconnect, clear its directional candidate and stop only if that browser owns an active directional execution.
6. Expose directional readiness, mapping, and real-control state in `/api/runtime-config` and WebSocket config without changing existing response fields.
7. Add npm scripts for the new suites and include them in `npm test`.

## Task 6: Add 9982 confirmation-card labels and 3D preview

**Files:**
- Modify: `web-control/web/js/voice-control.js`
- Modify: `web-control/web/js/main.js`
- Modify: `web-control/server/test/language-browser-smoke.js`
- Modify: `web-control/server/test/browser-smoke.js`

1. Add failing browser tests for the new skill allowlist, all bilingual-independent action labels, default/custom magnitude display, and explicit confirm button requirement.
2. Extend candidate validation to accept only `directional_joint_control@1` with one approved action and positive finite `deltaDeg`.
3. Compute the same target for the 3D preview from fresh six-axis state; show every changed joint, current/target/delta, fixed speed, and `preview only` when real control is disabled.
4. Apply the mechanical-limit and lift FK semantic checks in the browser for early feedback; the Node check remains authoritative.
5. Keep manual joint, gripper, Home, stop, Coke Skill preview, right-side controls, and result rendering unchanged.

## Task 7: Local regression verification

**Files:**
- Verify only; no deployment changes.

1. Run `python contracts/validate_directional.py` and all existing contract validators.
2. Run `python -m unittest -v test_language_contract.py test_directional_language_contract.py` from `thirdhand-voice` with the existing isolated test dependency path if needed.
3. Run focused Node suites: directional contract/FK/orchestrator, upstream, manual control, browser Language, and proxy wiring.
4. Run full `npm test` from `web-control/server`.
5. Run `git diff --check` where available and a file-level whitespace check in this non-Git integration copy.
6. Inspect the final diff and confirm no file under formal 3000, formal 3001, old `thirdhand-staging`, or the running 9981/3002 deployment path was edited.

## Task 8: Copy only reviewed files and start isolated preview staging

**Remote target:**
- `/home/nieqingcao/th0814/thirdhand-language9981/language-sync-20260814-221750`

1. Read-only audit listeners/PIDs/cwds for 3000, 3001, 9981, 3002, 9982, and 3003. Abort if 9982 or 3003 is owned by an unrelated process.
2. Record hashes of remote target files and copy only the reviewed changed files into the new target tree. Do not copy credentials and do not edit launch files for 3000/3001/9981/3002.
3. Start Voice 3003 from the new target tree by inheriting only the already configured runtime environment through a non-printing launcher; never display, log, or write API credentials.
4. Start web 9982 from the new target tree with loopback bind, `VOICE_ENDPOINT=ws://127.0.0.1:3003/v1/voice`, `LANGUAGE_UPSTREAM_WS=ws://127.0.0.1:3000/ws`, `MANUAL_UPSTREAM_CONTROL=1`, `DIRECTIONAL_CONTROL_ENABLED=1`, and `DIRECTIONAL_REAL_CONTROL=0`.
5. Verify HTTP, WebSocket, AI text candidate creation, all ten previews, runtime-config flags, and right-side forwarding. Do not click Execute for any real directional motion.
6. Re-check that the original 3000/3001/9981/3002 PIDs and cwd values are unchanged and healthy.
7. Give the user the SSH tunnel command for 9982/3003 and a preview-only acceptance checklist. Real directional execution remains disabled until the user explicitly authorizes a specific physical test while beside the arm with the E-stop.

