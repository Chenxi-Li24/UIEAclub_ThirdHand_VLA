# D435 Real-Time Perception HUD Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a standalone, tested real-time HUD that exclusively uses RealSense serial `349622074226` for RGB/depth, detects and tracks objects, estimates robust range/XYZ and motion, maintains stable world objects, and renders dynamic information cards and trails.

**Architecture:** Add project-owned camera, perception, spatial, world-state, visualization, and application boundaries below the existing Vision Service Python package. Ultralytics and RealSense SDK objects remain inside adapters; immutable project types connect modules. ByteTrack supplies transient backend IDs while a HUD-specific stable-ID store supplies application IDs and lifecycle state.

**Tech Stack:** Python 3.11, NumPy, OpenCV, pyrealsense2/librealsense, Ultralytics YOLO26/ByteTrack, optional Supervision, pytest.

**Spec:** `docs/superpowers/specs/2026-10-03-d435-realtime-hud-design.md`

## Global Constraints

- Open only RealSense SDK serial `349622074226`; never choose a camera by `/dev/videoN` or first-device order.
- Treat the hardware as D435 with no IMU, regardless of the earlier D435i label.
- Default streams are aligned RGB and depth at `640x480@30`.
- Do not add Qwen/VLM, SAM, SLAM, Rerun, robot/CAN control, or XVisio/Lumos input.
- Never download model weights implicitly; the YOLO model path is explicit and must exist.
- Missing depth preserves 2D tracking and is represented as unavailable, never `(0, 0, 0)`.
- Keep Ultralytics optional and document its AGPL-3.0/commercial-license boundary.
- Do not overwrite or bundle unrelated user changes already present in the dirty repository.

## Review Focus

- Multiple attached cameras: opening the HUD must select serial `349622074226` and never XVisio.
- Camera loss or ownership conflict: initialization/runtime must fail clearly without emitting stale frames or killing another process.
- Depth discontinuities and invalid pixels: edge/background contamination must not become an object's range or XYZ.
- Track ID changes and short occlusion: application object IDs must remain bounded and ambiguity/loss must be explicit.
- Display edges and missing data: HUD cards must remain on-frame and show unavailable spatial data honestly.

---

### Task 1: RealSense Camera Contract and Hardware Gate

**Files:**
- Create: `services/vision/python/thirdhand_va/vision/camera/realsense.py`
- Modify: `services/vision/python/thirdhand_va/vision/camera/__init__.py`
- Create: `tests/python/vision_service/test_d435_camera.py`
- Create: `scripts/vision/verify_d435_hud_camera.py`

**Interfaces:**
- Consumes: `pyrealsense2` through an injectable backend and explicit device serial.
- Produces: `CameraIntrinsics`, `RgbdCapture`, `RealSenseConfig`, `RealSenseCamera.open()`, `read(timeout_ms)`, and `close()`.

- [ ] **Step 1: Write failing unit tests for configuration, serial selection, and frame conversion**

Test that `RealSenseConfig()` defaults to serial `349622074226` and `640x480@30`; rejects empty serials and invalid dimensions/FPS; fake enumeration containing XVisio-like and multiple RealSense devices still selects only the exact serial; `read()` returns BGR `uint8`, aligned depth metres as `float32`, color intrinsics, positive sequence/monotonic timestamp; timeout, missing stream, serial mismatch, busy device, and disconnect raise typed `RealSenseCameraError`; close is idempotent.

- [ ] **Step 2: Run the focused test and verify RED**

Run: `local/runtimes/vision-python/bin/python -m pytest tests/python/vision_service/test_d435_camera.py -q`

Expected: FAIL because `thirdhand_va.vision.camera.realsense` does not exist.

- [ ] **Step 3: Implement the camera adapter and opt-in verifier**

Implement immutable dataclasses and a context-managed adapter. Create `rs.align(rs.stream.color)` once after exact serial binding. Convert aligned Z16 depth using the device depth scale and set invalid values to `NaN`. The verifier must capture 40 frames, validate shapes, intrinsics, depth scale/coverage and observed FPS, and print a machine-readable summary; it must not write images or open XVisio.

- [ ] **Step 4: Run unit tests and the connected-camera gate**

