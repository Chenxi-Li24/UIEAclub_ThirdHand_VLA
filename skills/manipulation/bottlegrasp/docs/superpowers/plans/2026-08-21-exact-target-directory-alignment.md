# Exact Target Directory Alignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Align `bottlegrasp` with the approved target tree while ensuring every newly listed module has a real, independently testable responsibility rather than being an empty placeholder.

**Architecture:** Keep `common` as the only V/A contract layer, `vision` and `action` as reusable domains, and `apps` as side-effect-owning composition roots. Remove migration-only source paths after every active consumer uses canonical imports; preserve the unusable upstream Web snapshot as an artifact instead of active application code.

**Tech Stack:** Python 3.10+, dataclasses, NumPy, PyYAML, pytest, Node.js CommonJS and built-in `node:test`, C++14/CMake.

**Spec:** `docs/superpowers/specs/2026-08-21-functional-module-reorganization-design.md` plus the user-approved target directory image.

## Global Constraints

- V must not import A or send robot commands.
- Library imports must not open hardware, connect sockets, start processes, parse CLI arguments, or call `process.exit()`/`sys.exit()`.
- Every target-tree source file must implement one named responsibility and have an observable behavior test.
- Physical execution remains fail-closed and `robot_control_enabled` remains false unless an injected application explicitly enables an execution gate.
- Real camera, CUDA, Web service, and robot tests remain opt-in.
- Migration-only old source paths are removed only after active imports and spawn paths use canonical locations.
- Work stays inside `bottlegrasp`; no commit is created because the whole subtree is untracked in its parent repository.

---

### Task 1: Complete common contracts and Action safety/core interfaces

**Files:**
- Create: `src/thirdhand_va/common/errors.py`
- Create: `src/thirdhand_va/common/contracts/arm_state.py`
- Modify: `src/thirdhand_va/common/contracts/__init__.py`
- Modify: `src/thirdhand_va/action/calibration/handeye.py`
- Create: `src/thirdhand_va/action/safety/workspace-check.js`
- Create: `src/thirdhand_va/action/safety/execution-gate.js`
- Create: `src/thirdhand_va/action/adapters/robot-client.js`
- Create: `src/thirdhand_va/action/adapters/vision-client.js`
- Create: `src/thirdhand_va/action/grasp/grasp-controller.js`
- Modify: `src/thirdhand_va/action/grasp/workflow-client.js`
- Create: `src/thirdhand_va/action/operator/controller.js`
- Test: `tests/common/test_arm_state.py`
- Test: `tests/action/safety/safety-gate.test.js`
- Test: `tests/action/adapters/clients.test.js`
- Test: `tests/action/grasp/grasp-controller.test.js`
- Test: `tests/action/operator/controller.test.js`

**Interfaces:**
- `ArmState.from_message(message, received_monotonic_ns, stationary_since_monotonic_ns) -> ArmState`
- `checkWorkspace(pointM, bounds) -> { allowed, blockers }`
- `evaluateExecutionGate(context) -> ActionDecision`
- `RobotClient.send(command) -> boolean`, using an injected transport.
- `VisionClient.accept(message) -> boolean`, emitting only validated versioned results.
- `GraspController.start(request) -> { accepted, ... }`, executing only a gate-approved plan through `RobotClient`.
- `WorkflowClient` reports completion through an injected callback and never terminates its host process.
- `OperatorController.start(targetIndex)` and `.stop()` delegate to injected workflow/safety dependencies.

- [x] Write contract and Action module tests with literal expected decisions and invalid-input cases.
- [x] Run them and confirm missing modules/exports fail for the intended reason.
- [x] Implement immutable contracts, fail-closed safety decisions, and injected clients/controllers.
- [x] Move the existing `ArmState` implementation from calibration into common without changing its validation semantics.
- [x] Run the new tests and all existing common/Action tests.

### Task 2: Replace incomplete application snapshots with target application roots

**Files:**
- Create: `configs/action.yaml`
- Move/archive: `apps/bottle_pick/web-server.js` -> `artifacts/integration/legacy-web-server.js`
- Create: `apps/bottle_pick/web_server.js`
- Replace: `apps/bottle_pick/operator-run.js` and `operator-stop.js` with `apps/bottle_pick/run.js`
- Modify: `src/thirdhand_va/action/adapters/camera-bridge.js`
- Create: `tests/integration/web-server.test.js`
- Create: `tests/integration/app-run.test.js`

