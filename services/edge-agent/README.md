# Edge Agent implementation status

C1b now has a separately packaged probe-only wheel with five modules and no robot
or media runtime. A dedicated Python3.11 venv is proposed for campus Ubuntu; its
existing robot environments are not upgraded. The explicit CLI supports bounded
duration, planned reconnect cycles and credential-free RTT/gap statistics. It
terminates on unexpected failure instead of retrying. See the
[C1b deployment review](../../docs/operations/2026-10-30-C1b-deployment-review.md).

The installed CLI is the bounded **probe only** transport described in
[`services/device-relay/README.md`](../device-relay/README.md). It does not open a
Robot Service or automatically reconnect. The following command path components
are tested with FakeRobot and are not enabled by that probe:

- `protocol.py` checks exact Ed25519 bytes, key ID, current device/boot/executor/
  connection and short validity before JSON command use.
- `command_gate.py` accepts a closed operation set and persists a command ID,
  payload digest and sequence before submitting to the local Robot Service.
- `journal.py` uses SQLite WAL/FULL durability. A lost response is `unknown` and
  is not submitted again after Agent restart. Changed payloads cannot reuse IDs.
- `robot_client.py` authenticates only to a literal loopback origin, does not use
  environment proxies or follow redirects, and sends the original cloud-signed
  envelope. Reading context/binding does not connect SDK.

The Robot Service independently verifies cloud signatures, lease/executor binding,
monotonic one-second expiry and the existing 500ms state freshness check. In
`ROBOT_ACCESS_MODE=remote`, old `/ws`, `/execution` and `/meituan` upgrades are
rejected. The independent 50ms watchdog requests priority software stop on expiry
or worker/CAN-config change; an unknown stop prevents a new grant. This is a
software request, not proof of physical stopping if the SDK/OS/CAN path is blocked.

Physical controllers remain `HARDWARE_ACCEPTANCE_REQUIRED`; no config-file flag
or incoming JSON boolean enables hardware in this implementation. A reviewed
onsite acceptance integration is still needed at C3. Production must additionally
restrict CAN and SDK ownership with OS permissions so local CLI processes cannot
bypass the service. Root/maintenance identity is a separately audited OS trust
boundary. Never equate SDK-worker termination with confirmed stopped motors.

The bound-executor transport, lease/outbox and media modules now have isolated
FakeRobot tests. Actual composition, deployment, media transport and hardware
acceptance remain gated by the B/C plan and current implementation status. A
local FakeRobot test pass does not mark those field gates complete.

Run from the repository root with Python 3.11+:

```sh
python -m pip install -r services/edge-agent/requirements-test.txt
python -m pytest -q tests/python/edge_agent
```

On Windows the test runtime must permit SQLite file locking. The development
sandbox here stalled in SQLite WAL initialization; the isolated unsandboxed test
directory passed. No production database, token or device is used by these tests.
