# ChArUco Dual-Camera Refit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local, motion-free workflow that captures 12 ChArUco fit poses, robustly solves a fixed-intrinsics Lumos-to-D435 transform, and validates it on 10 separate poses from the existing browser page.

**Architecture:** Keep capture evidence, nonlinear solving, workflow orchestration, the Node security adapter, and browser rendering in separate modules. The Python workflow owns all phase transitions and content-addressed evidence; Node only invokes fixed commands and whitelists responses; the page chooses one permitted action from the returned phase and never receives paths or robot controls.

**Tech Stack:** Python 3.11, OpenCV 4.11 ChArUco/solvePnP, repository `PinholeCamera` and `SeucmCamera`, NumPy, SciPy `least_squares`/`Rotation`, Node.js/Express, plain browser JavaScript, pytest, Ruff.

## Global Constraints

- The physical target is DFOPTIX `CC200-15-11.25`: OpenCV ChArUco `(12, 9)`, square `0.015 m`, marker `0.01125 m`, dictionary `DICT_5X5_100`.
- Lumos remains native EUCM/SEUCM; never reinterpret it as pinhole.
- Fit capture accepts exactly 12 distinct poses with at least 24 common corners, D435 RMSE at most `1.5 px`, capture skew at most `100 ms`, and separation of at least `0.015 m` or `3 deg` from every accepted pose.
- Solving fixes both camera intrinsics and optimizes only one six-degree-of-freedom `T_lumos_from_d435` with SciPy `least_squares(method="trf", loss="soft_l1", f_scale=2.0, x_scale="jac")`.
- A candidate is written only when convergence succeeds, all EUCM projections are valid, baseline is in `[0.02, 0.30] m`, rotation is at most `45 deg`, and aggregate fit P95 is at most `3 px`.
- Held-out validation uses a different directory and exactly 10 distinct passing poses with Lumos P95 at most `4 px`.
- Every generated candidate remains `status: candidate_only`, `executable: false`; hand-eye and table calibration remain blockers.
- The workflow must not import robot, CAN, gripper, or motion modules and must not modify the existing live calibration candidate.
- Node accepts only loopback/same-origin requests, allows one worker at a time, uses no shell, limits combined output to 1 MiB, uses 15-second capture and 60-second solve timeouts, and fixes all paths and URLs server-side.

---

## File Structure

- Create `web-control/server/vision_models/dual_camera_candidate.py`: strict typed loader/writer shared by legacy validation and refit solving.
- Create `web-control/server/vision_models/dual_camera_refit_capture.py`: fit observation type, capture gates, immutable fit manifest, and summary.
- Create `web-control/server/vision_models/dual_camera_refit_solver.py`: pure residual construction, robust initialization, joint solve, metrics, and candidate serialization.
- Create `scripts/vision/dual_camera_refit_workflow.py`: CLI phase orchestration for `status`, `capture-fit`, `solve`, and `capture-validation`.
- Modify `scripts/vision/validate_legacy_dual_camera.py`: consume the shared candidate loader so generated schema-v2 candidates can be held-out validated.
- Modify `web-control/server/calibration-capture-api.js`: whitelist the workflow report and expose three POST actions with one single-flight lock.
- Modify `web-control/server/config.js` and `web-control/server/proxy.js`: supply fixed fit, candidate, and validation locations.
- Modify `web-control/web/calibration-capture.html`: label fit/solve/validation stages and add solver metrics without adding another primary button.
- Modify `web-control/web/calibration-capture.js`: phase-driven action selection and rendering.
- Modify focused Python/Node/browser tests and `web-control/README.md`.

### Task 1: Shared Candidate Contract

**Files:**
- Create: `web-control/server/vision_models/dual_camera_candidate.py`
- Modify: `scripts/vision/validate_legacy_dual_camera.py`
- Test: `tests/vision_deployment/test_dual_camera_candidate.py`
- Test: `tests/vision_deployment/test_legacy_dual_camera_validation_cli.py`

