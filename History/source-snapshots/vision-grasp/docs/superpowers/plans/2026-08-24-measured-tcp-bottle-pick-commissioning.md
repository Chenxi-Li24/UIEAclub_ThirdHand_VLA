# Measured-TCP Bottle Pick Commissioning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a supervised, low-speed, real-robot workflow that starts at measured Home, lets the user select an upright opaque bottle by stable ID, grasps and places it upright at one commissioned fixed point, then returns to measured Home and confirms stop/depower.

**Architecture:** Preserve the existing Vision/Action split and Startouch hardware adapter, but replace the unsafe base-frame grasp offset with an approved `T_flange_tcp` artifact. Add independently runnable calibration, physical-validation, tool-envelope, and staged-commissioning modules. Production readiness comes only from a content-bound Level-5 activation manifest plus explicit per-process robot authorization; no single YAML Boolean can bypass the evidence chain.

**Tech Stack:** Python 3.10+, NumPy 1.26.4, OpenCV 4.11.0 `cv2.aruco`, PyYAML 6.0.2, Node.js 24, `yaml` 2.9.0, built-in `node:test`, pytest 8.4.2, Lumos/XVisio native SDK, existing Startouch Python SDK bridge.

**Spec:** [`docs/superpowers/specs/2026-08-24-measured-tcp-bottle-pick-commissioning-design.md`](../specs/2026-08-24-measured-tcp-bottle-pick-commissioning-design.md)

## Global Constraints

- Work only inside `PinZiZhuaQuSkill`; the old hand-eye and TH-Fanxy trees are read-only migration sources, never runtime dependencies.
- Do not connect the camera or robot from unit/integration tests. Live entrypoints require both an explicit CLI flag and the existing exact authorization environment value.
- Every pure core module must have a direct script/VS Code debugger that accepts a fixture and prints structured blockers, measurements, and output paths.
- Keep Vision Python-only and Action orchestration JavaScript-only except for pure calibration solvers. Exchange immutable JSON/JSONL artifacts across the boundary.
- Use SI units in persisted transforms (`m`, `rad`) and homogeneous `4 x 4` matrices. Every pose carries `pose_frame`, transform semantics, camera/tool identities, and content IDs.
- Never execute or approve `grasp.flange_offset_base_m`, the historical `[0.0475, 0.0100, 0]` base-frame offset, or any report derived from it.
- During commissioning, `robot.speed_scale` stays `0.05`; a successful Level 5 does not raise it.
- Any stage after possible gripper contact fails to `manual_recovery`; it must not automatically open or move Home while a bottle may be held.
- Use `apply_patch` for text edits, preserve unrelated dirty-worktree changes, stage only task-owned files, and run the narrow test before each broader regression.
- Each task below ends in one focused commit. Do not combine generated hardware evidence with unrelated source changes.

## Reuse and license map

| Reused source | How it is used | Runtime dependency | License handling |
|---|---|---:|---|
| OpenCV ChArUco/PnP | Official `CharucoBoard`, `CharucoDetector.detectBoard`, sub-pixel corners, `solvePnP`, reprojection | Existing dependency | Record Apache-2.0 and official links |
| Local `ThirdHand-XVisio-handeye-web` | Exact CC200 profile, 960×960 SDK rectification, LUT identity, capture contract, HORAUD evidence | No | Focused port with MIT provenance in `THIRD_PARTY_NOTICES.md` |
| ROS-Industrial calibration | Observation/evidence/residual serialization pattern | No | Record Apache-2.0 reference |
| RoboDK TCP calibration | Multi-orientation fixed-point/pivot equation | No | Method reference only |
| MoveIt Task Constructor | Serial, gated stage architecture | No | Architecture reference only |
| Local TH-Fanxy | Raise-first, clearance translation, constrained final approach | No | Focused behavior port; retain local provenance |
| Existing Startouch SDK bridge | `move_l`, `move_joint`/preset, gripper, state proof, software stop | Yes, already present | No second robot protocol |

## Target interface map

```text
L input: stable bottle ID 1..5
        |
        v
Vision pipeline -> BottleGraspBand + T_base_tcp_desired + immutable evidence
        |
        v
Action runtime -> activation manifest + T_flange_camera + T_flange_tcp
        |
        v
Execution geometry: T_base_flange_command =
                    T_base_tcp_desired @ inverse(T_flange_tcp)
        |
        v
Tool-envelope gate -> staged pick/place controller -> existing Startouch adapter
        |
        v
measured Home -> stop/depower proof -> result returned to L
```

The external command contract remains:

```json
{
  "schema": "thirdhand.va.command.v1",
  "cmd": "start",
  "target_id": 1,
  "request_id": "caller-generated-id"
}
```

The service accepts this command only after automatic Home coordination reports `ready_for_selection`.

---

### Task 1: Import the exact board/camera evidence and build the offline ChArUco module

**Files:**

- Create: `configs/calibration/charuco-cc200-15-11.25.yaml`
- Create: `configs/calibration/lumos-ego-std-rectified.yaml`
- Create: `src/thirdhand_va/vision/calibration/__init__.py`
- Create: `src/thirdhand_va/vision/calibration/fiducial.py`
- Create: `scripts/vision/debug_fiducial.py`
- Create: `tests/vision/calibration/test_fiducial.py`
- Create: `tests/fixtures/calibration/cc200-15-11.25/manifest.json`
- Import: `tests/fixtures/calibration/cc200-15-11.25/sample_0001.{jpg,json}`
- Import: `tests/fixtures/calibration/cc200-15-11.25/sample_0008.{jpg,json}`
- Import: `tests/fixtures/calibration/cc200-15-11.25/sample_0024.{jpg,json}`
- Create: `THIRD_PARTY_NOTICES.md`
- Modify: `tests/common/test_repository_layout.py`

- [ ] **Step 1: Write the failing board/profile and replay tests**

Define the public Python contract in the test before implementation:

```python
from thirdhand_va.vision.calibration.fiducial import (
    FiducialFrame,
    detect_board,
    load_charuco_profile,
    load_rectified_camera_profile,
)

board = load_charuco_profile("configs/calibration/charuco-cc200-15-11.25.yaml")
camera = load_rectified_camera_profile(
    "configs/calibration/lumos-ego-std-rectified.yaml"
)
observation = detect_board(
    FiducialFrame.from_replay(
        image_path=fixture / "sample_0001.jpg",
        metadata_path=fixture / "sample_0001.json",
    ),
    board=board,
    camera=camera,
    require_depth=False,
)
assert board.dictionary == "DICT_5X5_100"
assert board.squares_x == 12 and board.squares_y == 9
assert board.square_length_m == 0.015
assert board.marker_length_m == 0.01125
assert observation.accepted
assert observation.charuco_corner_count >= 30
assert observation.reprojection_rmse_px <= 1.0
```

Add rejection tests for wrong serial, wrong LUT hash, raw-fisheye role, wrong resolution/K, duplicate/out-of-range IDs, clipped/low-coverage board, fewer than 20 markers, fewer than 30 ChArUco corners, and `require_depth=True` with no depth evidence.

