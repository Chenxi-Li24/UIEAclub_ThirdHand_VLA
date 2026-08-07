# Dual-Camera Online Perception Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Continuously run RTMDet-Ins and DINO on Lumos RGB while pairing D435 metric depth into the existing fail-closed dual-camera core, expose read-only status/overlay endpoints, and leave all robot execution disabled.

**Architecture:** One Python camera bridge owns the D435 and GPU model runtime so raw depth never crosses a JSON boundary. It reads timestamped Lumos JPEG snapshots, keeps only the latest RGB/depth frames, runs the existing identity/fusion core, and emits read-only JSON plus a Lumos overlay pipe to Node. Physical device names stay inside a role map so a future native-aligned depth fisheye can replace both current inputs without changing identity, target-state, or safety consumers.

**Tech Stack:** Python 3.11, NumPy, OpenCV, pyrealsense2, PyTorch 2.7/cu128, MMDetection/RTMDet-Ins, Transformers/DINOv2, Express, Node.js, pytest, Node smoke tests.

## Global Constraints

- `canonical_rgb` is Lumos RGB; `metric_depth` is D435 depth; D435 RGB is `debug_only`.
- RGB-depth pairing skew is at most 50 ms, fused frame age at most 200 ms, and robot-pose skew at most 50 ms.
- Model p95 latency is at most 300 ms and GPU reserved memory at most 7.2 GiB.
- Processing is latest-frame-only; a slow model drops old frames instead of growing a queue.
- A stream with no new frame for more than 2 s is stale/disconnected and must re-enter through normal confirmation gates.
- `robot_execution_enabled` remains exactly `false`; deployment must not write to robot, gripper, or CAN.
- Invalid/missing calibration, depth, robot pose, identity confirmation, or timing may preserve `trackable` identity but must always produce `actionable: false`.
- The current COCO checkpoint is an infrastructure fallback, not a task-trained transparent-bottle checkpoint.
- The deployed service uses `STARTOUCH_SIMULATE=1` and a non-CAN placeholder interface.

## File Structure

- `web-control/server/vision/online_frames.py`: immutable logical camera-role frames and latest-only pairing.
- `web-control/server/vision/dual_camera.py`: generic role names and missing-input fail-closed behavior.
- `web-control/server/vision_models/online.py`: model engine, result serialization, overlay, and bounded metrics.
- `web-control/server/vision_models/lumos_client.py`: read-only snapshot client and provenance validation.
- `web-control/server/lumos_http_server.py`: snapshot endpoint with sequence/monotonic headers.
- `web-control/server/camera_bridge.py`: sole D435 owner and orchestration threads; no robot connection.
- `web-control/server/camera-bridge.js`: child configuration and second MJPEG pipe.
- `web-control/server/vision-status.js`: bounded presentation-only status store.
- `web-control/server/proxy.js`: read-only status and overlay routes.
- `web-control/web/camera-test.html`: role, overlay, metrics, and blocker display.
- `configs/vision/remind3d.yaml`: online roles, timing, source, and model runtime.
- `scripts/vision/start_dual_camera_online.sh`: safe simulated lifecycle.
- `scripts/vision/verify_dual_camera_online.py`: live readiness/soak verifier.

---

### Task 1: Logical Roles and Fail-Closed Missing Inputs

**Files:**
- Create: `web-control/server/vision/online_frames.py`
- Create: `web-control/server/tests/vision/test_online_frames.py`
- Modify: `web-control/server/vision/dual_camera.py`
- Modify: `web-control/server/vision/__init__.py`
- Modify: `web-control/server/tests/vision/test_dual_camera.py`

**Interfaces:**
- Produces `CameraRoleMap(canonical_rgb_source, metric_depth_source, debug_rgb_source, fusion_mode)`.
- Produces immutable `RgbFrame(stamp, image_rgb)`, `DepthFrame(stamp, depth_z_m)`, and `FramePair`.
- Produces `LatestFramePairer(role_map, max_frame_skew_ns, max_frame_age_ns).pair(rgb, depth, now_ns)`.
- `DualCameraConfig` gains `roles: CameraRoleMap`.
- `DualCameraPerception.process` accepts optional robot pose, depth, and calibration.