**Interfaces:**
- Consumes: repository camera model constructors and `vision.geometry.validate_transform`.
- Produces: `DualCameraCandidate`, `load_dual_camera_candidate(path) -> DualCameraCandidate`, and `build_refit_candidate_payload(...) -> dict[str, Any]`.

- [ ] **Step 1: Write failing loader and content-ID tests**

```python
def test_generated_candidate_round_trip(tmp_path, legacy_candidate_payload):
    payload = build_refit_candidate_payload(
        seed_payload=legacy_candidate_payload,
        transform=np.eye(4),
        fit_dataset_id="sha256:" + "1" * 64,
        metrics={"samples": 12, "corners": 960, "median_px": 0.3, "p95_px": 0.8},
    )
    path = tmp_path / "candidate.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    loaded = load_dual_camera_candidate(path)
    assert loaded.candidate_id == payload["candidate_id"]
    assert loaded.provenance == "charuco_fixed_intrinsics_refit"
    assert loaded.executable is False

def test_generated_candidate_rejects_tampered_transform(tmp_path, valid_refit_payload):
    valid_refit_payload["T_lumos_from_d435"][0][3] += 0.01
    path = tmp_path / "candidate.json"
    path.write_text(json.dumps(valid_refit_payload), encoding="utf-8")
    with pytest.raises(CalibrationCaptureError, match="integrity"):
        load_dual_camera_candidate(path)
```

- [ ] **Step 2: Run tests and confirm missing-module failure**

Run: `.venv/bin/pytest -q tests/vision_deployment/test_dual_camera_candidate.py`

Expected: collection fails because `vision_models.dual_camera_candidate` does not exist.

- [ ] **Step 3: Implement the typed schema-v1/schema-v2 contract**

Implement a frozen `DualCameraCandidate` containing candidate ID, provenance, immutable 4×4 transform, typed D435/Lumos models, and `executable=False`. Accept the exact audited legacy seed as provenance `legacy_seed`; accept schema-v2 records only if their `candidate_id` equals the SHA-256 of the canonical payload with `candidate_id` omitted. Reject symlinks, oversized JSON, unsupported camera models, NaN, executable records, invalid transforms, and missing fit dataset IDs.

```python
@dataclass(frozen=True)
class DualCameraCandidate:
    candidate_id: str
    provenance: str
    t_lumos_from_d435: np.ndarray = field(compare=False, repr=False)
    d435: PinholeCamera = field(compare=False)
    lumos: SeucmCamera = field(compare=False)
    executable: bool = False

def refit_candidate_id(payload_without_id: dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(_canonical(payload_without_id)).hexdigest()
```

- [ ] **Step 4: Replace the validator-local loader and preserve legacy behavior**

Import `DualCameraCandidate as LegacyCandidateConfig` and `load_dual_camera_candidate as load_candidate` in `validate_legacy_dual_camera.py`; remove its duplicate camera/payload loader. Add a CLI test that a valid generated candidate reaches status, while a tampered candidate produces bounded JSON and no filesystem path.

- [ ] **Step 5: Run focused tests and lint**

Run: `.venv/bin/pytest -q tests/vision_deployment/test_dual_camera_candidate.py tests/vision_deployment/test_legacy_dual_camera_validation.py tests/vision_deployment/test_legacy_dual_camera_validation_cli.py`

Run: `.venv/bin/ruff check web-control/server/vision_models/dual_camera_candidate.py scripts/vision/validate_legacy_dual_camera.py tests/vision_deployment/test_dual_camera_candidate.py`

Expected: all tests pass and Ruff reports no errors.

- [ ] **Step 6: Commit**

```bash
git add web-control/server/vision_models/dual_camera_candidate.py scripts/vision/validate_legacy_dual_camera.py tests/vision_deployment/test_dual_camera_candidate.py tests/vision_deployment/test_legacy_dual_camera_validation_cli.py
git commit -m "refactor(vision): share dual-camera candidate contract"
```

### Task 2: Immutable Fit Evidence Capture

**Files:**
- Create: `web-control/server/vision_models/dual_camera_refit_capture.py`
- Test: `tests/vision_deployment/test_dual_camera_refit_capture.py`

