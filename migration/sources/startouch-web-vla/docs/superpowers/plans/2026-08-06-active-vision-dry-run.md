# Active Vision Dry-Run Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build deterministic Lumos-guided D435 observation proposals, identity-preserving session logic, replay evidence, and a read-only web presentation without granting any process permission to move the robot.

**Architecture:** New pure-Python units own active-view contracts, table geometry, observation-pose selection, depth-quality/refinement decisions, and the session state machine. A hardware-independent online adapter attaches bounded dry-run proposals to existing `detection_result` events; Node sanitizes and presents them but exposes no new motion command. The checked-in production catalog is intentionally empty and every execution flag remains exactly `false`, so current hardware can validate blockers and proposal telemetry without CAN writes.

**Tech Stack:** Python 3.11, NumPy, SciPy already present in the vision environment, PyYAML, pytest, Node.js 18+, Express, browser JavaScript, Node smoke tests.

## Global Constraints

- `canonical_rgb` remains Lumos RGB; `metric_depth` remains D435 depth; D435 RGB remains debug-only.
- The desktop is fixed and represented in robot-base coordinates by `normal · xyz + offset_m = 0`.
- Desktop-ray intersections are coarse observation-planning evidence only and must never populate a grasp `position_m`.
- The D435 quality ROI starts as the central 60% of image width and height.
- Depth acquisition requires at least 80 registered mask points.
- Stability requires 5 stop-and-look samples, each within 10 mm of the temporal median, with per-axis MAD at most 5 mm.
- RGB-depth skew remains at most 50 ms, fused frame age at most 200 ms, and robot-pose skew at most 50 ms.
- A refinement proposal is capped at 20 mm translation, 5° rotation, and 3 iterations; this phase emits proposals only and never executes them.
- Calibration, table, robot-model, and observation-catalog IDs are content-addressed with `sha256:`.
- `robot_execution_enabled` and `active_view_execution_enabled` remain exactly `false` in every checked-in config, event, API response, and UI state.
- Files in `web-control/server/vision/` must not import Startouch, CAN, socket, subprocess, WebSocket, or camera hardware.
- Existing port-3000 real control and port-3100 read-only deployments must not be stopped or reconfigured while executing this plan.

## File Structure

- `web-control/server/vision/active_view_types.py`: immutable active-view domain contracts and enums only.
- `web-control/server/vision/active_view_geometry.py`: Lumos mask-to-table estimates and convex coverage geometry.
- `web-control/server/vision/active_view_planner.py`: observation-pose ranking, depth-quality checks, and bounded refinement proposals.
- `web-control/server/vision/active_view_session.py`: deterministic event/state transitions and depth-stability window.
- `web-control/server/vision/active_view_replay.py`: bounded deterministic dry-run replay and metrics.
- `web-control/server/vision_models/active_view_online.py`: YAML loading, model-boundary adaptation, and JSON serialization.
- `configs/vision/active_view.yaml`: execution-locked defaults and an explicitly empty real observation catalog.
- `web-control/server/vision_models/online.py`: calls the optional dry-run adapter after identity assignment.
- `web-control/server/camera_bridge.py`: constructs the dry-run adapter; still accepts no target or motion stdin command.
- `web-control/server/camera-bridge.js`: forwards the active-view config path only.
- `web-control/server/vision-status.js`: sanitizes bounded active-view presentation data.
- `web-control/web/camera-test.html`: read-only active-view status and blocker panel.
- `scripts/vision/verify_active_view_dry_run.py`: validates online proposal telemetry while requiring execution false.

---

### Task 1: Immutable Contracts and Execution-Locked Configuration

**Files:**
- Create: `web-control/server/vision/active_view_types.py`
- Create: `web-control/server/vision_models/active_view_online.py`
- Create: `web-control/server/tests/vision/test_active_view_types.py`
- Create: `web-control/server/tests/vision_models/test_active_view_online.py`
- Create: `configs/vision/active_view.yaml`
- Modify: `web-control/server/vision/__init__.py`

**Interfaces:**
- Produces `TablePlane(normal_base, offset_m, position_rmse_m, calibration_id, validated)`.
- Produces `CoarseTargetEstimate(identity_id, center_xy_m, covariance_xy_m2, samples_xy_m, source_stamp, calibration_id)`.
- Produces `ObservationPose(pose_id, joints_deg, t_base_from_flange, coverage_polygon_xy_m, allowed_start_pose_ids, path_validation_id, calibration_id)`.
- Produces `DepthQuality(valid_points, central_fraction, center_d435_m, center_base_m, mad_m, acceptable, reasons)`.
- Produces `ObservationMoveProposal(kind, identity_id, source_stamp, expires_ns, target_pose_id, joints_deg, delta_base_m, rotation_delta_rad, evidence_ids, reasons)` where `kind` is `none`, `coarse_pose`, or `refine_delta`.
- Produces `ActiveViewConfig` and `load_active_view_config(path)`.

