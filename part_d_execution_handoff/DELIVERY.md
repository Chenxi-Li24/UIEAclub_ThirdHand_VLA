# PART D / Execution handoff

## Delivery status

This package is directly startable and integratable for:

- `simulate` using `startouch_fixed_waypoint_adapter_v1`;
- a **local no-motion preflight** interpretation of `dry-run`;
- the fixed `pick_zone_a -> drop_zone_b -> HOME` plan only.

It is **not** a real-hardware execution delivery. `real` is hard-blocked, no
motion/gripper command was sent while producing this package, and the existing
Startouch Bridge, SDK, CAN interface, and SSH robot host were not contacted.

## Code and version

| Item | Value |
| --- | --- |
| Repository | `https://github.com/Chenxi-Li24/UIEAclub_ThirdHand_VLA.git` |
| Local path used | `/Users/Mihail/Library/Mobile Documents/com~apple~CloudDocs/XJTLU/UIEA/Control skill/UIEAclub_ThirdHand_VLA` |
| Branch | `control-fixed-a-to-b` |
| Implementation commit | `dfa5dd3765267d56322f2a3a8d874bc556af4969` |
| Worktree at final handoff | Clean; no uncommitted task files |
| HTTP entrypoint | `web-control/server/startouch_execution_service.py` |
| Adapter | `web-control/scripts/startouch_fixed_waypoint_adapter.py` |
| Existing runner reused for parsing/config validation | `web-control/scripts/fixed_pick_place.py` |
| Existing Bridge reference | `web-control/server/startouch_bridge.py` |
| Existing YAML | `configs/tasks/fixed_pick_place.yaml` |
| Focused tests | `tests/control/test_startouch_fixed_waypoint_adapter.py`, `tests/control/test_startouch_execution_service.py`, `tests/control/test_part_d_handoff.py` |

The manifest's `commit` is the immutable implementation commit. The following
local metadata-only commit updates that SHA and the fresh evidence inside this
package; this avoids falsely claiming that a Git commit can contain its own
hash. Nothing is pushed.

## Reproducible environment

Tested versions:

- macOS Darwin 25.5.0, arm64;
- Python 3.12.13;
- Node 24.17.0 (not needed by the PART D HTTP service);
- PyYAML 6.0.3;
- jsonschema 4.26.0;
- pytest 9.1.1;
- pytest-asyncio 1.4.0;
- Ruff 0.16.3;
- Startouch SDK version: not loaded or queried for this no-hardware delivery.

From the repository root:

```bash
python3.12 -m venv .venv-control
.venv-control/bin/python -m pip install -r requirements/control-adapter.txt
```

The shared contract must be available as either `contracts/schema.json` inside
the repository or `../contracts/schema.json` beside the repository. The tested
layout uses the sibling `../contracts/schema.json` supplied by the team. A
different authoritative location can be selected with
`THIRDHAND_CONTRACT_SCHEMA`; the shared file is never modified by this code.

## Environment variables

Safe defaults are recorded in the root `.env.example`:

| Variable | Default/purpose |
| --- | --- |
| `THIRDHAND_ROBOT_HOST` | `127.0.0.1`; any non-loopback bind is refused |
| `THIRDHAND_ROBOT_PORT` | `7788` |
| `THIRDHAND_ROBOT_ENDPOINT` | Orchestrator value `http://127.0.0.1:7788/v1/execution` |
| `THIRDHAND_ROBOT_REQUEST_TIMEOUT_S` | `5`; HTTP body read timeout |
| `THIRDHAND_ROBOT_MAX_BODY_BYTES` | `1048576` |
| `THIRDHAND_CONTRACT_SCHEMA` | Optional absolute/checkout-relative path to the authoritative `schema.json` |
| `THIRDHAND_EXECUTION_BINDINGS_FILE` | Optional Orchestrator-owned ID binding file |

No token, password, SSH key, private key, CAN name, or machine credential is
required by this service.

## Start, health, execute, stop

Start on the required port:

```bash
.venv-control/bin/python web-control/server/startouch_execution_service.py \
  --host 127.0.0.1 --port 7788
```

