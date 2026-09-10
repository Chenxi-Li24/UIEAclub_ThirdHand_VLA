# Unified Project Directory Map

This document defines ownership and data flow for the canonical repository. The guiding rule is simple: formal runtime code may depend only on tracked code in this repository and verified assets under `local/`; it may not import old projects or `archive/`.

| Path | Owner | Inputs | Outputs | Lifecycle | Git tracking | Migration source |
|---|---|---|---|---|---|---|
| `thirdhand` | Operations | Command and profile | Process lifecycle actions | Per operator command | Tracked | New |
| `apps/web` | Web team | Service APIs and task events | 9983 UI/API | Always online after start | Tracked | `Thirdhand_language` |
| `apps/robot-console` | Robot team | Robot state and commands | 3000 maintenance UI | Online when robot profile enabled | Tracked | Existing `web-control` |
| `apps/orchestrator` | AI platform | User text, Skill catalog, perception | Plans and Skill calls | Always online after start | Tracked | New plus reviewed prototypes |
| `apps/launcher` | Platform | Runtime profile and asset report | Managed processes and state | Per `thirdhand` lifecycle | Tracked | New |
| `platform/contracts` | Platform | JSON values | Versioned validation results | Library | Tracked | New |
| `platform/skill_registry` | Platform | Skill manifests and resources | Sorted availability catalog | Always online after start | Tracked | New |
| `platform/task_engine` | Platform | Plans, events, outcomes | Task state transitions | Always online after start | Tracked | New |
| `platform/authorization` | Safety | Immutable plans and user approval | Expiring authorization | Always online after start | Tracked | New |
| `platform/resources` | Platform | Devices, assets, service health | Resource availability | Always online after start | Tracked | New |
| `platform/audit` | Safety | Task and service events | Trace records | Always online after start | Tracked code; runtime data ignored | Existing audit patterns plus new |
| `services/robot` | Robot team | Authorized motion requests and CAN feedback | Robot state and command results | Single CAN owner | Tracked | Accepted Startouch service |
| `services/vision` | Vision team | XVisio RGB-D | Frames, detections, TargetRefs, poses | Always online after start | Tracked | `PinZiZhuaQuSkill` |
| `services/speech` | Speech team | Browser/microphone audio and text | ASR text and TTS audio | Always online after start | Tracked | `Thirdhand_language` |
| `services/model` | AI platform | Versioned inference requests | Model results and health | Always online after start | Tracked | New adapters |
| `services/supervisor` | Safety | Robot and vision state | Stop/interruption decisions | Required for automated motion | Tracked | `PinZiZhuaQuSkill` plus new boundary |
| `skills` | Skill owners | Versioned requests and Platform refs | Plans/results | Discovered; workers enabled by resources | Tracked | Reviewed capabilities |
| `drivers/startouch` | Robot team | Robot service calls | SDK/CAN translation | Loaded only by robot service | Tracked adapters | Existing web control and SDK examples |
| `drivers/xvisio` | Vision team | Vision service calls | Synchronized RGB-D | Loaded only by vision service | Tracked adapters | FastUMI/XVisio source |
| `drivers/audio` | Speech team | Browser/device audio | Normalized streams | Loaded by speech service | Tracked | `Thirdhand_language` |
| `configs` | Platform and operators | Reviewed non-secret settings | Service/Skill behavior | Read at startup | Tracked examples and safe defaults | All accepted projects |
| `assets/robot` | Robot team | Approved geometry | URDF/STL/materials/limits | Read-only runtime assets | Tracked if redistributable | Current robot model package |
| `local` | Local operator | Explicit copied SDK/models/runtimes | Verified host-local assets | Persistent local delivery | README/manifest metadata only | External and old project payloads |
| `runtime` | Launcher | Live events and captures | PID/log/task/cache data | Recreated per run | README only | New |
| `tools` | Platform | Source paths/manifests/system state | Imports, diagnostics, hashes | Explicit command only | Tracked | New plus reviewed scripts |
| `tests` | All owners | Source and fixtures | Verification evidence | CI/local/manual tiers | Tracked; hardware skipped by default | Consolidated |
| `archive` | Maintainers | Retired reviewed source | Provenance history | Never loaded formally | Reviewed source/docs only | Legacy projects |
| `docs` | Maintainers | Decisions and verification | Operator/developer guidance | Updated with releases | Tracked | Consolidated |

## Data Boundaries

- Secrets remain in ignored local configuration and are never included in examples.
- Images, audio, depth, point clouds, logs, PID files, and task results belong under `runtime/`.
- SDK binaries, model weights, copied source distributions, and runtime environments belong under `local/`.
- Only Robot Service owns `can0`; Skills and the LLM never send CAN frames directly.
- Only Vision Service owns live XVisio capture; consumers exchange lightweight references instead of duplicating camera ownership.
- Historical code is non-executable documentation until intentionally revived through a new reviewed migration.
