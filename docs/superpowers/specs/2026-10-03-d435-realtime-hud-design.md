# D435 Real-Time Perception HUD Design

## Goal

Build a first-stage, real-time perception HUD driven exclusively by the connected Intel RealSense D435. The system must detect objects, maintain stable identities, attach robust metric depth and camera-frame XYZ coordinates, estimate motion, and render a restrained science-fiction HUD without adding VLM, SAM, SLAM, robot control, or XVisio/Lumos input.

## Confirmed Hardware and Runtime

- The target camera is the RealSense device whose SDK serial number is `349622074226`.
- The device firmware identifies it as `Intel RealSense D435`, product ID `0B07`, not D435i. No IMU is exposed.
- XVisio/Lumos serial `250801DR48FP25002738` and `/dev/video0-1` are out of scope.
- The validated camera baseline is aligned RGB and depth at `640x480`, 30 FPS, with Z16 depth scale approximately `0.001 m`.
- The implementation runtime is Python 3.11 with a CUDA 12.8-compatible PyTorch build. The broken base Python 3.14/CUDA 13 runtime is not used.
- The existing Vision Service remains the process owner and integration boundary.

## Scope

### Included

- RealSense RGB/depth capture selected by serial number.
- Depth-to-color alignment and capture health reporting.
- YOLO Detect and optional Seg result adaptation behind a project-owned interface.
- ByteTrack as the initial tracker; tracker selection remains configurable.
- Application-level stable object IDs distinct from tracker backend IDs.
- Robust ROI/mask depth estimation, deprojection, camera-frame XYZ, motion velocity and direction.
- Unified `WorldObject` snapshots and bounded trajectory history.
- OpenCV/Supervision-assisted HUD rendering and a standalone runnable application.
- Unit, contract, replay, and opt-in hardware tests.

### Excluded

- Qwen/VLM analysis, SAM, SLAM, Rerun, robot motion, grasping, CAN access, IMU use, multi-camera registration, and autonomous actions.
- Claims that a tracker ID can remain permanent through arbitrary occlusion or restart.
- Silent model downloads during tests or normal startup.

## Architecture Choice

Three approaches were considered:

1. Extend the existing Vision Service with focused modules. This is selected because the repository already owns lifecycle, stable IDs, event contracts, tests, and browser delivery.
2. Build a separate HUD application. This would isolate dependencies but duplicate camera ownership and state contracts, risking conflicts with the running service.
3. Add HUD behavior directly to the current `camera_bridge.py`. This is fastest initially but would enlarge an already central process and make independent testing difficult.

The selected design adds focused modules below `services/vision/python/thirdhand_va/vision/` and keeps `camera_bridge.py` as composition code. Exactly one process may own the D435 at a time.

## Components

### Camera

`RealSenseCamera` accepts an explicit serial number and stream configuration. It creates the RealSense pipeline and align object once, returns immutable `RgbdFrame` values, reports calibration and depth scale, and releases the device deterministically. It refuses to select a camera by `/dev/videoN` or by first-device ordering.

Each frame carries monotonic capture time, frame number, BGR image, aligned depth array, color-stream intrinsics, and depth scale. A missing stream, timeout, serial mismatch, or disconnect produces a typed health/error result rather than a stale frame.

### Detection

`Detector` is a project-owned protocol. `UltralyticsDetector` converts model output into immutable `Detection` values containing class ID/name, confidence, XYXY box, and an optional native-resolution boolean mask. No Ultralytics object crosses this boundary.

Model path is explicit. Startup fails clearly when the configured weight is missing. The implementation does not download a model implicitly. Detect models are accepted; segmentation masks are used when present.

### Tracking

The first backend is ByteTrack because it provides a low-overhead measurable baseline. Backend track IDs are treated as transient. The existing stable-ID manager remains responsible for application identity and ambiguity/lost-state handling. Tracker selection is configuration, allowing a later TrackTrack or BoT-SORT comparison without changing downstream contracts.

### Spatial Estimation

Depth is sampled from an eroded segmentation mask when available. Without a mask, a configurable inner fraction of the bounding box is used. Invalid, non-finite, zero, too-near, and too-far samples are rejected. Remaining samples are filtered using median and MAD before estimating depth.

The aligned depth is deprojected using the aligned color stream intrinsics. XYZ is expressed in the D435 color optical frame in metres: positive X right, positive Y down, positive Z forward. Distance shown as range is the Euclidean norm of XYZ; optical-axis depth remains separately available as Z. Results with too few valid samples are explicitly unavailable.