Read-only local health and capabilities:

```bash
curl --fail --silent http://127.0.0.1:7788/health
curl --fail --silent http://127.0.0.1:7788/v1/capabilities
```

Replay the two safe modes:

```bash
curl --fail --silent --header 'Content-Type: application/json' \
  --data @part_d_execution_handoff/examples/execution_request_simulate.json \
  http://127.0.0.1:7788/v1/execution

curl --fail --silent --header 'Content-Type: application/json' \
  --data @part_d_execution_handoff/examples/execution_request_dry_run.json \
  http://127.0.0.1:7788/v1/execution
```

Stop only the PART D HTTP process with `Ctrl-C`. There is intentionally no
remote shutdown endpoint. Do not start/stop `startouch_bridge.py` for these
commands.

### Existing Bridge reference (not started in this delivery)

The only approved hardware boundary remains
`web-control/server/startouch_bridge.py`. The existing
`web-control/scripts/fixed_pick_place.py::BridgeClient.start()` launches it as
a child process using the current Python executable:

```text
python -u web-control/server/startouch_bridge.py
```

Its command protocol is newline-delimited JSON on child stdin. Bridge events
are newline-delimited JSON on the dedicated `STARTOUCH_EVENT_FD` on POSIX (or
stdout fallback); stdout/stderr are otherwise drained as logs. Existing commands
include `connect`, `get_state`, motion, gripper, stop, disconnect, and shutdown.
This PART D service does not launch that child, write a command, read robot
state, or import its vendor SDK. Consequently it creates no second SDK/CAN
owner. Future Bridge integration must continue through this existing
`BridgeClient`; direct SDK/CAN code is out of scope.

### Protocol boundary

| Item | Value |
| --- | --- |
| Transport | HTTP/1.1 JSON, UTF-8 |
| Bind | `127.0.0.1:7788` only |
| Health | `GET /health` |
| Capabilities | `GET /v1/capabilities` |
| Execution | `POST /v1/execution` |
| Authentication | None; safety relies on loopback-only binding |
| Request timeout | 5 seconds to read the HTTP body |
| Skill execution timeout | Orchestrator contract value is 120 seconds; current local work completes synchronously well below it |
| Body limit | 1 MiB |
| Concurrency | `ThreadingHTTPServer` plus one non-blocking global execution mutex |
| Busy behavior | HTTP 409 plus schema-valid `execution.result`, `status=blocked`, `executedSteps=0` |

Malformed JSON/protocol failures return `service.error` with
`payload.stage=execution`. Contract-valid but unsupported or unsafe semantic
requests return `execution.result` with `status=blocked`.

## Command risk classification

| Command/path | Classification in this delivery |
| --- | --- |
| Start PART D HTTP service | Local software only; no Bridge/SDK/CAN |
| `GET /health`, `GET /v1/capabilities` | Local read-only service metadata |
| POST `simulate` | Contract/YAML/route software simulation only |
| POST `dry-run` | Local contract/config/route preflight only |
| Existing `fixed_pick_place.py --dry-run` | **Not used**; it starts the Bridge, constructs vendor SDK with `dry_run=True`, and submits logical move/gripper requests |
| Existing Bridge `connect/get_state` | Can initialise SDK/read state; not called here |
| Existing Bridge motion/gripper commands | Hardware-capable; forbidden and not called here |
| Any `real` request | Blocked before Bridge access |

## Adapter and execution-plan support

| Adapter/plan | Status | Behavior |
| --- | --- | --- |
| `startouch_fixed_waypoint_adapter_v1` / `fixed_waypoint_a_to_b` | Implemented for simulate and local dry-run | Validates shared Schema, fixed constants, safety, YAML, route, and output |
| `startouch_action_chunk_adapter_v1` / `act_chunk` | Not implemented or registered | Schema-valid ACT request is fail-closed with `action_chunk_adapter_unavailable` |
| `real` fixed waypoint | Deliberately disabled | `real_mode_disabled`; no hardware access |