Run: `local/runtimes/vision-python/bin/python -m pytest tests/python/vision_service/test_d435_camera.py -q`

Expected: PASS.

Run: `PYTHONPATH=services/vision/python /home/nieqingcao/miniconda3/envs/thirdhand-remind3d/bin/python scripts/vision/verify_d435_hud_camera.py --serial 349622074226 --frames 40`

Expected: exit 0; `camera_name` is `Intel RealSense D435`, both arrays are `640x480`, median FPS is near 30, and valid depth coverage is nonzero.

- [ ] **Step 5: Commit**

```bash
git add services/vision/python/thirdhand_va/vision/camera/realsense.py services/vision/python/thirdhand_va/vision/camera/__init__.py tests/python/vision_service/test_d435_camera.py scripts/vision/verify_d435_hud_camera.py
git commit -m "feat: add serial-bound D435 RGBD capture"
```

### Task 2: Detection and Tracking Adapters

**Files:**
- Create: `services/vision/python/thirdhand_va/vision/perception/object_detection.py`
- Create: `services/vision/python/thirdhand_va/vision/perception/ultralytics_adapter.py`
- Create: `services/vision/python/thirdhand_va/vision/tracking/bytetrack_adapter.py`
- Modify: `services/vision/python/thirdhand_va/vision/perception/__init__.py`
- Modify: `services/vision/python/thirdhand_va/vision/tracking/__init__.py`
- Create: `tests/python/vision_service/test_hud_detection_tracking.py`

**Interfaces:**
- Consumes: BGR NumPy frames and explicit local model path.
- Produces: immutable `ObjectDetection`, `TrackedDetection`, `Detector.detect(frame)`, and `ObjectTracker.update(detections, frame, persist=True)` contracts.

- [ ] **Step 1: Write failing adapter tests**

Test immutable normalized detections, class-name mapping, confidence/box validation, optional boolean masks resized to native frame dimensions, empty results, explicit missing-model failure, no implicit downloads, ByteTrack tracker IDs, lost/empty frames, and rejection of malformed backend values. Use fake Ultralytics-shaped results; unit tests must not load weights.

- [ ] **Step 2: Run the focused test and verify RED**

Run: `local/runtimes/vision-python/bin/python -m pytest tests/python/vision_service/test_hud_detection_tracking.py -q`

Expected: FAIL on missing modules.

- [ ] **Step 3: Implement project-owned protocols and Ultralytics/ByteTrack adapters**

`UltralyticsDetector` loads only an existing path and converts `Results.boxes`/optional masks. `UltralyticsByteTrack` owns persistence and explicitly requests `bytetrack.yaml`; downstream code receives only project dataclasses. Imports of `ultralytics` are lazy so geometry/HUD tests run without it.

- [ ] **Step 4: Run the focused suite**

Run: `local/runtimes/vision-python/bin/python -m pytest tests/python/vision_service/test_hud_detection_tracking.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/vision/python/thirdhand_va/vision/perception/object_detection.py services/vision/python/thirdhand_va/vision/perception/ultralytics_adapter.py services/vision/python/thirdhand_va/vision/perception/__init__.py services/vision/python/thirdhand_va/vision/tracking/bytetrack_adapter.py services/vision/python/thirdhand_va/vision/tracking/__init__.py tests/python/vision_service/test_hud_detection_tracking.py
git commit -m "feat: add object detection and ByteTrack adapters"
```

### Task 3: Robust Spatial Estimation and World State

**Files:**
- Create: `services/vision/python/thirdhand_va/vision/geometry/object_spatial.py`
- Create: `services/vision/python/thirdhand_va/vision/world_state.py`
- Modify: `services/vision/python/thirdhand_va/vision/geometry/__init__.py`
- Create: `tests/python/vision_service/test_hud_spatial.py`
- Create: `tests/python/vision_service/test_hud_world_state.py`

**Interfaces:**
- Consumes: `RgbdCapture`, `TrackedDetection`, and monotonic timestamps.
- Produces: `SpatialEstimate`, `SpatialEstimator.estimate(detection, capture)`, `WorldObject`, `WorldSnapshot`, and `WorldState.update(tracks, spatial, now_ns)`.

- [ ] **Step 1: Write failing spatial tests**