- [ ] **Step 1: Write failing immutable-contract tests**

```python
def test_checked_in_active_view_config_is_execution_locked_and_empty():
    config = load_active_view_config(ROOT / "configs/vision/active_view.yaml")
    assert config.dry_run_enabled is True
    assert config.execution_enabled is False
    assert config.observation_poses == ()
    assert config.inner_roi_fraction == pytest.approx(0.60)
    assert config.min_depth_points == 80
    assert config.stable_sample_count == 5
    assert config.max_refinement_steps == 3


def test_move_proposal_copies_arrays_and_rejects_execution_payloads():
    joints = np.arange(6, dtype=float)
    proposal = ObservationMoveProposal.coarse(
        identity_id=4,
        source_stamp=FrameStamp("lumos_rgb", 7, 100),
        expires_ns=200,
        target_pose_id="table_left",
        joints_deg=joints,
        evidence_ids=("sha256:" + "a" * 64,),
    )
    joints[:] = 99
    assert proposal.joints_deg.tolist() == list(range(6))
    assert proposal.delta_base_m is None
    with pytest.raises(ValueError, match="execution"):
        load_active_view_config_dict({"active_view_execution_enabled": True})
```

- [ ] **Step 2: Run the tests and confirm missing modules fail collection**

Run: `PYTHONPATH=web-control/server pytest -q web-control/server/tests/vision/test_active_view_types.py web-control/server/tests/vision_models/test_active_view_online.py`

Expected: FAIL because `vision.active_view_types` and `vision_models.active_view_online` do not exist.

- [ ] **Step 3: Add the checked-in fail-closed YAML**

```yaml
schema_version: 1
dry_run_enabled: true
active_view_execution_enabled: false
table_plane:
  normal_base: [0.0, 0.0, 1.0]
  offset_m: 0.0
  position_rmse_m: 0.010
  calibration_id: "sha256:ca498e702d72d6e78657596b3b7a55f7a7384b17329b40abc890ea7b6f74a941"
  validated: false
quality:
  inner_roi_fraction: 0.60
  coverage_margin_m: 0.010
  min_depth_points: 80
  min_central_fraction: 0.60
  stable_sample_count: 5
  max_center_deviation_m: 0.010
  max_axis_mad_m: 0.005
motion_proposals:
  max_translation_m: 0.020
  max_rotation_deg: 5.0
  max_refinement_steps: 3
  proposal_ttl_ms: 200
observation_poses: []
```

- [ ] **Step 4: Implement strict dataclasses and loader**

```python
@dataclass(frozen=True)
class ActiveViewConfig:
    dry_run_enabled: bool
    execution_enabled: bool
    table_plane: TablePlane
    inner_roi_fraction: float
    coverage_margin_m: float
    min_depth_points: int
    min_central_fraction: float
    stable_sample_count: int
    max_center_deviation_m: float
    max_axis_mad_m: float
    max_translation_m: float
    max_rotation_rad: float
    max_refinement_steps: int
    proposal_ttl_ns: int
    observation_poses: tuple[ObservationPose, ...]

    def __post_init__(self) -> None:
        if self.execution_enabled is not False:
            raise InvalidDataError("active-view execution must remain disabled")
```

The loader must reject unknown schema versions, non-finite arrays, non-convex coverage polygons, duplicate pose IDs, invalid `sha256:` IDs, non-positive limits, any proposal TTL over 1 s, and any true execution flag. All NumPy members are copied and read-only. Export the new contracts through `vision.__all__`.

- [ ] **Step 5: Run focused and dependency-boundary tests**

Run: `PYTHONPATH=web-control/server pytest -q web-control/server/tests/vision/test_active_view_types.py web-control/server/tests/vision_models/test_active_view_online.py web-control/server/tests/vision/test_no_hardware_dependencies.py`

Expected: PASS; the checked-in config loads but its table and pose catalog remain non-actionable.

- [ ] **Step 6: Commit**

```bash
git add configs/vision/active_view.yaml web-control/server/vision/active_view_types.py web-control/server/vision/__init__.py web-control/server/vision_models/active_view_online.py web-control/server/tests/vision/test_active_view_types.py web-control/server/tests/vision_models/test_active_view_online.py
git commit -m "feat(vision): add active-view dry-run contracts"
```

---

### Task 2: Lumos Mask-to-Desktop Geometry

**Files:**
- Create: `web-control/server/vision/active_view_geometry.py`
- Create: `web-control/server/tests/vision/test_active_view_geometry.py`
- Modify: `web-control/server/vision/__init__.py`

