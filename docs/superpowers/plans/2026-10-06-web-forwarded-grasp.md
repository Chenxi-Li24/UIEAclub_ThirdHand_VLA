# Web-forwarded bottle grasp Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the old web grasp entry with one complete 60 mm TCP bottle-grasp sequence over the existing web forwarding route.

**Architecture:** A geometry module builds frame-correct segmented waypoints. A correlated 9983/ws client feeds a coordinator which reuses wrist-first depth acquisition and publishes status through the current gateway. Only the gateway is restarted; the SDK connection stays intact.

**Tech Stack:** Node.js 24, ws, node:test, existing hand-eye/frame artifacts and active-depth planner.

**Spec:** docs/superpowers/specs/2026-10-06-web-forwarded-grasp-design.md

## Global Constraints

- T_flange_grip: [0.060,0,0] m, approximate/user-specified, not measured.
- T_flange_sdk_tool: [0.17334,0,0] m; SDK and hand-eye unchanged.
- Preapproach 0.200 m preserving current SDK height; bounded final approach <=0.220 m; lift +0.050 m base Z; segments <=0.005 m. Updated after live rising-approach camera truncation; see spec.
- Surface point, no half-width advance; no placement or automatic release.
- Imported autonomy stays false; perception robotControlEnabled remains false.
- All actuation uses 9983/ws; no direct CAN, protected execution route or reconnect.
- Preserve local root and unrelated remote changes. Commit focused experimental changes, no unsolicited push/merge.

## Review Focus

1. A rotated wrist must rotate the 60 mm offset and SDK correction exactly once.
2. Late/unrelated acknowledgments must not advance phases or authorize closure.
3. A held bottle must not lose torque because an idle failure closes the SDK.
4. A concurrent manual command or target switch must not alter an active grasp.
5. Contact closure differs from reaching zero; lift requires fresh contact evidence.

---

### Task 1: Frame-correct geometry and experiment config

**Files:** Create apps/web/src/grasp/geometry.js, apps/web/configs/web-grasp.json; Test tests/node/web/grasp-geometry.test.js.

**Interfaces:** buildGraspGeometry({observation,stableId,robot,config}) returns target, orientation, grip/flange/SDK points, segmented preapproach/approach/lift paths. getGripPosition(robot,config), validateConfig(config), validateJoints(joints,limits) are pure helpers.

- [ ] Write tests: identity target [0.4,0,0.2] -> flange [0.34,0,0.2], SDK [0.51334,0,0.2]; quarter-turn target -> flange Y -0.060 and SDK Y +0.11334; corrupt/stale projection rejected; surface unchanged; segments <=0.005 m.
- [ ] Run node --test tests/node/web/grasp-geometry.test.js; expect missing geometry module failure.
- [ ] Implement pure matrix composition using the existing rigid-transform helper; add user-specified 60 mm config separately from measured action config.
- [ ] Run geometry tests and npm run test:node; expect focused green, record full-suite result.
- [ ] Commit the focused Task 1 files.

### Task 2: Correlated web-only robot transport

**Files:** Create apps/web/src/grasp/robot-client.js; Test tests/node/web/grasp-robot-client.test.js.

**Interfaces:** WebRobotClient({url,now,stateMaxAgeMs}) exposes ready(), state(), command(payload,timeoutMs), preview(pose), stop(), close(), plus execute(primitive) for existing depth-coordinator adaptation.

- [ ] Write real local-WebSocket tests for fresh robot_state, accepted-before-complete, late wrong IDs, reached false, stale state, invalid joints, socket loss and idle close without connect/disconnect or stop commands.
- [ ] Run transport tests; expect missing module failure.
- [ ] Implement one-in-flight correlation, fresh canonical input validation and bounded joint-step adapter using servo. Do not connect the native SDK.
- [ ] Run transport tests and npm run test:node; record output.
- [ ] Commit Task 2 files.

### Task 3: One-shot coordinator with depth, contact and holding

**Files:** Create apps/web/src/grasp/coordinator.js, apps/web/src/grasp/index.js; Test tests/node/web/grasp-coordinator.test.js.

**Interfaces:** createGraspController({config,robotClient,visionClient,depthCoordinator}) returns status(), start(stableId,requestId), stop(sessionId), close(), and emits grasp.status. Production factory constructs the existing depth coordinator with web-only transport.

- [ ] Write simulated-feedback tests for depth -> all checked motion -> open -> preapproach -> target refresh -> approach -> close -> contact -> lift/hold without phase confirmation; duplicate start, changed target, failed contact/no lift, stop while moving and idle failure preserving SDK.
- [ ] Run coordinator tests; expect missing factory failure.
- [ ] Implement single-session ownership, all-path preview and sequential segment execution. Treat gripper contact as fresh stable nonzero width, not a false calibration approval.
- [ ] Run coordinator tests and npm run test:node; record output.
- [ ] Commit Task 3 files.

### Task 4: Replace web entry and deploy without SDK restart

**Files:** Modify apps/web/src/server.js, apps/web/src/robot-proxy.js, apps/web/public/js/main.js; Test tests/node/web/grasp-gateway.test.js.

**Interfaces:** Optional WEB_GRASP_CONFIG activates our controller; /api/grasp start/stop/status and runtime config expose only public capability/status. The old frontend commands are retired. RobotProxy rejects competing actuation while an owner is active.

- [ ] Write gateway tests for unavailable-default, validated start, foreign Origin rejection, status broadcast, duplicate start, motion-owner rejection and always-available stop.
- [ ] Run gateway tests; expect absent routes/ownership failures.
- [ ] Implement targeted integration and browser status rendering, preserving old imported capability false and unrelated language/manual UI.
- [ ] Run npm run test:node, focused all grasp tests and frontend syntax checks. Save complete logs.
- [ ] Commit focused integration changes; produce patch/review package and get a fresh whole-patch code review.
- [ ] Resolve important review findings with red/green tests, rerun the whole Node suite.
- [ ] Deploy only hash-checked targeted changes and separate new modules/config; back up overwritten files. Restart only the idle web gateway with preserved environment plus experimental config. Confirm original Robot/bridge/Vision PIDs and SDK file hashes unchanged.
- [ ] Execute the current selected bottle through the web API after fresh path/depth checks, record the full event trace and inspect the physical result. Stop truthfully on a concrete runtime failure; never claim IK preview or simulated success is a real grasp.
