# Spatial Bottle Vision Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Build an offline-testable RGB-D vision module that identifies generic bottles, selects a requested left/right ordinal, locks that physical target, computes its camera-frame grasp pose, and produces a 3100-site-compatible visualization stream without controlling or opening the robot or camera during development.

**Architecture:** Grounded-SAM supplies generic bottle masks; a lightweight shape/score filter validates candidates, a spatial selector assigns L/R ordinals at the fixed observation pose, and a target lock preserves identity across later frames. Existing depth geometry and 4-of-5 stability produce a fail-closed `xvisio_color` grasp pose. A renderer and bridge serializer emit annotated MJPEG plus provenance-paired JSON events over the existing stdout/fd3/fd4 protocol.

**Tech Stack:** Python 3.10+, NumPy, PyYAML, OpenCV headless, pytest; existing XVisio native reader is retained but not invoked in this plan.

## Global Constraints

- Work only in `$HOME/th0814/VA/.worktrees/vision-core` on `feature/vision-core`.
- Do not open the XVisio/USB camera, start a live camera bridge, start the 3100 server, or run live inference while the hand-eye-calibration teammate owns the camera.
- Tests use synthetic RGB-D/XYZ, saved frame bundles, and in-memory/fake file descriptors only.
- Output coordinates remain in `xvisio_color`; no base-frame transform, motion command, CAN, gripper, or robot-control action is produced.
- Selection input is `selection_side` (`left` or `right`) plus a positive `requested_ordinal`.
- Sort left by increasing mask-centroid x and right by decreasing mask-centroid x; reject out-of-range and ambiguous horizontal ordering.
- Select once at the fixed observation pose, then lock the target; do not re-sort after camera motion.
- Final hardware state remains `hardware_validation_pending` until the user explicitly releases the camera for testing.
- Existing 3100 site owns the port and `#camera-feed`; VA supplies protocol-compatible output and never binds port 3100 itself.

---

## File Structure

- `src/thirdhand_va/perception/bottle_candidates.py`: generic bottle score, mask, and shape validation.
- `src/thirdhand_va/selection.py`: ordinal ranking, ambiguity rejection, and stateful target locking.
- `src/thirdhand_va/contracts.py`: spatial-rank and selection metadata on decisions.
- `src/thirdhand_va/pipeline.py`: filter -> select/lock -> depth geometry -> stability orchestration.
- `src/thirdhand_va/visualization.py`: deterministic annotated frame rendering.
- `src/thirdhand_va/bridge.py`: MJPEG part and fd3 detection-event serialization.
- `scripts/camera_bridge_va.py`: future live/replay bridge entry point; import is side-effect free.
- `src/thirdhand_va/cli.py`: direction/ordinal arguments and updated payload schema.
- `configs/vision.yaml`, `src/thirdhand_va/config.py`: generic-bottle and lock thresholds.
- `docs/3100-vision-integration.md`: exact handoff instructions and camera-resource warning.

### Task 1: Generic Bottle Candidate Filter

**Files:**
- Create: `src/thirdhand_va/perception/bottle_candidates.py`
- Create: `tests/perception/test_bottle_candidates.py`
- Modify: `src/thirdhand_va/config.py`
- Modify: `configs/vision.yaml`

**Interfaces:**
- Consumes: `RawCandidate`, `VisionConfig`, RGB image shape.
- Produces: `BottleCandidateFilter(config).filter(rgb, raw_candidates) -> tuple[MaskCandidate, ...]`.

- [x] **Step 1: Write failing tests for generic bottle acceptance and fail-closed masks**

```python
def test_accepts_any_generic_bottle_without_brand_descriptor(config, bottle_raw, rgb):
    result = BottleCandidateFilter(config).filter(rgb, (bottle_raw,))
    assert result[0].authorized is True
    assert result[0].label == "bottle"

def test_rejects_small_or_misaligned_mask(config, bottle_raw, rgb):
    bad = replace(bottle_raw, mask=np.ones((2, 2), dtype=bool))
    result = BottleCandidateFilter(config).filter(rgb, (bad,))
    assert result[0].authorized is False
    assert "mask_missing_or_misaligned" in result[0].reasons
```

- [x] **Step 2: Run `pytest tests/perception/test_bottle_candidates.py -v` and confirm failure because the module is absent.**

- [x] **Step 3: Add `min_bottle_score` to strict config and implement filter**

