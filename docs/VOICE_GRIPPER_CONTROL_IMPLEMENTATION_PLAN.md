# Voice-to-Gripper Authorized Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended for this task) or `superpowers:executing-plans` to implement this plan task by task. Use `superpowers:test-driven-development` for each behavior change and `superpowers:verification-before-completion` before reporting completion.

- Date: 2026-09-13
- Status: implementation plan; no runtime code has been changed
- Delivery scope: approved Phase 0 through Phase 2 only
- Branch constraint: remain on `refactor/unified-platform-foundation`
- Repository constraint: do not commit, push, merge, rebase, or switch branches unless the user separately authorizes it

**Goal:** Connect speech or text candidates such as `gripper.open` and `gripper.close` to the real Startouch gripper through a server-side plan, exact one-use authorization, typed execution primitive, current Robot Service safety checks, and real feedback verification.

**Architecture:** The browser continues to proxy speech through `/voice`, vision through `/vision`, and manual robot controls through `/ws`. AI-originated physical actions use a new `/plan` route to an Orchestrator on loopback port `3200`. Orchestrator creates a server-owned `TaskPlan`; Authorization binds one operator confirmation to that exact plan digest; Task Engine consumes the grant once; `manipulation.gripper-control` sends a typed primitive over a private `/execution` Robot Service route. Robot Service remains the only `can0` and Startouch SDK owner.

**Tech Stack:** Node.js 24 CommonJS services, browser ES modules, `ws`, JSON Schema Draft 2020-12, Ajv 8, Node `crypto`, Node built-in test runner, existing launcher/runtime profiles, existing Startouch bridge.

**Spec:** [`VOICE_ACTION_CONTROL_CHAIN_DESIGN.md`](VOICE_ACTION_CONTROL_CHAIN_DESIGN.md)

## Global Constraints

1. Do not stop, restart, adopt, or kill currently running services until the Phase 0 operator checkpoint is explicitly approved. Current externally started services may be serving ports `3000`, `3004`, `3100`, and `9983`.
2. Starting a process, opening the page, reconnecting WebSocket, refreshing the page, loading a model, or restoring launcher state must never connect the SDK, enable motors, command the gripper, or move any arm joint.
3. Robot Service is the sole owner of Startouch SDK and `can0`. Browser, Orchestrator, Skill Workers, Vision, Speech, Model, and Supervisor must not import `startouch` or open SocketCAN.
4. Keep existing browser manual controls on `/ws`. Do not broaden `apps/web/src/robot-proxy.js` to accept candidate, authorization, or typed execution messages.
5. Every AI-originated physical action must pass `/plan -> TaskPlan -> Authorization -> Task Engine -> Skill Worker -> Robot /execution`.
6. Unknown schemas, message types, intents, Skill IDs, operations, properties, stale state, missing readiness, expired grants, digest mismatch, replay, and duplicate confirmation fail closed.
7. A software stop is not a hardware emergency stop. Keep the current operator warning, and require physical emergency-stop or power-isolation access for hardware acceptance.
8. Do not import runtime code from `History/` or any old project directory. Historical code may be read only as migration evidence.
9. Phase 0–2 may enable only `gripper.open` and `gripper.close`. Joint jog, Home, bottle picking, visual target execution, active view, VLA, ACT, and Diffusion Policy remain unavailable through `/plan`.
10. Use simulation and fake backends before hardware. Hardware execution requires a separate explicit operator approval after the dry-run evidence is presented.
11. Because the user has prohibited commits, each task ends with a review checkpoint rather than a commit. Preserve a clean audit trail with `git status --short`, focused test output, and `git diff --check`.

## Protocol Baseline

The initial `/plan` browser protocol is `thirdhand.plan.v1` and uses these exact messages:

```json
{"type":"candidate.submit","candidate":{"candidateId":"uuid","traceId":"uuid","intent":"gripper.open","source":"voice","transcript":"打开夹爪"}}
```

```json
{"type":"plan.proposed","proposal":{"schema":"thirdhand.plan-proposal.v1","proposalId":"uuid","planDigest":"sha256:...","expiresAt":"2026-09-13T10:00:30.000Z","plan":{},"readiness":{},"risks":["夹爪运动可能造成夹伤或挤压。"]}}
```

```json
{"type":"authorization.grant","proposalId":"uuid","planId":"uuid","planRevision":1,"planDigest":"sha256:..."}
```

The terminal execution response is a `thirdhand.skill-result.v1` carried in:

```json
{"type":"skill.result","result":{"schema":"thirdhand.skill-result.v1","taskId":"uuid","traceId":"uuid","skillId":"manipulation.gripper-control","status":"completed","reason":{"code":"target_reached","message":"Gripper reached the authorized target"},"output":{"startedAt":"...","finishedAt":"...","requestedPercent":100,"actualPercent":99.2}}}
```

No browser-supplied percentage, timeout, tolerance, Skill ID, target reference, or operation is trusted at authorization time. Those values are recovered from the server-stored proposal.

## Task 1: Make Launcher Port Ownership Fail Closed

**Files:**

- Modify: `apps/launcher/src/service-supervisor.js`
- Modify: `apps/launcher/src/state-store.js`
- Modify: `tests/node/launcher/service-supervisor.test.js`
- Add: `tests/node/launcher/port-probe.test.js`

**Interfaces:**

```js
async function probeTcpPort({ host, port, timeoutMs = 250 })
// -> { occupied: boolean, errorCode: string | null }

async ServiceSupervisor.preflight()
// -> { ok: boolean, services: [{ id, state, reason, bind, port }] }
```

The states used by `preflight()` are exactly `owned_running`, `available`, and `blocked_external`. A listening port whose PID identity is not proven by `pid + processStartMarker + commandHash` is `blocked_external`; it is never silently adopted.

**Step 1: Write failing port-probe tests**

Add tests that open an ephemeral TCP server and assert that `probeTcpPort()` reports `occupied: true`, then close it and assert `occupied: false`. Also test `ECONNREFUSED` as available and an invalid host as an explicit probe error.

```js
test('reports a listening TCP endpoint as occupied', async t => {
  const server = net.createServer();
  await listen(server);
  t.after(() => close(server));
  const address = server.address();
  assert.deepEqual(
    await probeTcpPort({ host: '127.0.0.1', port: address.port }),
    { occupied: true, errorCode: null },
  );
});
```

Run:

```bash
node --test tests/node/launcher/port-probe.test.js
```

Expected: FAIL because `probeTcpPort` does not exist.

**Step 2: Implement the minimal TCP probe**

Use `node:net`, always destroy the socket, and distinguish `ECONNREFUSED` from DNS, permission, and timeout failures. Export the helper from `service-supervisor.js` so the unit test exercises production code.

**Step 3: Write failing preflight tests**

Add cases proving:

- an occupied unrecorded service port blocks startup before `spawn` is called;
- an occupied port with matching launcher state is `owned_running`;
- a PID identity mismatch is `blocked_external` with reason `process_identity_mismatch`;
- one blocked service prevents every later service from spawning;
- `stopAll()` still refuses to terminate a process it does not own.

Run:

```bash
node --test --test-name-pattern="preflight|external|identity" tests/node/launcher/service-supervisor.test.js
```

Expected: FAIL because startup has no all-service preflight.

**Step 4: Implement all-service preflight**

Perform preflight for all enabled services before the first spawn. Persist diagnostic state without replacing valid owned records. Throw one error listing every blocked service and port. Do not add process discovery or kill logic.

Required error shape:

```js
error.code = 'external_service_ownership';
error.services = [{ id: 'robot', bind: '127.0.0.1', port: 3000, reason: 'external_port_in_use' }];
```

**Step 5: Verify Phase 0 logic without touching live services**

```bash
node --test tests/node/launcher/port-probe.test.js tests/node/launcher/service-supervisor.test.js
npm run test:launcher
git diff --check
git status --short
```

Expected: all launcher tests pass; no live project process was started or stopped.

## Task 2: Add Plan, Authorization, and Execution Contracts

**Files:**

- Add: `platform/contracts/schemas/plan-proposal.schema.json`
- Add: `platform/contracts/schemas/task-authorization-v2.schema.json`
- Add: `platform/contracts/schemas/execution-primitive.schema.json`
- Modify: `tests/node/contracts/contracts.test.js`
- Modify: `docs/SKILL_PROTOCOL.md`

**Contract decisions:**

- Keep `thirdhand.task-plan.v1` unchanged.
- Add `thirdhand.task-authorization.v2`; v1 remains readable but cannot authorize Phase 2 execution.
- Add `thirdhand.execution-primitive.v1` with only `gripper.set` in Phase 2.
- Set `additionalProperties: false` at every object layer.
- Store authorization consumption state server-side; do not put mutable `consumed` fields in the signed grant.

Required authorization v2 fields:

```json
{
  "schema": "thirdhand.task-authorization.v2",
  "authorizationId": "uuid",
  "taskId": "uuid",
  "planId": "uuid",
  "planRevision": 1,
  "targetRef": "robot:gripper",
  "planDigest": "sha256:<64 lowercase hex characters>",
  "authorizedOperations": ["gripper.set"],
  "issuedAt": "date-time",
  "expiresAt": "date-time"
}
```