- [ ] **Step 1: Write failing role and pairing tests**

```python
def test_current_roles_reject_excessive_pair_skew():
    roles = CameraRoleMap("lumos_rgb", "d435_depth", "d435_rgb", "cross_camera")
    pairer = LatestFramePairer(roles, 50_000_000, 200_000_000)
    rgb = RgbFrame(FrameStamp("lumos_rgb", 4, 1_000_000_000), np.zeros((5, 5, 3), np.uint8))
    depth = DepthFrame(FrameStamp("d435_depth", 9, 1_070_000_000), np.ones((5, 5)))
    pair = pairer.pair(rgb, depth, 1_080_000_000)
    assert pair.frame_skew_ns == 70_000_000
    assert pair.reasons == ("frame_skew_exceeded",)
```

Add cases for wrong source roles, future timestamps, invalid arrays, stale frames, and a future `native_aligned` map with separate logical RGB/depth names from one device.

- [ ] **Step 2: Verify the tests fail**

Run: `PYTHONPATH=web-control/server pytest -q web-control/server/tests/vision/test_online_frames.py web-control/server/tests/vision/test_dual_camera.py`

Expected: collection fails because `vision.online_frames` and optional-input behavior do not exist.

- [ ] **Step 3: Implement immutable frames and pairing**

Copy arrays, mark them read-only, validate source names, finite positive depth, shapes, timestamps, and return ordered deduplicated reasons. Pairing never sleeps, buffers, interpolates, or invents timestamps.

- [ ] **Step 4: Preserve identity while rejecting missing geometry**

Missing calibration, depth, or robot pose adds `calibration_unavailable`, `depth_unavailable`, or `robot_pose_unavailable`, skips registration/base transform, and builds identity observations with `pose=None`. Only set identity calibration from a concrete content-addressed bundle. All such targets remain non-actionable.

- [ ] **Step 5: Run vision tests**

Run: `PYTHONPATH=web-control/server pytest -q web-control/server/tests/vision`

Expected: all pass; validated synthetic inputs still become actionable only after existing confirmation gates.

- [ ] **Step 6: Commit**

```bash
git add web-control/server/vision/online_frames.py web-control/server/vision/dual_camera.py web-control/server/vision/__init__.py web-control/server/tests/vision/test_online_frames.py web-control/server/tests/vision/test_dual_camera.py
git commit -m "feat(vision): add logical online camera roles"
```

---

### Task 2: Timestamped Lumos Snapshot and Client

**Files:**
- Modify: `web-control/server/lumos_http_server.py`
- Modify: `web-control/server/tests/test_lumos_http_server.py`
- Create: `web-control/server/vision_models/lumos_client.py`
- Create: `web-control/server/tests/vision_models/test_lumos_client.py`

**Interfaces:**
- `GET /frame.jpg` returns JPEG plus `X-Lumos-Sequence` and `X-Lumos-Monotonic-Ns`.
- `LumosSnapshotClient(url, timeout_s).read(after_sequence) -> RgbFrame | None`.
- Loopback HTTP is accepted by default; remote input requires an explicit opt-in.

- [ ] **Step 1: Write failing endpoint/client tests**

```python
def test_client_preserves_snapshot_provenance(fake_opener):
    client = LumosSnapshotClient("http://127.0.0.1:3001/frame.jpg", 1.0, opener=fake_opener)
    frame = client.read(after_sequence=6)
    assert frame.stamp == FrameStamp("lumos_rgb", 7, 123_000_000)
    assert frame.image_rgb.shape == (8, 8, 3)
```

Use fake capture/HTTP responses; test missing/backward headers, non-JPEG, payload over 8 MiB, remote URL rejection, and 503.

