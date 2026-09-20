# Fixed Coke Bottle RGB-D Vision Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an independent XVisio vision service that identifies the fixed experimental Coca-Cola plastic bottle and returns a stable grasp pose in the camera frame from aligned RGB-D evidence.

**Architecture:** A native XVisio process owns the camera and emits full RGB, registered depth, and a registered XYZ map over a versioned local socket protocol. Python modules perform fixed-bottle verification, robust mask/point-cloud geometry, and five-frame fail-closed stabilization. Live and replay CLIs share one immutable pipeline; voice, hand-eye calibration, base-frame conversion, and robot control remain outside this project.

**Tech Stack:** C++17, XVisio SDK 3.2, OpenCV, Python 3.11, NumPy, SciPy, Pillow, PyYAML, Transformers Grounding DINO, SAM2, pytest.

## Global Constraints

- All created or modified project files live under `$HOME/th0814/VA`.
- Other ThirdHand directories are read-only references; copy only the minimum reusable source into `VA`.
- Target is one fixed experimental Coca-Cola plastic bottle, upright on a table.
- Pepsi bottles, water bottles, ordinary bottles, and cans are negative objects.
- Camera serial must equal `250801DR48FP25002738`.
- Formal input is full RGB plus registered depth from the continuous XVisio stream.
- Current output frame is `xvisio_color`; do not produce robot-base coordinates.
- No voice, hand-eye solver, robot SDK, CAN owner, or motion command is implemented here.
- Five observations form a decision window; at least four consistent observations are required.
- Any missing identity, geometry, freshness, or uniqueness evidence returns a non-ready result.
- Model weights and large capture artifacts are never committed to Git.

---

## Planned File Map

```text
VA/
├── pyproject.toml
├── .gitignore
├── configs/vision.yaml
├── native/xvisio_rgbd_stream/{CMakeLists.txt,xvisio_rgbd_stream.cpp}
├── src/thirdhand_va/
│   ├── contracts.py
│   ├── config.py
│   ├── camera/{protocol.py,stream.py,recording.py}
│   ├── perception/{interfaces.py,grounded_sam.py,fixed_bottle.py,references.py}
│   ├── geometry/{pointcloud.py,grasp_pose.py}
│   ├── tracking/stability.py
│   ├── pipeline.py
│   └── cli.py
├── scripts/{build_native.sh,capture_reference.py,run_live.py,run_replay.py}
├── tests/{camera,perception,geometry,tracking,test_pipeline.py,test_cli.py}
└── artifacts/.gitkeep
```

### Task 1: Package, configuration, and immutable contracts

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `configs/vision.yaml`
- Create: `src/thirdhand_va/contracts.py`
- Create: `src/thirdhand_va/config.py`
- Test: `tests/test_contracts.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `RgbdFrame`, `MaskCandidate`, `GraspPoseCamera`, `VisionDecision`, `VisionConfig`.
- `RgbdFrame.xyz_camera_m` has shape `(H,W,3)` and shares pixels with RGB and depth.

- [ ] **Step 1: Write contract tests**

```python
def test_rgbd_frame_rejects_misaligned_arrays():
    with pytest.raises(ValueError, match="same height and width"):
        RgbdFrame(1, 10, "250801DR48FP25002738",
                  np.zeros((4, 5, 3), np.uint8),
                  np.zeros((3, 5), np.float32),
                  np.zeros((4, 5, 3), np.float32))

def test_ready_decision_requires_pose_and_unique_target():
    with pytest.raises(ValueError, match="ready decision"):
        VisionDecision(status="ready", frame_id=1, target=None, pose=None,
                       reasons=())