**Interfaces:**
- Consumes: `TargetCorners`, `CalibrationTargetSpec`, `DualCameraCandidate`, JPEG bytes, frame midpoint timestamps.
- Produces: `DualCameraFitObservation`, `evaluate_fit_pair(...)`, `append_fit_observation(...) -> Path`, `load_fit_manifest(...) -> dict | None`, and `fit_summary(...) -> dict`.

- [ ] **Step 1: Write gate-before-write tests**

```python
@pytest.mark.parametrize("mutation,match", [
    (lambda result: replace(result, common_points=23), "common points"),
    (lambda result: replace(result, d435_reprojection_rmse_px=1.51), "D435"),
])
def test_append_rejects_bad_sample_without_files(tmp_path, fit_result, target, mutation, match):
    with pytest.raises(CalibrationCaptureError, match=match):
        append_fit_observation(
            tmp_path, sample_id="fit-01", lumos_jpeg=b"lumos", d435_jpeg=b"d435",
            result=mutation(fit_result), target=target, capture_skew_ms=20.0,
        )
    assert list(tmp_path.rglob("*")) == []

def test_append_rejects_duplicate_pose_without_second_image(tmp_path, fit_result, target):
    append_fit_observation(tmp_path, sample_id="fit-01", lumos_jpeg=b"a", d435_jpeg=b"b",
                           result=fit_result, target=target, capture_skew_ms=20.0)
    with pytest.raises(CalibrationCaptureError, match="distinct"):
        append_fit_observation(tmp_path, sample_id="fit-02", lumos_jpeg=b"c", d435_jpeg=b"d",
                               result=fit_result, target=target, capture_skew_ms=20.0)
    assert not (tmp_path / "images/lumos/fit-02.jpg").exists()
```

- [ ] **Step 2: Run tests and confirm missing-module failure**

Run: `.venv/bin/pytest -q tests/vision_deployment/test_dual_camera_refit_capture.py`

Expected: collection fails because the capture module is absent.

- [ ] **Step 3: Implement fit observation evaluation**

Factor target matching and D435 PnP into focused private helpers. `evaluate_fit_pair` must store common point IDs, board object points, both pixel arrays, `T_d435_from_board`, and D435 RMSE; it may compute old-seed Lumos P95 as diagnostic data but must never use it in `passes_fit_gate`.

```python
@dataclass(frozen=True)
class DualCameraFitObservation:
    point_ids: tuple[int, ...]
    object_points_m: np.ndarray
    d435_image_points_px: np.ndarray
    lumos_image_points_px: np.ndarray
    t_d435_from_board: np.ndarray
    d435_reprojection_rmse_px: float
    old_candidate_lumos_p95_px: float | None

    @property
    def common_points(self) -> int:
        return len(self.point_ids)
```

- [ ] **Step 4: Implement atomic content-addressed fit persistence**

The manifest name is `dual-camera-refit-fit.json`, has `purpose: "fit"`, fixed target and seed IDs, `motion_or_robot_access: false`, at most 12 observations, and a verified `content_id`. Check sample ID, skew, point count, D435 RMSE, uniqueness, pose separation, target/seed continuity, and destination collisions before calling `_atomic_write` for either image.

- [ ] **Step 5: Test successful append, reload, integrity, skew, maximum, and distinctness**

Add assertions that `fit_summary` reports `phase="fit_collect"` for 11 observations and `phase="fit_ready"` for 12; manifest tampering and a `101 ms` skew must be rejected.

- [ ] **Step 6: Run focused tests and lint**

Run: `.venv/bin/pytest -q tests/vision_deployment/test_dual_camera_refit_capture.py tests/vision_deployment/test_legacy_dual_camera_validation.py`

Run: `.venv/bin/ruff check web-control/server/vision_models/dual_camera_refit_capture.py tests/vision_deployment/test_dual_camera_refit_capture.py`

Expected: all tests pass and Ruff is clean.

- [ ] **Step 7: Commit**