Required execution primitive fields:

```json
{
  "schema": "thirdhand.execution-primitive.v1",
  "primitiveId": "uuid",
  "traceId": "uuid",
  "taskId": "uuid",
  "authorizationId": "uuid",
  "planDigest": "sha256:<64 lowercase hex characters>",
  "operation": "gripper.set",
  "parameters": {
    "positionPercent": 100,
    "tolerancePercent": 2,
    "timeoutMs": 3000
  }
}
```

**Step 1: Add failing positive and negative contract tests**

Cover valid examples plus missing digest, uppercase digest, extra fields, out-of-range percentage, zero timeout, unknown operation, and v1 authorization presented where v2 is required.

Run:

```bash
node --test tests/node/contracts/contracts.test.js
```

Expected: FAIL because the new schemas are unknown.

**Step 2: Add strict schemas**

Use Draft 2020-12 syntax already loaded by `createContractValidator()`. Do not modify the validator to guess or coerce schema versions.

**Step 3: Document the exact wire fields**

Update `docs/SKILL_PROTOCOL.md` with the v2 binding rule, the immutable digest, one-use server-side consumption, and `gripper.set` parameter units.

**Step 4: Verify contracts**

```bash
npm run test:contracts
git diff --check
```

## Task 3: Implement Canonical Plan Digest and One-Use Authorization Store

**Files:**

- Add: `platform/authorization/src/canonical-json.js`
- Add: `platform/authorization/src/authorization-store.js`
- Add: `platform/authorization/index.js`
- Add: `tests/node/authorization/canonical-json.test.js`
- Add: `tests/node/authorization/authorization-store.test.js`
- Modify: `package.json`

**Interfaces:**

```js
function canonicalize(value) // deterministic JSON string; sorted object keys
function digestPlan(plan)    // `sha256:${hex}`

class AuthorizationStore {
  issue({ plan, planDigest, expiresAt, authorizedOperations })
  consume({ authorizationId, plan, planDigest, operation })
  revokeAll(reason)
  inspect(authorizationId)
}
```

`consume()` returns the immutable grant and atomically records `consumedAt`. It throws stable codes: `authorization_unknown`, `authorization_expired`, `authorization_consumed`, `plan_digest_mismatch`, `plan_binding_mismatch`, and `operation_not_authorized`.

**Step 1: Write failing canonicalization tests**

Prove reordered object keys produce the same digest, array order changes the digest, numeric/string changes alter the digest, and non-JSON values are rejected.

```js
assert.equal(digestPlan({ b: 2, a: 1 }), digestPlan({ a: 1, b: 2 }));
assert.notEqual(digestPlan({ steps: ['a', 'b'] }), digestPlan({ steps: ['b', 'a'] }));
```

Run:

```bash
node --test tests/node/authorization/canonical-json.test.js
```

Expected: FAIL because the module does not exist.

**Step 2: Implement strict canonical JSON**

Sort object keys recursively, preserve array order, reject `undefined`, functions, symbols, non-finite numbers, cyclic objects, and non-plain objects. Hash UTF-8 bytes with `node:crypto.createHash('sha256')`.

**Step 3: Write failing authorization tests**

Cover exact binding, expiry boundary, wrong target, revision mutation, operation escalation, double consume, revoke-all, and concurrent `Promise.allSettled()` consume where exactly one caller succeeds.

Run:

```bash
node --test tests/node/authorization/authorization-store.test.js
```

Expected: FAIL because the store does not exist.

**Step 4: Implement the in-memory store**

Validate plan and authorization contracts at issue time. Compare a freshly computed digest at consume time. Perform all checks and the consumed-state write synchronously before returning so two event-loop callers cannot both succeed.

**Step 5: Register the focused test command**

Add:

```json
"test:authorization": "node --test tests/node/authorization/*.test.js"
```

Extend `test:node` to include `tests/node/authorization/*.test.js`.

**Step 6: Verify authorization**

```bash
npm run test:authorization
npm run test:contracts
git diff --check
```

## Task 4: Implement the Deterministic Task Engine

**Files:**

- Add: `platform/task_engine/src/task-engine.js`
- Add: `platform/task_engine/index.js`
- Add: `tests/node/task_engine/task-engine.test.js`
- Modify: `package.json`

**Interfaces:**

```js
class TaskEngine extends EventEmitter {
  registerProposal({ proposal })
  grantAuthorization({ proposalId, planId, planRevision, planDigest })
  executeAuthorized({ authorizationId })
  interrupt(taskId, reason)
  getTask(taskId)
}
```