**Interfaces:**
- Consumes `SeucmCamera`, `TablePlane`, `FrameStamp`, a Lumos boolean instance mask, and `T_base_from_lumos`.
- Produces `estimate_table_target(identity_id, mask, lumos, t_base_from_lumos, table, stamp) -> CoarseTargetEstimate`.
- Produces `contains_estimate(polygon_xy_m, estimate, minimum_edge_margin_m) -> bool` for convex polygons.

- [ ] **Step 1: Write failing ray/plane and coverage tests**

```python
def test_mask_lower_boundary_estimates_table_location_not_mask_center():
    mask = np.zeros((9, 9), dtype=bool)
    mask[2:8, 3:6] = True
    estimate = estimate_table_target(
        7, mask, camera(), camera_above_table(), validated_table(),
        FrameStamp("lumos_rgb", 4, 1_000),
    )
    assert estimate.identity_id == 7
    assert estimate.samples_xy_m.shape[0] >= 3
    np.testing.assert_allclose(estimate.center_xy_m, np.median(estimate.samples_xy_m, axis=0))
    assert estimate.covariance_xy_m2.shape == (2, 2)


def test_parallel_or_backward_rays_fail_closed():
    with pytest.raises(InvalidDataError, match="table intersection"):
        estimate_table_target(1, edge_mask(), camera(), horizontal_camera(), validated_table(), stamp())
```

Add tests for an empty/non-boolean mask, unvalidated table, wrong calibration ID, invalid SEUCM edge rays, fewer than three valid intersections, covariance positive semidefiniteness, convex polygon winding, boundary inclusion, and required edge margin.

- [ ] **Step 2: Verify the tests fail**

Run: `PYTHONPATH=web-control/server pytest -q web-control/server/tests/vision/test_active_view_geometry.py`

Expected: FAIL because `vision.active_view_geometry` does not exist.

- [ ] **Step 3: Implement lower-boundary sampling and intersections**

```python
rows, cols = np.nonzero(mask_array)
edges = []
for left, right in column_bins(cols.min(), cols.max(), maximum_bins=16):
    in_bin = (cols >= left) & (cols <= right)
    if in_bin.any():
        chosen_row = int(rows[in_bin].max())
        chosen_col = float(np.median(cols[in_bin & (rows == chosen_row)]))
        edges.append((chosen_col, float(chosen_row)))
rays_lumos, valid = lumos.unproject(np.asarray(edges, dtype=float))
origin_base = t_base_from_lumos[:3, 3]
rays_base = rays_lumos @ t_base_from_lumos[:3, :3].T
distance = -(table.normal_base @ origin_base + table.offset_m) / (rays_base @ table.normal_base)
```

Keep only finite positive intersections. Require at least three. Use the median XY center and a symmetric sample covariance plus `TablePlane.position_rmse_m` as the calibration noise floor. Never return Z or a `PoseEstimate`; this prevents the coarse estimate from entering grasp APIs.

- [ ] **Step 4: Implement convex coverage checks without new dependencies**

```python
def contains_estimate(polygon, estimate, minimum_edge_margin_m):
    points = np.vstack((estimate.samples_xy_m, estimate.center_xy_m[None, :]))
    for start, end in polygon_edges(polygon):
        inward = normalized_inward_normal(start, end, polygon)
        if np.min((points - start) @ inward) < minimum_edge_margin_m:
            return False
    return True
```

Reject self-intersecting or non-convex polygons at contract construction. Do not approximate a failed intersection with the image center or a fixed distance.

- [ ] **Step 5: Run geometry and existing camera tests**

Run: `PYTHONPATH=web-control/server pytest -q web-control/server/tests/vision/test_active_view_geometry.py web-control/server/tests/vision/test_camera_models.py web-control/server/tests/vision/test_geometry.py`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add web-control/server/vision/active_view_geometry.py web-control/server/vision/__init__.py web-control/server/tests/vision/test_active_view_geometry.py
git commit -m "feat(vision): estimate table targets from Lumos masks"
```

---

### Task 3: Safe Observation-Pose Selection

**Files:**
- Create: `web-control/server/vision/active_view_planner.py`
- Create: `web-control/server/tests/vision/test_active_view_planner.py`
- Modify: `web-control/server/vision/__init__.py`

**Interfaces:**
- Consumes `CoarseTargetEstimate`, a tuple of `ObservationPose`, current six joint angles, required calibration ID, `now_ns`, and `ActiveViewConfig`.
- Produces `match_observation_pose(current_joints_deg, poses) -> str | None`, accepting a pose only when every joint is within that catalog entry's validated joint tolerance.
- Produces `select_observation_pose(...) -> ObservationMoveProposal`.
- A successful coarse proposal contains only a catalog pose ID and copied six-joint target; a rejection is `kind="none"` with ordered reasons.

- [ ] **Step 1: Write failing deterministic-selection tests**

```python
def test_selector_prefers_covering_pose_with_lower_joint_travel():
    proposal = select_observation_pose(
        estimate=target_estimate(),
        poses=(far_covering_pose(), near_covering_pose()),
        current_joints_deg=np.zeros(6),
        required_calibration_id=CALIBRATION_ID,
        now_ns=1_000,
        config=config_with_catalog(),
    )
    assert proposal.kind == "coarse_pose"
    assert proposal.target_pose_id == "near"
    assert proposal.expires_ns == 200_001_000
    assert proposal.reasons == ()