The adapter imports the existing runner only for `load_config()`,
`action_sequence_for()`, and the established route constants. It verifies the
YAML workflow is `home_transit_ab`, the plan/YAML speed is `0.15`, and uses only
the first 11 states:

```text
OPEN_GRIPPER_READY -> MOVE_HOME_START -> APPROACH_A_UP
-> DESCEND_TO_A_PICK -> ADAPTIVE_GRASP_A -> LIFT_A
-> TRANSFER_A_UP_TO_B_UP -> DESCEND_TO_B -> RELEASE_AT_B
-> LIFT_AFTER_RELEASE_B -> RETURN_B_UP_TO_HOME
```

It stops there. `MOVE_HOME_TO_B_UP` and every B-to-A state are rejected.

The shared Schema allows `0 < safety.speedScale <= 0.15`, while the fixed plan
itself is exactly `0.15`. This adapter blocks a lower safety cap rather than
silently executing the fixed plan above the requested safety limit.

## Mode semantics

### `simulate`

- validates inbound/outbound JSON against the shared Schema;
- loads and validates the existing YAML and fixed route;
- simulates traversal of 11 route-state names;
- does not construct `BridgeClient`/`FixedPickPlaceRunner`, start Bridge,
  initialise SDK/CAN, access SSH, or issue commands;
- `executedSteps=11` means 11 software states inspected, not robot movement;
- all hardware/Bridge evidence remains false, zero, or null.

### `dry-run`

- performs the same contract/YAML/route checks;
- checks that the Bridge, runner, and YAML references exist locally;
- deliberately does **not** test Bridge/SDK reachability or robot state;
- does not start Bridge, initialise SDK/CAN, or issue any motion/gripper request;
- returns `executedSteps=0`, `hardwareFeedbackVerified=false`, and empty Bridge evidence;
- success proves only local interface/configuration preflight.

### `real`

- always blocked for this delivery;
- was not run;
- no request can enable it using an environment variable;
- future supervised work must separately verify the physical E-stop, unique
  target, fresh frame, exclusive motion, speed limit, Bridge events, and real
  feedback. A software stop is not a physical E-stop.

## Contract field mapping

| Contract field | Input validation / output mapping |
| --- | --- |
| `schemaVersion` | Input must be `1.0`; output is `1.0` |
| `type` | Input `execution.request`; output `execution.result` or HTTP-level `service.error` |
| `messageId` | Input identifier validated; output generates a new UUID-based identifier |
| `replyTo` | Output equals input `messageId` |
| `sessionId` | Validated and preserved |
| `traceId` | Validated and preserved; optionally compared with trusted binding |
| `ts` | Input non-negative epoch ms; output uses current epoch ms |
| `source` / `target` | Input must be `orchestrator -> robot`; output is `robot -> orchestrator` |
| `mode` | Preserved exactly; only simulate/dry-run succeed, real blocks |
| `status` | Input must be `ready`; output is success/failure/blocked |
| `candidateId` | Validated, optionally bound, and copied to result payload |
| `decisionId` | Validated and optionally compared with trusted binding; not allowed in result Schema |
| `confirmed` | Schema requires `true`; false/missing is blocked before all execution work |
| `targetId` | Validated and optionally compared with trusted binding; not allowed in result Schema |
| `executionPlan.kind` | Only `fixed_waypoint_a_to_b` is implemented; `act_chunk` blocks |
| `planId` | Validated; copied to output `sequenceId` |
| `adapterId` | Must be `startouch_fixed_waypoint_adapter_v1` |
| `bridgeRef` | Must be `web-control/server/startouch_bridge.py`; existence checked only |
| `configRef` | Must be `configs/tasks/fixed_pick_place.yaml`; loaded with existing runner |
| `routeStates` | Must be exact 11-state A-to-B-to-HOME route |
| `safety.uniqueTargetAuthorized` | Shared Schema requires `true`; no independent Vision evidence exists in this message |
| `safety.frameFresh` | Shared Schema requires `true`; no frame timestamp exists in this message |
| `safety.mutuallyExclusiveMotion` | Must be `true`; service also uses a local execution mutex |
| `safety.physicalEStopReady` | Boolean; real Schema requires true, but real remains disabled |
| `safety.speedScale` | Must match the fixed plan/YAML value `0.15` |
| `sequenceId` | Output equals input plan `planId` |
| `executor` | `fixed_pick_place_adapter` |
| `executedSteps` | 11 simulated states for simulate; 0 for dry-run/blocked/failure |
| `hardwareFeedbackVerified` | Always false in this delivery |
| `safetyEvent` | False for successful safe local checks; true for blocked/failure |
| `bridgeEvidence.bridgeRef` | Constant existing Bridge path |
| `bridgeEvidence.commandCompleteCount` | Always 0 because Bridge is not called |
| `bridgeEvidence.finalRobotStateRef` | Always null |
| Remaining `bridgeEvidence` booleans | Always false; never fabricated |

