# ThirdHand VLA system architecture

## Runtime boundaries

The repository contains two cooperating but independently deployable systems.

### Packaged VLA application

`src/uiea_thirdhand_vla/` is installed through `pyproject.toml` and started with
`python -m uiea_thirdhand_vla`. Its default web port is `8000`.

```text
Lumos camera
    -> calibration and ArUco/YOLO perception
    -> deterministic state machine
    -> safety checks
    -> robot and gripper adapters

Cloud VLA (optional) -> recommendation -> state-machine validation
Voice pipeline (optional) -> intent -> state-machine command
FastAPI console -> status and operator commands
```

The VLA client recommends actions; it does not bypass the local state machine or
safety layer.

### Startouch web-control stack

`web-control/` is the hardware-tested browser control path. The Node proxy on
port `3000` owns the browser session and starts or communicates with local
Python bridges. The Startouch bridge is the sole robot controller for its
configured CAN interface. The optional Lumos camera HTTP service uses port
`3001`.

```text
Browser UI :3000
    -> Node proxy
       -> Startouch Python bridge -> SDK -> can0 -> Lumos Touch R1
       -> D435 camera bridge -> MJPEG and guarded detections

Browser UI
    -> Lumos HTTP service :3001 -> Lumos RGB stream
```

The fixed A/B demo is a separate loopback service on `127.0.0.1:8766`. Resource
locks prevent it and the Startouch bridge from controlling the same CAN
interface simultaneously.

## Packaged application modules

| Module | Responsibility |
| --- | --- |
| `config` | Load and validate YAML configuration |
| `perception` | Camera capture, calibration, projection, and detection |
| `reasoning` | Optional cloud VLA sessions and recommendations |
| `orchestration` | Deterministic state machine and task flow |
| `control` | Robot, gripper, motion bounds, watchdog, and stop behavior |
| `logging` | Structured run metadata, transitions, and optional frames |
| `web` | FastAPI application and browser assets |

## Vision safety path

The offline REMIND-3D work under `web-control/server/vision/` separates camera
geometry, instance pose estimation, tracking, appearance identity, object
memory, and the fail-closed safety decision. Configuration lives in
`configs/vision/remind3d.yaml`. Robot execution remains disabled there until the
documented calibration and hardware acceptance gates are complete.

## Safety invariants

1. A process must hold the per-interface control lock before accessing real
   robot hardware.
2. Motion commands are checked against joint/workspace bounds and watchdog
   limits before execution.
3. Ambiguous identity, stale pose, invalid depth, or missing calibration fails
   closed in the vision-safety path.
4. Software stop does not replace the independent hardware emergency stop.
5. Offline tests use a non-hardware CAN interface name and never command motion.

## Runtime artifacts

Logs, captured frames, PID files, point backups, calibration output, and model
weights remain outside Git. Small deterministic fixtures under test directories
are versioned. Model locations and acquisition are documented in
[model_assets.md](model_assets.md).