```bash
git add web-control/server/vision_models/dual_camera_refit_capture.py tests/vision_deployment/test_dual_camera_refit_capture.py
git commit -m "feat(vision): capture dual-camera refit evidence"
```

### Task 3: Robust Fixed-Intrinsics Solver

**Files:**
- Create: `web-control/server/vision_models/dual_camera_refit_solver.py`
- Test: `tests/vision_deployment/test_dual_camera_refit_solver.py`

**Interfaces:**
- Consumes: verified fit manifest observations and `DualCameraCandidate` seed.
- Produces: `DualCameraRefitResult`, `solve_dual_camera_refit(manifest, seed) -> DualCameraRefitResult`, and `write_refit_candidate(path, result, seed, fit_dataset_id) -> Path`.

- [ ] **Step 1: Write a deterministic synthetic recovery test**

Generate 12 board poses spanning depth, horizontal/vertical translation, roll, pitch, and yaw. Project points through the fixed D435 and Lumos models using a known relative transform, add seeded `0.15 px` Gaussian noise plus one `6 px` outlier in every fourth pose, and assert:

```python
result = solve_dual_camera_refit(manifest, seed)
translation_error = np.linalg.norm(result.transform[:3, 3] - truth[:3, 3])
rotation_error_deg = Rotation.from_matrix(
    result.transform[:3, :3].T @ truth[:3, :3]
).magnitude() * 180.0 / np.pi
assert translation_error <= 0.001
assert rotation_error_deg <= 0.2
assert result.p95_px <= 2.0
assert result.samples == 12
```

- [ ] **Step 2: Run the synthetic test and confirm missing-module failure**

Run: `.venv/bin/pytest -q tests/vision_deployment/test_dual_camera_refit_solver.py::test_recovers_known_transform_with_noise_and_outliers`

Expected: collection fails because the solver module is absent.

- [ ] **Step 3: Implement transform parameterization and residuals**

Use a six-vector `[rotvec_x, rotvec_y, rotvec_z, tx, ty, tz]`; compose board-to-D435 points from each fixed `T_d435_from_board`, transform to Lumos, and call only `SeucmCamera.project`. Invalid projections return a finite large penalty for scoring, and the final result is rejected if any validity flag is false.

```python
def _matrix_from_parameters(parameters: np.ndarray) -> np.ndarray:
    transform = np.eye(4, dtype=float)
    transform[:3, :3] = Rotation.from_rotvec(parameters[:3]).as_matrix()
    transform[:3, 3] = parameters[3:]
    return transform
```

- [ ] **Step 4: Implement per-pose initialization and joint solve**

For every pose, solve six parameters from the old seed, aggregate translations with component-wise median and rotations with `Rotation.mean()`, then jointly solve one transform over all Lumos residuals with the exact global solver settings. Record `nfev`, convergence message category, point count, median, P95, baseline, and rotation degrees.

- [ ] **Step 5: Enforce solver and candidate gates**

Reject fewer than 12 fit observations, wrong purpose, manifest integrity mismatch, non-convergence, invalid EUCM domain, baseline outside `[0.02, 0.30]`, rotation above 45°, or P95 above 3 px. Write schema-v2 output atomically only after all gates pass; the payload includes source fit content ID, solver settings, camera source IDs, metrics, `candidate_only`, and `executable:false`.

- [ ] **Step 6: Add negative tests**

Test insufficient poses, fit/validation purpose confusion, impossible pixels, an out-of-range baseline, a tampered manifest, and verify no candidate file exists after each rejection.

- [ ] **Step 7: Run focused tests and lint**

Run: `.venv/bin/pytest -q tests/vision_deployment/test_dual_camera_refit_solver.py tests/vision_deployment/test_dual_camera_candidate.py`

Run: `.venv/bin/ruff check web-control/server/vision_models/dual_camera_refit_solver.py tests/vision_deployment/test_dual_camera_refit_solver.py`

Expected: all tests pass and Ruff is clean.

- [ ] **Step 8: Commit**