Cover mask-first sampling, bbox-inner-ROI fallback, erosion, zero/NaN/Inf/out-of-range rejection, MAD outlier rejection, too-few samples, correct pinhole deprojection, optical Z versus Euclidean range, and a foreground object beside a farther background edge.

- [ ] **Step 2: Run spatial tests and verify RED**

Run: `local/runtimes/vision-python/bin/python -m pytest tests/python/vision_service/test_hud_spatial.py -q`

Expected: FAIL on missing module.

- [ ] **Step 3: Implement robust spatial estimation**

Provide `SpatialConfig(min_depth_m, max_depth_m, min_valid_pixels, roi_fraction, erosion_px, mad_scale)`. Estimate a robust representative pixel and Z from surviving samples, deproject with aligned color intrinsics, and return a reason code when unavailable.

- [ ] **Step 4: Run spatial tests and verify GREEN**

Expected: PASS.

- [ ] **Step 5: Write failing world-state tests**

Test stable IDs distinct from backend IDs, confirmation, short occlusion, expiry, finite-time validation, bounded trajectory history, 3D velocity and exponential smoothing, stationary/moving status, eight-way direction labels, invalid-depth continuity without fabricated coordinates, class change rejection, and deterministic snapshot ordering.

- [ ] **Step 6: Run world-state tests and verify RED**

Run: `local/runtimes/vision-python/bin/python -m pytest tests/python/vision_service/test_hud_world_state.py -q`

Expected: FAIL on missing module.

- [ ] **Step 7: Implement world state**

Use a separate bounded ID allocator rather than the bottle-specific `[1,5]` manager. Keep histories by stable object ID, preserve last valid position only as historical data, and set current spatial values to unavailable when the current measurement is invalid. Lifecycle states are `tentative`, `confirmed`, `occluded`, and `expired`.

- [ ] **Step 8: Run both suites**

