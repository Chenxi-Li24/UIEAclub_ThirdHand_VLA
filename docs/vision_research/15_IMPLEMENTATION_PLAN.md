# ThirdHand Vision Safety Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Subagents are not permitted for this execution.

**Goal:** Build an offline-first, deterministic vision safety core that projects D435 depth into Lumos imagery, maintains timestamped 3D object state, and produces auditable Dry Run decisions without connecting to or commanding the arm.

**Architecture:** Add a pure-Python `vision` package beside the existing bridge code. Camera geometry, depth registration, tracking, object memory, safety checks, and replay are independent modules connected by immutable dataclasses; no module imports the arm SDK, opens a camera, or performs network I/O. Existing live services remain unchanged until the offline acceptance gates in `13_BENCHMARK_AND_ACCEPTANCE_PLAN.md` pass.

**Tech Stack:** Python 3.8+, NumPy, SciPy `linear_sum_assignment`, pytest, JSON/NPZ replay fixtures; OpenCV is allowed only in calibration adapters, not in the core Euler/SE(3) math.

## Global Constraints

- Never automatically connect, move, home, grip, release, or otherwise command the arm.
- Never create a second CAN connection, restart the running service, or change system configuration.
- Lumos fisheye RGB is the primary image coordinate system; D435 RGB is debug/calibration/fallback only.
- D435 depth points are transformed into Lumos coordinates and z-buffered there; a Lumos-space target mask selects the object cloud.
- Every robot-space result carries source timestamps, calibration identifiers, uncertainty, and a validity decision.
- `DryRunReport.approved` means “eligible for manual review,” never “execute automatically.”
- Calibration artifacts are append-only and content-addressed; existing calibration files are not overwritten.
- All implementation begins in an isolated Git worktree based on audited commit `1fe9da3d2256`.
- Tests must run without cameras, CAN, WebSocket services, root privileges, or internet access.

---

## File map

- `web-control/server/vision/__init__.py`: stable public imports only.
- `web-control/server/vision/types.py`: immutable frames, calibration metadata, tracks, targets, and Dry Run reports.
- `web-control/server/vision/geometry.py`: RPY/SE(3) construction, inversion, validation, and point transforms.
- `web-control/server/vision/camera_models.py`: pinhole and SEUCM projection/unprojection.
- `web-control/server/vision/depth_registration.py`: D435-Z deprojection, extrinsic transform, Lumos projection, and z-buffer registration.
- `web-control/server/vision/tracking.py`: timestamp-aware gated assignment and track lifecycle.
- `web-control/server/vision/object_memory.py`: base-frame object state with freshness and stability rules.
- `web-control/server/vision/safety.py`: calibration, timing, workspace, uncertainty, and reachability gates.
- `web-control/server/vision/dry_run.py`: deterministic grasp-candidate scoring and human-readable decision report.
- `web-control/server/vision/replay.py`: offline JSON/NPZ replay and metrics export.
- `web-control/server/tests/vision/`: unit and integration tests; no hardware fixtures.

### Task 1: Typed data contracts and provenance

**Files:**
- Create: `web-control/server/vision/__init__.py`
- Create: `web-control/server/vision/types.py`
- Test: `web-control/server/tests/vision/test_types.py`

**Interfaces:**
- Consumes: standard library `dataclasses`, `enum`, and NumPy arrays supplied by callers.
- Produces: `FrameStamp`, `CalibrationRef`, `PoseEstimate`, `TrackObservation`, `TrackState`, `SafetyDecision`, and `DryRunReport` frozen dataclasses; `InvalidDataError` for rejected construction.

- [ ] **Step 1: Write the failing contract tests**

```python
def test_frame_stamp_rejects_negative_time():
    with pytest.raises(InvalidDataError):
        FrameStamp(source="lumos", frame_id=3, monotonic_ns=-1)

def test_pose_estimate_requires_finite_xyz_and_covariance():
    pose = PoseEstimate(
        xyz_m=np.array([0.1, 0.2, 0.3]),
        covariance_m2=np.eye(3) * 1e-4,
        frame="robot_base",
        stamp=FrameStamp("lumos+d435", 7, 100),
        calibration_id="sha256:abc",
    )
    assert pose.xyz_m.shape == (3,)
    assert not pose.xyz_m.flags.writeable
```