- [ ] **Step 2: Run the narrow test and confirm it fails for the missing module**

Run:

```bash
PYTHONPATH=src /home/nieqingcao/miniconda3/envs/thirdhand-groundedsam2/bin/python \
  -m pytest tests/vision/calibration/test_fiducial.py -q
```

Expected: collection fails with `ModuleNotFoundError` for `thirdhand_va.vision.calibration`.

- [ ] **Step 3: Import only immutable representative evidence with provenance**

Copy `rgb_rectified.jpg` and normalized expected fields from samples `0001`, `0008`, and `0024` in the accepted 2026-08-17 dataset. The fixture manifest must record the original absolute source for audit only, each imported SHA-256, original OpenCV version, board ID, camera serial, camera model, rectification LUT SHA-256, and `T_camera_board`; tests/runtime must use only project-relative paths.

Add `THIRD_PARTY_NOTICES.md` entries for the MIT local port, OpenCV Apache-2.0, ROS-Industrial Apache-2.0, and the method-only RoboDK/MoveIt references.

- [ ] **Step 4: Implement strict immutable profiles and the detector**

Use these frozen result types and function names:

```python
@dataclass(frozen=True)
class CharucoProfile:
    profile_id: str
    squares_x: int
    squares_y: int
    square_length_m: float
    marker_length_m: float
    dictionary: str
    marker_ids: tuple[int, ...]

@dataclass(frozen=True)
class RectifiedCameraProfile:
    profile_id: str
    camera_serial: str
    image_role: str
    image_model: str
    width: int
    height: int
    camera_matrix: np.ndarray
    rectification_lut_sha256: str

@dataclass(frozen=True)
class FiducialFrame:
    sequence: int
    monotonic_ns: int
    rgb_bgr: np.ndarray
    depth_m: np.ndarray | None
    camera_serial: str
    image_role: str
    image_model: str
    rectification_lut_sha256: str

@dataclass(frozen=True)
class BoardObservation:
    accepted: bool
    blockers: tuple[str, ...]
    marker_ids: tuple[int, ...]
    charuco_ids: tuple[int, ...]
    charuco_corner_count: int
    coverage_x: float
    coverage_y: float
    reprojection_rmse_px: float
    depth_pnp_disagreement_m: float | None
    T_camera_board: np.ndarray | None
    overlay_bgr: np.ndarray
```

Construct exactly:

```python
dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_5X5_100)
board = cv2.aruco.CharucoBoard((12, 9), 0.015, 0.01125, dictionary)
detector = cv2.aruco.CharucoDetector(board)
charuco_corners, charuco_ids, marker_corners, marker_ids = detector.detectBoard(gray)
```

Refine accepted ChArUco corners with `cv2.cornerSubPix`, solve the pose with the official board object points and `cv2.solvePnP`, compute reprojection RMSE, and return blockers instead of guessing a pose. Do not undistort inside this module; the camera profile must say `color-camera-rectified` and the distortion vector passed to PnP is zero.

- [ ] **Step 5: Add a direct fixture/live debugger without hardware side effects by default**

`scripts/vision/debug_fiducial.py` accepts either `--fixture tests/fixtures/calibration/cc200-15-11.25/sample_0001` or `--live --allow-camera`. It prints one JSON result per frame and writes the overlay under `artifacts/vision/fiducial/`. Without both live flags, it never opens a device.

- [ ] **Step 6: Run tests and debugger**

Run:

```bash
PYTHONPATH=src /home/nieqingcao/miniconda3/envs/thirdhand-groundedsam2/bin/python \
  -m pytest tests/vision/calibration/test_fiducial.py \
  tests/common/test_repository_layout.py -q
PYTHONPATH=src /home/nieqingcao/miniconda3/envs/thirdhand-groundedsam2/bin/python \
  scripts/vision/debug_fiducial.py \
  --fixture tests/fixtures/calibration/cc200-15-11.25/sample_0001
```

Expected: replay passes and the debugger prints marker IDs, corner count, coverage, reprojection RMSE, pose, and `depth_unavailable_for_live_approval` only when depth is intentionally absent.

- [ ] **Step 7: Commit**

```bash
git add THIRD_PARTY_NOTICES.md configs/calibration \
  src/thirdhand_va/vision/calibration scripts/vision/debug_fiducial.py \
  tests/vision/calibration tests/fixtures/calibration/cc200-15-11.25 \
  tests/common/test_repository_layout.py
git commit -m "feat(vision): add exact CC200 fiducial validation"
```

---

### Task 2: Port the exact XVisio rectified RGB-D calibration stream without changing production RGB-D

**Files:**

- Create: `native/vision/xvisio_calibration_stream/CMakeLists.txt`
- Create: `native/vision/xvisio_calibration_stream/xvisio_calibration_stream.cpp`
- Create: `src/thirdhand_va/vision/calibration/stream.py`
- Create: `scripts/vision/build_calibration_native.sh`
- Create: `tests/vision/calibration/test_calibration_stream.py`
- Create: `tests/fixtures/calibration/xvisio-calibration-packet-v1.bin`
- Modify: `.gitignore`

- [ ] **Step 1: Write a failing protocol test**

The test constructs a tiny deterministic packet and verifies one synchronized frame keeps these fields together:

```python
frame = CalibrationStream.read_one(io.BytesIO(packet))
assert frame.sequence == 42
assert frame.rectified_rgb_bgr.shape == (960, 960, 3)
assert frame.rectified_depth_m.shape == (960, 960)
assert frame.camera_serial == "250801DR48FP25002738"
assert frame.image_model == "xv::Seucm-via-CameraModel-project"
assert frame.camera_matrix.tolist() == [
    [420.0, 0.0, 479.5],
    [0.0, 420.0, 479.5],
    [0.0, 0.0, 1.0],
]
assert frame.rectification_lut_sha256 == (
    "sha256:62a74023ff7b456232e5e1a24eebcabb"
    "9016e1c24f11ea8f21c62938099389c6"
)
assert frame.rectified_rgb_bgr.flags.writeable is False
assert frame.rectified_depth_m.flags.writeable is False
```

Add malformed-length, wrong magic/version, oversized payload, JPEG mismatch, non-finite intrinsics, serial mismatch, stale timestamp, and truncated-read cases.

- [ ] **Step 2: Run the narrow test and confirm the import/protocol failure**

```bash
PYTHONPATH=src /home/nieqingcao/miniconda3/envs/thirdhand-groundedsam2/bin/python \
  -m pytest tests/vision/calibration/test_calibration_stream.py -q
```

- [ ] **Step 3: Port the proven native bridge as a separate calibration executable**

Start from the MIT `ThirdHand-XVisio-handeye-web` v2 bridge, retaining its:

- SDK `CameraModel.project` 960×960 rectification LUT;
- `fx=fy=420`, `cx=cy=479.5` contract;
- LUT SHA-256 generation;
- synchronized color/ToF callback boundary;
- nearest-Z depth registration;
- bounded packet sizes and monotonic sequence.