```

- [ ] **Step 2: Run tests and confirm they fail because the package is absent**

Run: `python -m pytest tests/test_contracts.py tests/test_config.py -v`
Expected: collection fails with `ModuleNotFoundError: thirdhand_va`.

- [ ] **Step 3: Implement frozen dataclasses and exact configuration validation**

`VisionConfig` must include the serial, working range, minimum mask pixels, minimum depth points, minimum depth ratio, 5-frame window, 4 required hits, maximum pose spread, model IDs, and configurable `HF_HOME`. Reject unknown YAML keys.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_contracts.py tests/test_config.py -v`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml .gitignore configs src/thirdhand_va tests/test_contracts.py tests/test_config.py
git commit -m "feat: define VA vision contracts and config"
```

### Task 2: Versioned XVisio RGB-D/XYZ transport

**Files:**
- Create: `native/xvisio_rgbd_stream/CMakeLists.txt`
- Create: `native/xvisio_rgbd_stream/xvisio_rgbd_stream.cpp`
- Create: `src/thirdhand_va/camera/protocol.py`
- Create: `src/thirdhand_va/camera/stream.py`
- Create: `scripts/build_native.sh`
- Test: `tests/camera/test_protocol.py`
- Test: `tests/camera/test_stream.py`

**Interfaces:**
- Consumes: `RgbdFrame`.
- Produces: `decode_packet_header(bytes) -> PacketHeader`; `XVisioStream.read_after(sequence, timeout_s) -> RgbdFrame | None`.
- Protocol v2 payload order: RGB `uint8`, depth `float32`, XYZ `float32`; all arrays use the same `width × height` grid.

- [ ] **Step 1: Write synthetic protocol tests**

```python
def test_protocol_v2_decodes_rgb_depth_and_xyz():
    packet = make_packet(width=2, height=1, sequence=7, stamp_ns=99,
                         serial="250801DR48FP25002738")
    frame = read_one_packet(io.BytesIO(packet))
    assert frame.rgb.shape == (1, 2, 3)
    assert frame.depth_m.shape == (1, 2)
    assert frame.xyz_camera_m.shape == (1, 2, 3)
    assert frame.sequence == 7

def test_protocol_rejects_wrong_serial():
    with pytest.raises(CameraProtocolError, match="serial"):
        read_one_packet(io.BytesIO(make_packet(serial="old-camera")))
```

- [ ] **Step 2: Run the protocol tests and confirm failure**

Run: `python -m pytest tests/camera/test_protocol.py tests/camera/test_stream.py -v`
Expected: import failure for `thirdhand_va.camera.protocol`.

- [ ] **Step 3: Implement Python protocol v2 and bounded stream ownership**

Keep the existing socket-pair/process ownership pattern. Validate magic, version, dimensions, byte counts, sequence, timestamp, serial, finite XYZ, and depth/XYZ agreement. Normalize invalid depth and XYZ pixels to `NaN`; retain only the latest immutable frame.

- [ ] **Step 4: Copy and adapt the proven native stream**

Copy from the read-only reference `ThirdHand-XVisio/web-control/server/xvisio_native/xvisio_rgbd_stream.cpp`. Preserve full-color decode, ToF raytrace, ToF→IMU→color transform, crop mapping, z-buffering, and the 66 ms publication floor. While registering each depth sample, store the winning `point_color[x,y,z]` in the XYZ map alongside `depth_m`; publish receipt monotonic time and the verified serial. Do not copy `camera_bridge_xvisio.py` or legacy D435 naming.

- [ ] **Step 5: Build native code**

Run: `bash scripts/build_native.sh`
Expected: `build/xvisio_rgbd_stream/xvisio_rgbd_stream` exists and links against `libxvsdk` and OpenCV.

- [ ] **Step 6: Run tests and a five-frame hardware smoke test**

Run: `python -m pytest tests/camera -v`
Run: `python -m thirdhand_va.cli camera-smoke --frames 5`
Expected: tests pass; smoke output reports five increasing sequence/timestamp values, correct serial, aligned `(480,640)` depth/XYZ, and no robot activity.

- [ ] **Step 7: Commit**

```bash
git add native src/thirdhand_va/camera scripts/build_native.sh tests/camera
git commit -m "feat: stream aligned XVisio RGB-D and XYZ"
```

### Task 3: Deterministic recording and replay

**Files:**
- Create: `src/thirdhand_va/camera/recording.py`
- Create: `scripts/run_replay.py`
- Test: `tests/camera/test_recording.py`

**Interfaces:**
- Produces: `write_frame_bundle(directory, frame) -> content_id`; `read_frame_bundle(directory) -> RgbdFrame`.
- Metadata uses JSON; arrays use compressed NPZ; the SHA-256 covers canonical metadata and array bytes.

- [ ] **Step 1: Write round-trip and tamper tests**

```python
def test_recording_round_trip_preserves_arrays(tmp_path, rgbd_frame):
    content_id = write_frame_bundle(tmp_path, rgbd_frame)
    loaded = read_frame_bundle(tmp_path)
    assert content_id.startswith("sha256:")
    np.testing.assert_array_equal(loaded.rgb, rgbd_frame.rgb)