- [ ] **Step 2: Run the tests and verify they fail because `vision.types` does not exist**

Run: `cd web-control/server && python3 -m pytest tests/vision/test_types.py -v`

Expected: collection error containing `ModuleNotFoundError: No module named 'vision'`.

- [ ] **Step 3: Implement frozen dataclasses with shape, finiteness, monotonic-time, and covariance checks**

```python
@dataclass(frozen=True)
class FrameStamp:
    source: str
    frame_id: int
    monotonic_ns: int

    def __post_init__(self) -> None:
        if not self.source or self.frame_id < 0 or self.monotonic_ns < 0:
            raise InvalidDataError("invalid frame provenance")

@dataclass(frozen=True)
class PoseEstimate:
    xyz_m: np.ndarray
    covariance_m2: np.ndarray
    frame: str
    stamp: FrameStamp
    calibration_id: str
```

The shared array validator must copy inputs, require exact shapes, reject non-finite values, and mark stored arrays read-only. `DryRunReport` contains `approved: bool`, `reasons: tuple[str, ...]`, `candidate_xyz_m`, `score`, `target_track_id`, and `calibration_id`.

- [ ] **Step 4: Run the contract tests**

Run: `cd web-control/server && python3 -m pytest tests/vision/test_types.py -v`

Expected: all tests pass.

- [ ] **Step 5: Commit the data contracts**

```bash
git add web-control/server/vision web-control/server/tests/vision/test_types.py
git commit -m "feat(vision): add immutable provenance contracts"
```

### Task 2: Correct RPY and SE(3) geometry

**Files:**
- Create: `web-control/server/vision/geometry.py`
- Test: `web-control/server/tests/vision/test_geometry.py`

**Interfaces:**
- Consumes: radians in `(roll, pitch, yaw)` order and NumPy points shaped `(N, 3)`.
- Produces: `rpy_xyz_to_matrix(rpy_rad) -> ndarray[3,3]`, `make_transform(rotation, translation_m) -> ndarray[4,4]`, `invert_transform(transform)`, `transform_points(transform, points_m)`, and `validate_transform(transform)`.

- [ ] **Step 1: Write tests that expose the audited Rodrigues/Euler defect**

```python
def test_rpy_uses_rz_ry_rx_not_rodrigues_vector():
    rpy = np.deg2rad([20.0, -15.0, 35.0])
    expected = rz(rpy[2]) @ ry(rpy[1]) @ rx(rpy[0])
    np.testing.assert_allclose(rpy_xyz_to_matrix(rpy), expected, atol=1e-12)

def test_transform_round_trip():
    transform = make_transform(rpy_xyz_to_matrix([0.2, -0.1, 0.4]), [0.3, -0.2, 0.8])
    points = np.array([[0.0, 0.0, 0.0], [0.2, -0.4, 1.1]])
    np.testing.assert_allclose(
        transform_points(invert_transform(transform), transform_points(transform, points)),
        points,
        atol=1e-12,
    )
```

- [ ] **Step 2: Run the geometry tests and verify import failure**

Run: `cd web-control/server && python3 -m pytest tests/vision/test_geometry.py -v`

Expected: failure containing `No module named 'vision.geometry'`.

- [ ] **Step 3: Implement explicit axis rotations and rigid-transform validation**

```python
def rpy_xyz_to_matrix(rpy_rad: ArrayLike) -> np.ndarray:
    roll, pitch, yaw = finite_vector(rpy_rad, 3)
    return rotation_z(yaw) @ rotation_y(pitch) @ rotation_x(roll)

def invert_transform(transform: ArrayLike) -> np.ndarray:
    t = validate_transform(transform)
    result = np.eye(4)
    result[:3, :3] = t[:3, :3].T
    result[:3, 3] = -t[:3, :3].T @ t[:3, 3]
    return result
```

`validate_transform` must require shape `(4,4)`, last row `[0,0,0,1]`, determinant `+1`, and `R.T @ R == I` within `1e-8`.

- [ ] **Step 4: Run geometry tests and the existing offline tests**

Run: `cd web-control/server && python3 -m pytest tests/vision/test_geometry.py -v && python3 -m pytest tests -q`

Expected: the new tests pass; any pre-existing hardware-only tests are reported separately rather than started.

