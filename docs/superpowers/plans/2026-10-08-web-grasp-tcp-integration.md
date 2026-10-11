# Web grasp and TCP integration plan

> Execute inline using executing-plans and TDD. User already instructed continuous execution without routine approval pauses.

**Goal:** Connect the current main website to the existing experimental grasp and TCP calibration implementations, with active measured TCP consumed by each grasp session.

**Architecture:** Existing web 9983 → existing Robot 3000 only. Restore missing modules selectively; shared frame normalization and hash-bound repository-relative evidence; one TCP artifact store used by calibration and grasp. Preserve main Dummy and existing controls.

**Spec:** docs/superpowers/specs/2026-10-08-web-grasp-tcp-design.md

### Task 1: Restore modules and portable runtime wiring

**Files:** apps/web/src/grasp/, apps/web/src/tcp-calibration/, tools/tcp_calibration/, tools/frames/canonical_robot_client.js, apps/web/public/tcp-calibration.html, apps/web/public/js/tcp-calibration.js, apps/web/public/css/tcp-calibration.css, apps/web/src/config.js, apps/web/src/server.js, configs/vision/, configs/runtime/manual-control.json, tests/node/web/*integration*.test.js.

**Interfaces:** createFromFile(file, {ownerToken, tcpStore, webUrl}) creates a lazy grasp controller. createTcpCalibrationRoutes accepts canMutate() for runtime ownership checks. loadPolicy(filename) resolves relative bindings against the policy file while keeping strict hashes. Gateway exposes tcpCalibration readiness and routes plus grasp status. Unsupported teach uses explicit local stationary-hold confirmation without sending mode commands.

- [x] Add tests showing main runtime cannot currently construct its configured grasp/TCP components; verify failing.
- [x] Import selected feature modules/tests and notices, retain main integrations, filter fixed_tcp_demo, resolve relative frame policy paths, add re-bound handeye/config/profile.
- [x] Add unsupported-teach capture test and implement stationary manual-hold UI confirmation.
- [x] Run node --test tests/node/web/grasp-*.test.js tests/node/web/tcp-calibration-*.test.js tools/frames/test_canonical_robot_client.js; commit.

### Task 2: Consume active TCP and render grasp workflow

**Files:** apps/web/src/tcp-calibration/artifact-store.js, apps/web/src/grasp/{index,geometry,coordinator}.js, apps/web/src/server.js, apps/web/public/{index.html,js/main.js,css/style.css}, tests/node/web/grasp-tcp-integration.test.js, tests/node/web/grasp-ui.test.js.

**Interfaces:** store.activeTcp(framePolicyId) returns null or immutable {id,source,T_flange_grasp_tcp}; throws for corrupt/unverified/mismatched active data. Coordinator resolves TCP before marking start active, freezes session config and publishes tcp plus plan/progress/result. Runtime/status endpoints expose current TCP or an explicit unavailable reason. UI reads current HTTP state on connect and renders status consistently with WS broadcasts.

- [x] Test active candidate identity, hash corruption, measured off-axis TCP and 90-degree rotation, freeze across artifact changes, and no duplicate 60 mm backoff; watch failures.
- [x] Implement full rigid transform geometry and per-session resolver, ownership checks between calibration and grasp, dynamic runtime config/provenance.
- [x] Test real UI rendering/recovery for progress, errors, target/TCP and completion; implement panel and calibration link.
- [x] Run grasp/TCP test set; commit.

### Task 3: Offline end-to-end and regression verification

**Files:** tests/node/web/grasp-tcp-e2e.test.js, docs/hardware/web-grasp-tcp-integration.md.

**Interfaces:** Simulated transport boundary supplies real coordinator and gateway with measured artifact and frame-bound vision. HTTP start plus WS/HTTP status must reach complete with measured TCP identity and literal expected grip coordinates; stop/failure preserve ownership semantics.

- [x] Exercise start → depth → plan → motion → contact → lift through real gateway/controller with synthetic external IO only; watch fail if any boundary is missing, then fix.
- [x] Document activation semantics, fallback/retreat, configuration, restart and offline-vs-live verification boundary.
- [x] Run full Node suite and TCP Python tests. Compare baseline failures, never label partial suite as full success. Commit and request one fresh read-only reviewer of base..HEAD; fix important findings with regression tests.

## Review Focus

1. Missing/corrupt active TCP must not silently fall back (Task 2).
2. Rotated/off-axis transform must preserve tool orientation and convert SDK coordinates exactly once (Task 2).
3. Unsupported teach must never send a mode-changing command (Task 1).
4. Concurrent activation/capture/teach/grasp/active depth must not share motion ownership (Task 2).
5. Gateway restart/reconnect must expose active TCP and workflow state without prior broadcasts (Tasks 2–3).