- [ ] **Step 2: Verify tests fail**

Run: `PYTHONPATH=web-control/server pytest -q web-control/server/tests/test_lumos_http_server.py web-control/server/tests/vision_models/test_lumos_client.py`

Expected: failures because snapshot headers and client do not exist.

- [ ] **Step 3: Implement snapshot provenance**

Store `last_frame_monotonic_ns = time.monotonic_ns()` when publishing. `/frame.jpg` returns the latest immutable JPEG/headers or the existing JSON 503 status. Preserve `/health` and `/camera_lumos` compatibility.

- [ ] **Step 4: Implement bounded client**

Validate scheme/host/status/content type/byte limit/strict sequence/timestamp, decode BGR JPEG, convert to RGB, and return `None` only for a non-new sequence. Transport or contract failures raise `ModelContractError`; retries belong to the orchestration thread.

- [ ] **Step 5: Test and commit**

```bash
PYTHONPATH=web-control/server pytest -q web-control/server/tests/test_lumos_http_server.py web-control/server/tests/vision_models/test_lumos_client.py
git add web-control/server/lumos_http_server.py web-control/server/vision_models/lumos_client.py web-control/server/tests/test_lumos_http_server.py web-control/server/tests/vision_models/test_lumos_client.py
git commit -m "feat(vision): expose timestamped Lumos snapshots"
```

---

### Task 3: Hardware-Independent Online Model Engine

**Files:**
- Create: `web-control/server/vision_models/online.py`
- Create: `web-control/server/tests/vision_models/test_online.py`
- Modify: `web-control/server/vision_models/__init__.py`
- Modify: `configs/vision/remind3d.yaml`
- Modify: `web-control/server/vision_models/offline_replay.py`
- Modify: `web-control/server/tests/vision_models/test_offline_replay.py`

**Interfaces:**
- Produces `OnlineVisionConfig` from `load_online_vision_config(path)`.
- Produces `OnlinePerceptionEngine(segmenter, encoder, perception, config).process(pair, robot_pose, calibration, arm_stationary, now_ns)`; the four constructor collaborators use structural `predict`, `encode`, `process`, and immutable-config contracts so unit tests can inject hardware-free fakes.
- Produces `OnlinePerceptionResult.to_event()` and `render_overlay(image_rgb, result)`.

- [ ] **Step 1: Write failing engine tests with fake models**

```python
def test_engine_uses_lumos_identity_and_rejects_missing_calibration():
    result = fake_engine().process(valid_pair(), robot_pose=None, calibration=None, arm_stationary=True, now_ns=1_020_000_000)
    target = result.targets[0]
    assert result.canonical_rgb_source == "lumos_rgb"
    assert result.metric_depth_source == "d435_depth"
    assert target.identity_id == 1
    assert target.actionable is False
    assert "calibration_unavailable" in target.reasons
```

Also test second-frame confirmation, empty detections, model errors, bounded 256-sample latency, p95, overlay dimensions, and JSON serialization without NumPy/NaN.

- [ ] **Step 2: Verify tests fail**

Run: `PYTHONPATH=web-control/server pytest -q web-control/server/tests/vision_models/test_online.py web-control/server/tests/vision_models/test_offline_replay.py`

- [ ] **Step 3: Extend exact online YAML schema**

Add role, online, and timing objects. Use the official COCO RTMDet checkpoint as fallback with `task_checkpoint_validated:false`, DINOv2-small, CUDA, latest-only scheduling, and execution false. Reject remote URLs, nonexistent files, wrong types, non-CUDA devices, and any true execution flag.

- [ ] **Step 4: Implement dependency-injected engine**

Run detector then DINO once per accepted Lumos frame, calculate mask visibility from mask/bbox area, delegate identity/geometry to `DualCameraPerception`, record latency and optional CUDA memory, and expose model/task-checkpoint status. Do not import hardware or robot modules.