def test_recording_rejects_tampered_metadata(tmp_path, rgbd_frame):
    write_frame_bundle(tmp_path, rgbd_frame)
    (tmp_path / "metadata.json").write_text("{}")
    with pytest.raises(RecordingError, match="content"):
        read_frame_bundle(tmp_path)
```

- [ ] **Step 2: Run failing tests, implement atomic writer/reader, rerun**

Run: `python -m pytest tests/camera/test_recording.py -v`
Expected before implementation: import failure. Expected after implementation: all pass.

- [ ] **Step 3: Commit**

```bash
git add src/thirdhand_va/camera/recording.py scripts/run_replay.py tests/camera/test_recording.py
git commit -m "feat: add reproducible RGB-D recording and replay"
```

### Task 4: Fixed experimental bottle verification

**Files:**
- Create: `src/thirdhand_va/perception/interfaces.py`
- Create: `src/thirdhand_va/perception/grounded_sam.py`
- Create: `src/thirdhand_va/perception/references.py`
- Create: `src/thirdhand_va/perception/fixed_bottle.py`
- Create: `scripts/capture_reference.py`
- Test: `tests/perception/test_fixed_bottle.py`
- Test: `tests/perception/test_references.py`

**Interfaces:**
- Produces: `PerceptionBackend.infer(rgb) -> tuple[RawCandidate,...]` and `FixedBottleVerifier.verify(rgb, raw_candidates) -> tuple[MaskCandidate,...]`.
- A candidate is authorized only when Coke evidence, SAM mask, fixed-reference similarity, bottle shape, and competitor margin all pass.

- [ ] **Step 1: Write fail-closed gate tests with a fake backend**

```python
def test_coke_can_is_rejected_even_with_brand_score(verifier, coke_can):
    result = verifier.verify(coke_can.rgb, (coke_can.candidate,))
    assert result[0].authorized is False
    assert "container_type_not_bottle" in result[0].reasons

def test_pepsi_reference_conflict_is_rejected(verifier, pepsi_bottle):
    result = verifier.verify(pepsi_bottle.rgb, (pepsi_bottle.candidate,))
    assert "fixed_reference_mismatch" in result[0].reasons

def test_fixed_bottle_requires_valid_mask_and_reference(verifier, fixed_bottle):
    result = verifier.verify(fixed_bottle.rgb, (fixed_bottle.candidate,))
    assert result[0].authorized is True
```

- [ ] **Step 2: Run tests and confirm failure**

Run: `python -m pytest tests/perception -v`
Expected: missing perception modules.

- [ ] **Step 3: Implement the pure fixed-bottle gate and content-addressed reference bank**

Use mask area, mask height/width, upper-neck width divided by body width, competitor overlap, and cosine similarity to positive reference descriptors. Every threshold comes from `VisionConfig`; an empty or mismatched reference bank blocks authorization.

- [ ] **Step 4: Implement the Grounding DINO/SAM2 backend adapter**

Adapt the proven logic from `ThirdHand-XVisio/groundedsam2_brand_verifier`. Use positive prompt `coca-cola plastic bottle` and explicit competitors `pepsi bottle`, `water bottle`, `ordinary bottle`, `coca-cola can`. Keep model loading lazy and one-time. Store masks as arrays internally; only artifact writers create files.

- [ ] **Step 5: Capture a fixed-bottle reference set**

Run: `python scripts/capture_reference.py --output artifacts/reference/fixed_coke --count 20`
Expected: 20 content-addressed, full-RGB crops covering front, side, and small rotations. The command refuses frames without one operator-confirmed candidate and never moves the arm.

- [ ] **Step 6: Run perception tests and one live inference preview**

Run: `python -m pytest tests/perception -v`
Run: `python -m thirdhand_va.cli perceive --frames 5 --artifacts artifacts/perception-smoke`
Expected: unit tests pass; output includes masks, scores, gate reasons, and `robot_control_enabled=false`.

- [ ] **Step 7: Commit code and reference manifest only**

```bash
git add src/thirdhand_va/perception scripts/capture_reference.py tests/perception artifacts/reference/fixed_coke/manifest.json
git commit -m "feat: verify the fixed Coke bottle instance"
```

### Task 5: Robust camera-frame grasp geometry

**Files:**
- Create: `src/thirdhand_va/geometry/pointcloud.py`
- Create: `src/thirdhand_va/geometry/grasp_pose.py`
- Test: `tests/geometry/test_pointcloud.py`
- Test: `tests/geometry/test_grasp_pose.py`

**Interfaces:**
- Consumes: authorized `MaskCandidate` plus `RgbdFrame.xyz_camera_m`.
- Produces: `estimate_grasp_pose(frame, candidate, config) -> GraspPoseCamera`.

- [ ] **Step 1: Write synthetic cylinder tests**

```python
def test_pose_uses_mask_xyz_not_bbox_center(cylinder_scene):
    pose = estimate_grasp_pose(*cylinder_scene.inputs)
    np.testing.assert_allclose(pose.point_m, cylinder_scene.expected_center, atol=0.005)

