# Web And Startouch Robot Service Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Migrate the current Startouch control page into `apps/web` and its hardware backend into an isolated `services/robot` process managed by `./thirdhand`.

**Architecture:** The browser connects only to Web Gateway on port 9983. Web Gateway serves the existing UI and proxies an allowlisted robot WebSocket protocol to Robot Service on loopback port 3000. Robot Service alone spawns the Python SDK bridge and owns `can0`; service startup and browser connection never imply SDK connection or motion.

**Tech Stack:** Node.js 24, `ws`, built-in Node HTTP server, Python 3.11, Startouch SDK, existing HTML/CSS/Three.js/URDF.

**Spec:** `docs/superpowers/specs/2026-09-10-unified-platform-skills-design.md`

## Global Constraints

- Work only in `/home/nieqingcao/ThirdHand/UIEAclub_ThirdHand_VLA`; do not modify original source directories.
- Keep branch `refactor/unified-platform-foundation`; do not merge or push.
- Real hardware remains opt-in. Automated tests use `STARTOUCH_SIMULATE=1`.
- Robot Service binds `127.0.0.1:3000`; Web Gateway binds the configured LAN address on 9983.
- Connecting a browser does not connect the SDK. Connecting the SDK does not send home, zero, servo, gripper, or Cartesian commands.
- Only Robot Service may spawn the Startouch Python bridge or own `can0`.
- Preserve J1-J6 limits, speed limits, stale-feedback checks and accidental all-zero protection.
- Software stop is not described as an independent hardware emergency stop.
- D435/Lumos and old combined-proxy runtime logic stay outside formal code.
- Every runtime process writes its launcher readiness marker and removes it on shutdown.

---

### Task 1: Robot Motion Policy

**Files:**
- Create: `services/robot/src/motion-policy.js`
- Create: `tests/node/robot_service/motion-policy.test.js`

**Interfaces:**
- Produces: `validateJointTarget(joints, limits)`, `isAccidentalZeroTarget(target, current, source)`, and `moveTimeFor(target, current, maxSpeeds, options)`.

- [x] **Step 1: Write failing tests**

Cover wrong joint count, non-finite values, all six configured limits, explicit home exception, accidental non-home all-zero rejection, and bounded move time.

- [x] **Step 2: Verify RED**

Run: `node --test tests/node/robot_service/motion-policy.test.js`
Expected: FAIL because `motion-policy.js` does not exist.

- [x] **Step 3: Implement pure policy functions**

The module has no SDK, process, socket or filesystem imports. It returns stable error codes and never substitutes zero for unknown current state.

- [x] **Step 4: Verify GREEN**

Run the Task 1 test and expect all cases to pass.

- [x] **Step 5: Commit**

Commit message: `feat: add Startouch motion policy`.

### Task 2: Isolated Robot Service

**Files:**
- Create: `services/robot/package.json`
- Create: `services/robot/src/config.js`
- Create: `services/robot/src/startouch-bridge.js`
- Create: `services/robot/src/startouch_bridge.py`
- Create: `services/robot/src/robot-controller.js`
- Create: `services/robot/src/server.js`
- Create: `tests/node/robot_service/server.test.js`
- Create: `tests/python/robot_service/test_bridge_simulation.py`
- Modify: `package.json`
- Modify: `package-lock.json`

**Interfaces:**
- HTTP `GET /health` returns service state without opening hardware.
- WebSocket `/ws` accepts `connect`, `disconnect`, `status`, `servo`, `preset`, `gripper`, `software_stop`, `estop`, and `ping`.
- Emits existing browser-compatible `config`, `connection`, `robot_state`, `motion_state`, `command_status`, `software_stop`, `sdk_log`, `error`, and `pong` messages.

- [x] **Step 1: Write failing simulation tests**

Start the server with a temporary ready file, dynamic port, project-local SDK path and `STARTOUCH_SIMULATE=1`. Assert health is ready but disconnected; opening WebSocket causes no robot connection; explicit connect yields state; safe servo and gripper complete; accidental zero is rejected; shutdown removes readiness.

- [x] **Step 2: Verify RED**

Run Node and Python robot-service tests. Expected: missing modules and entrypoints.

- [x] **Step 3: Copy and constrain the bridge**

Copy the accepted bridge sources from `migration/sources/startouch-web-vla/web-control/server/`. Replace old home-directory defaults with required/project-local configuration. Keep SDK import and `SingleArm` construction inside explicit `connect`.

- [x] **Step 4: Implement controller and server**

The controller owns state and command validation. The server binds loopback, writes readiness only after listen, and performs graceful bridge shutdown on SIGTERM.

- [x] **Step 5: Verify GREEN**

