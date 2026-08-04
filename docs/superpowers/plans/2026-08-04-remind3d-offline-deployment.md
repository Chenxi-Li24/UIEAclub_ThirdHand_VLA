# REMIND-3D Offline Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy a hardware-isolated REMIND-3D perception path that keeps persistent physical-object identities, estimates mask-filtered robot-base positions, and can be exercised through deterministic replay before any arm integration.

**Architecture:** The existing `vision` package remains a pure NumPy/SciPy safety core. A new persistent identity engine consumes normalized appearance descriptors plus optional robot-base poses, performs class-gated global assignment with ambiguity rejection, and retains bounded work/stable prototype banks. Heavy RTMDet and DINO dependencies live in a separate `vision_models` package and feed immutable contracts into the core; no model module imports or calls robot, CAN, camera, service, or transport code.

**Tech Stack:** Python 3.10/3.11, NumPy, SciPy, pytest; optional PyTorch 2.7 CUDA 12.8, Transformers, MMDetection/MMDeploy for model inference.

## Global Constraints

- Lumos fisheye RGB is the canonical image; D435 supplies registered depth only.
- No shared camera trigger means actionable online observations remain stop-and-look only.
- Identity association must never force a match when the best and second-best candidates are within the configured ambiguity margin.
- Missing depth may preserve a visible identity but may not create an actionable robot-base target.
- A moved object uses 3D only as a short-horizon cue; long-gap re-identification is appearance-led.
- Every appearance vector is finite, non-empty, L2-normalized, immutable, and has one fixed dimension per engine instance.
- Prototype banks, identity count, and inactive lifetime are bounded.
- Model imports and model failures cannot import or invoke CAN, Startouch, robot, gripper, sockets, subprocesses, or web-service modules.
- No task in this plan starts services, opens cameras, imports a robot SDK, or moves the arm.
- DINOv3 remains the accuracy-first gated model; `facebook/dinov2-small` is the ungated deployment fallback.
- RTX 5060 compute capability 12.0 requires a CUDA 12.8-or-newer PyTorch build; model smoke tests must report the actual device and compute capability.
- RTMDet is not declared usable until an actual instance-mask inference succeeds on this workstation.

---

### Task 1: Persistent identity contracts and REMIND-style association

**Files:**
- Create: `web-control/server/vision/identity.py`
- Create: `web-control/server/tests/vision/test_identity.py`
- Modify: `web-control/server/vision/__init__.py`

**Interfaces:**
- Consumes: `PoseEstimate`, a normalized appearance descriptor, label/confidence/visibility, and monotonic update time.
- Produces: `IdentityObservation`, `IdentityAssignment`, `IdentitySnapshot`, `IdentityStatus`, `PersistentIdentityMemory`, and `PersistentIdentityConfig`.

- [ ] **Step 1: Write failing validation and identity-lifecycle tests**

Create literal descriptors such as `[1, 0, 0]`, `[0, 1, 0]`, and hand-built `PoseEstimate` values. Cover these observable behaviors:

```python
def test_identity_reappears_with_same_id_after_inactive_gap():
    memory = PersistentIdentityMemory(config(min_confirmed_hits=1))
    first = memory.update([observation("cup", [1, 0, 0], 0)], 0)
    assert first.assignments[0].identity_id == 1
    assert memory.update([], 2_000_000_000).snapshots[0].status is IdentityStatus.INACTIVE
    returned = memory.update([observation("cup", [0.99, 0.01, 0], 3_000_000_000)], 3_000_000_000)
    assert returned.assignments[0].identity_id == 1

def test_equal_candidates_are_ambiguous_and_do_not_mutate_memory():
    memory = seeded_two_cup_memory()
    before = memory.snapshots(now_ns=100)
    result = memory.update([observation("cup", [1, 1, 0], 200)], 200)
    assert result.assignments[0].identity_id is None
    assert result.assignments[0].status is IdentityStatus.AMBIGUOUS
    assert memory.snapshots(now_ns=200) == before
```