## Identity and authorization continuity

A standalone `execution.request` contains IDs and boolean gates but not the
upstream confirmation/Vision/Policy records. Therefore Part D cannot prove
cross-message consistency or actual frame freshness from that message alone.

For stateful integration, the Orchestrator may atomically maintain a JSON file
mapping `sessionId` to `traceId`, `candidateId`, `decisionId`, and `targetId`,
then set `THIRDHAND_EXECUTION_BINDINGS_FILE`. See
`config/identity_bindings.example.json`. This config file is not a contract
message and is intentionally kept outside `examples/`. When configured, missing sessions or
any mismatch are blocked. Without it, the Orchestrator remains responsible for
the upstream chain, as assigned by the team contract.

## Failure behavior and evidence

- duplicate JSON keys and malformed HTTP requests produce `service.error`;
- schema-invalid execution requests produce a schema-valid blocked result so
  the required unconfirmed negative replay has a deterministic reply;
- unsupported ACT, identity mismatch, real mode, wrong route/speed, and busy
  execution are blocked with zero steps/evidence;
- local config/preflight faults return failure with zero steps/evidence;
- bridge/CAN/stale/timeout tests are **synthetic fault injection only** because
  this delivery intentionally never contacts Bridge/CAN;
- `execution_result_bridge_failure.json` is a replay shape, not proof of an
  observed Bridge failure.

There is an unavoidable contract-document tension: `confirmed:false` is
forbidden by `schema.json`, yet the delivery request requires an unconfirmed
request sample and also says all samples should validate. The negative request
is intentionally schema-invalid and is tested to be rejected. All positive
requests and every result file validate against the shared Schema.

## Verification commands

```bash
PYTHONPATH=src .venv-control/bin/python -m pytest -q -p no:cacheprovider \
  tests/control/test_startouch_fixed_waypoint_adapter.py \
  tests/control/test_startouch_execution_service.py \
  tests/control/test_part_d_handoff.py

RUFF_CACHE_DIR=/tmp/thirdhand-ruff-cache \
  .venv-control/bin/python -m ruff check \
  web-control/scripts/startouch_fixed_waypoint_adapter.py \
  web-control/server/startouch_execution_service.py \
  tests/control/test_startouch_fixed_waypoint_adapter.py \
  tests/control/test_startouch_execution_service.py \
  tests/control/test_part_d_handoff.py
```

Fresh results are in `evidence/`.

## Known limitations / Orchestrator decisions

1. Decide whether to provide and own the optional identity-binding registry.
2. Decide whether this stricter local dry-run is sufficient for integration.
   Bridge/SDK/state reachability needs a later supervised, read-only design; the
   existing runner dry-run does not meet the no-command requirement.
3. `startouch_action_chunk_adapter_v1` is absent, so ACT is not executable.
4. Real hardware, physical E-stop, Bridge event mapping, feedback, CAN state,
   stale-state detection, and timeout evidence are unverified here.
5. No authentication is implemented; the endpoint is deliberately loopback-only.
6. The contract Schema is currently a sibling directory and must remain
   available at runtime, be placed in the agreed repository layout, or be
   selected with `THIRDHAND_CONTRACT_SCHEMA`.