def test_pose_survives_holes_and_outliers(cylinder_with_outliers):
    pose = estimate_grasp_pose(*cylinder_with_outliers.inputs)
    assert pose.valid_points >= 80
    assert pose.position_std_m.max() < 0.01

def test_insufficient_depth_is_rejected(sparse_scene):
    with pytest.raises(GeometryRejected, match="depth_insufficient"):
        estimate_grasp_pose(*sparse_scene.inputs)
```

- [ ] **Step 2: Run tests and confirm failure**

Run: `python -m pytest tests/geometry -v`
Expected: missing geometry modules.

- [ ] **Step 3: Implement mask erosion, robust filtering, PCA axis, and safe grasp band**

Erode the mask before sampling XYZ. Reject non-finite points, enforce configured range, remove median/MAD outliers, fit the dominant bottle axis with PCA, and select the center of the middle safe band. Return axis, camera-facing side approach vector, estimated width, covariance, valid-point count, depth ratio, and rejection reasons. Never fall back to bbox center.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/geometry -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/thirdhand_va/geometry tests/geometry
git commit -m "feat: estimate camera-frame bottle grasp pose"
```

### Task 6: Five-frame identity and pose stability

**Files:**
- Create: `src/thirdhand_va/tracking/stability.py`
- Test: `tests/tracking/test_stability.py`

**Interfaces:**
- Produces: `StabilityWindow.update(frame, candidates_with_pose, now_ns) -> VisionDecision`.
- Requires exactly one authorized track, 4/5 hits, monotonic frames, fresh timestamps, sufficient IoU, and bounded 3-D spread.

- [ ] **Step 1: Write temporal safety tests**

```python
def test_four_of_five_consistent_observations_become_ready(window, stable_sequence):
    decisions = [window.update(*item) for item in stable_sequence]
    assert decisions[-1].status == "ready"

def test_two_authorized_bottles_are_ambiguous(window, two_target_sequence):
    decision = run_sequence(window, two_target_sequence)
    assert decision.status == "uncertain"
    assert "multiple_authorized_targets" in decision.reasons

def test_stale_or_jumping_pose_never_becomes_ready(window, jumping_sequence):
    assert run_sequence(window, jumping_sequence).status != "ready"
```

- [ ] **Step 2: Run failing tests, implement bounded tracking, rerun**

Run: `python -m pytest tests/tracking/test_stability.py -v`
Expected before implementation: import failure. Expected after implementation: all pass.

- [ ] **Step 3: Commit**

```bash
git add src/thirdhand_va/tracking tests/tracking
git commit -m "feat: require stable fixed-bottle grasp evidence"
```

### Task 7: Integrated live/replay pipeline and CLI

**Files:**
- Create: `src/thirdhand_va/pipeline.py`
- Create: `src/thirdhand_va/cli.py`
- Create: `scripts/run_live.py`
- Test: `tests/test_pipeline.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Produces: `VisionPipeline.process(frame) -> VisionDecision`.
- CLI subcommands: `camera-smoke`, `record`, `perceive`, `live`, `replay`.
- JSON output always declares `frame="xvisio_color"` and `robot_control_enabled=false`.

- [ ] **Step 1: Write end-to-end tests with fake camera and fake backend**

```python
def test_pipeline_returns_ready_only_after_stable_pose(pipeline, five_frames):
    results = [pipeline.process(frame) for frame in five_frames]
    assert [item.status for item in results[:3]] == ["uncertain"] * 3
    assert results[3].status == "ready"
    assert results[3].pose.frame == "xvisio_color"