Extend only the calibration packet to include `rectified_depth_m`: transform each valid ToF point into the color-camera frame, project it with the frozen rectified pinhole `K`, and retain the nearest positive color-camera Z per rectified pixel. Keep the existing `native/vision/xvisio_rgbd_stream` and production 640-grid protocol unchanged.

Name the packet magic `XVCALB1\0`, version `1`, and serialize fixed header, camera serial, model string, rectification LUT ID, rectified JPEG, then `float32` rectified depth. Limit live output to `2 Hz` because this executable is commissioning-only.

- [ ] **Step 4: Implement the strict Python reader and immutable frame adapter**

`CalibrationStream(binary, expected_profile).read_one()` must validate every bound field before exposing a `FiducialFrame`; decode JPEG once, mark RGB/depth arrays read-only, and reject a different camera identity or LUT before calling OpenCV.

- [ ] **Step 5: Build and run protocol tests only**

```bash
bash scripts/vision/build_calibration_native.sh
PYTHONPATH=src /home/nieqingcao/miniconda3/envs/thirdhand-groundedsam2/bin/python \
  -m pytest tests/vision/calibration/test_calibration_stream.py \
  tests/vision/calibration/test_fiducial.py -q
```

Do not run the native executable against the live camera in this task.

- [ ] **Step 6: Commit**

```bash
git add native/vision/xvisio_calibration_stream \
  src/thirdhand_va/vision/calibration/stream.py \
  scripts/vision/build_calibration_native.sh \
  tests/vision/calibration/test_calibration_stream.py \
  tests/fixtures/calibration/xvisio-calibration-packet-v1.bin .gitignore
git commit -m "feat(vision): add isolated XVisio calibration stream"
```

---

### Task 3: Validate the existing hand-eye transform physically at high clearance

**Files:**

- Create: `src/thirdhand_va/action/calibration/handeye_physical.py`
- Create: `scripts/action/debug_handeye_physical.py`
- Create: `scripts/action/capture_handeye_physical.js`
- Create: `tests/action/calibration/test_handeye_physical.py`
- Create: `tests/action/calibration/capture_handeye_physical.test.js`
- Create: `tests/fixtures/calibration/handeye-physical-pass.json`
- Create: `tests/fixtures/calibration/handeye-physical-fail.json`
- Modify: `src/thirdhand_va/action/calibration/handeye_approval.js`
- Modify: `tests/action/calibration/approve_handeye.test.js`
- Modify: `scripts/action/approve_handeye_pregrasp.js`

- [ ] **Step 1: Write failing solver tests using a synthetic fixed board**

Test the exact chain:

```python
T_base_board_i = (
    observation.T_base_flange
    @ pending_handeye.T_flange_camera
    @ observation.T_camera_board
)
```

Require at least five accepted observations, at least three distinct rotation axes, matching camera/robot identities, and maximum translation spread `<= 0.010 m`. Assert the pass fixture reports median pose, per-axis spread, maximum translation deviation, rotation spread, reprojection values, and depth/PnP disagreement. Perturb one sample by `0.012 m` and assert rejection.

- [ ] **Step 2: Run the Python test and observe the missing module failure**

```bash
PYTHONPATH=src /home/nieqingcao/miniconda3/envs/thirdhand-groundedsam2/bin/python \
  -m pytest tests/action/calibration/test_handeye_physical.py -q
```

- [ ] **Step 3: Implement the pure physical validator and immutable report**

Expose:

```python
def validate_handeye_physical(
    observations: Sequence[HandEyePhysicalObservation],
    T_flange_camera: np.ndarray,
    *,
    max_base_board_spread_m: float = 0.010,
) -> HandEyePhysicalReport:
    """Transform one fixed board into base for every sample and fail closed."""
```

Write `thirdhand-handeye-physical-validation-v2`; it binds the pending hand-eye content ID, board profile ID, camera profile/LUT ID, source observation IDs, robot identity, thresholds, every residual, and pass/fail blockers.

- [ ] **Step 4: Write the failing capture/approval tests**

The capture script must accept JSONL `board_observation` events from `debug_fiducial.py --live-jsonl`, pair each with a fresh Startouch `T_base_flange`, and only record when the arm is healthy, stationary, and the identities/timestamps match. It may call the existing `HomeCoordinator` on `finish`, but must never send `move_l`, `gripper`, or an arbitrary joint target.

Approval tests must reject:

- the old three-stage hover report;
- a report containing any base-frame grasp offset;
- any report with an `over_target`, `hover`, descent, rotation change, or gripper command;
- any physical report not bound to the pending calibration bytes;
- a report with spread over `10 mm`.

- [ ] **Step 5: Implement capture and make approval consume only the new report schema**

`scripts/action/capture_handeye_physical.js` commands are `start`, `capture`, `finish`, and `abort`. `finish` invokes the Python solver offline and, on pass, writes a new `configs/calibration/lumos-handeye.approved.json`; it never mutates `lumos-handeye.pending.json`.

The approved file retains the historical HORAUD numerical metrics and sets physical approval only from the new content-bound report.

- [ ] **Step 6: Run module tests and replay debugger**

```bash
PYTHONPATH=src /home/nieqingcao/miniconda3/envs/thirdhand-groundedsam2/bin/python \
  -m pytest tests/action/calibration/test_handeye_physical.py -q
/usr/local/lib/nodejs/node-v24.18.0-linux-x64/bin/node --test \
  tests/action/calibration/capture_handeye_physical.test.js \
  tests/action/calibration/approve_handeye.test.js
PYTHONPATH=src /home/nieqingcao/miniconda3/envs/thirdhand-groundedsam2/bin/python \
  scripts/action/debug_handeye_physical.py \
  tests/fixtures/calibration/handeye-physical-pass.json
```

- [ ] **Step 7: Commit**

```bash
git add src/thirdhand_va/action/calibration/handeye_physical.py \
  src/thirdhand_va/action/calibration/handeye_approval.js \
  scripts/action/debug_handeye_physical.py \
  scripts/action/capture_handeye_physical.js \
  scripts/action/approve_handeye_pregrasp.js \
  tests/action/calibration tests/fixtures/calibration/handeye-physical-*.json
git commit -m "feat(calibration): add physical hand-eye approval"
```

---

### Task 4: Measure and approve the operational gripper TCP

**Files:**

- Create: `src/thirdhand_va/action/calibration/tool_tcp.py`
- Create: `scripts/action/debug_tool_tcp.py`
- Create: `scripts/action/commission_tool_tcp.js`
- Create: `tests/action/calibration/test_tool_tcp.py`
- Create: `tests/action/calibration/commission_tool_tcp.test.js`
- Create: `tests/fixtures/calibration/tool-tcp-pass.json`
- Create: `tests/fixtures/calibration/tool-tcp-fail.json`
- Generate during commissioning: `configs/calibration/gripper-tcp.pending.json`
- Generate after verification: `configs/calibration/gripper-tcp.approved.json`

- [ ] **Step 1: Write failing pivot-solver tests**

Use at least eight synthetic `T_base_flange` poses and the standard equation:

```text
R_base_flange_i * t_flange_probe - p_base_fixed = -p_base_flange_i
```

Assert recovery of the known `t_flange_probe`, full-rank design matrix, orientation diversity, RMS/max residuals, and fixed point. Reject fewer than eight samples, rank deficiency, insufficient angular diversity, repeated poses, non-rigid transforms, residual over `5 mm`, and missing/invalid caliper distance.

- [ ] **Step 2: Run the narrow test and confirm failure**

```bash
PYTHONPATH=src /home/nieqingcao/miniconda3/envs/thirdhand-groundedsam2/bin/python \
  -m pytest tests/action/calibration/test_tool_tcp.py -q
```

- [ ] **Step 3: Implement the pure TCP solver**

Expose:

```python
def solve_tool_tcp(
    flange_poses: Sequence[np.ndarray],
    *,
    probe_tip_to_grasp_plane_m: float,
    tool_axis_flange: np.ndarray,
    R_flange_tcp: np.ndarray,
) -> ToolTcpReport:
    """Solve probe-tip translation, then shift to the operational grasp center."""
```

The report schema is `thirdhand-tool-tcp-v1` and contains `T_flange_tcp.matrix_4x4`, probe translation, caliper shift, tool-axis convention, pivot point, sample IDs, singular values, RMS/max residual, verification error, and measured conservative gripper envelope. It never contains a base-frame offset.

- [ ] **Step 4: Write capture-script tests before hardware code**

`commission_tool_tcp.js` records the current fresh measured flange pose only after the operator has manually touched the protected point. It must not issue any autonomous contact move. Test `start`, `record`, `undo`, `solve`, `abort`, and duplicate/stale pose rejection. `solve` requires Home return and stop/depower proof before writing `configs/calibration/gripper-tcp.pending.json`; it cannot create the approved artifact.

- [ ] **Step 5: Implement capture, replay debugger, and high-clearance verification contract**

After pivot solve and probe removal, the script records two no-contact ChArUco corner-38 verification observations: production orientation and one separately approved high-clearance orientation. Both calculate:

```text
T_base_tcp_measured = T_base_flange @ T_flange_tcp
error_m = norm(t_base_tcp_measured - t_base_corner_38_desired)
```

No descent is allowed; both observations stay at the configured clearance height. Only this verification step may promote the pending artifact to `configs/calibration/gripper-tcp.approved.json`. Approval requires pivot RMS `<= 5 mm`, each verification error `<= 10 mm`, and measured envelope dimensions.

- [ ] **Step 6: Run module tests**

```bash
PYTHONPATH=src /home/nieqingcao/miniconda3/envs/thirdhand-groundedsam2/bin/python \
  -m pytest tests/action/calibration/test_tool_tcp.py -q
/usr/local/lib/nodejs/node-v24.18.0-linux-x64/bin/node --test \
  tests/action/calibration/commission_tool_tcp.test.js
PYTHONPATH=src /home/nieqingcao/miniconda3/envs/thirdhand-groundedsam2/bin/python \
  scripts/action/debug_tool_tcp.py tests/fixtures/calibration/tool-tcp-pass.json
```

- [ ] **Step 7: Commit**

```bash
git add src/thirdhand_va/action/calibration/tool_tcp.py \
  scripts/action/debug_tool_tcp.py scripts/action/commission_tool_tcp.js \
  tests/action/calibration/test_tool_tcp.py \
  tests/action/calibration/commission_tool_tcp.test.js \
  tests/fixtures/calibration/tool-tcp-*.json
git commit -m "feat(calibration): add measured operational TCP workflow"
```

---

### Task 5: Add a small rigid-transform core and eliminate base-offset execution geometry

**Files:**

- Create: `src/thirdhand_va/action/geometry/rigid_transform.js`
- Create: `tests/action/geometry/rigid_transform.test.js`
- Modify: `src/thirdhand_va/action/grasp/execution_plan.js`
- Modify: `src/thirdhand_va/action/evidence/action_evidence.js`
- Modify: `tests/action/grasp/execution_plan.test.js`
- Modify: `tests/action/evidence/action_evidence.test.js`
- Create: `tests/fixtures/action/legacy-base-offset-collision.json`

- [ ] **Step 1: Write failing transform-contract tests**

The module API is:

```javascript
const {
  assertRigidTransform,
  invertRigidTransform,
  multiplyTransforms,
  transformPoint,
  flangeCommandForTcp,
} = require('../../../src/thirdhand_va/action/geometry/rigid_transform');

const command = flangeCommandForTcp(TBaseTcpDesired, TFlangeTcp);
assert.deepEqual(
  command,
  multiplyTransforms(TBaseTcpDesired, invertRigidTransform(TFlangeTcp)),
);
```

Test identity, rotation-sensitive TCP translation, inverse round trip, determinant/orthonormal rejection, wrong bottom row, alias protection/deep freeze, and millimetre/metre mistakes. Assert that a 90-degree flange rotation rotates the tool translation; this is the regression the old base-frame constant failed.

- [ ] **Step 2: Add the historical incident as a permanently rejected fixture**

Record that the old report commanded `detected + [0.0475, 0.0100, 0]`, a `0.0485412 m` displacement, changed Euler by roughly `0.77737 rad`, and descended about `0.100565 m` below clearance. Tests must assert this fixture cannot parse as a v3 plan or approval artifact.

- [ ] **Step 3: Run tests and observe failures**

```bash
/usr/local/lib/nodejs/node-v24.18.0-linux-x64/bin/node --test \
  tests/action/geometry/rigid_transform.test.js \
  tests/action/grasp/execution_plan.test.js \
  tests/action/evidence/action_evidence.test.js
```

- [ ] **Step 4: Implement the transform core and v3 execution geometry**

`buildExecutionPlan` consumes `target.T_base_tcp_desired`, approved `T_flange_tcp`, and approved path geometry. It emits `thirdhand-execution-plan-v3` waypoints as full transforms, never `detectedGraspM`, `commandedFlangeGraspM`, `flangeOffsetBaseM`, or `graspOffsetBaseM`.

For upright placement, persist `grasp_center_height_above_table_m` in the target evidence and compute the destination TCP height from the commissioned placement table plane:

```text
place_tcp_z_base_m = place_table_z_base_m + grasp_center_height_above_table_m
```

Keep the approved upright TCP rotation through lift, transfer, lower, release, and retreat. Never reuse the source grasp Z as an unexplained placement constant.

The action evidence binds:

```javascript
{
  pose_frame: 'base',
  translation_unit: 'm',
  rotation_convention: 'right_handed_homogeneous_matrix',
  T_base_tcp_desired,
  T_flange_tcp_id,
  handeye_id,
  camera_profile_id,
  vision_config_id,
  path_validation_id,
}
```

- [ ] **Step 5: Run the focused tests**

```bash
/usr/local/lib/nodejs/node-v24.18.0-linux-x64/bin/node --test \
  tests/action/geometry/rigid_transform.test.js \
  tests/action/grasp/execution_plan.test.js \
  tests/action/evidence/action_evidence.test.js
```

