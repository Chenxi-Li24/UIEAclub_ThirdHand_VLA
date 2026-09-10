# Hand-Eye and Table Calibration Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace invalid legacy hand-eye/table artifacts with independently validated,
content-addressed camera and table evidence while preserving the completed relative
extrinsic.

**Architecture:** Pure Python modules own candidate adaptation, table fitting, and evidence
construction. Existing typed ChArUco capture and hand-eye solve modules remain unchanged
where possible. A Python workflow CLI is wrapped by an allowlisted Node API and a separate
read-only calibration page; no calibration component can command the robot.

**Tech Stack:** Python 3.11, NumPy, SciPy/OpenCV, pytest, Node.js/Express, browser smoke tests.

## Global Constraints

- Use `data/calibration/dual-camera-refit/candidate.json` and its independent validation;
  never authorize from `/home/nieqingcao/calibration/*.json`.
- Hand-eye: 15 poses, at least 24 ChArUco points, per-frame RMSE <=1.5 px, translation span
  >=30 mm, rotation span >=15 degrees, held-out position P95 <=10 mm, held-out reprojection
  RMSE <=1 px.
- Table: 8 samples with board flat, fit RMSE <=5 mm, held-out point-to-plane P95 <=8 mm,
  normal within 15 degrees of base +Z.
- Every runtime source and output is content-addressed and atomically written.
- Calibration capture is read-only and sends only `{cmd:"status"}` to the existing robot
  service. It never imports Startouch/CAN or sends motion/gripper commands.
- Real observation motion and autonomous grasp remain disabled by this plan.

---

### Task 1: Candidate-backed hand-eye capture input

**Files:**
- Create: `web-control/server/vision_models/calibration_completion.py`
- Modify: `scripts/vision/capture_handeye_sample.py`
- Test: `tests/vision_deployment/test_calibration_completion.py`
- Test: `tests/vision_deployment/test_handeye_capture_contract.py`

**Interfaces:**
- `load_handeye_capture_input(candidate_path) -> HandEyeCaptureInput`
- `HandEyeCaptureInput` exposes `d435`, `distortion_coeffs`, and `source_id` only.

- [ ] Write tests that accept the real schema-v2 shape and reject a legacy seed, tampered
  candidate ID, nonzero/unknown distortion, and executable candidates.
- [ ] Run the focused tests and confirm failure because the adapter is missing.
- [ ] Implement the immutable adapter using `load_dual_camera_candidate`; add
  `--candidate` to the capture CLI without weakening loopback/read-only constraints.
- [ ] Run hand-eye capture and completion tests; commit the task.

### Task 2: Table sample contract and held-out plane solver

**Files:**
- Create: `web-control/server/vision_models/table_calibration.py`
- Create: `tests/vision_deployment/test_table_calibration.py`
- Create: `scripts/vision/capture_table_sample.py`
- Create: `scripts/vision/solve_table_dataset.py`

**Interfaces:**
- `TableCalibrationSample(sample_id, split, T_base_from_flange, T_d435_from_board)`
- `append_table_sample(...) -> Path`
- `solve_table_calibration(samples, T_flange_from_d435, calibration_id) -> TableResult`

- [ ] Write tests for correct composition, deterministic 6/2 split, content/image
  provenance, robust plane recovery, normal orientation, and every numeric/diversity gate.
- [ ] Run tests and confirm missing-module failure.
- [ ] Implement atomic typed capture manifest and pure robust plane solver.
- [ ] Add thin CLIs that reuse existing ChArUco detection and stable robot-state readers.
- [ ] Run table and existing calibration tests; commit the task.

### Task 3: Build camera/table foundation evidence

**Files:**
- Modify: `web-control/server/vision_models/calibration_completion.py`
- Create: `scripts/vision/finalize_calibration_foundation.py`
- Modify: `tests/vision_deployment/test_calibration_completion.py`

**Interfaces:**
- `build_foundation_evidence(candidate, relative_validation, handeye, table) -> (camera, table)`
- Outputs match `load_active_view_foundation` exactly.

- [ ] Write tests for transform direction, aggregate/radial-edge metrics, audit payloads,
  content IDs, tamper rejection, blocker propagation, and round-trip loading through
  `load_active_view_foundation`.
- [ ] Run tests and confirm the builder is missing.
- [ ] Implement derivation and strict atomic finalizer with no invented metrics.
- [ ] Run completion/catalog tests; commit the task.

### Task 4: Workflow API and isolated browser page

**Files:**
- Create: `scripts/vision/calibration_completion_workflow.py`
- Create: `web-control/server/calibration-completion-api.js`
- Create: `web-control/server/test/calibration-completion-api-smoke.js`
- Modify: `web-control/server/proxy.js`
- Modify: `web-control/server/config.js`
- Modify: `web-control/server/package.json`
- Create: `web-control/web/calibration-completion.html`
- Create: `web-control/web/calibration-completion.js`
- Create: `web-control/server/test/calibration-completion-browser-smoke.js`
- Modify: `tests/web/test_web_ui_security.py`

**Interfaces:**
- `GET /api/calibration-completion/status`
- `POST /api/calibration-completion/capture-handeye`
- `POST /api/calibration-completion/solve-handeye`
- `POST /api/calibration-completion/capture-table`
- `POST /api/calibration-completion/finalize`

- [ ] Write API/CLI/browser tests for the exact state machine, loopback-only access,
  operation lock, bounded output, no shell, no coordinates, and no motion commands.
- [ ] Run tests and confirm missing-route/page failures.
- [ ] Implement the workflow, allowlisted API, and phase-specific page.
- [ ] Run Node, web security, calibration, and browser tests; commit the task.

### Task 5: Live capture and completion gate

**Runtime outputs:**
- `data/calibration/handeye-current/`
- `data/calibration/table-current/`
- `data/calibration/active-view-foundation/camera.json`
- `data/calibration/active-view-foundation/table.json`

- [ ] Verify ports/PIDs, cameras, immutable candidate and robot read-only status.
- [ ] Capture 15 physically distinct hand-eye poses with the board fixed; solve and require
  all held-out gates.
- [ ] Place the board flat and capture 8 distinct table locations; solve and require all
  held-out gates.
- [ ] Finalize evidence and run `load_active_view_foundation` plus the complete calibration,
  vision, Node, and web verification suites.
- [ ] Record exact hashes/metrics and leave both active-view and grasp execution disabled.