**Interfaces:**
- `createWebServer({ cameraBridge, host, port }) -> { server, start, stop }` uses Node HTTP and exposes `/health` plus `/api/vision/select` without robot control.
- `main(argv, dependencies) -> Promise<number>` supports `start TARGET` and `stop` while keeping socket/process ownership in the app.
- `CameraBridge.buildSpawnSpec()` starts `python -m apps.bottle_pick.camera_bridge` from the repository root.

- [x] Write HTTP and CLI-app tests that use injected in-memory transports and no network/hardware dependencies.
- [x] Run them and confirm the target app files are missing.
- [x] Implement `web_server.js`, `run.js`, and canonical camera spawn configuration.
- [x] Archive the non-runnable upstream snapshot and remove obsolete app files.
- [x] Run integration and adapter tests.

### Task 3: Add independently runnable target debug scripts

**Files:**
- Create: `scripts/vision/camera_smoke.py`
- Create: `scripts/vision/record_rgbd.py`
- Rename: `scripts/vision/run_replay.py` -> `scripts/vision/replay_rgbd.py`
- Create: `scripts/vision/debug_perception.py`
- Create: `scripts/vision/debug_selection.py`
- Create: `scripts/vision/debug_geometry.py`
- Create: `scripts/vision/debug_pipeline.py`
- Create: `scripts/action/debug_calibration.py`
- Create: `scripts/action/debug_alignment.js`
- Create: `scripts/action/debug_grasp.js`
- Rename: `scripts/action/operator-control.sh` -> `scripts/action/operator_control.sh`
- Test: `tests/integration/test_debug_entrypoints.py`
- Test: `tests/action/debug-scripts.test.js`

**Interfaces:**
- Each script exposes `build_parser`/`main` or `main(argv)` and performs no side effect on import.
- Hardware scripts require `--allow-camera`; replay/selection/geometry/grasp debug paths run from explicit recorded or synthetic inputs.
- Every output is structured JSON and includes `robot_control_enabled: false`.

- [x] Write subprocess tests for help, safe defaults, synthetic selection, and fail-closed grasp debug output.
- [x] Run them and confirm missing entry points fail.
- [x] Implement the smallest target scripts by composing canonical public modules.
- [x] Remove superseded CLI files only after tests use the new entries.
- [x] Run script tests, compile checks, and offline validation.

### Task 4: Mirror the target tests/docs layout and remove migration paths

**Files:**
- Move Action tests under `tests/action/{observation,alignment,grasp,safety,adapters,operator}`.
- Move: `docs/validation-protocol.md` -> `docs/vision/validation-protocol.md`
- Move: `docs/3100-vision-integration.md` -> `docs/integration/3100-vision-integration.md`
- Create: `docs/vision/modules.md`
- Create: `docs/action/modules.md`
- Create: `docs/integration/contracts.md`
- Modify: `README.md`
- Modify: `docs/architecture.md`
- Remove: old Python re-export modules/packages, `integration/web-control`, `operator`, root script wrappers, and their compatibility-only tests.
- Modify: `tests/common/test_repository_layout.py`

**Interfaces:**
- Only `thirdhand_va.common`, `.vision`, and `.action` are active source domains.
- Documentation commands resolve to existing target-tree files.
- The repository layout test checks required target files and rejects migration-only source paths.

- [x] Expand the layout test with the approved target files and forbidden migration paths.
- [x] Run it and confirm it fails before cleanup.
- [x] Move tests/docs, update commands, then delete migration-only wrappers with `apply_patch`.
- [x] Update every active import and adapter spawn path to canonical locations.
- [x] Run layout, import, documentation command, Python, and Node tests.

### Task 5: Full verification and evidence refresh

**Files:**
- Modify: `artifacts/integration/reorganization-verification.json`

**Interfaces:**
- Verification evidence records exact Python/Node totals, skipped hardware tests, target layout status, offline validation status, and `robot_control_enabled=false`.

- [x] Install/editable-build the final package and verify JSON Schema package data.
- [x] Run all non-hardware Python tests and all Node tests from their final directories.
- [x] Run default hardware collection and confirm tests skip without opt-in.
- [x] Run offline spatial validation and assert no camera opened and robot control stayed false.
- [x] Compile Python, syntax-check JavaScript/shell, scan V-to-A imports and machine-specific paths.
- [x] Refresh verification JSON and print the final target tree.