```bash
git add web-control/server/vision_models/dual_camera_refit_solver.py tests/vision_deployment/test_dual_camera_refit_solver.py
git commit -m "feat(vision): solve robust dual-camera refit"
```

### Task 4: Four-Phase Python Workflow CLI

**Files:**
- Create: `scripts/vision/dual_camera_refit_workflow.py`
- Test: `tests/vision_deployment/test_dual_camera_refit_workflow_cli.py`

**Interfaces:**
- Consumes: the capture/solver functions, current target/seed, loopback frame URLs, separate fit and validation directories, and candidate path.
- Produces: bounded schema-v1 JSON actions `status`, `capture_fit`, `solve`, `capture_validation` with `phase`, `progress`, optional `sample`, optional `fit_metrics`, blockers, and fixed safety flags.

- [ ] **Step 1: Write phase-transition CLI tests with monkeypatched operations**

```python
def test_status_starts_in_fit_collect(run_cli, tmp_path):
    report = run_cli("--action", "status", "--fit-output", str(tmp_path / "fit"),
                     "--validation-output", str(tmp_path / "validation"),
                     "--candidate-output", str(tmp_path / "candidate.json"))
    assert report["phase"] == "fit_collect"
    assert report["progress"] == {"current": 0, "required": 12, "purpose": "fit"}
    assert report["safety"] == {"motion_or_robot_access": False, "executable": False}
```

Cover `fit_collect -> fit_ready -> validation_collect -> relative_validated`, reject solve before 12 fit poses, reject validation before candidate creation, and ensure validation never reads the fit directory.

- [ ] **Step 2: Run tests and confirm script-missing failure**

Run: `.venv/bin/pytest -q tests/vision_deployment/test_dual_camera_refit_workflow_cli.py`

Expected: failures because the workflow script does not exist.

- [ ] **Step 3: Implement fixed phase resolution and public reports**

Resolve phase only from integrity-checked artifacts: no candidate means fit count decides `fit_collect`/`fit_ready`; a candidate means validation count decides `validation_collect`/`relative_validated`. Use stable path-free error codes: `target_not_visible`, `pose_not_distinct`, `insufficient_common_points`, `d435_pixel_gate_failed`, `capture_skew_failed`, `fit_not_ready`, `solve_failed`, `candidate_not_ready`, and `validation_pixel_gate_failed`.

- [ ] **Step 4: Implement concurrent frame capture and fit action**

Reuse `fetch_jpeg`, `detect_target_corners`, and midpoint timing with a `ThreadPoolExecutor(max_workers=2)`. Decode against exact camera dimensions, reject skew over 100 ms, evaluate the fit pair, and append `fit-NN` without using the old Lumos gate.

- [ ] **Step 5: Implement solve and validation actions**

Solve reads only the verified fit manifest and writes only the configured candidate output. Held-out capture invokes the existing evaluator/appender using the generated candidate and `pose-NN` under the validation directory with both pass and distinct gates enabled.

- [ ] **Step 6: Run CLI contract tests and lint**

Run: `.venv/bin/pytest -q tests/vision_deployment/test_dual_camera_refit_workflow_cli.py tests/vision_deployment/test_legacy_dual_camera_validation_cli.py`

Run: `.venv/bin/ruff check scripts/vision/dual_camera_refit_workflow.py tests/vision_deployment/test_dual_camera_refit_workflow_cli.py`

Expected: all tests pass and Ruff is clean.

- [ ] **Step 7: Commit**

```bash
git add scripts/vision/dual_camera_refit_workflow.py tests/vision_deployment/test_dual_camera_refit_workflow_cli.py
git commit -m "feat(vision): orchestrate dual-camera refit workflow"
```

### Task 5: Secure Node Workflow Adapter

**Files:**
- Modify: `web-control/server/calibration-capture-api.js`
- Modify: `web-control/server/config.js`
- Modify: `web-control/server/proxy.js`
- Modify: `web-control/server/test/calibration-capture-api-smoke.js`