Dependencies are injected:

```js
new TaskEngine({
  authorizationStore,
  resolveSkill,
  readinessProvider,
  clock,
});
```

Allowed state transitions are:

```text
proposed -> awaiting_authorization -> authorized -> running -> completed
                                               |          -> failed
                                               |          -> interrupted
proposed/awaiting_authorization/authorized -> expired
```

**Step 1: Write failing state-machine tests**

Test one valid completion and reject execution before grant, a second grant, a second execution, invalid transition, changed readiness, expired proposal, Skill failure, and interruption. Assert emitted events preserve `traceId`, `taskId`, and timestamps.

Run:

```bash
node --test tests/node/task_engine/task-engine.test.js
```

Expected: FAIL because Task Engine does not exist.

**Step 2: Implement state transitions and event journal**

Keep plans immutable with `structuredClone()` plus deep freeze. Re-check readiness immediately before issuing authorization and immediately before execution. Do not retry a failed or uncertain Skill.

**Step 3: Register tests**

Add `test:task-engine` and include the directory in `test:node`.

**Step 4: Verify engine and authorization together**

```bash
npm run test:authorization
npm run test:task-engine
git diff --check
```

## Task 5: Define the Gripper-Control Skill and Server-Owned Plans

**Files:**

- Add: `skills/manipulation/gripper-control/manifest.yaml`
- Add: `skills/manipulation/gripper-control/SKILL.md`
- Add: `skills/manipulation/gripper-control/schemas/input.json`
- Add: `skills/manipulation/gripper-control/schemas/plan.json`
- Add: `skills/manipulation/gripper-control/schemas/result.json`
- Add: `skills/manipulation/gripper-control/src/plan.js`
- Add: `tests/node/gripper_skill/plan.test.js`
- Modify: `package.json`

**Manifest:**

```yaml
schema: thirdhand.skill-manifest.v1
id: manipulation.gripper-control
version: 0.1.0
summary: Execute one authorized Startouch gripper position command.
risk: physical-motion
lifecycle: worker
runtime: node
operations: [plan, execute, status, cancel]
requires:
  services: [robot]
  devices: [startouch]
  models: []
schemas:
  input: schemas/input.json
  plan: schemas/plan.json
  result: schemas/result.json
entrypoint: src/worker.js
healthcheck: status
```

**Plan mapping:**

```js
const GRIPPER_INTENTS = Object.freeze({
  'gripper.open': 100,
  'gripper.close': 0,
});
```

Every plan uses `targetRef: 'robot:gripper'`, `operation: 'gripper.set'`, `tolerancePercent: 2`, `timeoutMs: 3000`, and exactly one physical step. Open/close semantics must be verified against the existing manual slider before hardware acceptance; if the current hardware direction is reversed, change both mappings together, rerun simulation tests, and require a new operator approval.

**Step 1: Write failing plan tests**

Assert exact values for open and close, reject every other intent, ignore browser-injected parameters, include pinch risk, and produce a contract-valid `thirdhand.task-plan.v1` with a future expiry proposal.

Run:

```bash
node --test tests/node/gripper_skill/plan.test.js
```

Expected: FAIL because the Skill does not exist.

**Step 2: Implement deterministic plan creation**

Inject `clock` and `idFactory` for tests. Use server constants for position, tolerance, timeout, target, Skill ID, and risk. Preserve candidate ID and trace ID as audit metadata only; do not copy arbitrary candidate properties into the plan.

**Step 3: Validate manifest discovery**

Extend existing Skill Registry tests to assert that `manipulation.gripper-control` is discovered only when Robot Service and the Startouch device are ready, and that no model or Vision dependency is required.

Run:

```bash
npm run test:skills
node --test tests/node/gripper_skill/plan.test.js
git diff --check
```

## Task 6: Add a Private Authorized Execution Route to Robot Service

**Files:**

- Add: `services/robot/src/execution-gateway.js`
- Add: `services/robot/src/execution-token.js`
- Modify: `services/robot/src/server.js`
- Modify: `services/robot/src/robot-controller.js`
- Modify: `services/robot/src/config.js`
- Add: `tests/node/robot_service/execution-gateway.test.js`
- Modify: `tests/node/robot_service/server.test.js`

**Private transport:**

- WebSocket path: `/execution`
- Bind: existing Robot Service loopback bind only
- Header: `x-thirdhand-execution-token`
- Token file: `${ROOT}/runtime/run/robot-execution.token`
- Token comparison: `crypto.timingSafeEqual` after equal-length check
- Browser Web Gateway must not proxy this path