- [ ] **Step 5: Commit geometry**

```bash
git add web-control/server/vision/geometry.py web-control/server/tests/vision/test_geometry.py
git commit -m "fix(vision): implement correct RPY and SE3 math"
```

### Task 3: Lumos SEUCM and D435 pinhole camera models

**Files:**
- Create: `web-control/server/vision/camera_models.py`
- Test: `web-control/server/tests/vision/test_camera_models.py`

**Interfaces:**
- Consumes: `PinholeCamera(fx, fy, cx, cy, width, height)` and `SeucmCamera(fx, fy, cx, cy, alpha, beta, width, height)`.
- Produces: `project(points_camera_m) -> (uv_px, valid)`, `unproject(uv_px) -> (unit_rays, valid)`, and `deproject_z(uv_px, z_m) -> points_camera_m` for pinhole depth.

- [ ] **Step 1: Write center-ray, round-trip, field-domain, and Z-depth tests**

```python
def test_seucm_project_unproject_round_trip():
    camera = SeucmCamera(392.168, 392.168, 637.761, 640.597, 0.678979, 0.749026, 1280, 1280)
    rays = normalize_rows(np.array([[0.0, 0.0, 1.0], [0.3, -0.2, 0.9327379]]))
    uv, projected = camera.project(rays)
    recovered, unprojected = camera.unproject(uv)
    assert projected.all() and unprojected.all()
    np.testing.assert_allclose(recovered, rays, atol=2e-6)

def test_pinhole_depth_is_z_not_euclidean_range():
    camera = PinholeCamera(600.0, 600.0, 320.0, 240.0, 640, 480)
    point = camera.deproject_z(np.array([[620.0, 240.0]]), np.array([1.0]))
    np.testing.assert_allclose(point, [[0.5, 0.0, 1.0]])
```

- [ ] **Step 2: Run the tests and verify the camera module is missing**

Run: `cd web-control/server && python3 -m pytest tests/vision/test_camera_models.py -v`

Expected: import failure for `vision.camera_models`.

- [ ] **Step 3: Implement vectorized SEUCM projection/unprojection with explicit validity masks**

```python
denominator = alpha * np.sqrt(beta * (x*x + y*y) + z*z) + (1.0 - alpha) * z
u = fx * x / denominator + cx
v = fy * y / denominator + cy

r2 = mx*mx + my*my
sqrt_term = 1.0 - (2.0 * alpha - 1.0) * beta * r2
mz = (1.0 - beta * alpha * alpha * r2) / (
    alpha * np.sqrt(sqrt_term) + 1.0 - alpha
)
rays = normalize_rows(np.column_stack((mx, my, mz)))
```

Validity must reject non-finite inputs, non-positive projection denominators, points behind the valid SEUCM domain, negative square-root terms, and pixels outside image bounds.

- [ ] **Step 4: Run camera-model tests**

Run: `cd web-control/server && python3 -m pytest tests/vision/test_camera_models.py -v`

Expected: all tests pass, including round-trip angular error below `2e-6` radians.

- [ ] **Step 5: Commit camera models**

```bash
git add web-control/server/vision/camera_models.py web-control/server/tests/vision/test_camera_models.py
git commit -m "feat(vision): add pinhole and SEUCM camera models"
```

### Task 4: D435 depth registration into Lumos pixels

**Files:**
- Create: `web-control/server/vision/depth_registration.py`
- Test: `web-control/server/tests/vision/test_depth_registration.py`

**Interfaces:**
- Consumes: D435 Z-depth image in metres, `PinholeCamera`, D435-to-Lumos `4x4` transform, and `SeucmCamera`.
- Produces: `register_depth_to_lumos(...) -> RegisteredDepth`, containing Lumos-space `z_m`, `range_m`, `valid`, and `source_count` arrays; `select_masked_cloud(registered, mask) -> ndarray[N,3]`.

- [ ] **Step 1: Write synthetic identity, translated-camera, and occlusion tests**