Also test class gating, global one-to-one assignment, descriptor-dimension mismatch, non-finite/zero descriptors, time regression, short-gap 3D hard gating, long-gap appearance-led matching, low-confidence/no-visibility memory-update suppression, confirmation, occluded/inactive transitions, prototype-bank caps, identity-count cap, and calibration changes invalidating robot-space positions without deleting appearance memory.

- [ ] **Step 2: Run identity tests and verify RED**

Run:

```bash
cd web-control/server
PYTHONPATH=/tmp/thirdhand-vision-test-deps:. /home/nieqingcao/miniconda3/envs/LumosTouch/bin/python -m pytest tests/vision/test_identity.py -v
```

Expected: collection fails because `vision.identity` does not exist.

- [ ] **Step 3: Implement validated immutable contracts**

Use these public signatures:

```python
class IdentityStatus(str, Enum):
    TENTATIVE = "tentative"
    CONFIRMED = "confirmed"
    OCCLUDED = "occluded"
    INACTIVE = "inactive"
    AMBIGUOUS = "ambiguous"

@dataclass(frozen=True)
class IdentityObservation:
    observation_id: int
    label: str
    confidence: float
    visibility: float
    descriptor: np.ndarray
    stamp: FrameStamp
    pose: PoseEstimate | None = None

@dataclass(frozen=True)
class PersistentIdentityConfig:
    max_cosine_distance: float
    ambiguity_margin: float
    appearance_weight: float
    position_weight: float
    max_position_distance_m: float
    position_gate_max_age_ns: int
    occluded_after_ns: int
    inactive_after_ns: int
    min_confirmed_hits: int
    min_memory_confidence: float
    min_memory_visibility: float
    work_bank_size: int
    stable_bank_size: int
    max_identities: int

class PersistentIdentityMemory:
    def update(self, observations: Iterable[IdentityObservation], now_ns: int) -> IdentityUpdate: ...
    def snapshots(self, now_ns: int) -> tuple[IdentitySnapshot, ...]: ...
    def set_calibration(self, calibration_id: str) -> None: ...
```

Normalize and freeze descriptors in `IdentityObservation`. Reject duplicate observation IDs, mixed timestamps, future stamps, mixed descriptor dimensions, and non-robot-base poses.

- [ ] **Step 4: Implement association and bounded memory**

Compute appearance cost as the minimum cosine distance across stable and work prototypes. Apply class and maximum-cosine gates first. While the gap is no greater than `position_gate_max_age_ns`, reject a valid pose pair whose Euclidean base-frame displacement exceeds `max_position_distance_m`; after that gap, omit position from the score. Renormalize weights over available channels.

Before Hungarian assignment, mark an observation ambiguous when its two lowest finite candidate costs differ by no more than `ambiguity_margin`; exclude that column from assignment. Run `scipy.optimize.linear_sum_assignment` on the remaining finite matrix. Create a new tentative identity only for an unmatched observation that was not ambiguous.

Append to the work bank only when confidence and visibility pass their thresholds. Once confirmed, consolidate sufficiently distinct high-confidence views into the stable bank. Cap both banks and evict the oldest inactive identities first when `max_identities` is reached.

- [ ] **Step 5: Run focused and complete core tests**

Run the focused identity tests, then all `tests/vision`. Expected: all tests pass and the boundary test finds no hardware/process/transport imports.

- [ ] **Step 6: Commit Task 1**

```bash
git add web-control/server/vision/identity.py web-control/server/tests/vision/test_identity.py web-control/server/vision/__init__.py
git commit -m "feat(vision): add persistent appearance identity memory"
```

### Task 2: Mask-filtered D435 pose estimation

**Files:**
- Create: `web-control/server/vision/instance_pose.py`
- Create: `web-control/server/tests/vision/test_instance_pose.py`
- Modify: `web-control/server/vision/__init__.py`

**Interfaces:**
- Consumes: `RegisteredDepth`, a native-Lumos boolean instance mask, `t_base_from_lumos`, `FrameStamp`, calibration ID, and `InstancePoseConfig`.
- Produces: a `PoseEstimate` in `robot_base` or raises `InvalidDataError` with a stable rejection reason.