- [ ] **Step 5: Test and commit**

```bash
PYTHONPATH=web-control/server pytest -q web-control/server/tests/vision web-control/server/tests/vision_models
git add configs/vision/remind3d.yaml web-control/server/vision_models/online.py web-control/server/vision_models/offline_replay.py web-control/server/vision_models/__init__.py web-control/server/tests/vision_models/test_online.py web-control/server/tests/vision_models/test_offline_replay.py
git commit -m "feat(vision): add online REMIND perception engine"
```

---

### Task 4: D435 Ownership and Online Bridge Integration

**Files:**
- Modify: `requirements/remind3d-cu128.txt`
- Modify: `scripts/vision/bootstrap_remind3d_env.sh`
- Modify: `tests/vision_deployment/test_bootstrap_contract.py`
- Modify: `web-control/server/camera_bridge.py`
- Modify: `web-control/server/camera-bridge.js`
- Create: `tests/vision_deployment/test_online_camera_bridge_contract.py`

**Interfaces:**
- Pins `pyrealsense2==2.57.7.10387` in the isolated model environment.
- Python reads `VISION_ONLINE_ENABLED`, `VISION_CONFIG`, `LUMOS_SNAPSHOT_URL`, and `VISION_OVERLAY_FD`.
- Node exposes `CameraBridge.getVisionMjpegStream()` from child fd 4.
- Child emits `vision_status`, `detection_result`, and `vision_error`; D435 RGB detection remains debug-only.

- [ ] **Step 1: Write failing dependency/bridge tests**

```python
def test_model_environment_pins_and_imports_realsense():
    requirements = Path("requirements/remind3d-cu128.txt").read_text()
    bootstrap = Path("scripts/vision/bootstrap_remind3d_env.sh").read_text()
    assert "pyrealsense2==2.57.7.10387" in requirements
    assert "import pyrealsense2" in bootstrap

def test_online_bridge_has_no_robot_or_can_dependency():
    source = Path("web-control/server/camera_bridge.py").read_text()
    assert "SingleArm" not in source
    assert "can0" not in source
    assert "VISION_OVERLAY_FD" in source
```

Also assert depth is converted by the device depth scale, latest-only buffers have capacity one, fd 4 carries overlay only, and stdin cannot submit a target/detection.

- [ ] **Step 2: Verify deployment tests fail**

Run: `pytest -q tests/vision_deployment`

- [ ] **Step 3: Pin RealSense in the isolated environment contract**

Update requirements/import gate only. Do not mutate `LumosTouch`; install after offline tests and only if the exact environment import fails.

- [ ] **Step 4: Integrate latest-only worker**

The D435 thread publishes copied depth-in-metres and live pinhole intrinsics into a single-slot condition buffer. A Lumos reader retries with capped 0.1–2.0 s backoff. One model thread initializes CUDA/models once, consumes only newer Lumos plus latest D435, emits status/results, and writes overlay MJPEG to fd 4. Exceptions mark vision unavailable and keep debug streaming; they never create actionable output.

Forward robot pose only as optional read-only input. The camera process never opens Startouch/CAN or sends commands.

- [ ] **Step 5: Add Node fd and environment forwarding**

Spawn with five stdio entries, parse only fd 3 as JSON, expose only fd 4 via `getVisionMjpegStream()`, and use the existing exact-child shutdown lifecycle.

- [ ] **Step 6: Test and commit**

```bash
pytest -q tests/vision_deployment
PYTHONPATH=web-control/server pytest -q web-control/server/tests/vision web-control/server/tests/vision_models
node --check web-control/server/camera-bridge.js
git add requirements/remind3d-cu128.txt scripts/vision/bootstrap_remind3d_env.sh tests/vision_deployment/test_bootstrap_contract.py tests/vision_deployment/test_online_camera_bridge_contract.py web-control/server/camera_bridge.py web-control/server/camera-bridge.js
git commit -m "feat(vision): connect online models to dual-camera bridge"
```