**Robot interface:**

```js
RobotController.executePrimitive(primitive, reply)
```

It accepts only a contract-valid `thirdhand.execution-primitive.v1` with `operation === 'gripper.set'`. It converts `positionPercent / 100` exactly once and calls a request-correlated gripper operation. It must not route through browser `handleCommand()` and must not add `execute` to `ALLOWED_COMMANDS`.

**Step 1: Write failing authentication tests**

Start the simulated Robot server with a temporary token file. Assert `/execution` rejects missing, incorrect, empty, and oversized tokens before accepting WebSocket messages. Assert `/ws` behavior is unchanged.

Run:

```bash
node --test --test-name-pattern="execution token|private execution" tests/node/robot_service/execution-gateway.test.js
```

Expected: FAIL because `/execution` does not exist.

**Step 2: Implement token loading and route isolation**

Read the token once at service start and require file mode no broader than owner read/write on Linux. When no token-file setting is present, keep the existing manual `/ws` service available but do not create `/execution`; health must report `execution.available:false` with reason `execution_token_not_configured`. When a token-file setting is present but the file is missing or insecure, fail startup. Tests may inject a token directly; production execution must use the file.

**Step 3: Write failing primitive safety tests**

Cover schema rejection, unknown operation, stale Robot state, disconnected SDK, active arm motion, percentage bounds, duplicate `primitiveId`, and an assertion that no `move_joint` bridge message is emitted.

**Step 4: Implement primitive validation and replay cache**

Maintain a bounded in-memory primitive-ID cache for the process lifetime. Mark the ID accepted before sending to the bridge. Preserve existing `_motionReadinessError()` checks. Return stable statuses `accepted`, `completed`, `failed`, or `uncertain` with `primitiveId`, `taskId`, and `traceId`.

**Step 5: Correlate completion with real gripper feedback**

After bridge acceptance, wait for fresh `robot_state.gripper_position`. Success requires:

```text
abs(actualPercent - requestedPercent) <= tolerancePercent
AND feedback timestamp is newer than command acceptance
AND no arm joint changed more than 0.5 degrees from the pre-command sample
```

Timeout produces `uncertain`, not `completed`, and no automatic retry. Bridge error or disconnect produces `failed` or `interrupted` with evidence.

**Step 6: Verify Robot Service**

```bash
node --test tests/node/robot_service/execution-gateway.test.js tests/node/robot_service/server.test.js
npm run test:node
git diff --check
```

No hardware service may be started during this task.

## Task 7: Implement the Gripper Skill Worker and Robot Execution Client

**Files:**

- Add: `apps/orchestrator/src/robot-execution-client.js`
- Add: `skills/manipulation/gripper-control/src/worker.js`
- Add: `tests/node/gripper_skill/worker.test.js`

**Interfaces:**

```js
class RobotExecutionClient {
  execute(primitive, { signal })
  health()
  close()
}

async function execute({ plan, authorization, robotClient, clock, idFactory })
// -> thirdhand.skill-result.v1
```

**Step 1: Write failing Worker tests**

Use a fake Robot client. Assert the Worker builds one exact primitive from the immutable plan, never accepts a browser position override, maps Robot `completed` to Skill `completed`, maps `uncertain` without retry, and does not create any arm operation.

Run:

```bash
node --test tests/node/gripper_skill/worker.test.js
```

Expected: FAIL because the Worker does not exist.

**Step 2: Implement Worker and client**

The client connects directly to `ws://127.0.0.1:3000/execution`, reads the same owner-only token file, sends one primitive, and resolves only on a matching `primitiveId`. It closes or aborts on timeout and rejects unmatched or malformed replies.

**Step 3: Verify Worker**

```bash
node --test tests/node/gripper_skill/plan.test.js tests/node/gripper_skill/worker.test.js
npm run test:skills
git diff --check
```

## Task 8: Implement Orchestrator `/plan`

**Files:**

- Add: `apps/orchestrator/package.json`
- Add: `apps/orchestrator/src/config.js`
- Add: `apps/orchestrator/src/protocol.js`
- Add: `apps/orchestrator/src/readiness.js`
- Add: `apps/orchestrator/src/server.js`
- Modify: `apps/orchestrator/README.md`
- Add: `tests/node/orchestrator/server.test.js`
- Add: `tests/node/orchestrator/readiness.test.js`
- Modify: `package.json`

**Service contract:**

- HTTP `GET /health`: service status plus Robot execution readiness
- WebSocket `/plan`: protocol `thirdhand.plan.v1`
- Default bind: `127.0.0.1:3200`
- Ready file: `runtime/run/orchestrator.ready`
- Proposal lifetime: 30 seconds
- Maximum pending proposals per browser connection: 1