```python
class BottleCandidateFilter:
    def filter(self, rgb, raw_candidates):
        return tuple(self._convert(item, rgb.shape[:2]) for item in raw_candidates
                     if item.prompt_label == "bottle")
```

The converter must require score >= `min_bottle_score`, aligned mask, `min_mask_pixels`, and the existing bottle aspect/neck-body shape checks; it must not inspect descriptors, reference banks, Coke labels, or competitor margins.

- [x] **Step 4: Run the new tests plus `pytest tests/test_config.py tests/perception -v`; confirm all pass.**

- [x] **Step 5: Commit with `git commit -m "feat: filter generic bottle candidates"`.**

### Task 2: Spatial Ordinal Ranking and Selection

**Files:**
- Create: `src/thirdhand_va/selection.py`
- Create: `tests/test_selection.py`
- Modify: `src/thirdhand_va/contracts.py`
- Modify: `src/thirdhand_va/config.py`
- Modify: `configs/vision.yaml`

**Interfaces:**
- Consumes: authorized `MaskCandidate` tuple, `SelectionRequest(side: Literal["left", "right"], ordinal: int)`.
- Produces: `SpatialRank(detection_id, centroid_xy, left_ordinal, right_ordinal)`, `SelectionResult(selected, ranks, reasons)`, and `SpatialBottleSelector.select(...)`.

- [x] **Step 1: Write failing tests for three/four bottle ranks, direction, range, and ambiguity**

```python
def test_three_bottles_left_two_and_right_two_are_middle(candidates):
    selector = SpatialBottleSelector(min_horizontal_gap_px=8.0)
    left = selector.select(candidates, SelectionRequest("left", 2))
    right = selector.select(candidates, SelectionRequest("right", 2))
    assert left.selected.detection_id == right.selected.detection_id == 20

def test_four_bottles_left_two_and_right_two_differ(four_candidates):
    selector = SpatialBottleSelector(min_horizontal_gap_px=8.0)
    assert selector.select(four_candidates, SelectionRequest("left", 2)).selected.detection_id == 20
    assert selector.select(four_candidates, SelectionRequest("right", 2)).selected.detection_id == 30
```

Also assert ordinal 0 raises `ValueError`, ordinal 5 returns `ordinal_out_of_range`, and adjacent centroids closer than the configured gap return `horizontal_order_ambiguous` with no selected target.

- [x] **Step 2: Run `pytest tests/test_selection.py -v`; confirm failure on missing types.**

- [x] **Step 3: Implement immutable request/rank/result contracts and centroid sorting.**

```python
centroids = [(candidate, mask_centroid(candidate.mask)) for candidate in authorized]
ordered = sorted(centroids, key=lambda item: item[1][0])
ranks = tuple(SpatialRank(c.detection_id, xy, index + 1, len(ordered) - index)
              for index, (c, xy) in enumerate(ordered))
```

- [x] **Step 4: Run `pytest tests/test_selection.py tests/test_contracts.py -v`; confirm pass.**

- [x] **Step 5: Commit with `git commit -m "feat: select bottles by spatial ordinal"`.**

### Task 3: Target Lock Across Camera Motion

**Files:**
- Modify: `src/thirdhand_va/selection.py`
- Modify: `tests/test_selection.py`
- Modify: `src/thirdhand_va/config.py`
- Modify: `configs/vision.yaml`

**Interfaces:**
- Consumes: selected candidate and later candidate sets; optional `GraspPoseCamera` confirmation.
- Produces: `TargetLock.acquire(candidate)`, `match(candidates) -> SelectionResult`, `confirm_pose(pose) -> tuple[bool, tuple[str, ...]]`, and `reset()`.

- [x] **Step 1: Write failing tests proving no re-sort after motion**

```python
def test_lock_follows_selected_mask_when_screen_order_changes(selected, moved_candidates):
    lock = TargetLock(min_mask_iou=0.20, max_center_distance_px=80.0,
                      max_point_distance_m=0.05)
    lock.acquire(selected)
    result = lock.match(moved_candidates)
    assert result.selected.detection_id == 202

def test_lock_rejects_two_equally_plausible_matches(selected, ambiguous_matches):
    lock = configured_lock(selected)
    assert lock.match(ambiguous_matches).reasons == ("target_lock_ambiguous",)
```