Run robot Node/Python tests, process-leak check, and source-boundary audit.

- [x] **Step 6: Commit**

Commit message: `feat: migrate isolated Startouch robot service`.

### Task 3: Web Gateway And Control Page

**Files:**
- Create: `apps/web/package.json`
- Create: `apps/web/src/config.js`
- Create: `apps/web/src/static-server.js`
- Create: `apps/web/src/robot-proxy.js`
- Create: `apps/web/src/server.js`
- Create: `apps/web/public/**`
- Create: `tests/node/web/server.test.js`

**Interfaces:**
- HTTP `GET /health` reports Web and Robot upstream state.
- Static `/` serves the migrated page.
- WebSocket `/ws` forwards only allowlisted robot commands to `ws://127.0.0.1:3000/ws`.
- Vision HTTP paths are reserved and return explicit 503 until Vision Service is migrated.

- [x] **Step 1: Write failing gateway tests**

Use a stub Robot WebSocket service. Assert index/static assets load, path traversal is rejected, robot config/state is relayed, robot commands are forwarded, unsupported vision/grasp commands are rejected, and upstream loss does not crash Web Gateway.

- [x] **Step 2: Verify RED**

Run: `node --test tests/node/web/server.test.js`.
Expected: missing Web Gateway modules.

- [x] **Step 3: Copy frontend assets**

Copy the current page from the migration snapshot into `apps/web/public`. Do not copy combined `proxy.js`, D435/Lumos bridge code, logs, environments, caches or secrets.

- [x] **Step 4: Implement gateway**

Use built-in HTTP serving and `ws`. Normalize static paths under `public`; mount robot model assets from `assets/robot`; keep Robot Service loopback-only.

- [x] **Step 5: Verify GREEN**

Run gateway tests and load the page in a browser against simulated Robot Service.

- [x] **Step 6: Commit**

Commit message: `feat: migrate Startouch web gateway`.

### Task 4: Robot Model Assets And Runtime Profiles

**Files:**
- Create locally: `assets/robot/startouch-v3/**` (Git ignored)
- Create: `configs/runtime/manual-control-simulation.json`
- Create: `configs/runtime/manual-control.json`
- Modify: `configs/runtime/default.json`
- Modify: `tests/unit/platform/test_repository_layout.py`
- Modify: `tests/integration/test_simulated_lifecycle.py`

**Interfaces:**
- Simulation profile: Robot `127.0.0.1:13000`, Web `192.168.58.68:9983`, no CAN.
- Hardware profile: Robot `127.0.0.1:3000`, Web `192.168.58.68:9983`, explicit browser connect required.
- Existing foundation `simulation` profile remains unchanged.

- [x] **Step 1: Write failing profile and asset tests**

Assert both profiles use formal entrypoints, Robot remains loopback-only, simulation sets `STARTOUCH_SIMULATE=1`, model metadata is recorded, and default does not silently enable hardware.

- [x] **Step 2: Verify RED**

Run platform and integration tests; expect missing profiles/assets.

- [x] **Step 3: Copy model assets and add profiles**

Copy URDF/STL from the original project without modifying it. Record provenance. Configure the launcher environment and shutdown order.

- [x] **Step 4: Verify GREEN**

Run profile tests, start/status/restart/stop the manual simulation profile, and confirm no process opens `can0`.

- [x] **Step 5: Commit**

Commit message: `feat: add manual control runtime profiles`.

### Task 5: Documentation And Acceptance

**Files:**
- Modify: `docs/RUN_GUIDE.md`
- Modify: `docs/OPERATIONS.md`
- Modify: `docs/DIRECTORY_MAP.md`
- Create: `docs/services/ROBOT_SERVICE_PROTOCOL.md`
- Create: `docs/apps/WEB_GATEWAY.md`
- Modify: `README.md`

**Interfaces:**
- Documents exact start/stop/status commands, URLs, command/event protocol, simulation versus hardware behavior, current unavailable vision/voice features, port ownership, rollback and safety.

- [x] **Step 1: Document verified behavior**

Record the tested LAN URL, simulation command, hardware opt-in command, logs, health endpoints and known 9983 Tailscale listener coexistence.

- [x] **Step 2: Run acceptance**

Run all Python and Node foundation tests plus new Robot/Web tests, boundary audit, `git diff --check`, simulation browser HTTP checks, lifecycle idempotence and residual-process checks.

- [x] **Step 3: Keep services stopped**

After acceptance, stop the simulation profile. Confirm no `proxy.js`, Robot Service, Web Gateway, Python bridge or fake service remains.

- [x] **Step 4: Commit**

Commit message: `docs: document migrated manual control services`.