**Step 1: Write failing readiness tests**

Assert readiness is false for Robot disconnected, state stale, moving, execution token unavailable, or Robot health unreachable. A connected, state-ready, non-moving simulated Robot with fresh state is ready.

**Step 2: Implement explicit readiness snapshot**

Use structured fields:

```json
{
  "robot": {"reachable": true, "connected": true, "stateReady": true, "moving": false, "fresh": true},
  "skill": {"id": "manipulation.gripper-control", "available": true},
  "authorizationReady": true,
  "capturedAt": "date-time"
}
```

**Step 3: Write failing protocol tests**

Cover valid `candidate.submit`, invalid schema, unsupported intent, duplicate candidate ID, one pending proposal limit, authorization without proposal, digest mutation, expiry, double click, browser disconnect before grant, and result forwarding.

Run:

```bash
node --test tests/node/orchestrator/server.test.js
```

Expected: FAIL because Orchestrator has no server.

**Step 4: Implement candidate-to-result flow**

Server sequence:

```text
candidate.submit
-> validate candidate
-> query readiness
-> create deterministic gripper plan
-> digest and store immutable proposal
-> plan.proposed
-> authorization.grant
-> re-check proposal identity, digest, expiry, and readiness
-> issue and consume one grant through Task Engine
-> execute Worker
-> skill.result
```

Close or replacement of a browser connection expires its unexecuted proposal. A disconnect during execution calls Task Engine `interrupt()` and Robot client abort; it does not report success without Robot evidence.

**Step 5: Register tests and verify service**

Add `test:orchestrator` and include Orchestrator, Task Engine, Authorization, and gripper Skill test directories in `test:node`.

```bash
npm run test:orchestrator
npm run test:task-engine
npm run test:authorization
git diff --check
```

## Task 9: Proxy `/plan` Through the Web Gateway

**Files:**

- Modify: `apps/web/src/config.js`
- Modify: `apps/web/src/server.js`
- Modify: `tests/node/web/server.test.js`
- Modify: `docs/apps/WEB_GATEWAY.md`

**Configuration:**

```text
ORCHESTRATOR_WS_URL=ws://127.0.0.1:3200/plan
Browser route=/plan
Subprotocol=thirdhand.plan.v1
```

**Step 1: Write failing gateway tests**

Create a stub Orchestrator and assert:

- `/api/runtime-config` reports Plan endpoint and protocol;
- `/health` names Orchestrator as a dependency;
- `/plan` requires `thirdhand.plan.v1`;
- messages are proxied unchanged;
- `/ws` still rejects candidate and authorization messages;
- `/execution` is not exposed by the gateway.

Run:

```bash
node --test --test-name-pattern="plan|execution" tests/node/web/server.test.js
```

Expected: FAIL because the route is absent.

**Step 2: Add the dedicated proxy**

Reuse `WebSocketProxy` with the Plan subprotocol. Keep a distinct `planProxy` lifecycle and close it during gateway shutdown. Do not modify the Robot command allowlist.

**Step 3: Verify Web Gateway**

```bash
node --test tests/node/web/server.test.js
git diff --check
```

## Task 10: Replace the Browser Fail-Closed Stub With a Plan Channel

**Files:**

- Add: `apps/web/public/js/plan-channel.mjs`
- Modify: `apps/web/public/js/main.js`
- Modify: `apps/web/public/js/voice-control.js`
- Add: `tests/node/web/plan-channel.test.mjs`
- Modify: `tests/node/web/server.test.js`

**Browser interface:**

```js
class PlanChannel {
  constructor(wsClient)
  isReady()
  submitCandidate(candidate)
  grantAuthorization(proposal)
  on(type, handler)
}
```

`VoiceControl` receives `planChannel`, not `robotChannel`. Manual UI controls keep their existing Robot `WSClient` instance.

**Step 1: Write failing Plan Channel tests**

Use a fake WebSocket client to prove candidate submission requires an open connection, authorization sends only proposal identity fields, double grant is suppressed locally, and disconnect clears pending proposal state.

Run:

```bash
node --test tests/node/web/plan-channel.test.mjs
```

Expected: FAIL because the module does not exist.

**Step 2: Implement the protocol adapter**

Parse only known message types: `plan.proposed`, `plan.rejected`, `authorization.granted`, `execution.started`, and `skill.result`. Unknown or malformed server messages surface an error and do not alter authorization state.

**Step 3: Rewire `VoiceControl`**