Run: `local/runtimes/vision-python/bin/python -m pytest tests/python/vision_service/test_hud_spatial.py tests/python/vision_service/test_hud_world_state.py -q`

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add services/vision/python/thirdhand_va/vision/geometry/object_spatial.py services/vision/python/thirdhand_va/vision/geometry/__init__.py services/vision/python/thirdhand_va/vision/world_state.py tests/python/vision_service/test_hud_spatial.py tests/python/vision_service/test_hud_world_state.py
git commit -m "feat: add robust object spatial world state"
```

### Task 4: HUD Renderer

**Files:**
- Create: `services/vision/python/thirdhand_va/vision/visualization/hud.py`
- Modify: `services/vision/python/thirdhand_va/vision/visualization/__init__.py`
- Create: `tests/python/vision_service/test_hud_renderer.py`

**Interfaces:**
- Consumes: BGR frame plus immutable `WorldSnapshot` and `HudStatus`.
- Produces: `HudRenderer.render(frame, snapshot, status) -> NDArray[np.uint8]`.

- [ ] **Step 1: Write failing renderer tests**

Test output shape/dtype, input non-mutation, visible pixels for confirmed targets, card placement near all four edges, clipped boxes, trail and direction arrow drawing, system FPS/object count, and exact missing-data labels `RANGE --` and `XYZ --`. Include empty-world rendering.

- [ ] **Step 2: Run the focused test and verify RED**

Run: `local/runtimes/vision-python/bin/python -m pytest tests/python/vision_service/test_hud_renderer.py -q`

Expected: FAIL on missing module.

- [ ] **Step 3: Implement the OpenCV renderer**

Keep rendering pure. Use corner brackets instead of heavy filled boxes, deterministic per-object colors, an anchor/leader line, clamped information cards, bounded trails, movement arrows, and a compact top-right status block. Supervision may be used when installed but must not be required for the core renderer.

- [ ] **Step 4: Run tests and generate one synthetic preview**

Run: `local/runtimes/vision-python/bin/python -m pytest tests/python/vision_service/test_hud_renderer.py -q`

Expected: PASS.

Render a synthetic frame to `.superpowers/sdd/2026-10-03-d435-realtime-hud/hud-preview.png` for visual inspection; do not commit the artifact.

- [ ] **Step 5: Commit**

```bash
git add services/vision/python/thirdhand_va/vision/visualization/hud.py services/vision/python/thirdhand_va/vision/visualization/__init__.py tests/python/vision_service/test_hud_renderer.py
git commit -m "feat: add realtime perception HUD renderer"
```

### Task 5: Standalone Application, Configuration, Documentation, and End-to-End Verification

**Files:**
- Create: `services/vision/python/thirdhand_va/vision/hud_app.py`
- Create: `configs/d435-hud.yaml`
- Create: `scripts/vision/run_d435_hud.sh`
- Create: `tests/python/vision_service/test_hud_app.py`
- Create: `docs/D435_HUD.md`
- Modify: `services/README.md`

**Interfaces:**
- Consumes: Tasks 1–4 interfaces plus YAML configuration and explicit model path.
- Produces: `HudApp.run()`, CLI module `python -m thirdhand_va.vision.hud_app`, and launcher `scripts/vision/run_d435_hud.sh`.

- [ ] **Step 1: Write failing orchestration and configuration tests**

Test strict YAML parsing, exact camera serial default, missing model rejection before camera open, dependency construction, per-frame data flow, empty detections, unavailable depth, detector exception, camera timeout/disconnect, `q`/SIGINT clean shutdown, optional video writer cleanup, periodic metrics, and an all-fake three-frame replay that yields deterministic IDs and HUD frames.

- [ ] **Step 2: Run the focused test and verify RED**

Run: `local/runtimes/vision-python/bin/python -m pytest tests/python/vision_service/test_hud_app.py -q`

Expected: FAIL on missing application module.

- [ ] **Step 3: Implement the composition root and strict configuration**

Validate configuration before opening hardware. Compose one camera owner, Ultralytics ByteTrack inference, spatial estimates, world state, and renderer. Support `--config`, `--model`, `--headless`, `--output`, and `--max-frames`; log FPS, P50/P95 latency, object count, camera health and current serial. Exit nonzero on initialization/runtime failure.

- [ ] **Step 4: Add operator documentation and licensing notice**

Document environment selection, dependency installation without changing base Python, local model placement, exact run commands, controls, coordinate convention, D435-versus-D435i correction, XVisio exclusion, common camera ownership failures, test commands, and Ultralytics AGPL/commercial-license requirements.

- [ ] **Step 5: Run focused and complete HUD suites**

Run: `local/runtimes/vision-python/bin/python -m pytest tests/python/vision_service/test_d435_camera.py tests/python/vision_service/test_hud_detection_tracking.py tests/python/vision_service/test_hud_spatial.py tests/python/vision_service/test_hud_world_state.py tests/python/vision_service/test_hud_renderer.py tests/python/vision_service/test_hud_app.py -q`

Expected: PASS.

- [ ] **Step 6: Run repository-adjacent regressions**

Run: `local/runtimes/vision-python/bin/python -m pytest tests/python/vision_service -q`

Expected: PASS with no new failures.

- [ ] **Step 7: Run connected-hardware and local-model smoke tests**

Run the Task 1 hardware verifier again. Then run:

`PYTHONPATH=services/vision/python local/runtimes/vision-python/bin/python -m thirdhand_va.vision.hud_app --config configs/d435-hud.yaml --model <existing-local-yolo-model> --headless --max-frames 120`

Expected: exact serial `349622074226`, clean 120-frame exit, nonzero detections when objects from the model vocabulary are visible, spatial estimates for detections with valid depth, no XVisio access, and no implicit download. If no compatible local model exists, record this smoke test as blocked rather than downloading one; all fake/replay and camera-only gates must still pass.

- [ ] **Step 8: Commit**

```bash
git add services/vision/python/thirdhand_va/vision/hud_app.py configs/d435-hud.yaml scripts/vision/run_d435_hud.sh tests/python/vision_service/test_hud_app.py docs/D435_HUD.md services/README.md
git commit -m "feat: deliver standalone D435 perception HUD"
```

- [ ] **Step 9: Final verification**

Run `git diff --check`, the complete HUD suite, adjacent Vision Service suite, D435 hardware verifier, and the 120-frame local-model smoke test. Record exact commands, versions, pass counts, FPS/latency, and any hardware/model limitation in the execution ledger.