- [ ] **Step 6: Commit**

```bash
git add src/thirdhand_va/action/geometry \
  src/thirdhand_va/action/grasp/execution_plan.js \
  src/thirdhand_va/action/evidence/action_evidence.js \
  tests/action/geometry tests/action/grasp/execution_plan.test.js \
  tests/action/evidence/action_evidence.test.js \
  tests/fixtures/action/legacy-base-offset-collision.json
git commit -m "fix(action): replace base offset with measured TCP transforms"
```

---

### Task 6: Estimate a stable table-relative bottle grasp band

**Files:**

- Create: `src/thirdhand_va/vision/geometry/bottle_grasp_band.py`
- Create: `scripts/vision/debug_bottle_grasp_band.py`
- Create: `tests/vision/geometry/test_bottle_grasp_band.py`
- Create: `tests/fixtures/geometry/bottle-grasp-band.npz`
- Modify: `src/thirdhand_va/vision/geometry/grasp_pose.py`
- Modify: `src/thirdhand_va/vision/pipeline.py`
- Modify: `tests/vision/geometry/test_grasp_pose.py`
- Modify: `tests/vision/test_pipeline.py`
- Modify: `src/thirdhand_va/vision/visualization/overlay.py`
- Modify: `tests/vision/visualization/test_visualization.py`

- [ ] **Step 1: Write failing pure geometry tests**

Define:

```python
@dataclass(frozen=True)
class BottleGraspBand:
    accepted: bool
    blockers: tuple[str, ...]
    center_base_m: tuple[float, float, float] | None
    lower_z_base_m: float | None
    upper_z_base_m: float | None
    width_m: float | None
    reliable_height_m: float | None
    table_z_base_m: float | None
    frame_count: int

def estimate_bottle_grasp_band(
    target_cloud_camera_m: np.ndarray,
    background_cloud_camera_m: np.ndarray,
    T_base_camera: np.ndarray,
) -> BottleGraspBand:
    """Estimate table plane and a stable 35%-65% body band in base coordinates."""
```

Test upright cylindrical and tapered opaque bottles, width `<= 0.072 m`, at least `0.020 m` continuous band, five-frame stability, and adequate finger/table clearance. Reject clipped masks, sparse depth, tabletop leakage, implausible height, excessive width, occlusion, unstable center/height, and a tilted/non-planar table fit.

- [ ] **Step 2: Run the narrow test and confirm failure**

```bash
PYTHONPATH=src /home/nieqingcao/miniconda3/envs/thirdhand-groundedsam2/bin/python \
  -m pytest tests/vision/geometry/test_bottle_grasp_band.py -q
```

- [ ] **Step 3: Implement robust table/band geometry using existing point-cloud utilities**

Reuse `pointcloud.py` filtering and existing target masks. Fit the table from non-target points with deterministic RANSAC parameters, transform accepted points with the approved `T_base_camera`, bin vertical widths, and choose the longest continuous safe interval within 35%-65% reliable height. Return blockers; never substitute a default bottle height or Z.

- [ ] **Step 4: Integrate into the pipeline contract and overlay**

The pipeline emits a `T_base_tcp_desired` only after five stationary frames agree within configured center/height/width tolerances. The overlay draws the table plane, reliable height, chosen band, width, TCP center, stable ID, and blockers.

- [ ] **Step 5: Add and run the direct debugger**

```bash
PYTHONPATH=src /home/nieqingcao/miniconda3/envs/thirdhand-groundedsam2/bin/python \
  scripts/vision/debug_bottle_grasp_band.py \
  --fixture tests/fixtures/geometry/bottle-grasp-band.npz \
  --output artifacts/vision/debug/bottle-grasp-band.jpg
PYTHONPATH=src /home/nieqingcao/miniconda3/envs/thirdhand-groundedsam2/bin/python \
  -m pytest tests/vision/geometry/test_bottle_grasp_band.py \
  tests/vision/geometry/test_grasp_pose.py tests/vision/test_pipeline.py \
  tests/vision/visualization/test_visualization.py -q
```

- [ ] **Step 6: Commit**

```bash
git add src/thirdhand_va/vision/geometry/bottle_grasp_band.py \
  src/thirdhand_va/vision/geometry/grasp_pose.py \
  src/thirdhand_va/vision/pipeline.py \
  src/thirdhand_va/vision/visualization/overlay.py \
  scripts/vision/debug_bottle_grasp_band.py \
  tests/vision/geometry tests/vision/test_pipeline.py \
  tests/vision/visualization/test_visualization.py \
  tests/fixtures/geometry/bottle-grasp-band.npz
git commit -m "feat(vision): add table-relative bottle grasp band"
```

---

### Task 7: Gate every waypoint and segment with the measured tool envelope

**Files:**

- Create: `src/thirdhand_va/action/safety/tool_envelope.js`
- Create: `tests/action/safety/tool_envelope.test.js`
- Create: `scripts/action/debug_tool_envelope.js`
- Create: `tests/fixtures/action/tool-envelope-scene.json`
- Modify: `src/thirdhand_va/action/safety/execution_gate.js`
- Modify: `tests/action/safety/execution_gate.test.js`

- [ ] **Step 1: Write failing envelope tests**

Expose:

```javascript
const result = evaluateToolEnvelope({
  TBaseFlangeWaypoints,
  TFlangeTcp,
  gripperEnvelope,
  tablePlaneBase,
  workspaceM,
  obstacleAabbsBase,
  targetAabbBase,
  targetContactStages: new Set(['final_approach', 'close']),
});
assert.equal(result.allowed, true);
assert.deepEqual(result.blockers, []);
```

Test flange-safe-but-finger-unsafe table collision, swept transfer collision with another bottle, target contact outside final approach/close, safe vertical target entry, workspace boundary, malformed envelope, non-rigid transforms, and exact boundary conservatism.

- [ ] **Step 2: Run tests and observe the missing module failure**

```bash
/usr/local/lib/nodejs/node-v24.18.0-linux-x64/bin/node --test \
  tests/action/safety/tool_envelope.test.js
```

- [ ] **Step 3: Implement deterministic conservative geometry**

Model the tool as a union of measured flange-frame AABBs/capsules transformed at each waypoint. Use a standard segment-vs-expanded-AABB slab intersection for straight-line swept checks. Sample orientation-only clearance rotations at a fixed bounded angular increment. Inflate all obstacles by the measured envelope uncertainty and `10 mm` commissioning margin.

Permit target-envelope intersection only in the named contact stages and never permit table intersection.

- [ ] **Step 4: Integrate into the execution gate and add the fixture debugger**

`evaluateExecutionGate` receives a completed envelope proof object whose content ID is bound to the plan. A Boolean such as `safetyApproved: true` is insufficient without that object.

Run:

```bash
/usr/local/lib/nodejs/node-v24.18.0-linux-x64/bin/node \
  scripts/action/debug_tool_envelope.js \
  tests/fixtures/action/tool-envelope-scene.json
/usr/local/lib/nodejs/node-v24.18.0-linux-x64/bin/node --test \
  tests/action/safety/tool_envelope.test.js \
  tests/action/safety/execution_gate.test.js
```

