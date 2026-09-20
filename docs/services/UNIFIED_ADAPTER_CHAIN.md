# Unified Vision, Robot, And Web Skill Adapters

## Service Ownership

- Web Gateway owns LAN access on `192.168.58.68:9983`.
- Vision Service is the only XVisio owner and listens on `127.0.0.1:3100`.
- Robot Service is the only Startouch SDK and `can0` owner and listens on `127.0.0.1:3000`.
- Bottle-pick runtime listens on `127.0.0.1:8766`; it never opens the camera or CAN device directly.
- Speech remains independent on `127.0.0.1:3004`.

## Request Chain

1. The browser confirms a `pick_and_place_bottle@1` candidate on port 9983.
2. `BottlePickAdapter` reads `GET /api/vision/observation` from port 3100.
3. The adapter binds the selected stable ID to one request ID and calls `POST /api/va/start` on port 8766.
4. The bottle-pick runtime consumes Vision Service events through `VisionServiceClient`.
5. When physical execution is explicitly enabled and all gates pass, its `RobotWebSocketClient` uses the low-level protocol on port 3000.
6. Robot Service alone translates `move_l`, `move_joint`, gripper, preset, state, and software-stop messages to the Startouch bridge.

## Adapter Contracts

### Vision Service

- `GET /api/vision/observation` returns the latest normalized observation.
- `GET /api/vision/targets/{1..5}` resolves one stable target.
- `POST /api/vision/select` preserves or creates a request ID.
- `/ws` remains the event stream used by the web UI and bottle-pick runtime.
- Vision responses always state `robotControlEnabled: false`.

The XVisio bridge publishes `thirdhand-va-detection-v3`. One event binds the
RGB image, registered metric depth, XYZ image, inference result, and overlay to
the same `frame_id` and `monotonic_ns`. Each target includes:

- a request-independent `stable_id` and backend tracking ID;
- `tentative`, `confirmed`, `occluded`, `lost`, or `retired` track state;
- mask-derived depth validity, valid-point count, and valid ratio;
- a robust `camera_xyz_m` estimate when current depth is usable;
- `base_xyz_m: null` until an approved hand-eye transform is available;
- explicit perception and geometry blockers.

Occluded, lost, and retired tracks retain identity but never retain actionable
depth. Their depth validity is false and their metric coordinates are cleared.
Selection binds one confirmed stable ID to one request ID; it does not silently
switch to another target after occlusion or loss.

The camera bridge has first-frame and stalled-frame watchdogs. Vision Service
restarts a failed bridge, clears stale images and detections, and replays camera,
configuration, and model provenance to reconnecting Skill clients.

### Robot Service

The `/ws` endpoint supports the `thirdhand-robot-capability-v1` handshake and
`thirdhand-robot-lowlevel-v1` commands. State messages contain explicit SI units,
strictly increasing sequence data, flange pose, joints, velocity, and gripper width.
The Home preset is the commissioned non-zero joint pose; an accidental all-zero
target remains blocked unless it is sent through the explicitly named `zero` preset.
The former all-zero Home is now `zero`; the `home` name is shared by Robot Service,
the 9983 UI, voice control, and Bottle-pick for the commissioned safe Home pose.

### Web Skill Adapter

The web adapter does not generate a trajectory. It only:

- requires a selected stable target;
- creates one correlated VA request;
- reports progress and the terminal Skill result;
- fails closed when Vision Service or the bottle-pick runtime is unavailable.

## Runtime Configuration

`configs/runtime/manual-control.json` starts services in this order:

1. Robot Service
2. Speech Service
3. Vision Service
4. Bottle-pick runtime
5. Web Gateway

The bottle-pick runtime receives:

- `THIRDHAND_VA_VISION_WS_URL=ws://127.0.0.1:3100/ws`
- `THIRDHAND_VISION_HTTP_URL=http://127.0.0.1:3100`
- `THIRDHAND_ROBOT_WS_URL=ws://127.0.0.1:3000/ws`

## Current Safety Lock

The adapters are online, but physical bottle picking remains disabled:

- `configs/action.yaml` has `execution_enabled: false`;
- the runtime profile sets `THIRDHAND_VA_ENABLE_ROBOT=0`;
- Vision Service supplies camera-frame depth evidence and model provenance, but
  no hand-eye artifact is approved, so `base_xyz_m` remains null;
- the placement path and supervised physical-motion acceptance are not complete.

Do not remove these locks merely to make the button advance. Physical activation
requires an approved hand-eye calibration, accepted v3 depth observations, a
validated placement path, fresh stationary robot feedback, and one explicit
supervised-motion authorization.