```

Add tests for empty catalog, uncovered uncertainty region, disallowed start pose, calibration mismatch, unvalidated path ID, non-finite current joints, no current-pose match, already-covered current pose returning `kind="none"` with `observation_already_sufficient`, and stable tie-breaking by `pose_id`.

- [ ] **Step 2: Verify the tests fail**

Run: `PYTHONPATH=web-control/server pytest -q web-control/server/tests/vision/test_active_view_planner.py`

Expected: FAIL because the planner does not exist.

- [ ] **Step 3: Implement filtering and deterministic ranking**

```python
current_pose_id = match_observation_pose(current_joints_deg, poses)
if current_pose_id is None:
    return ObservationMoveProposal.rejected(identity_id, stamp, "current_pose_unvalidated")
eligible = [
    pose for pose in poses
    if pose.calibration_id == required_calibration_id
    and current_pose_id in pose.allowed_start_pose_ids
    and contains_estimate(pose.coverage_polygon_xy_m, estimate, config.coverage_margin_m)
]
ranked = sorted(
    eligible,
    key=lambda pose: (
        float(np.max(np.abs(pose.joints_deg - current_joints_deg))),
        float(np.linalg.norm(pose.joints_deg - current_joints_deg)),
        pose.pose_id,
    ),
)
```

Determine `current_pose_id` with `match_observation_pose`; do not trust a caller-supplied name when joints do not match. Return ordered fail-closed reasons. Copy the selected joint array and include table, camera-chain, robot-model, catalog, and path validation IDs in `evidence_ids`. Never synthesize a Cartesian pose when the catalog has no match.

- [ ] **Step 4: Run planner, geometry, and immutable-contract tests**

Run: `PYTHONPATH=web-control/server pytest -q web-control/server/tests/vision/test_active_view_types.py web-control/server/tests/vision/test_active_view_geometry.py web-control/server/tests/vision/test_active_view_planner.py`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web-control/server/vision/active_view_planner.py web-control/server/vision/__init__.py web-control/server/tests/vision/test_active_view_planner.py
git commit -m "feat(vision): select validated observation poses"
```

---

### Task 4: D435 Quality Gate and Bounded Refinement Proposal

**Files:**
- Modify: `web-control/server/vision/active_view_planner.py`
- Modify: `web-control/server/tests/vision/test_active_view_planner.py`
- Modify: `web-control/server/vision/__init__.py`

**Interfaces:**
- Produces `evaluate_depth_quality(registered, target_mask, d435, t_d435_from_lumos, t_base_from_lumos, config) -> DepthQuality`.
- Produces `propose_refinement(identity_id, quality, t_base_from_d435, stamp, now_ns, step_index, config, evidence_ids) -> ObservationMoveProposal`.
- A refinement proposal contains `delta_base_m` and a zero `rotation_delta_rad`; it never contains joints or an absolute target pose.

- [ ] **Step 1: Add failing D435 quality tests**

```python
def test_good_central_depth_requests_no_extra_motion():
    quality = evaluate_depth_quality(
        registered=central_registered_depth(100),
        target_mask=target_mask(),
        d435=d435(),
        t_d435_from_lumos=np.eye(4),
        t_base_from_lumos=np.eye(4),
        config=active_config(),
    )
    assert quality.valid_points == 100
    assert quality.central_fraction >= 0.60
    assert quality.reasons == ()
    proposal = propose_refinement(3, quality, np.eye(4), stamp(), 1_000, 0, active_config(), EVIDENCE)
    assert proposal.kind == "none"
    assert proposal.reasons == ("depth_quality_sufficient",)
```

Add cases for fewer than 80 points, central fraction below 0.60, points behind the camera, transform mismatch, translation clipping at 20 mm, no optical-axis Z translation, and `step_index >= 3` returning `view_refinement_exhausted`.

- [ ] **Step 2: Verify the new tests fail**

Run: `PYTHONPATH=web-control/server pytest -q web-control/server/tests/vision/test_active_view_planner.py -k 'depth or refinement or central'`