def test_cli_json_contains_no_robot_or_base_pose(cli_runner, replay_dir):
    result = cli_runner("replay", str(replay_dir))
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["robot_control_enabled"] is False
    assert payload["pose"]["frame"] == "xvisio_color"
```

- [ ] **Step 2: Run tests and confirm failure**

Run: `python -m pytest tests/test_pipeline.py tests/test_cli.py -v`
Expected: missing pipeline and CLI modules.

- [ ] **Step 3: Implement orchestration and atomic artifact output**

The pipeline calls perception, geometry, and stability in that order. A rejected stage contributes a named blocker and prevents later authorization. CLI catches known failures, prints one schema-stable JSON object, writes diagnostic artifacts under the requested directory, and returns `0` only for successful command execution, not merely for a `ready` target.

- [ ] **Step 4: Run the complete offline suite**

Run: `python -m pytest -v`
Expected: all tests pass without requiring camera hardware or model downloads.

- [ ] **Step 5: Commit**

```bash
git add src/thirdhand_va/pipeline.py src/thirdhand_va/cli.py scripts/run_live.py tests/test_pipeline.py tests/test_cli.py
git commit -m "feat: assemble the standalone VA vision pipeline"
```

### Task 8: Hardware and fixed-object acceptance evidence

**Files:**
- Create: `scripts/validate_camera_alignment.py`
- Create: `scripts/evaluate_fixed_bottle.py`
- Create: `docs/validation-protocol.md`
- Create: `artifacts/validation/.gitkeep`
- Test: `tests/test_evaluation.py`

**Interfaces:**
- Produces machine-readable camera, recognition, and 3-D repeatability reports under `artifacts/validation/`.

- [ ] **Step 1: Test metric aggregation with deterministic fixtures**

Verify recall, false authorization count, depth coverage, pose repeatability, latency percentiles, and blocker counts. A report cannot pass with zero positive or zero negative samples.

- [ ] **Step 2: Run tests, implement evaluators, rerun**

Run: `python -m pytest tests/test_evaluation.py -v`
Expected before implementation: missing evaluator. Expected after implementation: all pass.

- [ ] **Step 3: Validate RGB/depth/XYZ alignment and 30-minute camera stability**

Run: `python scripts/validate_camera_alignment.py --duration-s 1800 --output artifacts/validation/camera.json`
Expected: correct serial, no process exit, monotonic frames, common RGB/depth/XYZ shape, and a report that records valid-depth ratio and frame intervals without claiming geometric alignment unless the target check passes.

- [ ] **Step 4: Collect positive and negative evaluation sequences**

Record the fixed bottle at multiple central-workspace positions and rotations, then record Pepsi bottle, water bottle, ordinary bottle, and Coke can negatives under the same lighting range. Store raw sequences outside Git and commit only the manifest with content hashes.

- [ ] **Step 5: Run fixed-bottle and camera-frame pose evaluation**

Run: `python scripts/evaluate_fixed_bottle.py --manifest artifacts/validation/manifest.json --output artifacts/validation/report.json`
Expected gates: positive recall at least 95%, zero authorization on the declared negative set, all unsafe cases rejected, and static camera-frame grasp-point repeatability at 5 mm scale. If a gate fails, keep the report and return nonzero; do not lower thresholds automatically.

- [ ] **Step 6: Run complete verification and commit**

Run: `python -m pytest -v`
Run: `git diff --check`
Expected: all tests pass and no whitespace errors.

```bash
git add scripts/validate_camera_alignment.py scripts/evaluate_fixed_bottle.py docs/validation-protocol.md tests/test_evaluation.py artifacts/validation/.gitkeep artifacts/validation/manifest.json
git commit -m "test: add VA hardware and fixed-bottle acceptance"
```

## Execution Order and Checkpoints

1. Tasks 1–3 create a camera-only, recordable RGB-D/XYZ foundation.
2. Task 4 pauses at the physical reference-capture step if the fixed experimental bottle is unavailable; earlier tasks continue independently.
3. Tasks 5–7 use synthetic and recorded fixtures and must not require hand-eye or robot access.
4. Task 8 is the only hardware acceptance checkpoint and never moves the arm.
5. After Task 8 passes, current VA work is complete. Future voice, hand-eye, base-frame conversion, and robot integration require a separate approved specification.