---

### Task 5: Read-Only Status API and Camera Page

**Files:**
- Create: `web-control/server/vision-status.js`
- Create: `web-control/server/test/vision-status-smoke.js`
- Modify: `web-control/server/config.js`
- Modify: `web-control/server/proxy.js`
- Modify: `web-control/server/package.json`
- Modify: `web-control/web/camera-test.html`
- Modify: `tests/web/test_web_ui_security.py`

**Interfaces:**
- `VisionStatusStore.updateStatus(event)`, `updateTargets(event)`, and `snapshot(nowMs)`.
- `GET /api/vision/status` returns JSON; `GET /camera_lumos_vision` returns read-only overlay MJPEG.
- WebSocket forwards status/results/errors; no new browser command exists.

- [ ] **Step 1: Write failing Node/security tests**

```javascript
const store = new VisionStatusStore({ staleAfterMs: 2000 });
store.updateStatus({ type: 'vision_status', ts: 1000, online: true,
  canonical_rgb_source: 'lumos_rgb', metric_depth_source: 'd435_depth' });
assert.equal(store.snapshot(3101).stale, true);
assert.equal(store.snapshot(3101).robotExecutionEnabled, false);
```

Python source tests require the overlay route, role labels, status/blocker panels, and absence of `grasp_object` or editable coordinates.

- [ ] **Step 2: Verify tests fail**

Run: `cd web-control/server && node test/vision-status-smoke.js`

Run: `pytest -q tests/web/test_web_ui_security.py`

- [ ] **Step 3: Implement bounded store and proxy routes**

Store child events only, cap targets at 256, strip non-finite positions, and force execution false from server config. Overlay returns 503 until fd 4 exists. Status always includes roles, model, source age, blockers, timing/GPU metrics, and execution lock.

- [ ] **Step 4: Implement read-only page**

Use Lumos overlay as primary and D435 debug/depth as secondary. Poll status once per second, show exact blockers, retry broken MJPEG with capped backoff, and expose no motion/grasp controls.

- [ ] **Step 5: Test and commit**

```bash
cd web-control/server && npm test
cd ../.. && pytest -q tests/web/test_web_ui_security.py
git add web-control/server/vision-status.js web-control/server/test/vision-status-smoke.js web-control/server/config.js web-control/server/proxy.js web-control/server/package.json web-control/web/camera-test.html tests/web/test_web_ui_security.py
git commit -m "feat(web): expose read-only online vision status"
```

---

### Task 6: Safe Launch and Live Verifier

**Files:**
- Create: `scripts/vision/start_dual_camera_online.sh`
- Create: `scripts/vision/verify_dual_camera_online.py`
- Create: `tests/vision_deployment/test_online_launch_contract.py`
- Modify: `.gitignore`

**Interfaces:**
- Launcher supports `--foreground`, `--background`, `--stop`, and `--status` for only the owned port-3100 process.
- Verifier supports `--base-url`, `--duration-seconds`, and `--output`, writes atomic JSON, and exits nonzero for online deployment failures.

- [ ] **Step 1: Write failing lifecycle tests**

```python
def test_launcher_cannot_target_real_can_or_enable_execution():
    source = Path("scripts/vision/start_dual_camera_online.sh").read_text()
    assert "STARTOUCH_SIMULATE=1" in source
    assert "STARTOUCH_CAN_INTERFACE=thirdhand-vision-test" in source
    assert "VISION_ONLINE_ENABLED=1" in source
    assert "WEB_PORT=3100" in source
```

Add verifier unit tests for healthy, stale, wrong roles, execution true, model failure, source sequence not advancing, and atomic output.

- [ ] **Step 2: Verify tests fail**

Run: `pytest -q tests/vision_deployment/test_online_launch_contract.py`

- [ ] **Step 3: Implement exact-target lifecycle**