Add tests for `target_track_lost` and for a confirmed pose jump beyond `max_track_point_distance_m`.

- [x] **Step 2: Run the target-lock test subset and confirm failure.**

- [x] **Step 3: Implement matching with mask IoU first, 2D centroid distance second, unique-best margin, and 3D confirmation.**

Only `acquire()` may establish identity from an ordinal. `match()` must never call ordinal sorting. If no unique eligible candidate exists, return no target and clear readiness through a blocker reason.

- [x] **Step 4: Run `pytest tests/test_selection.py -v`; confirm all selection and lock tests pass.**

- [x] **Step 5: Commit with `git commit -m "feat: lock ordinal target across frames"`.**

### Task 4: Pipeline and CLI Integration

**Files:**
- Modify: `src/thirdhand_va/pipeline.py`
- Modify: `src/thirdhand_va/cli.py`
- Modify: `src/thirdhand_va/perception/grounded_sam.py`
- Modify: `tests/test_pipeline.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Consumes: `VisionPipeline(config, backend, SelectionRequest)` and `process(frame)`.
- Produces: `VisionDecision` carrying request, ranks, selected target, camera pose, blockers, and 4/5 status; CLI `--selection-side {left,right}` and `--ordinal N`.

- [x] **Step 1: Replace fixed-Coke pipeline tests with multi-bottle synthetic RGB-D tests.**

```python
pipeline = VisionPipeline(config, FakeBackend(candidates), SelectionRequest("left", 2))
results = [pipeline.process(frame, now_ns=frame.monotonic_ns + 1_000_000)
           for frame in frames]
assert results[-1].status == "ready"
assert results[-1].target.detection_id == 2
assert results[-1].pose.frame == "xvisio_color"
```

Add rejection assertions for out-of-range ordinal, depth holes, lock loss, and pose spread; assert no payload key contains `base`, `robot_command`, or an enabled robot flag.

- [x] **Step 2: Run `pytest tests/test_pipeline.py tests/test_cli.py -v`; confirm old constructor/payload behavior fails.**

- [x] **Step 3: Wire the generic filter, selector/lock, geometry, and stability window.**

Use Grounded-SAM prompt `bottle`. Remove `ReferenceBank` from `VisionPipeline` and CLI perception/replay construction. Include `selection_side`, `requested_ordinal`, and all ranks in `decision_to_payload`; keep `robot_control_enabled: false`.

- [x] **Step 4: Run `pytest tests/test_pipeline.py tests/test_cli.py tests/tracking tests/geometry -v`; confirm pass.**

- [x] **Step 5: Commit with `git commit -m "feat: integrate ordinal selection pipeline"`.**

### Task 5: Algorithm Visualization

**Files:**
- Create: `src/thirdhand_va/visualization.py`
- Create: `tests/test_visualization.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes: RGB ndarray, `VisionDecision`, ranks, measured processing milliseconds/FPS.
- Produces: `render_overlay(rgb, decision, metrics) -> NDArray[np.uint8]` and `encode_jpeg(image, quality=85) -> bytes`.

- [x] **Step 1: Write failing pixel- and JPEG-level tests.**

```python
overlay = render_overlay(rgb, ready_decision, RenderMetrics(fps=12.5, latency_ms=41.0))
assert overlay.shape == rgb.shape
assert np.any(overlay[ready_decision.target.mask] != rgb[ready_decision.target.mask])
assert encode_jpeg(overlay).startswith(b"\xff\xd8")
```

Add a rejected-decision test showing stale ready state is absent and a status panel contains the blocker state via returned `OverlayMetadata` labels.

- [x] **Step 2: Run `pytest tests/test_visualization.py -v`; confirm module-not-found failure.**

- [x] **Step 3: Implement OpenCV overlay drawing.**

Draw translucent per-instance masks, contours, centroids, `L#/R#`, request, green selected outline, grasp point projection nearest to the selected mask centroid, bottle axis/approach arrows when pose exists, depth ratio, stable hits, FPS, latency, status/blockers, `robot_control_enabled=false`, and `hardware_validation_pending`.

- [x] **Step 4: Run visualization tests and save one synthetic JPEG under `artifacts/validation/spatial-overlay.jpg` for manual inspection.**

- [x] **Step 5: Commit with `git commit -m "feat: render spatial grasp visualization"`.**