- [ ] **Step 5: Commit**

```bash
git add src/thirdhand_va/action/safety/tool_envelope.js \
  src/thirdhand_va/action/safety/execution_gate.js \
  scripts/action/debug_tool_envelope.js \
  tests/action/safety/tool_envelope.test.js \
  tests/action/safety/execution_gate.test.js \
  tests/fixtures/action/tool-envelope-scene.json
git commit -m "feat(action): validate measured tool swept envelope"
```

---

### Task 8: Replace Boolean readiness with strict artifacts and an activation manifest

**Files:**

- Create: `src/thirdhand_va/action/runtime/activation_manifest.js`
- Create: `src/thirdhand_va/action/commissioning/report_chain.js`
- Create: `tests/action/runtime/activation_manifest.test.js`
- Create: `tests/action/commissioning/report_chain.test.js`
- Create: `tests/fixtures/action/activation-manifest-pass.json`
- Modify: `src/thirdhand_va/action/config.js`
- Modify: `configs/action.yaml`
- Modify: `src/thirdhand_va/action/runtime/approved_runtime.js`
- Modify: `tests/action/config.test.js`
- Modify: `tests/action/runtime/approved_runtime.test.js`

- [ ] **Step 1: Write failing v3 config and activation tests**

The base config becomes `thirdhand-action-config-v3`. Remove `execution_enabled`, `grasp.flange_offset_base_m`, `grasp.offset_validated`, and `place.validated`. Add fixed expected paths that need no manual YAML edit:

```yaml
calibration:
  pending_handeye_file: "calibration/lumos-handeye.pending.json"
  approved_handeye_file: "calibration/lumos-handeye.approved.json"
  approved_tool_tcp_file: "calibration/gripper-tcp.approved.json"
commissioning:
  activation_manifest_file: "action/activation-manifest.approved.json"
  required_level: 5
place:
  strategy: "commissioned_fixed_point"
  nominal_fixed_xy_m: [0.282831634, -0.591124195]
  path_validation_file: "action/pick-place-path.approved.json"
  home_preset: "home"
```

The nominal fixed point is non-executable until Level 3 writes the approved path. Level 3 selects the final fixed XY only after proving complete tool-envelope clearance from the table edge, the board, Home corridor, camera cable corridor, and the allowed bottle scene; it may replace the nominal point and binds that exact measured value and local table Z in the manifest.

Tests prove that config loading succeeds in an inactive repository, but readiness reports exact missing blockers. Add rejection tests for an activation manifest with only `approved: true`, wrong artifact hashes, wrong camera/tool IDs, wrong Home joints/ranges, wrong fixed place, speed over `0.05`, changed code/config content IDs, old path schema, and any legacy base-offset field.

- [ ] **Step 2: Run focused tests and confirm schema failures**

```bash
/usr/local/lib/nodejs/node-v24.18.0-linux-x64/bin/node --test \
  tests/action/config.test.js \
  tests/action/runtime/activation_manifest.test.js \
  tests/action/commissioning/report_chain.test.js \
  tests/action/runtime/approved_runtime.test.js
```

- [ ] **Step 3: Implement content-addressed loaders and the report chain**

`loadActionConfig()` parses static limits only. `loadActivationManifest()` separately loads and hashes:

- approved hand-eye artifact;
- approved tool TCP artifact;
- Level-3 path artifact with fixed point, startup Home ranges, and envelope proof;
- Level-4 soft-bottle report;
- Level-5 supervised run report;
- vision/action config bytes and listed source-module bytes.

Expose:

```javascript
function evaluateRuntimeReadiness({ config, manifest, explicitRobotAuthorization }) {
  return Object.freeze({
    allowed: blockers.length === 0,
    blockers: Object.freeze(blockers),
    runtimeEvidence: blockers.length === 0 ? boundEvidence : null,
  });
}
```

Both the manifest and the exact per-process authorization are required. An environment variable alone or a manifest alone must fail.

`report_chain.js` enforces parent content IDs: Level 1 depends on Level 0, Level 2 on Level 1, and so on. A report generated by a lower level cannot approve a higher level.

- [ ] **Step 4: Run tests and the inactive config debugger**

```bash
/usr/local/lib/nodejs/node-v24.18.0-linux-x64/bin/node --test \
  tests/action/config.test.js tests/action/runtime/activation_manifest.test.js \
  tests/action/commissioning/report_chain.test.js \
  tests/action/runtime/approved_runtime.test.js
/usr/local/lib/nodejs/node-v24.18.0-linux-x64/bin/node \
  scripts/action/debug_workflow.js --target-id 1 --simulate
```

Expected: simulation remains runnable; real readiness lists missing commissioning artifacts without opening Startouch.

- [ ] **Step 5: Commit**

```bash
git add src/thirdhand_va/action/runtime \
  src/thirdhand_va/action/commissioning/report_chain.js \
  src/thirdhand_va/action/config.js configs/action.yaml \
  tests/action/runtime tests/action/commissioning \
  tests/action/config.test.js tests/fixtures/action/activation-manifest-pass.json
git commit -m "feat(action): bind execution to commissioning manifest"
```

---

### Task 9: Implement the serial measured-TCP pick/place state machine

**Files:**

- Create: `src/thirdhand_va/action/commissioning/staged_pick_place.js`
- Create: `tests/action/commissioning/staged_pick_place.test.js`
- Modify: `src/thirdhand_va/action/grasp/grasp_controller.js`
- Modify: `src/thirdhand_va/action/grasp/workflow.js`
- Modify: `src/thirdhand_va/action/alignment/visual_align_controller.js`
- Modify: `src/thirdhand_va/action/safety/home_coordinator.js`
- Modify: `tests/action/grasp/grasp_controller.test.js`
- Modify: `tests/action/grasp/workflow.test.js`
- Modify: `tests/action/alignment/visual_align_controller.test.js`
- Modify: `tests/action/safety/home_coordinator.test.js`

- [ ] **Step 1: Write the failing stage-sequence test**

The exact normal sequence is:

```javascript
const NORMAL_STAGES = Object.freeze([
  'measured_home',
  'open',
  'raise_current',
  'translate_clearance',
  'rotate_clearance',
  'pregrasp',
  'final_approach',
  'close',
  'lift',
  'transfer',
  'lower',
  'release',
  'retreat',
  'return_home',
  'confirm_home',
  'confirm_stopped',
]);
```

Assert one correlated command at a time, no phase advance without a matching completion plus fresh measured state, exact envelope proof per stage, vertical-only near-table segments, clearance-only rotation, gripper width contact/release proof, final six-joint Home proof, and stop/depower proof.

- [ ] **Step 2: Add failure-state tests**

Before contact, failures issue a correlated software stop and only use a validated recovery corridor. At/after `close`, timeout, stale state, disconnect, or uncertain contact transitions to `manual_recovery` with `holdingObjectPossible: true`; it sends neither `open` nor `preset home` automatically.