```python
def test_z_buffer_keeps_nearest_lumos_surface():
    result = rasterize_lumos_points(
        uv_px=np.array([[5.2, 7.1], [5.4, 7.4]]),
        points_lumos_m=np.array([[0.0, 0.0, 0.8], [0.0, 0.0, 1.2]]),
        image_shape=(12, 12),
    )
    assert result.valid[7, 5]
    assert result.z_m[7, 5] == pytest.approx(0.8)
    assert result.source_count[7, 5] == 2

def test_registration_rejects_zero_nan_and_out_of_view_depth():
    depth = np.array([[0.0, np.nan], [0.5, 12.0]])
    result = register_depth_to_lumos(depth, d435, np.eye(4), lumos, min_depth_m=0.1, max_depth_m=3.0)
    assert result.valid.sum() <= 1
```

- [ ] **Step 2: Run the depth-registration tests and verify import failure**

Run: `cd web-control/server && python3 -m pytest tests/vision/test_depth_registration.py -v`

Expected: import failure for `vision.depth_registration`.

- [ ] **Step 3: Implement deprojection, transform, projection, nearest-depth z-buffer, and mask selection**

```python
rows, cols = np.nonzero(np.isfinite(depth_z_m) & (depth_z_m >= min_depth_m) & (depth_z_m <= max_depth_m))
uv_d435 = np.column_stack((cols, rows)).astype(float)
points_d435 = d435.deproject_z(uv_d435, depth_z_m[rows, cols])
points_lumos = transform_points(t_lumos_from_d435, points_d435)
uv_lumos, valid = lumos.project(points_lumos)
return rasterize_lumos_points(uv_lumos[valid], points_lumos[valid], (lumos.height, lumos.width))
```

Use integer nearest-pixel rasterization for the baseline, stable sorting by `(pixel_index, z)`, and count all projected contributors per pixel. Never use the desk plane as a substitute for missing depth.

- [ ] **Step 4: Run registration tests and benchmark one synthetic 848×480 frame**

Run: `cd web-control/server && python3 -m pytest tests/vision/test_depth_registration.py -v && python3 -m pytest tests/vision/test_depth_registration.py -q --durations=5`

Expected: all correctness tests pass and the timing is recorded in the test artifact without asserting a workstation-specific hard limit.

- [ ] **Step 5: Commit depth registration**

```bash
git add web-control/server/vision/depth_registration.py web-control/server/tests/vision/test_depth_registration.py
git commit -m "feat(vision): register D435 depth into Lumos pixels"
```

### Task 5: Timestamp-aware 3D tracking

**Files:**
- Create: `web-control/server/vision/tracking.py`
- Test: `web-control/server/tests/vision/test_tracking.py`

**Interfaces:**
- Consumes: `TrackObservation` sequences and `TrackerConfig(max_distance_m, max_age_ns, min_confirmed_hits)`.
- Produces: `MultiObjectTracker.update(observations, now_ns) -> tuple[TrackState, ...]` with monotonic integer IDs, hit/miss counts, confirmed flag, velocity, covariance, and last-seen time.

- [ ] **Step 1: Write tests for global assignment, occlusion survival, expiry, class gating, and out-of-order timestamps**

```python
def test_confirmed_track_survives_one_empty_detection_frame():
    tracker = MultiObjectTracker(TrackerConfig(0.20, 500_000_000, 2))
    first = tracker.update([observation([0.0, 0.0, 1.0], 0)], 0)
    second = tracker.update([observation([0.01, 0.0, 1.0], 100_000_000)], 100_000_000)
    third = tracker.update([], 200_000_000)
    assert second[0].confirmed
    assert third[0].track_id == first[0].track_id
    assert third[0].misses == 1

def test_update_rejects_time_regression():
    tracker = MultiObjectTracker(TrackerConfig(0.20, 500_000_000, 2))
    tracker.update([], 10)
    with pytest.raises(InvalidDataError):
        tracker.update([], 9)
```

- [ ] **Step 2: Run tracking tests and verify import failure**

Run: `cd web-control/server && python3 -m pytest tests/vision/test_tracking.py -v`

Expected: import failure for `vision.tracking`.

- [ ] **Step 3: Implement constant-velocity prediction, class-gated Mahalanobis cost, and Hungarian assignment**

```python
cost = np.full((len(tracks), len(observations)), np.inf)
for row, track in enumerate(tracks):
    predicted = track.xyz_m + track.velocity_mps * dt_s
    for col, observation in enumerate(observations):
        if track.label == observation.label:
            distance = np.linalg.norm(predicted - observation.pose.xyz_m)
            if distance <= config.max_distance_m:
                cost[row, col] = distance
rows, cols = linear_sum_assignment(np.where(np.isfinite(cost), cost, 1e9))
matches = [(r, c) for r, c in zip(rows, cols) if np.isfinite(cost[r, c])]
```