### Task 6: 3100 CameraBridge Protocol Adapter

**Files:**
- Create: `src/thirdhand_va/bridge.py`
- Create: `scripts/camera_bridge_va.py`
- Create: `tests/test_bridge.py`
- Create: `docs/3100-vision-integration.md`

**Interfaces:**
- Consumes: JPEG bytes, `VisionDecision`, frame id, monotonic ns, observed-at ms.
- Produces: stdout primary multipart MJPEG; fd3 newline-delimited `detection_result`; fd4 overlay multipart MJPEG with provenance headers.

- [x] **Step 1: Write failing byte-exact protocol tests.**

```python
part = build_mjpeg_part(jpeg, provenance)
assert part.startswith(b"--frame\r\nContent-Type: image/jpeg\r\n")
assert b"X-ThirdHand-Frame-Id: 42\r\n" in part
assert hashlib.sha256(jpeg).hexdigest().encode() in part

event = build_detection_event(decision, provenance)
assert event["type"] == "detection_result"
assert event["frame_id"] == 42
assert event["robot_control_enabled"] is False
```

Use `io.BytesIO` to assert fd3/fd4 pairing, newest-frame replacement, and broken/slow sink handling without threads accumulating stale frames.

- [x] **Step 2: Run `pytest tests/test_bridge.py -v`; confirm failure.**

- [x] **Step 3: Implement serializer, latest-frame publisher, and side-effect-free entry point.**

`camera_bridge_va.py` must not open hardware on import. `--source replay --bundles ...` is the offline test mode; `--source live` is present for future integration but guarded by an explicit `--allow-camera` flag and is not executed during this task.

- [x] **Step 4: Document that the teammate only needs to allowlist `camera_bridge_va.py`/set `CAMERA_BRIDGE_SCRIPT`; VA does not edit the control site, bind 3100, or enable execution. Run `pytest tests/test_bridge.py -v`.**

- [x] **Step 5: Commit with `git commit -m "feat: add 3100 vision bridge adapter"`.**

### Task 7: Offline End-to-End Validation and Handoff

**Files:**
- Create: `scripts/validate_spatial_vision_offline.py`
- Create: `tests/test_offline_validation.py`
- Modify: `docs/validation-protocol.md`
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes: deterministic synthetic 1-4 bottle scenes and optional saved frame bundles.
- Produces: `artifacts/validation/spatial-vision-offline.json`, overlay JPEGs, protocol sample bytes, and exit code 0 only when every offline scenario passes.

- [x] **Step 1: Write a failing test for the validation report matrix.**

```python
report = run_validation(output_dir=tmp_path)
assert report["hardware_validation"] == "pending"
assert report["robot_control_enabled"] is False
assert all(case["passed"] for case in report["cases"])
assert {case["name"] for case in report["cases"]} >= {
    "one_left_1", "two_right_1", "three_left_2", "three_right_2",
    "four_left_2", "four_right_2", "ordinal_out_of_range",
    "horizontal_ambiguity", "depth_hole", "track_loss",
}
```

- [x] **Step 2: Run `pytest tests/test_offline_validation.py -v`; confirm failure.**

- [x] **Step 3: Implement deterministic scene generation and report writing without importing or constructing `XVisioStream`.**

- [x] **Step 4: Run `pytest -q`, then `python scripts/validate_spatial_vision_offline.py --output artifacts/validation`; inspect the generated overlay with an image viewer and confirm the report says `hardware_validation_pending`.**

- [x] **Step 5: Run `git diff --check`, verify no process is listening/started by the validation script, update the plan checkboxes, and commit with `git commit -m "test: validate spatial bottle vision offline"`.**

## Self-Review

- Spec coverage: generic recognition, left/right ordinal selection, ambiguity/range rejection, lock-after-selection, RGB-D grasp pose, 4-of-5 stability, rich overlay, stdout/fd3/fd4 protocol, no robot output, and deferred hardware validation are each assigned to Tasks 1-7.
- Placeholder scan: no TBD/TODO/placeholder or unspecified error-handling steps remain.
- Type consistency: `SelectionRequest`, `SpatialRank`, `SelectionResult`, `TargetLock`, `VisionDecision`, renderer, and bridge signatures are defined before downstream use.
- Scope boundary: the existing 3100 website and hand-eye calibration files are read-only references; this plan changes only VA files and never launches camera hardware.