### World State

`WorldObject` contains:

- `object_id`, `backend_track_id`, `class_id`, `class_name`, and confidence;
- box and optional mask;
- `depth_z_m`, `distance_m`, and optional `xyz_m`;
- velocity vector, scalar speed, direction, and bounded trajectory;
- `first_seen`, `last_seen`, lifecycle status, and spatial validity reason.

World-state updates use monotonic timestamps. Velocity is computed from valid temporally separated 3D observations and smoothed over a short configurable window. Invalid depth never becomes `(0, 0, 0)`. Missing detections transition through observed, temporarily lost, and expired states.

### HUD

The renderer consumes only an image and world-state snapshot. It draws restrained cyan/amber overlays: corner box lines, target anchor, leader line, information card, track trail, direction arrow, and compact system status. Labels show class, stable ID, confidence, range, XYZ, speed/direction, and lifecycle state.

Layout is clamped to the frame and chooses a left/right card position to reduce clipping. Missing spatial data displays `RANGE --` and `XYZ --`; it is never represented as a valid zero measurement. Rendering must not mutate world state.

### Application

The standalone entry point composes camera, detector, tracker, spatial estimator, state store, and renderer. It supports a display window and optional video output, prints periodic FPS/latency/health summaries, and exits cleanly on `q`, SIGINT, camera disconnect, or initialization failure.

## Configuration

Configuration includes:

- RealSense serial fixed by default to `349622074226`;
- `640x480@30` RGB and aligned depth;
- explicit model path, confidence and IoU thresholds;
- tracker backend and tracker thresholds;
- depth minimum/maximum, minimum valid pixels, ROI fraction, erosion, and MAD scale;
- trajectory length, lost timeout, velocity smoothing, and movement threshold;
- HUD colors, scale, visibility switches, and output mode.

Invalid configurations fail before opening the camera.

## Licensing Boundary

The repository is MIT licensed, while the installed Ultralytics package and official YOLO models are offered under AGPL-3.0 or an Ultralytics Enterprise license. The adapter is optional and isolated. Documentation must state that distributing a non-AGPL product with Ultralytics requires an appropriate commercial license or replacement with a license-compatible detector. librealsense is Apache-2.0 and Supervision is MIT.

## Failure Handling

- Wrong or absent serial: fail closed with a device list; never fall back to XVisio.
- Camera already owned: report ownership/busy error without killing the other process.
- Frame timeout or disconnect: stop publishing fresh state and exit or reconnect only when explicitly configured.
- Detector failure: report the model error; do not emit fabricated empty-success results.
- Missing/invalid depth: preserve 2D detection and tracking while marking spatial data unavailable.
- Tracker ID switch: stable-ID layer may re-associate when evidence supports it; ambiguity remains explicit.
- Rendering failure: surface the error without corrupting perception state.

## Testing and Acceptance

### Automated

- Camera configuration and serial-selection tests use a fake RealSense backend.
- Depth tests cover masks, ROI fallback, zero depth, edge contamination, outliers, insufficient samples, and intrinsics/deprojection.
- Detection adapter tests use synthetic Ultralytics-shaped results.
- Tracking/world-state tests cover stable IDs, occlusion, expiry, invalid depth, timestamp gaps, speed, direction, and bounded history.
- HUD tests verify frame shape, non-mutation, clipping, and missing-data labels.
- Pipeline replay tests use synthetic frames and detections without hardware, network, or model downloads.

### Hardware gate

An opt-in test opens only serial `349622074226`, captures at least 40 aligned frames at `640x480@30`, verifies matching shapes, plausible depth scale, usable depth coverage, intrinsics, clean shutdown, and that XVisio was never selected.

### Completion criteria

- A single command starts the HUD using the D435 and an explicit local model.
- Every visible detection has a stable application ID and trajectory.
- Valid targets show robust range and camera-frame XYZ; invalid depth is visibly unavailable.
- Moving targets show smoothed speed and direction.
- The pipeline runs without using the XVisio camera and without requiring Qwen, SAM, SLAM, Rerun, robot control, or network access.
- Automated tests pass and the opt-in D435 camera test passes on the connected hardware.

## Implementation Order

1. Camera abstraction and D435 hardware gate.
2. Spatial depth filtering and deprojection.
3. Detector protocol and Ultralytics adapter.
4. ByteTrack adapter and stable World State.
5. HUD renderer.
6. Standalone application and configuration.
7. Replay, integration, performance, and hardware verification.