Unmatched confirmed tracks remain until `now_ns - last_seen_ns > max_age_ns`; unmatched observations start tentative tracks; IDs are never reused in a process.

- [ ] **Step 4: Run tracking tests**

Run: `cd web-control/server && python3 -m pytest tests/vision/test_tracking.py -v`

Expected: all lifecycle and assignment tests pass.

- [ ] **Step 5: Commit tracking**

```bash
git add web-control/server/vision/tracking.py web-control/server/tests/vision/test_tracking.py
git commit -m "feat(vision): add timestamp-aware 3D tracking"
```

### Task 6: Stable base-frame object memory

**Files:**
- Create: `web-control/server/vision/object_memory.py`
- Test: `web-control/server/tests/vision/test_object_memory.py`

**Interfaces:**
- Consumes: confirmed `TrackState` values, current monotonic time, and `ObjectMemoryConfig(max_age_ns, max_position_std_m, min_hits)`.
- Produces: `ObjectMemory.ingest(tracks, now_ns)`, `get(track_id, now_ns) -> TrackState | None`, and `select_stable(label, now_ns) -> tuple[TrackState, ...]` sorted by uncertainty then track ID.

- [ ] **Step 1: Write freshness, uncertainty, deterministic-order, and calibration-change tests**

```python
def test_stable_selection_excludes_stale_or_uncertain_tracks():
    memory = ObjectMemory(ObjectMemoryConfig(300_000_000, 0.025, 3))
    memory.ingest([stable_track(2), uncertain_track(3)], now_ns=100)
    assert [track.track_id for track in memory.select_stable("cup", 200)] == [2]
    assert memory.select_stable("cup", 400_000_101) == ()

def test_calibration_change_invalidates_robot_space_memory():
    memory.ingest([stable_track(2, calibration_id="sha256:a")], now_ns=100)
    memory.set_calibration("sha256:b")
    assert memory.get(2, 101) is None
```

- [ ] **Step 2: Run object-memory tests and verify import failure**

Run: `cd web-control/server && python3 -m pytest tests/vision/test_object_memory.py -v`

Expected: import failure for `vision.object_memory`.

- [ ] **Step 3: Implement bounded deterministic memory keyed by track ID and calibration ID**

```python
def select_stable(self, label: str, now_ns: int) -> tuple[TrackState, ...]:
    candidates = [
        track for track in self._tracks.values()
        if track.label == label
        and track.confirmed
        and track.hits >= self.config.min_hits
        and now_ns - track.last_seen_ns <= self.config.max_age_ns
        and np.sqrt(np.max(np.diag(track.pose.covariance_m2))) <= self.config.max_position_std_m
    ]
    return tuple(sorted(candidates, key=lambda track: (np.trace(track.pose.covariance_m2), track.track_id)))
```

`set_calibration` clears entries whenever the calibration ID changes; `ingest` rejects tracks whose pose frame is not `robot_base`.

- [ ] **Step 4: Run object-memory tests**

Run: `cd web-control/server && python3 -m pytest tests/vision/test_object_memory.py -v`

Expected: all tests pass.

- [ ] **Step 5: Commit object memory**

```bash
git add web-control/server/vision/object_memory.py web-control/server/tests/vision/test_object_memory.py
git commit -m "feat(vision): add stable base-frame object memory"
```

### Task 7: Deterministic safety gate and Dry Run report

**Files:**
- Create: `web-control/server/vision/safety.py`
- Create: `web-control/server/vision/dry_run.py`
- Test: `web-control/server/tests/vision/test_safety.py`
- Test: `web-control/server/tests/vision/test_dry_run.py`

**Interfaces:**
- Consumes: stable `TrackState`, `SafetyConfig`, target cloud, table plane, current time, and calibration status.
- Produces: `evaluate_target_safety(...) -> SafetyDecision`, `generate_top_down_candidates(...) -> tuple[GraspCandidate, ...]`, and `build_dry_run_report(...) -> DryRunReport`.

- [ ] **Step 1: Write fail-closed tests for missing calibration, stale frames, excessive uncertainty, empty cloud, workspace violation, and no candidate**