Test that a number cannot be selected before startup Home. Test startup automatic Home only from the Level-3-approved six-joint range. Test each successful run returns to Home before the service becomes ready for another number.

- [ ] **Step 3: Run the focused tests and observe sequence failures**

```bash
/usr/local/lib/nodejs/node-v24.18.0-linux-x64/bin/node --test \
  tests/action/commissioning/staged_pick_place.test.js \
  tests/action/grasp/grasp_controller.test.js \
  tests/action/grasp/workflow.test.js \
  tests/action/alignment/visual_align_controller.test.js \
  tests/action/safety/home_coordinator.test.js
```

- [ ] **Step 4: Implement the staged controller using only the existing robot client**

Map stages to existing adapter commands:

```text
open/close/release      -> gripper
raise/translate/rotate/
pregrasp/approach/lift/
transfer/lower/retreat  -> move_l
return_home             -> preset (adapter maps to move_joint)
failure stop            -> software_stop
```

All `move_l` commands carry the full flange pose computed from desired TCP and `T_flange_tcp`, plus the configured linear speed. `raise_current` preserves current Euler; `translate_clearance` preserves it; `rotate_clearance` changes orientation only at the proven clearance pose. Do not reuse the old base offset or low hover planner.

- [ ] **Step 5: Make workflow own Home readiness and bottle selection timing**

On hardware-authorized service startup, `HomeCoordinator.start()` runs first. The `/api/va/start` endpoint returns `service_not_home_ready` until measured Home passes. After Home, Vision stabilizes numbered bottles and the user can select one. The final completion path returns Home, confirms stopped/depowered, publishes the result, then becomes `ready_for_selection` again.

Keep `VisualAlignController` only for stable target reacquisition/refinement at approved clearance; remove `graspOffsetBaseM` and prohibit it from descending, rotating below clearance, or commanding the gripper.

- [ ] **Step 6: Run the focused suite**

```bash
/usr/local/lib/nodejs/node-v24.18.0-linux-x64/bin/node --test \
  tests/action/commissioning/staged_pick_place.test.js \
  tests/action/grasp/grasp_controller.test.js \
  tests/action/grasp/workflow.test.js \
  tests/action/alignment/visual_align_controller.test.js \
  tests/action/safety/home_coordinator.test.js
```

- [ ] **Step 7: Commit**

```bash
git add src/thirdhand_va/action/commissioning/staged_pick_place.js \
  src/thirdhand_va/action/grasp src/thirdhand_va/action/alignment \
  src/thirdhand_va/action/safety/home_coordinator.js \
  tests/action/commissioning/staged_pick_place.test.js \
  tests/action/grasp tests/action/alignment \
  tests/action/safety/home_coordinator.test.js
git commit -m "feat(action): add staged measured-TCP pick place controller"
```

---

### Task 10: Add independent commissioning levels, real-service entrypoint, and VS Code debugging

**Files:**

- Create: `scripts/action/run_commissioning.js`
- Create: `scripts/action/debug_commissioning.js`
- Create: `tests/action/operator/run_commissioning.test.js`
- Modify: `apps/bottle_pick/run.js`
- Modify: `apps/bottle_pick/web_server.js`
- Modify: `src/thirdhand_va/action/operator/controller.js`
- Modify: `tests/integration/app_run.test.js`
- Modify: `tests/integration/va_service.test.js`
- Modify: `tests/integration/web_server.test.js`
- Modify: `.vscode/launch.json`
- Modify: `.vscode/tasks.json`
- Create: `docs/hardware/measured-tcp-bottle-commissioning.md`
- Modify: `README.md`

- [ ] **Step 1: Write failing commissioning-runner tests**

Test `--level 0..5`, prerequisite report hashes, explicit live flags, exact authorization value, camera-only Level 0 never opening robot, Level 1/2 never issuing autonomous contact motion, Level 3 requiring an empty scene, Level 4 requiring soft single-bottle confirmation, and Level 5 requiring all prior reports.

Test that `node apps/bottle_pick/run.js start 1` remains the formal L-facing command and receives `service_not_home_ready`, `commissioning_incomplete`, `accepted`, or a structured failure; it must not bypass commissioning.

- [ ] **Step 2: Run focused tests and observe failures**

```bash
/usr/local/lib/nodejs/node-v24.18.0-linux-x64/bin/node --test \
  tests/action/operator/run_commissioning.test.js \
  tests/integration/app_run.test.js tests/integration/va_service.test.js \
  tests/integration/web_server.test.js
```

- [ ] **Step 3: Implement one runner with cohesive per-level adapters**

`run_commissioning.js --level N` loads the report chain and delegates to the existing independent modules. It writes one content-addressed report per run under `artifacts/action/commissioning/level-N/`. Only a successful Level 5 writes `configs/action/activation-manifest.approved.json` atomically.

The production service still requires:

```bash
THIRDHAND_ALLOW_ROBOT=I_ACCEPT_SUPERVISED_ROBOT_MOTION \
THIRDHAND_VA_ALLOW_CAMERA=1 \
node apps/bottle_pick/web_server.js --allow-robot
```

The exact CLI/environment combination is process authorization, not calibration approval; missing manifest still blocks it.

- [ ] **Step 4: Add direct VS Code launch entries**

Add these names and keep offline entries free of live environment values:

```text
Vision: Debug CC200 Fiducial (Replay)
Vision: Validate CC200 Fiducial (Live Camera, Level 0)
Action: Debug Hand-Eye Physical (Replay)
Action: Capture Hand-Eye Physical (Real, Level 1)
Action: Debug Tool TCP (Replay)
Action: Capture Tool TCP (Real, Level 2)
Action: Validate Empty Corridors (Real, Level 3)
Action: Validate Soft Bottle (Real, Level 4)
VA: Supervised Complete Pick Place (Real, Level 5)
VA: Debug Complete Workflow (Simulated)
```

Use VS Code input variables for bottle ID and commissioning level where applicable. Every real entry writes the planned stages first and requires the operator to trigger the launch; it does not prompt between normal stages once a level has started.

- [ ] **Step 5: Write operator documentation around observable proofs**

Document, for each level: physical setup, which file to open for breakpoints, F5 profile, terminal command, expected JSON fields/overlay, pass threshold, generated artifact, safe stop command, and manual-recovery behavior. State clearly that Level 2 requires a pointed probe and caliper measurement and Level 3 requires an empty work area.

- [ ] **Step 6: Run integration tests**

```bash
/usr/local/lib/nodejs/node-v24.18.0-linux-x64/bin/node --test \
  tests/action/operator/run_commissioning.test.js \
  tests/integration/app_run.test.js tests/integration/va_service.test.js \
  tests/integration/web_server.test.js
```

- [ ] **Step 7: Commit**

```bash
git add scripts/action/run_commissioning.js \
  scripts/action/debug_commissioning.js apps/bottle_pick \
  src/thirdhand_va/action/operator/controller.js \
  tests/action/operator/run_commissioning.test.js tests/integration \
  .vscode/launch.json .vscode/tasks.json \
  docs/hardware/measured-tcp-bottle-commissioning.md README.md
git commit -m "feat(operator): add staged real-robot commissioning workflow"
```