Expected: FAIL because the quality/refinement functions are absent.

- [ ] **Step 3: Implement quality computation in D435 coordinates**

```python
selected_lumos = registered.points_lumos_m[registered.valid & target_mask]
selected_d435 = transform_points(t_d435_from_lumos, selected_lumos)
uv, projected = d435.project(selected_d435)
u0 = d435.width * (1.0 - config.inner_roi_fraction) * 0.5
u1 = d435.width - u0
v0 = d435.height * (1.0 - config.inner_roi_fraction) * 0.5
v1 = d435.height - v0
central = projected & (uv[:, 0] >= u0) & (uv[:, 0] < u1) & (uv[:, 1] >= v0) & (uv[:, 1] < v1)
```

Transform valid points to robot base, compute median center and per-axis MAD, and return explicit reasons for point count, central coverage, or non-finite geometry. Do not use D435 RGB detections.

- [ ] **Step 4: Implement a lateral-only dry-run correction**

```python
center_d435 = quality.center_d435_m
lateral_d435 = np.array([center_d435[0], center_d435[1], 0.0])
raw_delta_base = t_base_from_d435[:3, :3] @ lateral_d435
norm = np.linalg.norm(raw_delta_base)
delta_base = raw_delta_base * min(1.0, config.max_translation_m / max(norm, 1e-12))
```

Reject missing depth and excessive iteration counts. Keep rotation zero in this phase; rotational servoing is not needed to validate the concept and would enlarge the safety surface.

- [ ] **Step 5: Run planner and depth-registration tests**

Run: `PYTHONPATH=web-control/server pytest -q web-control/server/tests/vision/test_active_view_planner.py web-control/server/tests/vision/test_depth_registration.py web-control/server/tests/vision/test_instance_pose.py`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add web-control/server/vision/active_view_planner.py web-control/server/vision/__init__.py web-control/server/tests/vision/test_active_view_planner.py
git commit -m "feat(vision): gate D435 quality and propose bounded refinement"
```

---

### Task 5: Identity-Bound Active-View Session State Machine

**Files:**
- Create: `web-control/server/vision/active_view_session.py`
- Create: `web-control/server/tests/vision/test_active_view_session.py`
- Modify: `web-control/server/vision/__init__.py`

**Interfaces:**
- Produces `ActiveViewPhase` with the exact phases in the approved design.
- Produces immutable events `LockTarget`, `ProposalReady`, `MoveStarted`, `MoveCompleted`, `Settled`, `IdentityObserved`, `DepthObserved`, `Cancel`, and `EvidenceExpired`; `DepthObserved` contains both a `PoseEstimate` and its `DepthQuality`.
- Produces `ActiveViewSession.start(session_id, identity_id, calibration_ids, now_ns)` and `session.transition(event, config) -> ActiveViewSession`.
- Produces `DepthStabilityWindow(sample_count, max_center_deviation_m, max_axis_mad_m).add(identity_id, pose) -> DepthStabilityDecision`.

- [ ] **Step 1: Write failing transition and stale-event tests**

```python
def test_session_requires_move_completion_settle_identity_and_stable_depth():
    session = ActiveViewSession.start("session-1", 9, EVIDENCE, 100)
    session = session.transition(ProposalReady("session-1", coarse_proposal()), config())
    session = session.transition(MoveStarted("session-1", "request-1", 110), config())
    session = session.transition(MoveCompleted("session-1", "request-1", 120), config())
    session = session.transition(Settled("session-1", 140), config())
    session = session.transition(IdentityObserved("session-1", 9, True, 150), config())
    for index, pose in enumerate(stable_poses(), start=1):
        session = session.transition(
            DepthObserved("session-1", 9, pose, good_depth_quality(), 150 + index),
            config(),
        )
    assert session.phase is ActiveViewPhase.GRASP_PREVIEW


def test_wrong_session_or_identity_aborts_without_recovery():
    session = ActiveViewSession.start("current", 9, EVIDENCE, 100)
    with pytest.raises(InvalidTransition, match="session"):
        session.transition(IdentityObserved("old", 9, True, 110), config())
    aborted = session.transition(IdentityObserved("current", 10, True, 120), config())
    assert aborted.phase is ActiveViewPhase.ABORTED
    assert aborted.reasons == ("target_identity_changed",)