- [ ] **Step 1: Write failing robust-pose tests**

Use small hand-built `RegisteredDepth` arrays. Prove that mask erosion removes boundary contamination, sparse masks are rejected, median/MAD filtering removes a distant outlier, the returned center is transformed into robot-base coordinates, covariance is finite positive semidefinite, and invalid transforms/masks/calibration are rejected.

```python
def test_pose_uses_eroded_mask_and_rejects_background_depth():
    registered = registered_grid_with_center_object_and_boundary_background()
    pose = estimate_instance_pose(
        registered,
        mask=np.ones((5, 5), dtype=bool),
        t_base_from_lumos=translated_identity([0.1, 0.0, 0.0]),
        stamp=FrameStamp("lumos+d435", 1, 10),
        calibration_id="sha256:pose-test",
        config=InstancePoseConfig(min_points=4, erosion_px=1, mad_scale=3.5, noise_floor_m=0.002),
    )
    np.testing.assert_allclose(pose.xyz_m, [0.1, 0.0, 0.5], atol=1e-9)
```

- [ ] **Step 2: Run focused test and verify RED**

Expected: collection fails because `vision.instance_pose` does not exist.

- [ ] **Step 3: Implement erosion, robust filtering, transform, and covariance**

Validate the mask before applying `scipy.ndimage.binary_erosion`. Select finite registered Lumos points, require `min_points`, compute a coordinate-wise median, reject points outside `mad_scale * 1.4826 * MAD` with `noise_floor_m` as the lower scale bound, then require `min_points` again. Transform accepted points with `transform_points`, use their coordinate median as `xyz_m`, and calculate covariance of the mean plus `noise_floor_m**2` on the diagonal.

- [ ] **Step 4: Run pose and complete core tests**

Expected: all existing and new vision tests pass.

- [ ] **Step 5: Commit Task 2**

```bash
git add web-control/server/vision/instance_pose.py web-control/server/tests/vision/test_instance_pose.py web-control/server/vision/__init__.py
git commit -m "feat(vision): estimate robust poses from instance masks"
```

### Task 3: Model-side contracts, DINO pooling, and RTMDet adapter

**Files:**
- Create: `web-control/server/vision_models/__init__.py`
- Create: `web-control/server/vision_models/contracts.py`
- Create: `web-control/server/vision_models/dino.py`
- Create: `web-control/server/vision_models/rtmdet.py`
- Create: `web-control/server/tests/vision_models/test_contracts.py`
- Create: `web-control/server/tests/vision_models/test_dino.py`
- Create: `web-control/server/tests/vision_models/test_rtmdet.py`

**Interfaces:**
- Consumes: one RGB image, native-image instance masks, optional installed Transformers/PyTorch/MMDetection dependencies, and explicit model IDs/paths.
- Produces: `InstanceDetection` values and one normalized descriptor per mask; importing contracts never loads weights or initializes CUDA.

- [ ] **Step 1: Write failing model-contract and pure pooling tests**

Define tests for immutable boolean masks, box bounds, score validation, label mapping, mask-grid pooling, zero-coverage rejection, and result conversion from a complete fake MMDetection `pred_instances` structure. The fake substitutes only external inference output; all conversion and validation code remains real.

```python
def test_pool_patch_descriptors_averages_only_covered_patches():
    features = np.array([[[1.0, 0.0], [0.0, 1.0]], [[1.0, 0.0], [0.0, 1.0]]])
    mask = np.array([[True, False], [True, False]])
    descriptor = pool_patch_descriptor(features, mask)
    np.testing.assert_allclose(descriptor, [1.0, 0.0])
```

- [ ] **Step 2: Run model tests and verify RED**

Expected: collection fails because `vision_models` does not exist.

- [ ] **Step 3: Implement contracts and dependency-free feature pooling**

`InstanceDetection` owns `detection_id`, `label`, `score`, `bbox_xyxy`, and native-Lumos mask. `pool_patch_descriptor(feature_map, patch_mask)` accepts `[Hp, Wp, D]` features and `[Hp, Wp]` coverage, averages covered patches, L2 normalizes, freezes, and rejects empty/invalid input.