---

### Task 11: Run complete offline regression and audit every safety contract

**Files:**

- Modify: `tests/common/test_repository_layout.py`
- Modify: `tests/integration/test_debug_entrypoints.py`
- Modify: `tests/action/operator/debug_scripts.test.js`
- Modify: `.vscode/tasks.json`
- Create: `docs/reports/measured-tcp-offline-verification.md`

- [ ] **Step 1: Add repository-wide invariant tests**

Search source/config/approved fixtures and fail if executable code contains:

```text
flange_offset_base_m
graspOffsetBaseM
commandedFlangeGraspM
thirdhand-execution-plan-v2
thirdhand-pick-place-path-validation-v2
```

Allow these strings only in the named rejected historical fixture, migration tests, design/plan documentation, and Git history.

Assert every new core module has a fixture debugger and every real launch has an offline/replay counterpart. Ensure `Action: Full Offline Regression` includes calibration, transform, tool-envelope, commissioning, Home, workflow, and adapter tests.

- [ ] **Step 2: Run module suites separately**

```bash
PYTHONPATH=src /home/nieqingcao/miniconda3/envs/thirdhand-groundedsam2/bin/python \
  -m pytest tests/vision/calibration tests/vision/geometry -q
PYTHONPATH=src /home/nieqingcao/miniconda3/envs/thirdhand-groundedsam2/bin/python \
  -m pytest tests/action/calibration -q
/usr/local/lib/nodejs/node-v24.18.0-linux-x64/bin/node --test \
  tests/action/geometry tests/action/safety tests/action/commissioning
```

- [ ] **Step 3: Run the full offline regression**

```bash
PYTHONPATH=src /home/nieqingcao/miniconda3/envs/thirdhand-groundedsam2/bin/python \
  -m pytest tests/common tests/vision tests/action tests/integration -q
/usr/local/lib/nodejs/node-v24.18.0-linux-x64/bin/npm test
```

Expected: all tests pass; hardware-marked tests skip unless separately authorized; no live camera/robot process starts.

- [ ] **Step 4: Inspect the diff and write the verification report**

Record exact commands, counts, versions, imported provenance/hashes, known unverified hardware gates, and the absence of the legacy offset in executable paths. Do not write “real robot ready” merely because offline tests pass.

- [ ] **Step 5: Commit**

```bash
git add tests/common/test_repository_layout.py \
  tests/integration/test_debug_entrypoints.py \
  tests/action/operator/debug_scripts.test.js .vscode/tasks.json \
  docs/reports/measured-tcp-offline-verification.md
git commit -m "test(va): audit measured-TCP commissioning contracts"
```

---

### Task 12: Execute supervised Levels 0–5 and activate only after measured success

**Files generated by the commissioning tools:**

- `artifacts/vision/fiducial/level-0-report.json`
- `artifacts/action/commissioning/level-1/handeye-physical-report.json`
- `configs/calibration/lumos-handeye.approved.json`
- `artifacts/action/commissioning/level-2/tool-tcp-report.json`
- `configs/calibration/gripper-tcp.approved.json`
- `configs/action/pick-place-path.approved.json`
- `artifacts/action/commissioning/level-4/soft-bottle-report.json`
- `artifacts/action/commissioning/level-5/supervised-run-report.json`
- `configs/action/activation-manifest.approved.json`

- [ ] **Step 1: Run Level 0 camera-only validation**

Place and fix the exact CC200 board, then use the Level-0 VS Code launch. Require 30 stable live frames, IDs only `0..53`, at least 20 markers, at least 30 ChArUco corners, 50% X/Y coverage, reprojection RMSE `<= 1.0 px`, and depth/PnP disagreement `<= 20 mm`.

- [ ] **Step 2: Run Level 1 hand-eye physical validation**

With clear field, working emergency stop, and low-speed authorization, record five to eight safe high-clearance stationary board observations. No gripper command or table descent. Require maximum transformed base-board spread `<= 10 mm`, return Home, and stop/depower proof.

- [ ] **Step 3: Run Level 2 TCP measurement**

Clamp the rigid pointed probe symmetrically, measure probe-tip-to-grasp-plane distance with a caliper, and operator-teach at least eight orientations at one protected fixed point. Remove the probe, perform the two corner-38 high-clearance verifications, require pivot RMS `<= 5 mm` and 3D verification error `<= 10 mm`, return Home, and stop/depower.

- [ ] **Step 4: Run Level 3 empty-gripper corridors**

Remove every bottle. Validate raise, clearance translation, clearance rotation, vertical pick corridor, retreat, fixed-place corridor, and Home. Gripper opens/closes only in free space. Any unexpected motion stops the level and does not approve the path.

- [ ] **Step 5: Run Level 4 soft single-bottle sequence**

Use one empty lightweight soft opaque bottle: approach-without-close; grasp/lift/replace; then complete fixed-point placement. Require no early contact, valid contact width, retained lift, measured release, upright result, Home, and stop/depower.

- [ ] **Step 6: Run Level 5 complete workflow**

Start from Home, enter one visible stable bottle number, and let the normal sequence finish without intermediate prompts. Confirm upright fixed placement, measured Home, and stop/depower. The runner writes the activation manifest only after all automatic and operator-observed checks pass.

- [ ] **Step 7: Re-run production readiness and one L-interface smoke test**

```bash
THIRDHAND_ALLOW_ROBOT=I_ACCEPT_SUPERVISED_ROBOT_MOTION \
THIRDHAND_VA_ALLOW_CAMERA=1 \
node apps/bottle_pick/web_server.js --allow-robot
node apps/bottle_pick/run.js start 1
```

Observe the service Home itself before it accepts the number. After the bottle is placed, require `success`, `released`, `home_verified`, and `stopped_verified` in the final result. Use `node apps/bottle_pick/run.js stop` for operator stop.

- [ ] **Step 8: Commit only reviewed approved calibration/config artifacts**

Do not commit raw camera frames or transient logs. After manual review, stage only the approved immutable calibration, path, activation manifest, and final commissioning report summary. Re-run readiness after the commit to prove its listed content IDs still match.

---

## Completion evidence required before saying “all complete”

- Offline Python and JavaScript regressions pass with recorded command output.
- Exact CC200 live detection passes 30 stable RGB-D frames.
- Hand-eye physical spread is `<= 10 mm`.
- Tool pivot RMS is `<= 5 mm`; two-orientation TCP verification is `<= 10 mm`.
- Empty corridor and tool-envelope Level 3 passes.
- Soft-bottle Level 4 passes without collision.
- One Level-5 numbered bottle is grasped, placed upright, released, and the arm returns to measured Home and confirms stop/depower.
- `configs/action/activation-manifest.approved.json` content IDs match current code/config/calibration/tool/path artifacts.
- The legacy base-offset incident fixture is rejected by config, approval, planning, and execution tests.

Until all hardware items above pass, the accurate status is “implementation/offline verification complete; real-robot commissioning pending,” not “ready for unrestricted bottle picking.”
