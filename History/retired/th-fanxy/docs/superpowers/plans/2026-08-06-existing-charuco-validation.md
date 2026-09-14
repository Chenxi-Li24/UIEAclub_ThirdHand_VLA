# Existing ChArUco Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Validate the isolated legacy Lumos/D435 extrinsic seed with the laboratory's existing ChArUco board and content-addressed, non-executable evidence.

**Architecture:** Put board-specific parsing and feature extraction behind one keyed-correspondence interface. Keep the relative-extrinsic scorer and read-only HTTP capture CLI independent of target type and robot APIs.

**Tech Stack:** Python 3.11, OpenCV 4.11 contrib, NumPy, PyYAML, pytest, Ruff.

## Global Constraints

- Physical target: 12 OpenCV columns by 9 rows, `0.015 m` squares, `0.01125 m` markers, `DICT_5X5_100`.
- Require at least 24 common keyed points, D435 RMSE at most `1.5 px`, Lumos aggregate P95 at most `4.0 px`, and 10 observations.
- Validation must remain read-only and always emit `executable: false`.
- No camera-driver or robot-motion imports in the dual-camera validation CLI.

---

### Task 1: Generic target adapters

**Files:**
- Create: `web-control/server/vision_models/calibration_targets.py`
- Create: `configs/vision/calibration/charuco_12x9.yaml`
- Test: `tests/vision_deployment/test_calibration_targets.py`

**Interfaces:**
- Produces: `TargetCorners`, `AprilGridSpec`, `CharucoSpec`, `load_calibration_target(path)`, and `detect_target_corners(image, target)`.

- [ ] **Step 1: Write the failing test**

```python
def test_existing_charuco_definition_recovers_all_88_keyed_corners():
    target = load_calibration_target(CONFIG)
    image = target.board().generateImage((1200, 900), marginSize=40)
    detected = detect_target_corners(image, target)
    assert detected.point_ids == tuple(range(88))
    assert detected.object_points.shape == (88, 3)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest -q tests/vision_deployment/test_calibration_targets.py`
Expected: FAIL because the generic target module does not exist.

- [ ] **Step 3: Write minimal implementation**

Implement strict YAML parsing, the typed keyed-correspondence result, AprilTag
corner extraction, and ChArUco corner extraction with subpixel refinement. Map
ChArUco IDs directly to `board.getChessboardCorners()`.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest -q tests/vision_deployment/test_calibration_targets.py`
Expected: PASS.

### Task 2: Target-neutral legacy candidate scoring

**Files:**
- Modify: `web-control/server/vision_models/legacy_dual_camera_validation.py`
- Test: `tests/vision_deployment/test_legacy_dual_camera_validation.py`

**Interfaces:**
- Consumes: `TargetCorners` from Task 1.
- Produces: `evaluate_legacy_candidate_pair(...) -> LegacyCandidatePairResult` and `summarize_legacy_candidate(...) -> dict`.

- [ ] **Step 1: Write the failing test**

```python
def test_candidate_pair_matches_generic_feature_ids():
    result = evaluate_legacy_candidate_pair(
        d435=d435,
        lumos=lumos,
        t_lumos_from_d435=candidate,
        d435_detection=d435_detection,
        lumos_detection=lumos_detection,
    )
    assert result.common_points == 32
    assert result.passes_pixel_gate is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest -q tests/vision_deployment/test_legacy_dual_camera_validation.py`
Expected: FAIL because the scorer still requires AprilGrid-specific fields.

- [ ] **Step 3: Write minimal implementation**

Match integer feature IDs, retain the D435 PnP/native-SEUCM projection flow,
rename tag-specific metrics to `common_points`, and apply the 24-point gate.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest -q tests/vision_deployment/test_legacy_dual_camera_validation.py`
Expected: PASS.

### Task 3: Read-only capture CLI and immutable evidence

**Files:**
- Create: `scripts/vision/validate_legacy_dual_camera.py`
- Create: `configs/vision/calibration/legacy_dual_camera_candidate.json`
- Modify: `scripts/vision/capture_handeye_sample.py`
- Modify: `web-control/server/vision_models/calibration_capture.py`
- Test: `tests/vision_deployment/test_legacy_dual_camera_validation_cli.py`
- Test: `tests/vision_deployment/test_handeye_capture_contract.py`

**Interfaces:**
- Consumes: generic target loader/detector and target-neutral scorer.
- Produces: `append_observation(...)`, `load_candidate(...)`, `capture_one(...)`, and `legacy-dual-camera-validation.json`.

- [ ] **Step 1: Write the failing test**

```python
for index in range(10):
    append_observation(output, sample_id=f"pose-{index:02d}", result=good_result, ...)
assert manifest["summary"]["relative_extrinsic_validated"] is True
assert manifest["summary"]["executable"] is False
assert manifest["motion_or_robot_access"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest -q tests/vision_deployment/test_legacy_dual_camera_validation_cli.py`
Expected: FAIL because the CLI is absent or still AprilGrid-specific.

- [ ] **Step 3: Write minimal implementation**

Fetch both loopback JPEGs concurrently, verify dimensions, detect the configured
target, append hashed images and metrics atomically, validate existing manifest
integrity, and refuse executable candidate input.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest -q tests/vision_deployment/test_legacy_dual_camera_validation_cli.py tests/vision_deployment/test_handeye_capture_contract.py`
Expected: PASS.

### Task 4: Verification and handoff

**Files:**
- Modify: `docs/vision_research/17_ACTIVE_VIEW_REAL_VALIDATION_READINESS.md`

**Interfaces:**
- Consumes: all prior task outputs.
- Produces: tested commands and operator capture instructions.

- [ ] **Step 1: Run focused tests**

Run: `.venv/bin/python -m pytest -q tests/vision_deployment/test_calibration_targets.py tests/vision_deployment/test_legacy_dual_camera_validation.py tests/vision_deployment/test_legacy_dual_camera_validation_cli.py tests/vision_deployment/test_handeye_capture_contract.py`
Expected: all tests PASS.

- [ ] **Step 2: Run static and diff checks**

Run: `.venv/bin/ruff check scripts/vision/validate_legacy_dual_camera.py scripts/vision/capture_handeye_sample.py web-control/server/vision_models/calibration_targets.py web-control/server/vision_models/calibration_capture.py web-control/server/vision_models/legacy_dual_camera_validation.py tests/vision_deployment/test_calibration_targets.py tests/vision_deployment/test_legacy_dual_camera_validation.py tests/vision_deployment/test_legacy_dual_camera_validation_cli.py`
Expected: `All checks passed!`

Run: `git diff --check`
Expected: no output and exit code 0.

- [ ] **Step 3: Verify live camera preconditions without capture claims**

Run: `curl -fsS http://127.0.0.1:3100/api/vision/status`
Expected: service and both cameras report healthy. Do not claim physical
extrinsic validation until 10 operator-positioned target observations exist.

- [ ] **Step 4: Commit**

```bash
git add configs/vision/calibration scripts/vision web-control/server/vision_models \
  tests/vision_deployment docs/vision_research/17_ACTIVE_VIEW_REAL_VALIDATION_READINESS.md
git commit -m "feat(vision): validate legacy extrinsics with existing ChArUco"
```