```python
@pytest.mark.parametrize("reason", [
    "calibration_not_validated", "target_stale", "uncertainty_too_high",
    "target_cloud_too_small", "outside_workspace", "no_collision_free_candidate",
])
def test_dry_run_fails_closed(reason, scenario_factory):
    report = build_dry_run_report(**scenario_factory(reason))
    assert not report.approved
    assert reason in report.reasons

def test_report_never_contains_an_execute_command():
    report = build_dry_run_report(**valid_scenario())
    serialized = json.dumps(report.to_dict()).lower()
    assert "command" not in serialized and "websocket" not in serialized and "can" not in serialized
```

- [ ] **Step 2: Run safety tests and verify both modules are missing**

Run: `cd web-control/server && python3 -m pytest tests/vision/test_safety.py tests/vision/test_dry_run.py -v`

Expected: import failures for `vision.safety` and `vision.dry_run`.

- [ ] **Step 3: Implement conjunctive gates, top-down PCA candidates, and deterministic scoring**

```python
approved = all((
    calibration.validated,
    age_ns <= config.max_target_age_ns,
    position_std_m <= config.max_position_std_m,
    len(target_cloud_m) >= config.min_cloud_points,
    config.workspace_min_m <= xyz_m,
    xyz_m <= config.workspace_max_m,
))

score = (
    config.clearance_weight * clearance_m
    - config.uncertainty_weight * position_std_m
    - config.travel_weight * np.linalg.norm(pregrasp_xyz_m - config.nominal_pose_m)
)
```

The workspace comparison is component-wise and combined with `.all()`. Candidate output contains geometry only: pregrasp pose, grasp pose, retreat pose, width, score, and rejection reasons. It contains no SDK method, WebSocket message, or CAN frame.

- [ ] **Step 4: Run safety and Dry Run tests**

Run: `cd web-control/server && python3 -m pytest tests/vision/test_safety.py tests/vision/test_dry_run.py -v`

Expected: all fail-closed and deterministic-order tests pass.

- [ ] **Step 5: Commit safety and Dry Run**

```bash
git add web-control/server/vision/safety.py web-control/server/vision/dry_run.py web-control/server/tests/vision/test_safety.py web-control/server/tests/vision/test_dry_run.py
git commit -m "feat(vision): add fail-closed dry-run safety gate"
```

### Task 8: Offline replay, metrics, and provenance export

**Files:**
- Create: `web-control/server/vision/replay.py`
- Create: `web-control/server/tests/vision/fixtures/synthetic_replay.json`
- Create: `web-control/server/tests/vision/fixtures/synthetic_depth.npz`
- Test: `web-control/server/tests/vision/test_replay.py`

**Interfaces:**
- Consumes: JSON manifest with ordered frame stamps and NPZ arrays; all paths are relative to the manifest.
- Produces: `run_replay(manifest_path) -> ReplayMetrics` and CLI `python3 -m vision.replay --manifest PATH --output metrics.json`.

- [ ] **Step 1: Add a deterministic three-frame synthetic replay and expected metrics test**

```python
def test_replay_is_deterministic_and_reports_required_metrics(tmp_path):
    first = run_replay(FIXTURE_MANIFEST)
    second = run_replay(FIXTURE_MANIFEST)
    assert first.to_dict() == second.to_dict()
    assert first.registration_coverage == pytest.approx(0.75)
    assert first.id_switches == 0
    assert first.dry_run_approval_rate == pytest.approx(1.0 / 3.0)
    assert first.calibration_ids == ("sha256:synthetic-v1",)
```

- [ ] **Step 2: Run replay test and verify import failure**

Run: `cd web-control/server && python3 -m pytest tests/vision/test_replay.py -v`

Expected: import failure for `vision.replay`.

- [ ] **Step 3: Implement strict manifest parsing and atomic metrics output**

```python
def write_metrics_atomic(path: Path, metrics: ReplayMetrics) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(metrics.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)
```

The manifest parser must reject absolute data paths, `..` traversal, duplicate/non-monotonic frame stamps, unknown schema versions, and calibration-ID changes within a run. Metrics include registration coverage, valid target-cloud frames, track continuity, ID switches, latency percentiles supplied by the fixture, Dry Run approval/rejection counts, and rejection reasons.