On `intent.candidate`, call `planChannel.submitCandidate(candidate)`. Display the server-returned plan and risk summary. The confirm button calls `grantAuthorization()` once. UI success appears only after `skill.result.status === 'completed'`; sending a message or receiving `authorization.granted` is not success.

Use component-specific messages:

```text
Orchestrator unavailable
Robot Service not connected
Robot state stale
Robot is moving
Plan expired; submit the command again
```

Remove the misleading “3000 control channel not connected” message from the candidate path. Preserve local simulation preview, but label it as preview and never let it produce an execution result.

**Step 4: Verify browser integration statically and through protocol tests**

```bash
node --test tests/node/web/plan-channel.test.mjs tests/node/web/server.test.js
grep -R "robotChannel.*skill.candidate\|confirmation.decision" apps/web/public/js
git diff --check
```

Expected grep result: no active browser candidate execution path. Comments explaining removed compatibility are acceptable only when they cannot execute.

## Task 11: Generate the Private Token and Add Orchestrator to the Runtime Profile

**Files:**

- Add: `apps/launcher/src/runtime-secrets.js`
- Modify: `apps/launcher/src/service-supervisor.js`
- Modify: `configs/runtime/manual-control.json`
- Modify: `tests/node/launcher/service-supervisor.test.js`
- Add: `tests/node/launcher/runtime-secrets.test.js`
- Modify: `docs/OPERATIONS.md`
- Modify: `docs/RUN_GUIDE.md`

**Step 1: Write failing token lifecycle tests**

Assert launcher creates a 32-byte random token encoded as 64 lowercase hexadecimal characters, writes atomically with mode `0600`, reuses it for one owned profile run, rotates it after a clean full stop, and never logs its value.

Run:

```bash
node --test tests/node/launcher/runtime-secrets.test.js
```

Expected: FAIL because token generation does not exist.

**Step 2: Implement secret preparation before spawn**

Generate `runtime/run/robot-execution.token` only after preflight passes and before Robot Service starts. On failed startup, remove the newly generated token after all owned children are stopped. Never overwrite a token while an owned Robot process is running.

**Step 3: Update service order**

Add Orchestrator after Robot, Speech, and Vision and before Web. Set:

```json
{
  "id": "orchestrator",
  "command": "${NODE}",
  "args": ["${ROOT}/apps/orchestrator/src/server.js"],
  "cwd": "${ROOT}",
  "env": {
    "ORCHESTRATOR_HOST": "127.0.0.1",
    "ORCHESTRATOR_PORT": "3200",
    "ROBOT_HTTP_URL": "http://127.0.0.1:3000",
    "ROBOT_EXECUTION_WS_URL": "ws://127.0.0.1:3000/execution",
    "ROBOT_EXECUTION_TOKEN_FILE": "${ROOT}/runtime/run/robot-execution.token"
  },
  "bind": "127.0.0.1",
  "port": 3200,
  "shutdownOrder": 90,
  "enabled": true
}
```

Add `ROBOT_EXECUTION_TOKEN_FILE` to Robot and `ORCHESTRATOR_WS_URL` to Web. The launcher dependency order becomes:

```text
robot -> speech -> vision -> orchestrator -> web
```

Model and Supervisor remain documented but disabled because they are not needed for gripper-only Phase 2.

**Step 4: Update operator procedure**

Document a manual checkpoint for replacing currently external services:

1. Confirm the arm is stationary and the work area is clear.
2. Keep physical emergency stop or power isolation reachable.
3. Disconnect the SDK through the current page and verify Robot health reports disconnected.
4. Identify the exact project PIDs for ports `3000`, `3004`, `3100`, and `9983`.
5. Obtain explicit approval to stop only those PIDs.
6. Verify all five target ports, including `3200`, are clear.
7. Start the launcher profile and verify every PID is launcher-owned.

The implementation must not automate steps 3–5.

**Step 5: Verify configuration without starting it**

```bash
npm run test:launcher
node -e "JSON.parse(require('node:fs').readFileSync('configs/runtime/manual-control.json','utf8')); console.log('profile json ok')"
git diff --check
```

## Task 12: Complete Simulation, UI, and Hardware Acceptance Gates

**Files:**

- Add: `tests/integration/test_authorized_gripper_chain.py`
- Add: `tests/acceptance/GRIPPER_HARDWARE_ACCEPTANCE.md`
- Modify: `tests/README.md`
- Modify: `docs/RUN_GUIDE.md`
- Modify: `docs/VOICE_ACTION_CONTROL_CHAIN_DESIGN.md`
- Modify: `docs/INDEX.md`

**Step 1: Add a full simulated-chain test**