```

Add tests for two high-quality identity confirmations after movement, ambiguous identity, fixed delays not advancing movement, wrong request ID, depth while moving, unacceptable `DepthQuality`, evidence/calibration change, target movement over 10 mm, five-sample MAD, three-refinement limit, cancellation, and aborted sessions rejecting all events except creation of a new session.

- [ ] **Step 2: Verify tests fail**

Run: `PYTHONPATH=web-control/server pytest -q web-control/server/tests/vision/test_active_view_session.py`

Expected: FAIL because the session module does not exist.

- [ ] **Step 3: Implement explicit transition dispatch**

```python
def transition(self, event, config):
    if event.session_id != self.session_id:
        raise InvalidTransition("event session does not match active session")
    if self.phase in {ActiveViewPhase.ABORTED, ActiveViewPhase.COMPLETE}:
        raise InvalidTransition("terminal sessions cannot advance")
    handler = _TRANSITIONS.get((self.phase, type(event)))
    if handler is None:
        raise InvalidTransition(f"{type(event).__name__} is invalid in {self.phase.value}")
    return handler(self, event, config)
```

Each transition returns a new frozen session. Store request IDs and evidence hashes. Never call time, sleep, network, or an executor inside the state machine.

- [ ] **Step 4: Implement the bounded stability window**

```python
centers = np.asarray([sample.xyz_m for sample in self.samples[-self.sample_count:]])
median = np.median(centers, axis=0)
deviation = np.linalg.norm(centers - median, axis=1)
mad = np.median(np.abs(centers - median), axis=0)
stable = bool(
    len(centers) == self.sample_count
    and np.max(deviation) <= self.max_center_deviation_m
    and np.max(mad) <= self.max_axis_mad_m
)
```

Reset the window on identity change, calibration change, motion start, stale pose, or refinement. Never reuse a pre-motion depth sample.

- [ ] **Step 5: Run session and full pure-vision tests**

Run: `PYTHONPATH=web-control/server pytest -q web-control/server/tests/vision`

Expected: PASS, including the no-hardware dependency audit.

- [ ] **Step 6: Commit**

```bash
git add web-control/server/vision/active_view_session.py web-control/server/vision/__init__.py web-control/server/tests/vision/test_active_view_session.py
git commit -m "feat(vision): add identity-bound active-view sessions"
```

---

### Task 6: Attach Read-Only Proposals to Online Perception

**Files:**
- Modify: `web-control/server/vision_models/active_view_online.py`
- Modify: `web-control/server/vision_models/online.py`
- Modify: `web-control/server/vision_models/__init__.py`
- Modify: `web-control/server/camera_bridge.py`
- Modify: `web-control/server/camera-bridge.js`
- Modify: `web-control/server/tests/vision_models/test_active_view_online.py`
- Modify: `web-control/server/tests/vision_models/test_online.py`
- Modify: `tests/vision_deployment/test_online_camera_bridge_contract.py`

**Interfaces:**
- Produces `ActiveViewDryRunAdapter(config).evaluate(detections, targets, rgb_stamp, robot_pose, calibration, arm_stationary, now_ns) -> tuple[ActiveViewTargetReport, ...]`.
- `OnlinePerceptionResult.to_event()` adds `active_view_reports`; each report is presentation-only and includes no command name.
- The bridge reads `ACTIVE_VIEW_CONFIG` and still accepts only `arm_state`, `get_status`, and `shutdown` on stdin.

- [ ] **Step 1: Write failing model-boundary tests**

```python
def test_online_event_contains_bounded_nonexecuting_active_view_report():
    result = engine(active_view=synthetic_adapter()).process(
        pair(), robot_pose=robot_pose(), calibration=calibration(),
        arm_stationary=True, now_ns=1_010_000_000,
    )
    payload = result.to_event()
    report = payload["active_view_reports"][0]
    assert report["identity_id"] == payload["targets"][0]["identity_id"]
    assert report["active_view_execution_enabled"] is False
    encoded = json.dumps(report).lower()
    for forbidden in ("move_l", "move_joint", "trajectory", "gripper", "can"):
        assert forbidden not in encoded
