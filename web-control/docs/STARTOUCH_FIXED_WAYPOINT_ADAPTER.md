# Startouch fixed-waypoint contract adapter

`startouch_fixed_waypoint_adapter_v1` accepts the team contract's
`execution.request` and emits `execution.result`. The loopback HTTP wrapper is
`web-control/server/startouch_execution_service.py`; its default endpoint is
`http://127.0.0.1:7788/v1/execution` and its read-only health endpoint is
`http://127.0.0.1:7788/health`.

## Safety boundary

- `simulate` validates the contract, existing YAML, and the required A-to-B
  route. It reports 11 **software-simulated route states**, not hardware steps.
- `dry-run` is deliberately stricter than the existing runner's dry-run: it is
  a local no-motion preflight only. It does not start the Bridge or initialise
  the SDK/CAN, so it reports `executedSteps: 0` and no hardware evidence.
- `real` is always blocked in this delivery, even when the request says the
  physical E-stop is ready.
- `act_chunk` is blocked because `startouch_action_chunk_adapter_v1` has not
  been implemented or registered.
- The service binds only to `127.0.0.1`, has no authentication, accepts one
  execution at a time, and fails closed on concurrent requests.
- No code path constructs `BridgeClient` or `FixedPickPlaceRunner`, starts
  `startouch_bridge.py`, imports the vendor SDK, opens CAN, or sends a
  motion/gripper command.

The existing `fixed_pick_place.py --dry-run` was not reused here because it
still constructs the vendor SDK and submits logical motion/gripper requests to
the Bridge. Its hardware safety depends on vendor `dry_run=True`, which is not
strong enough for this no-command delivery.

## Reused project capability

The adapter loads `configs/tasks/fixed_pick_place.yaml` through the existing
`fixed_pick_place.py` configuration loader. It derives the route from
`HOME_TRANSIT_AB_ACTION_SEQUENCE` and truncates it at
`RETURN_B_UP_TO_HOME`. It never enters the B-to-A continuation.

The fixed plan and YAML use `speedScale: 0.15`. A lower safety cap is refused
instead of silently running the fixed plan above that cap.

## Run locally

Create the tested Python 3.12 environment and install dependencies:

```bash
python3.12 -m venv .venv-control
.venv-control/bin/python -m pip install -r requirements/control-adapter.txt
```

Start the loopback service:

```bash
.venv-control/bin/python web-control/server/startouch_execution_service.py \
  --host 127.0.0.1 --port 7788
```

In another terminal, check health and run the two no-hardware requests:

```bash
curl --fail --silent http://127.0.0.1:7788/health
curl --fail --silent --header 'Content-Type: application/json' \
  --data @part_d_execution_handoff/examples/execution_request_simulate.json \
  http://127.0.0.1:7788/v1/execution
curl --fail --silent --header 'Content-Type: application/json' \
  --data @part_d_execution_handoff/examples/execution_request_dry_run.json \
  http://127.0.0.1:7788/v1/execution
```

Stop only this HTTP service with `Ctrl-C`. Do not start or stop the existing
Startouch Bridge for these checks.

Run focused tests:

```bash
PYTHONPATH=src .venv-control/bin/python -m pytest -q -p no:cacheprovider \
  tests/control/test_startouch_fixed_waypoint_adapter.py \
  tests/control/test_startouch_execution_service.py \
  tests/control/test_part_d_handoff.py
```

## Identity binding

A single `execution.request` does not contain the upstream confirmation or
Vision records, so it cannot prove cross-message identity continuity by
itself. The HTTP service can optionally read an Orchestrator-owned binding file
using `THIRDHAND_EXECUTION_BINDINGS_FILE`. The file maps `sessionId` to exactly
the expected `traceId`, `candidateId`, `decisionId`, and `targetId`. If a file
is configured, any missing session or mismatch is blocked. Without a file, the
adapter checks identifier syntax, result inheritance, and the contract safety
booleans only.

## Not implemented

Bridge/SDK reachability, live state reads, hardware evidence mapping, physical
E-stop verification, real movement, and ACT action chunks remain supervised
future work. A schema-valid dry-run success means only that the local contract,
configuration, and route preflight passed; it is not a real pick-and-place.
