# Unified Foundation Operations

The unified project is operated from its repository root with one native command:

```bash
./thirdhand doctor
./thirdhand start
./thirdhand status
./thirdhand stop
./thirdhand verify-assets
```

No command invokes `sudo`, `systemd`, package installation, or an implicit network download. The launcher prefers a verified project-local Node 24 runtime at `local/runtimes/node/bin/node` and otherwise accepts a system Node 24 executable.

## Profiles

`THIRDHAND_PROFILE=simulation` selects five deterministic fake services on loopback ports 13000, 13004, 13100, 13101, and 13102. This profile never opens CAN, USB cameras, microphones, GPUs, or model files. It is the only runnable profile in the foundation phase.

The default profile records final ownership of 9983, 3000, 3100, and 3004, but all live services are disabled with `service_not_migrated`. Accepted old services continue running from their original projects until a later cutover is explicitly approved.

## Commands

| Command | Behavior |
|---|---|
| `doctor` | Read-only checks for repository, Node runtime, profile, and local asset manifest. It does not probe or initialize hardware in this phase. |
| `start` | Starts enabled services in profile order, waits for readiness, records process identity, and discovers Skill availability. Running it twice preserves the same owned PIDs. |
| `status` | Revalidates PID, Linux process start marker, and command hash before reporting a service ready. |
| `stop` | Revokes authorization first, then sends the configured graceful signal in descending shutdown order. A mismatched PID is reported `not_owned` and is not signaled. |
| `verify-assets` | Runs the read-only Python verifier against `configs/assets/manifest.local.json`; it never imports or downloads files. |

Every command accepts `--json`. A profile can be selected with `--profile simulation` or `THIRDHAND_PROFILE=simulation`.

## State And Logs

- Process ownership: `runtime/run/state.json`
- Readiness markers: `runtime/run/<service>.ready`
- Standard output: `runtime/logs/<service>.stdout.log`
- Standard error: `runtime/logs/<service>.stderr.log`

The state file is written through a sibling temporary file, flushed, and atomically renamed. PID alone is never accepted as ownership evidence.

## Failure And Degraded Startup

Missing optional policy models leave only those policy Skills unavailable. Missing Robot or Supervisor resources locks motion. Missing speech preserves text operation. Missing vision locks visually guided and policy motion. Interrupted tasks are not automatically resumed, and old authorizations are not reused.

Software stop depends on the browser, network, processes, operating system, and CAN stack. It is not an independent hardware emergency stop. Keep a physical emergency-stop or power-disconnect control accessible during every hardware test.