- [ ] **Step 4: Run the replay test twice and compare byte-identical JSON output**

Run: `cd web-control/server && python3 -m pytest tests/vision/test_replay.py -v && python3 -m vision.replay --manifest tests/vision/fixtures/synthetic_replay.json --output /tmp/thirdhand-metrics-a.json && python3 -m vision.replay --manifest tests/vision/fixtures/synthetic_replay.json --output /tmp/thirdhand-metrics-b.json && cmp /tmp/thirdhand-metrics-a.json /tmp/thirdhand-metrics-b.json`

Expected: tests pass and `cmp` exits `0`.

- [ ] **Step 5: Commit replay support**

```bash
git add web-control/server/vision/replay.py web-control/server/tests/vision/test_replay.py web-control/server/tests/vision/fixtures
git commit -m "test(vision): add deterministic offline replay benchmark"
```

### Task 9: Integration boundary and acceptance evidence

**Files:**
- Modify: `web-control/server/vision/__init__.py`
- Create: `web-control/server/tests/vision/test_no_hardware_dependencies.py`
- Create: `docs/vision_research/OFFLINE_IMPLEMENTATION_RESULTS.md`

**Interfaces:**
- Consumes: public interfaces from Tasks 1–8.
- Produces: a stable import surface and evidence that importing/running the package performs no hardware, service, network, or privilege operation.

- [ ] **Step 1: Write a static dependency-boundary test**

```python
FORBIDDEN = ("startouch", "can.interface", "pyrealsense2", "websocket", "socket", "subprocess", "sudo")

def test_vision_core_has_no_hardware_or_process_dependencies():
    package = Path(__file__).parents[2] / "vision"
    source = "\n".join(path.read_text(encoding="utf-8") for path in package.glob("*.py"))
    for token in FORBIDDEN:
        assert token not in source.lower()
```

- [ ] **Step 2: Run the boundary test before changing exports**

Run: `cd web-control/server && python3 -m pytest tests/vision/test_no_hardware_dependencies.py -v`

Expected: pass if Tasks 1–8 respected the boundary; otherwise fail on the exact forbidden token and remove that dependency before continuing.

- [ ] **Step 3: Export only the reviewed public contracts from `vision/__init__.py`**

```python
from .camera_models import PinholeCamera, SeucmCamera
from .depth_registration import RegisteredDepth, register_depth_to_lumos
from .dry_run import build_dry_run_report
from .geometry import invert_transform, make_transform, rpy_xyz_to_matrix, transform_points
from .object_memory import ObjectMemory, ObjectMemoryConfig
from .tracking import MultiObjectTracker, TrackerConfig

__all__ = [name for name in globals() if not name.startswith("_")]
```

- [ ] **Step 4: Run complete offline verification and record exact results**

Run: `cd web-control/server && python3 -m pytest tests/vision -v --durations=10`

Run: `git status --short && git log --oneline --decorate -10`

Expected: all offline vision tests pass; no command starts services or imports a hardware SDK. Record test count, duration, replay metrics, branch, commit IDs, Python/NumPy/SciPy versions, and unresolved manual gates in `docs/vision_research/OFFLINE_IMPLEMENTATION_RESULTS.md`.

- [ ] **Step 5: Commit acceptance evidence**

```bash
git add web-control/server/vision/__init__.py web-control/server/tests/vision/test_no_hardware_dependencies.py docs/vision_research/OFFLINE_IMPLEMENTATION_RESULTS.md
git commit -m "docs(vision): record offline safety-core acceptance"
```

## Manual gates after this plan

The following remain explicitly manual and are not authorized by this plan:

1. Recalibrate Lumos intrinsics with a documented SEUCM-compatible target and independently validate reprojection error.
2. Recalibrate D435-to-Lumos and camera-to-robot transforms, preserving raw captures and calibration hashes.
3. Collect synchronized static-scene replay data and pass all thresholds in `13_BENCHMARK_AND_ACCEPTANCE_PLAN.md`.
4. Review Dry Run overlays, proposed grasp/pregrasp/retreat poses, reachability, uncertainty, and collision margins.
5. Approve any future live-service integration as a separate change.
6. Approve any future real-arm movement as a separate, supervised procedure with an emergency stop and low-speed limits.