**Interfaces:**
- Consumes: bounded JSON emitted by `dual_camera_refit_workflow.py`.
- Produces: `GET /api/calibration/status`, `POST /api/calibration/capture-fit`, `POST /api/calibration/solve`, and `POST /api/calibration/capture`.

- [ ] **Step 1: Rewrite API smoke fixtures for all four phases**

Create reports with `phase`, `{current, required, purpose}`, optional sample and fit metrics. Assert fixed CLI actions, automatic IDs, no request-body path injection, same-origin/loopback enforcement, a shared single-flight lock across capture and solve, 15-second capture timeout, and 60-second solve timeout.

- [ ] **Step 2: Run the Node smoke test and confirm expected failures**

Run: `cd web-control/server && node test/calibration-capture-api-smoke.js`

Expected: FAIL because the current adapter supports only status/capture and old summary fields.

- [ ] **Step 3: Implement strict workflow report sanitizers**

Whitelist phases and action-specific sample IDs (`fit-NN` or `pose-NN`), finite non-negative metrics, bounded blocker strings, progress limits, and safety flags. Reject unknown properties by reconstructing a new public response; never return stderr, paths, command arguments, or worker messages.

- [ ] **Step 4: Implement phase-gated service methods and router paths**

Use one `operationInProgress` flag for every POST. `captureFit()` requires `fit_collect`; `solve()` requires `fit_ready`; `captureValidation()` requires `validation_collect`. Generate IDs from status and pass only fixed CLI arguments. Keep `spawn(shell:false)` and assign `60000 ms` only to solve.

- [ ] **Step 5: Wire fixed configuration**

Set repository-relative defaults for fit data, generated candidate, held-out validation data, target, seed, and loopback raw frame URLs. Preserve environment overrides for test ports but validate every path and URL in the service constructor.

- [ ] **Step 6: Run Node tests**

Run: `cd web-control/server && node test/calibration-capture-api-smoke.js`

Run: `cd web-control/server && npm test`

Expected: API smoke and the complete server suite pass.

- [ ] **Step 7: Commit**

```bash
git add web-control/server/calibration-capture-api.js web-control/server/config.js web-control/server/proxy.js web-control/server/test/calibration-capture-api-smoke.js
git commit -m "feat(web): expose safe dual-camera refit workflow"
```

### Task 6: Phase-Driven Single-Button Page

**Files:**
- Modify: `web-control/web/calibration-capture.html`
- Modify: `web-control/web/calibration-capture.js`
- Modify: `web-control/server/test/calibration-capture-client-smoke.js`
- Modify: `web-control/server/test/calibration-capture-browser-smoke.js`
- Modify: `tests/web/test_web_ui_security.py`
- Modify: `web-control/README.md`

**Interfaces:**
- Consumes: the sanitized four-phase API report.
- Produces: a single-button browser workflow with live raw Lumos/D435 images, progress, per-sample metrics, solver metrics, blockers, and no motion controls.

- [ ] **Step 1: Add client tests for button action and copy by phase**

Assert:

```javascript
client.render(report({ phase: 'fit_collect', current: 3, required: 12 }));
assert.equal(elements.captureButton.textContent, '采集拟合姿态');
await client.runPrimaryAction();
assert.equal(requests.at(-1).url, '/api/calibration/capture-fit');

client.render(report({ phase: 'fit_ready', current: 12, required: 12 }));
assert.equal(elements.captureButton.textContent, '求解新外参');
await client.runPrimaryAction();
assert.equal(requests.at(-1).url, '/api/calibration/solve');
```

Add equivalent assertions for `validation_collect` and disabled `relative_validated`.

- [ ] **Step 2: Run client/browser tests and confirm failures**

Run: `cd web-control/server && node test/calibration-capture-client-smoke.js && node test/calibration-capture-browser-smoke.js`

Expected: FAIL because the old client has one capture action and legacy copy.

- [ ] **Step 3: Update HTML without adding control authority**

Keep both `<img data-stream>` elements. Add stage label, separate fit/validation legend, baseline, rotation, fit median/P95, and retained blocker panel. Keep exactly one enabled primary button and no input for paths, URLs, transforms, CAN, robot, motion, gripper, or reset.