- [ ] **Step 4: Implement lazy DINO adapter**

`DinoMaskEncoder.__init__` imports PyTorch and Transformers locally, loads an explicit Hugging Face model ID, disables resize and center crop in the processor, and records its patch size. `encode(image_rgb, masks)` performs one forward pass, removes all special tokens using `Hp * Wp`, resizes each native mask to the patch grid with area coverage, and calls the pure pooling function. Default model ID is `facebook/dinov2-small`; DINOv3 requires an explicit ID and accepted access token outside the repository.

- [ ] **Step 5: Implement lazy RTMDet adapter**

`RTMDetInstanceSegmenter.__init__(config_path, checkpoint_path, labels, device)` imports `mmdet.apis` locally and refuses missing files. `predict(image_rgb)` calls `inference_detector`, filters by configured score, converts tensors through `detach().cpu().numpy()`, maps labels, and returns detections sorted by descending score then detection ID. Absence of masks is an error, not a box fallback.

- [ ] **Step 6: Run model unit tests without heavy dependencies**

Run `pytest tests/vision_models -v`. Expected: all pure contract/conversion tests pass; no test downloads weights or initializes CUDA.

- [ ] **Step 7: Commit Task 3**

```bash
git add web-control/server/vision_models web-control/server/tests/vision_models
git commit -m "feat(vision): add lazy RTMDet and DINO model adapters"
```

### Task 4: Deterministic REMIND-3D offline replay CLI

**Files:**
- Create: `web-control/server/vision_models/offline_replay.py`
- Create: `web-control/server/tests/vision_models/test_offline_replay.py`
- Create: `configs/vision/remind3d.yaml`
- Create: `web-control/server/tests/vision_models/fixtures/remind3d_observations.json`
- Create: `web-control/server/tests/vision_models/fixtures/remind3d_descriptors.npz`

**Interfaces:**
- Consumes: schema-versioned JSON plus relative NPZ descriptors/poses produced by a model process or annotated fixture.
- Produces: deterministic per-frame identity assignments, statuses, rejection reasons, ID-switch count, ambiguity count, and atomic JSON output; it never accepts an execution command.

- [ ] **Step 1: Write failing replay validation and metric tests**

Create a five-frame fixture with two same-class instances, one occlusion, one long-gap return, one ambiguous observation, and no robot command fields. Assert stable IDs across return, exactly one ambiguous assignment, zero forced assignment for that frame, zero ID switches, deterministic byte-identical output, path-traversal rejection, duplicate/non-monotonic stamps rejection, and unknown schema rejection.

- [ ] **Step 2: Run replay tests and verify RED**

Expected: collection fails because `vision_models.offline_replay` does not exist.

- [ ] **Step 3: Implement strict parser and engine adapter**

Use safe relative paths, `np.load(..., allow_pickle=False)`, explicit schema version `1`, and `PersistentIdentityMemory`. The CLI accepts only `--manifest` and `--output`; reject unknown manifest keys named `command`, `execute`, `move`, `gripper`, or `trajectory`. Serialize sorted keys and atomic replacement exactly like `vision.replay.write_metrics_atomic`.

- [ ] **Step 4: Add conservative deployment config**

Record canonical image `lumos_native_seucm`, primary detector `rtmdet_tiny_ins`, primary descriptor `dinov3_vits16`, fallback descriptor `facebook/dinov2-small`, all identity thresholds, minimum mask depth points, GPU memory gate `7.2 GiB`, latency gate `300 ms P95`, and `robot_execution_enabled: false`.

- [ ] **Step 5: Run replay twice and compare outputs**

Run the CLI twice against the fixture and use `cmp` to prove byte determinism. Then run all model and core tests.

- [ ] **Step 6: Commit Task 4**

```bash
git add configs/vision/remind3d.yaml web-control/server/vision_models/offline_replay.py web-control/server/tests/vision_models
git commit -m "feat(vision): add deterministic REMIND-3D replay"
```