The test starts isolated services on ephemeral ports with Robot simulation enabled, submits `gripper.open`, verifies no primitive before authorization, grants once, verifies one primitive and a completed SkillResult, then repeats these negative cases:

- double click;
- replay after completion;
- expired plan;
- changed digest;
- browser disconnect before grant;
- Robot stale state;
- Robot already moving;
- malformed candidate;
- unsupported `arm.home` candidate;
- Robot feedback timeout;
- unexpected arm-joint delta during gripper execution.

Run:

```bash
python -m pytest tests/integration/test_authorized_gripper_chain.py -v
```

Expected before implementation: FAIL. Expected after Tasks 1–11: PASS without hardware.

**Step 2: Run the complete software verification matrix**

```bash
npm run test:contracts
npm run test:authorization
npm run test:task-engine
npm run test:skills
npm run test:orchestrator
npm run test:launcher
npm run test:node
python -m pytest -q
git diff --check
git status --short
```

All commands must pass before requesting hardware approval.

**Step 3: Perform browser acceptance in simulation**

Open `http://192.168.58.68:9983` only after the simulation profile is running. Verify:

1. Voice and text “打开夹爪” produce a server plan and visible pinch-risk summary.
2. The gripper does not change before confirmation.
3. One click produces one execution.
4. A second click, refresh, reconnect, or copied grant cannot execute again.
5. Success appears only after simulated feedback.
6. Manual Robot controls still use `/ws` and are unaffected.
7. The page distinguishes software stop from independent hardware emergency stop.

Capture browser console output and one screenshot showing proposed, authorized/running, and completed states as acceptance evidence.

**Step 4: Present a hardware risk summary and request one explicit approval**

Do not continue automatically. Present current test results, live service ownership, Robot health, CAN state, gripper mapping, and this exact physical scope:

```text
One open command and one close command, with no object between the fingers,
no arm-joint target, no automatic retry, and hardware emergency stop reachable.
```

**Step 5: Execute approved hardware acceptance**

After approval only:

1. Verify `can0` is `UP` at 1,000,000 bit/s and receiving motor feedback.
2. Verify Robot reports six fresh joint values, `moving:false`, and current gripper feedback.
3. Record all six joints and the gripper position before the command.
4. Submit `gripper.open`, inspect the exact plan, and click confirm once.
5. Verify one primitive, target feedback within 2%, no joint change over 0.5 degrees, and no retry.
6. Submit `gripper.close` with the empty gripper and repeat the checks.
7. Verify duplicate confirmation and replay are rejected.
8. Trigger software stop in a non-moving state and verify the UI still states it is not a hardware emergency stop.
9. Save redacted logs containing IDs, timestamps, targets, actual feedback, and results; never save the execution token.

Any unexpected arm motion, stale state, missing feedback, token error, duplicate command, or uncertain result fails acceptance and requires immediate software stop plus operator use of hardware emergency stop/power isolation if motion cannot be confirmed stopped.

**Step 6: Update status documentation only after evidence exists**

Change the design status from “implementation has not started” to the actual verified state. Do not mark bottle picking, visual depth execution, Supervisor, Model Service, VLA, ACT, DP, or active view as migrated.

Run final checks:

```bash
grep -R "from .*History\|require(.*History\|import .*History" apps platform services skills
git diff --check
git status --short
```

Expected: no formal runtime import from `History/`; working-tree changes remain uncommitted for user review.

## Deferred Work After Phase 2

The following approved architecture remains explicitly outside this implementation plan and must receive its own design review and implementation plan:

1. Manual joint step, directional control, and Home intents through authorization.
2. Stable target identity, depth validity, camera-to-base calibration, and pose-revision binding.
3. Supervisor Service and interruption on target, scene, or calibration change.
4. Supervised bottle picking and placement.
5. Model Service adapters for VLA, ACT, and Diffusion Policy.
6. Active-view planning and camera motion.
7. AI-originated software-stop priority path.
8. History deletion after migration evidence, runtime-reference scans, and recoverable backup criteria pass.

## Completion Evidence Required

Phase 0–2 is complete only when all of the following are attached to the implementation record:

- launcher preflight tests and proof of unique process ownership;
- contract, digest, authorization replay, and Task Engine transition tests;
- Robot private-route authentication and primitive safety tests;
- browser Plan Channel and Web Gateway isolation tests;
- simulated end-to-end chain evidence;
- explicit hardware approval and the two-command acceptance log;
- proof that no arm joint moved during gripper operations;
- proof that no code imports from `History/` or old external projects;
- `git diff --check` output and a user-reviewed `git status --short`;
- no commit, push, merge, rebase, or branch switch unless separately authorized.