- [ ] **Step 4: Implement phase rendering and primary action**

Map phases to endpoint/button/status copy, render the current purpose progress grid, show sample metrics after capture and fit metrics after solve, and retain `busy`/visibility polling semantics. The final page must state that relative extrinsics passing does not authorize grasping.

- [ ] **Step 5: Update browser and security assertions**

Assert live stream requests appear, all four Chinese stage labels render, only one primary button exists, no robot endpoint is referenced, no inline script is present, and cross-origin input cannot reach the client API.

- [ ] **Step 6: Document operator sequence**

In `web-control/README.md`, document 12 varied fit poses, automatic solve, then 10 new validation poses. Explicitly say not to reuse fit poses for validation and that the process never moves the arm.

- [ ] **Step 7: Run focused tests**

Run: `cd web-control/server && node test/calibration-capture-client-smoke.js && node test/calibration-capture-browser-smoke.js`

Run: `.venv/bin/pytest -q tests/web/test_web_ui_security.py`

Expected: all tests pass.

- [ ] **Step 8: Commit**

```bash
git add web-control/web/calibration-capture.html web-control/web/calibration-capture.js web-control/server/test/calibration-capture-client-smoke.js web-control/server/test/calibration-capture-browser-smoke.js tests/web/test_web_ui_security.py web-control/README.md
git commit -m "feat(web): guide dual-camera refit capture"
```

### Task 7: Full Verification and Safe Runtime Handoff

**Files:**
- Modify only if verification exposes a defect: files already listed above.

**Interfaces:**
- Consumes: completed repository implementation and the simulated/read-only port-3100 process.
- Produces: fresh test evidence, browser screenshot, safe real-camera status, and a page ready for the user's physical board movements.

- [ ] **Step 1: Run all Python vision tests and Ruff**

Run: `.venv/bin/pytest -q tests/vision_deployment tests/web/test_web_ui_security.py`

Run: `.venv/bin/ruff check web-control/server/vision_models scripts/vision tests/vision_deployment`

Expected: all tests pass and Ruff is clean.

- [ ] **Step 2: Run the complete Node suite on a non-production test port**

Run: `cd web-control/server && VOICE_TEST_PORT=43652 npm test`

Expected: every Node and browser smoke test passes.

- [ ] **Step 3: Restart only the port-3100 simulated/read-only service**

Stop the existing port-3100 development session gracefully, then launch with:

```bash
WEB_PORT=3100 CAMERA_ENABLED=1 VISION_ONLINE_ENABLED=1 STARTOUCH_SIMULATE=1 STARTOUCH_REQUIRE_CAN_RX=0 STARTOUCH_GRIPPER=0 node proxy.js
```

Do not stop, signal, or reconfigure the real controller on port 3000 or the Lumos frame server on port 3001.

- [ ] **Step 4: Verify safe runtime status and browser rendering**

Request `http://127.0.0.1:3100/api/calibration/status` and assert `phase=fit_collect`, `motion_or_robot_access=false`, and `executable=false`. Open `http://127.0.0.1:3100/calibration-capture.html`, confirm both live frames are visible, the button says “采集拟合姿态”, and capture a screenshot.

- [ ] **Step 5: Verify rejection does not advance progress**

With no board or a partial board visible, call `POST /api/calibration/capture-fit`; confirm a bounded 422 code and unchanged fit count. Do not call solve or any robot endpoint.

- [ ] **Step 6: Review diff and commit verification fixes if needed**

Run: `git status --short && git diff --check && git log -8 --oneline`

Expected: only intended files are changed; unrelated untracked research artifacts remain untouched; `git diff --check` prints nothing.

- [ ] **Step 7: Physical collection handoff**

Tell the user the page is ready and ask only for the physical action required at each accepted pose: move/tilt the same board inside both live views, hold still, and press the single button. After 12 fit captures, the same button solves; then collect 10 new poses for held-out validation. Report fit and validation metrics separately and never describe the candidate as grasp-ready.