```

Add cases for missing calibration, absent robot pose, arm moving, empty pose catalog, detection/target ID mismatch, proposal TTL, at most 256 reports, and adapter exceptions becoming a report blocker without making the model unavailable.

- [ ] **Step 2: Verify tests fail**

Run: `PYTHONPATH=web-control/server pytest -q web-control/server/tests/vision_models/test_active_view_online.py web-control/server/tests/vision_models/test_online.py tests/vision_deployment/test_online_camera_bridge_contract.py`

Expected: FAIL because online results do not contain active-view reports.

- [ ] **Step 3: Implement the optional adapter boundary**

```python
reports = self.active_view.evaluate(
    detections=detections,
    targets=result.targets,
    rgb_stamp=pair.rgb.stamp,
    robot_pose=robot_pose,
    calibration=calibration,
    arm_stationary=arm_stationary,
    now_ns=now_ns,
) if self.active_view is not None else ()
```

Match masks to targets by `detection_id`, never by array position alone. Serialize only finite JSON values, cap strings/arrays, force execution false, and keep existing target `actionable` semantics unchanged.

- [ ] **Step 4: Wire the config without widening stdin**

```python
ACTIVE_VIEW_CONFIG = Path(
    os.environ.get("ACTIVE_VIEW_CONFIG", ROOT / "configs/vision/active_view.yaml")
).resolve()
```

Construct the adapter during model initialization. Forward the path through `camera-bridge.js`. Preserve the exact stdin allowlist and assert the Python bridge import graph still contains no Startouch/CAN dependency.

- [ ] **Step 5: Run model, bridge, and deployment tests**

Run: `PYTHONPATH=web-control/server pytest -q web-control/server/tests/vision web-control/server/tests/vision_models tests/vision_deployment/test_online_camera_bridge_contract.py`

Expected: PASS; checked-in live reports are blocked by unvalidated table/calibration and the empty catalog, and execution is false.

- [ ] **Step 6: Commit**

```bash
git add web-control/server/vision_models/active_view_online.py web-control/server/vision_models/online.py web-control/server/vision_models/__init__.py web-control/server/camera_bridge.py web-control/server/camera-bridge.js web-control/server/tests/vision_models/test_active_view_online.py web-control/server/tests/vision_models/test_online.py tests/vision_deployment/test_online_camera_bridge_contract.py
git commit -m "feat(vision): publish active-view dry-run proposals"
```

---

### Task 7: Read-Only Status Store and Camera Page

**Files:**
- Modify: `web-control/server/vision-status.js`
- Modify: `web-control/server/test/vision-status-smoke.js`
- Modify: `web-control/web/camera-test.html`
- Modify: `tests/web/test_web_ui_security.py`

**Interfaces:**
- `VisionStatusStore.updateTargets(event)` stores sanitized `activeViewReports` with a maximum of 256 entries.
- `GET /api/vision/status` includes `activeView` with execution false.
- The camera page displays coarse-estimate status, selected pose ID, D435 quality, proposal expiry, and blockers; it sends no POST or WebSocket motion command.

- [ ] **Step 1: Write failing Node and UI-security tests**

```javascript
store.updateTargets({ type: 'detection_result', ts: 1000, active_view_reports: [{
  identity_id: 3, kind: 'coarse_pose', target_pose_id: 'table_left',
  expires_ns: 200000000, reasons: [], active_view_execution_enabled: true
}] });
const snapshot = store.snapshot(1000);
assert.equal(snapshot.activeView.reports[0].identityId, 3);
assert.equal(snapshot.activeView.reports[0].executionEnabled, false);
```

Extend Python source tests to require the active-view panel and forbid `start_active_view`, `confirm_active_view`, `move_joint`, `move_l`, editable coordinates, POST requests, and WebSocket sends from `camera-test.html`.

- [ ] **Step 2: Verify tests fail**

Run: `cd web-control/server && node test/vision-status-smoke.js`

Run: `pytest -q tests/web/test_web_ui_security.py`

Expected: FAIL because active-view presentation fields do not exist.

- [ ] **Step 3: Implement bounded sanitization**

```javascript
function sanitizeActiveView(report) {
  return {
    identityId: nonNegativeIntegerOrNull(report?.identity_id),
    kind: ['none', 'coarse_pose', 'refine_delta'].includes(report?.kind) ? report.kind : 'none',
    targetPoseId: typeof report?.target_pose_id === 'string' ? report.target_pose_id.slice(0, 128) : null,
    expiresNs: nonNegativeIntegerOrNull(report?.expires_ns),
    reasons: boundedStrings(report?.reasons),
    executionEnabled: false,
  };
}
```

Strip joint targets, Cartesian deltas, matrices, covariance arrays, and unknown keys from the public API. The browser only needs the proposed pose name and evidence state during Dry Run.

- [ ] **Step 4: Add a read-only panel**

Use DOM `textContent`/`replaceChildren`. Show `观察建议`, `D435 深度质量`, `稳定样本`, `剩余精调`, and exact blocker names. Keep the existing “只读 · robotExecutionEnabled = false” banner and add `activeViewExecutionEnabled = false`.

- [ ] **Step 5: Run Node, web, and browser checks**

Run: `cd web-control/server && npm test`

Run: `cd ../.. && pytest -q tests/web/test_web_ui_security.py`

Expected: PASS; the camera page contains no command path.

- [ ] **Step 6: Commit**

```bash
git add web-control/server/vision-status.js web-control/server/test/vision-status-smoke.js web-control/web/camera-test.html tests/web/test_web_ui_security.py
git commit -m "feat(web): show active-view dry-run status"
```

---

### Task 8: Deterministic Replay, Online Verifier, and Evidence

**Files:**
- Create: `web-control/server/vision/active_view_replay.py`
- Create: `web-control/server/tests/vision/test_active_view_replay.py`
- Create: `web-control/server/tests/vision/fixtures/active_view_replay.json`
- Create: `scripts/vision/verify_active_view_dry_run.py`
- Create: `tests/vision_deployment/test_active_view_dry_run.py`
- Modify: `scripts/vision/start_dual_camera_online.sh`
- Modify: `docs/vision_research/REMIND3D_DEPLOYMENT_RESULTS.md`

**Interfaces:**
- `run_active_view_replay(path) -> ActiveViewReplayMetrics` is byte-deterministic and bounded.
- `verify_active_view_dry_run.evaluate_samples(statuses, expected_execution=False) -> dict` rejects execution, stale inputs, malformed proposals, and non-advancing camera sequences.
- The launcher forwards only `ACTIVE_VIEW_CONFIG`; it does not add a motion switch.

- [ ] **Step 1: Write failing replay and verifier tests**

```python
def test_replay_selects_expected_pose_and_never_emits_execution():
    first = run_active_view_replay(FIXTURE)
    second = run_active_view_replay(FIXTURE)
    assert first.to_dict() == second.to_dict()
    assert first.pose_selection_accuracy == pytest.approx(1.0)
    assert first.identity_switches == 0
    assert first.execution_proposals == 0