### Task 5: Reproducible environment, model smoke gate, and deployment evidence

**Files:**
- Create: `requirements/remind3d-cu128.txt`
- Create: `scripts/vision/bootstrap_remind3d_env.sh`
- Create: `scripts/vision/smoke_remind3d_models.py`
- Create: `tests/vision_deployment/test_bootstrap_contract.py`
- Create: `docs/vision_research/REMIND3D_DEPLOYMENT_RESULTS.md`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: network access, NVIDIA driver, explicit model paths/access credentials, and the isolated `thirdhand-remind3d` environment.
- Produces: pinned dependency installation, device/model/mask/descriptor smoke JSON, hashes, measured latency/VRAM, and a truthful gate status.

- [ ] **Step 1: Write failing bootstrap and smoke-contract tests**

Execute `bootstrap_remind3d_env.sh --print-plan` and assert its structured output selects Python 3.11, a CUDA 12.8 PyTorch wheel, a separate environment name, and never references the `LumosTouch` environment. Run `smoke_remind3d_models.py --check-config configs/vision/remind3d.yaml` in the light test environment and assert it validates paths/model IDs without importing Torch.

- [ ] **Step 2: Run deployment tests and verify RED**

Expected: tests fail because the scripts and requirements file do not exist.

- [ ] **Step 3: Implement reproducible bootstrap**

Pin the CUDA 12.8-compatible Torch/torchvision pair, NumPy, SciPy, OpenCV headless, Transformers, scikit-learn, PyYAML, psutil, pytest, MMEngine, MMDetection, and MMDeploy/ONNXRuntime tooling in the requirements file. The shell script creates only `thirdhand-remind3d`, installs from explicit indexes, prints every effective version, and stops on any failed import. It never upgrades base, `LumosTouch`, or the Startouch environment.

- [ ] **Step 4: Implement model smoke CLI**

The smoke command loads one RTMDet instance-segmentation model and one DINO encoder, runs a supplied image or deterministic generated RGB image, requires at least one mask for a supplied real image, reports descriptor dimension/norm, CUDA name/capability, peak allocated VRAM, and P50/P95 latency, and writes JSON atomically. It must fail if RTMDet returns boxes without masks, DINO returns non-finite descriptors, compute capability is unsupported, or peak VRAM exceeds 7.2 GiB.

- [ ] **Step 5: Attempt environment and real model smoke**

Run bootstrap, then the smoke CLI with explicit RTMDet config/checkpoint and DINOv2 fallback. If the network, gated model access, package compatibility, or weights block this step, record the exact command, timestamp, exit status, and error in the deployment results. Do not mark the detector or descriptor deployed without a successful inference artifact.

- [ ] **Step 6: Run fresh complete verification**

Run core tests, model tests, deployment tests, Ruff on new Python files, `git diff --check`, deterministic replay comparison, and the hardware-dependency boundary test. Record exact results and unresolved gates.

- [ ] **Step 7: Commit Task 5**

```bash
git add .gitignore requirements/remind3d-cu128.txt scripts/vision tests/vision_deployment docs/vision_research/REMIND3D_DEPLOYMENT_RESULTS.md
git commit -m "build(vision): add reproducible REMIND-3D deployment"
```

## Manual gates after this plan

1. Accept the DINOv3 license and provision access credentials if DINOv3 is to replace the DINOv2 fallback.
2. Collect and label synchronized Lumos RGB, D435 depth, flange pose, calibration ID, and ground-truth instance identity replay data.
3. Recalibrate and independently validate Lumos intrinsics, D435-to-Lumos extrinsics, and camera-to-robot transforms.
4. Fine-tune RTMDet-tiny-ins on actual target classes and Lumos optics, then pass mask recall and radial-edge metrics.
5. Pass long-gap ReID, ambiguity, ID-switch, absolute-position, jitter, latency, and VRAM thresholds from the selection report.
6. Review Dry Run overlays and rejection reasons before any live-service read-only integration.
7. Treat any real-arm movement as a separate supervised authorization with emergency stop, cleared workspace, low speed, and staged approach tests.