Resolve repository/artifact paths first; validate stored PID cmdline and cwd before signaling; never kill by pattern. Preflight USB IDs `040e:f408` and `8086:0b07`, Lumos health, model imports, config lock, checkpoint, and port 3100. Background mode writes an owned PID and append-only log.

- [ ] **Step 4: Implement verifier**

Sample once per second. Require both cameras ready, exact roles, model ready, advancing sequences, non-stale state, execution false, and latency/memory budgets. Calibration/task-checkpoint blockers are expected non-actionability evidence, not verifier failures. Record blocker histogram and source/config hashes.

- [ ] **Step 5: Test and commit**

```bash
pytest -q tests/vision_deployment/test_online_launch_contract.py
bash -n scripts/vision/start_dual_camera_online.sh
python -m py_compile scripts/vision/verify_dual_camera_online.py
git add scripts/vision/start_dual_camera_online.sh scripts/vision/verify_dual_camera_online.py tests/vision_deployment/test_online_launch_contract.py .gitignore
git commit -m "feat(vision): add safe online deployment lifecycle"
```

---

### Task 7: Install, Deploy, Soak, and Record Evidence

**Files:**
- Modify: `docs/vision_research/REMIND3D_DEPLOYMENT_RESULTS.md`
- Runtime: `artifacts/vision/dual-camera-online/readiness-20260805.json` (gitignored)
- Runtime: `artifacts/vision/dual-camera-online/online.log` (gitignored)
- Runtime: `artifacts/vision/dual-camera-online/lumos-overlay.jpg` (gitignored)

**Interfaces:**
- Produces a running read-only service at `http://127.0.0.1:3100/camera-test.html`.
- Produces content-addressed readiness evidence without enabling robot execution.

- [ ] **Step 1: Run complete offline verification**

Run model/core/deployment tests with the isolated Python, existing web tests with their current environment, `npm test`, shell syntax, and `git diff --check`. No offline command opens USB/CAN/robot.

- [ ] **Step 2: Install only missing isolated dependency**

If `thirdhand-remind3d` cannot import pyrealsense2, install the pinned requirements path. Re-run Python 3.11, Torch 2.7.0+cu128, CUDA 12.8/sm_120, MMCV GPU NMS, RTMDet, DINO, OpenCV, and RealSense gates. Do not modify `LumosTouch`.

- [ ] **Step 3: Restart only camera-only Lumos service**

Validate the port-3001 listener PID/cmdline/cwd, SIGTERM only that exact camera-only process, launch the current `lumos_http_server.py`, and verify health, snapshot headers, and MJPEG. Leave the existing port-3000 task untouched.

- [ ] **Step 4: Start online service**

Run: `bash scripts/vision/start_dual_camera_online.sh --background`

Expected: D435 opens once, models load on RTX 5060, roles are Lumos/D435, execution false, and current real blockers keep targets non-actionable.

- [ ] **Step 5: Run 60-second readiness and 30-minute soak**

Run the verifier for 60 seconds to `readiness-smoke-20260805.json`, then for 1800 seconds to `readiness-20260805.json`. Confirm source advancement, no restart/queue growth, latency/memory budgets, blocker preservation, and zero robot/gripper/CAN writes.

- [ ] **Step 6: Inspect UI and visual evidence**

Open the camera page, confirm Lumos is primary and D435 secondary, save one overlay JPEG, and compare displayed state to `/api/vision/status`.

- [ ] **Step 7: Update evidence and final verification**

Document exact commits, versions, USB IDs/serial, URL, report hash, test counts, live budgets, blockers, and execution false. Do not claim task-trained bottle detection, valid calibration, or grasp readiness. Run `git diff --check`, `git status --short`, and `git log -8 --oneline`.

- [ ] **Step 8: Commit documentation**

```bash
git add docs/vision_research/REMIND3D_DEPLOYMENT_RESULTS.md
git commit -m "docs: record dual-camera online deployment"
```