def test_verifier_rejects_any_active_view_execution_flag():
    status = healthy_status()
    status["activeView"] = {"executionEnabled": True, "reports": []}
    report = evaluate_samples([status, advanced_status()], expected_execution=False)
    assert report["passed"] is False
    assert "execution" in "\n".join(report["errors"]).lower()
```

The fixture must cover a fisheye-edge target, two same-class identities, one uncovered target, one already-good D435 view, and one clipped 20 mm refinement. Add manifest size, frame count, numeric finiteness, strict timestamp, calibration consistency, and path traversal rejection tests.

- [ ] **Step 2: Verify tests fail**

Run: `PYTHONPATH=web-control/server pytest -q web-control/server/tests/vision/test_active_view_replay.py tests/vision_deployment/test_active_view_dry_run.py`

Expected: FAIL because replay and verifier files do not exist.

- [ ] **Step 3: Implement bounded replay and metrics**

```python
@dataclass(frozen=True)
class ActiveViewReplayMetrics:
    frame_count: int
    proposal_count: int
    pose_selection_accuracy: float
    depth_quality_acceptance_rate: float
    identity_switches: int
    rejection_reasons: dict[str, int]
    execution_proposals: int = 0
```

Cap the manifest at 8 MiB, 10,000 frames, 256 targets per frame, and 64 poses. Sort metric keys and write atomic JSON with `allow_nan=False`. Reject any fixture field that resembles a robot command.

- [ ] **Step 4: Implement verifier and launcher contract**

Sample `/api/vision/status` once per second. Require both camera sequences to advance, roles to match, status age ≤2 s, both execution flags false, every proposal finite and unexpired at source time, and blocker preservation. Add `ACTIVE_VIEW_CONFIG` forwarding to the port-3100 launcher without adding any active-view motion environment variable.

- [ ] **Step 5: Run the complete offline gate**

Run: `PYTHONPATH=web-control/server pytest -q web-control/server/tests/vision web-control/server/tests/vision_models tests/vision_deployment tests/web`

Run: `cd web-control/server && npm test`

Run: `cd ../.. && bash -n scripts/vision/start_dual_camera_online.sh && python -m py_compile scripts/vision/verify_active_view_dry_run.py`

Expected: all commands exit 0; no command opens CAN or moves hardware.

- [ ] **Step 6: Run read-only live evidence without altering services**

Run the verifier against the already running port-3100 service for 60 seconds first. If its code must be restarted, use only the owned `thirdhand-dual-camera-online` lifecycle after checking the exact PID/cwd; leave port 3000 untouched. Save the report below `artifacts/vision/active-view-dry-run/` and confirm both execution flags are false for every sample.

- [ ] **Step 7: Record evidence and commit**

```bash
git add web-control/server/vision/active_view_replay.py web-control/server/tests/vision/test_active_view_replay.py web-control/server/tests/vision/fixtures/active_view_replay.json scripts/vision/verify_active_view_dry_run.py tests/vision_deployment/test_active_view_dry_run.py scripts/vision/start_dual_camera_online.sh docs/vision_research/REMIND3D_DEPLOYMENT_RESULTS.md
git commit -m "test(vision): verify active-view dry-run pipeline"
```

Before committing, document that the checked-in real catalog is empty, current calibration remains unavailable, live proposals are expected to be blocked, and no grasp readiness is claimed.
