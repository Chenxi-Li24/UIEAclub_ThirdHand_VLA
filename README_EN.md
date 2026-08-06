# ThirdHand VLA: A Complete Tutorial from Robot Geometry to Verifiable Vision and VLA

ThirdHand VLA is a research and experimental repository built around the Lumos Touch R1
six-degree-of-freedom desktop robot arm, the Lumos Ego ultra-wide-angle camera, and the
Intel RealSense D435. Its primary research track is **robot vision and 3D perception**;
its secondary track is **verifiable VLA decision-making**; an end-to-end vision–VLA system
is an optional integrated track. Robot control serves only as a supervised experimental
platform and safety boundary, not as the current SCI novelty claim.

> **Safety warning**
>
> Levels L0–L3 in this tutorial do not grant permission for physical motion. Any real motion
> requires on-site supervision, exclusive CAN ownership, low speed, a cleared workspace,
> and an independent hardware emergency stop that is immediately reachable. A web-based
> “software stop,” keyboard interrupt, voice emergency stop, and SDK `cleanup()` all depend
> on the computer and communication path. They cannot replace a hardware emergency stop
> or power isolation. Keep `robot_execution_enabled: false` in the vision configuration.
> Never remove calibration, freshness, identity, resource-ownership, or human-confirmation
> gates merely to make a demonstration pass.

[Project home](README.md) · [Architecture](docs/architecture.md) ·
[Setup guide](docs/setup_guide.md) · [Research evidence hub](docs/research/README.md) ·
[Vision research index](docs/vision_research/14_FINAL_TECHNICAL_DECISION.md)

## Learning outcomes

After completing this tutorial, you should be able to:

1. distinguish the two independent runtime boundaries: the installable Python VLA application
   and the Startouch Web control stack;
2. explain the pixel-to-robot-base chain using joint space, Cartesian pose, RPY, SE(3),
   intrinsics, extrinsics, and hand–eye calibration;
3. explain Lumos canonical RGB, D435 metric depth, cross-camera registration,
   persistent instance identity, object memory, and fail-closed gates;
4. explain why VLA and voice components produce only recommendations or structured candidates
   and cannot directly acquire execution authority;
5. follow the L0–L4 risk ladder to install, reproduce offline results, run simulation or
   read-only services, and preserve auditable evidence; and
6. connect hypotheses, datasets, experiment manifests, result records, figures, and limitations
   into a traceable SCI evidence chain.

## Suggested reading paths

| Reader | Shortest path | Completion criterion |
| --- | --- | --- |
| New developer | 1 → 2 → 5 → 6 → L0–L2 | Can identify every entry point's dependencies and control privileges without mistaking interface scaffolding for hardware capability |
| Vision researcher | 1 → 2 → 3 → 8 | Can trace camera timestamps through mask-based 3D pose, covariance, identity, and paper evidence |
| VLA researcher | 1 → 4 → 5 → 8 | Can design an offline comparison of candidate–preview–confirmation–local-validation variants |
| Reproducer | 1 → 6 → L0–L3 → 8 | Can reconstruct result records from a commit, commands, configuration, and dataset checksums |
| Supervised hardware operator | Section 1 safety boundary → 2.7 → 5 → L0–L4 | Stops whenever any gate fails and never treats a software stop as a hardware emergency stop |

## Navigation

1. [Understand the system](#tutorial-01-system)
2. [Robotics and geometry foundations](#tutorial-02-robotics-geometry)
3. [Perception and the primary vision research track](#tutorial-03-perception)
4. [VLA, voice, and human–machine interaction](#tutorial-04-vla-interaction)
5. [Control, orchestration, and safety](#tutorial-05-control-safety)
6. [Code map and runtime interfaces](#tutorial-06-code-map)
7. [L0–L4 hands-on tutorial](#tutorial-07-hands-on)
8. [SCI verification, troubleshooting, and publication path](#tutorial-08-research-verification)

---

<a id="tutorial-01-system"></a>

## 1. Understanding the ThirdHand System

### 1.1 Goals, non-goals, and representative tasks

This project studies how timestamped visual evidence—with a calibration source and quantified
uncertainty—can enter an auditable robot decision boundary safely. Representative tasks include
desktop instance segmentation, cross-camera depth registration, re-identification after
occlusion, offline VLA candidate evaluation, and supervised validation of a fixed-point motion
platform.

Current non-goals are unsupervised autonomous grasping, general collision planning, a
safety-certified controller, low-level motion control as the paper's central contribution, or
claims of algorithmic superiority based on a single qualitative screenshot. No effect can support
a publication claim without a dataset datasheet, experiment manifest, sample size, interval, and
generation command.

### 1.2 Hardware and data/control topology

```text
Observation plane
  Lumos Ego RGB (canonical_rgb, SEUCM) ─┐
                                        ├─ time pairing → registration → instance/identity/3D → read-only state
  Intel D435 depth (metric_depth, pinhole)┤
  Intel D435 RGB (debug_rgb)─────────────┘

Control plane
  Browser → Node :3000 → Startouch Python bridge → vendor SDK → SocketCAN can0
                                                   → Lumos Touch R1 + gripper

Independent boundaries
  Installable Python application :8000 (experimental framework)
  Lumos HTTP/MJPEG :3001; read-only dual-camera page :3100
  Fixed A/B local control page 127.0.0.1:8766
```

The logical roles in the [REMIND-3D configuration](configs/vision/remind3d.yaml) are fixed as
Lumos for primary appearance, D435 for metric depth, and D435 RGB for debugging. Physical device
enumeration can change, so algorithms must not treat `/dev/videoN` as a persistent identity. See
[Hardware and Camera Topology](docs/vision_research/02_HARDWARE_AND_CAMERA_TOPOLOGY.md) for the
device topology and stable-identifier strategy.

### 1.3 Two runtime boundaries

**Boundary A: installable Python VLA application.** The [entry point](src/uiea_thirdhand_vla/__main__.py)
starts with `python -m uiea_thirdhand_vla` or `thirdhand-vla`. It organizes cameras, ArUco/YOLO,
an optional cloud VLA, a deterministic state machine, control adapters, and a FastAPI object on
port `8000` by default. However, [Robot](src/uiea_thirdhand_vla/control/robot.py), ASR/NLU/TTS,
and portions of the Web API remain framework implementations. The
[FastAPI factory](src/uiea_thirdhand_vla/web/server.py) does not yet mount the API routers or
`/ws`. It is therefore an **Experimental** framework for development and offline validation, not
a verified hardware entry point.

```text
Lumos frame → ArUco / YOLO → deterministic state machine → local checks → adapters
optional VLA recommendation ────────────────────────────────┘
optional intent candidate ──────────────────────────────────┘
FastAPI object :8000 → `/static` mount / future route integration
```

**Boundary B: Startouch Web control stack.** The [Node proxy](web-control/server/proxy.js) listens
on `0.0.0.0:3000` by default and connects through a JSON Lines subprocess to the
[Startouch bridge](web-control/server/startouch_bridge.py). That bridge exclusively owns the
specified CAN interface and calls the external vendor SDK. This is the repository's directly
controlling boundary that has undergone hardware integration. Camera and vision state are
side-channel inputs and cannot bypass resource locks, command validation, or the execution switch.
Read the [Web control guide](web-control/README.md) before deployment.

### 1.4 Capability maturity and evidence maturity

Functional status and scientific-evidence status are two different dimensions:

- **Implemented**: code and a public interface exist; this does not mean deployment or algorithmic
  validity has been verified.
- **Verified**: automated tests or explicit dated engineering acceptance evidence exist; this does
  not automatically constitute an SCI comparison result.
- **Experimental**: the capability can run but remains gated by hardware, calibration, the task
  model, or system integration.
- **Planned**: only a research or design path exists; it is not a supported runtime capability.
- **Planned Evidence / 待补实验证据**: no result exists at all; only a future protocol and required
  artifacts may be described.
- **Evidence Incomplete / 待补充证据**: some results exist, but sample size, confidence intervals,
  statistical method, or source evidence is missing, insufficient, or untraceable. Neither evidence
  label may support an abstract-level conclusion.

Preregistration readiness is a third, independent field. Missing thresholds or a missing statistical
plan means preregistration is not ready. If no measurement exists, the evidence remains Planned
Evidence rather than Evidence Incomplete. See the [research evidence hub](docs/research/README.md)
for the full rules.

| Capability | Functional status | Citable fact | What is still missing |
| --- | --- | --- | --- |
| Python configuration, ArUco/YOLO, SEUCM, FSM | Implemented / Experimental | Modules and unit interfaces exist | End-to-end routers, real control adapters, and task acceptance |
| Direct Startouch Web control | Verified (engineering) | The Ubuntu 20.04 hardware path, CAN preflight, limits, locking, and stop path are documented/tested | It is not a safety-certified controller |
| Fixed A/B stepwise demo | Experimental | Simulation, dry-run, resource preflight, and manual stepwise entry points exist | Configuration still records `validated_real_cycles: 0`; it cannot be promoted to an unsupervised workflow |
| Offline vision safety core and deterministic replay | Verified (offline engineering) | Geometry, registration, tracking, memory, gate, and replay tests exist | Real datasets and comparative statistics remain incomplete |
| RTMDet + DINOv2 online dual-camera read-only state | Experimental | A dated deployment record and status verifier exist | Task-specific weights, cross-camera/hand–eye calibration, and paper statistics are incomplete |
| Vision-triggered physical execution | Planned | Authorization code fails closed and the configuration execution lock is false | Every calibration, identity, depth, latency, model, and on-site safety gate |
| Voice/text structured candidates | Experimental / partially Verified | The isolated Voice Bridge, protocol, and mock have tests | Candidates never receive real robot privileges; the VLA comparison study is incomplete |
| Vision/VLA/integrated publication claims | Planned Evidence | Hypotheses, schemas, and baseline templates exist | Frozen data, repeated experiments, intervals, statistical tests, and generated figures |

### 1.5 A port means “host + transport + port”

| Service | Default bind | Port/transport | Privilege and source |
| --- | --- | --- | --- |
| Python VLA FastAPI object | `0.0.0.0` | `8000/TCP` | Experimental; [configuration](configs/web.yaml) |
| Startouch Web/robot WebSocket | `0.0.0.0` | `3000/TCP` | Can produce control authority; [Node configuration](web-control/server/config.js) |
| Lumos HTTP snapshot/MJPEG | `0.0.0.0` | `3001/TCP` | Camera read-only; [service](web-control/server/lumos_http_server.py) |
| Voice Protocol v1 | `0.0.0.0` | `3001/TCP` (usually on Jetson) | Candidate-only; conflicts with Lumos TCP 3001 on the same host, so `3002` can be used instead |
| Online dual-camera page | `0.0.0.0` | `3100/TCP` (fixed by safe launcher) | Simulated robot and read-only vision; [launcher](scripts/vision/start_dual_camera_online.sh) |
| Fixed A/B control page | `127.0.0.1` | `8766/TCP` | Does not hold CAN while idle; supervised motion can start after activation |

Binding to `0.0.0.0` does not provide authentication or Internet security. Use these services only
on a controlled LAN and check port ownership first. Voice and Lumos may reuse the same port number
only when they run on different hosts, or after assigning different TCP ports.

---

<a id="tutorial-02-robotics-geometry"></a>

## 2. Robotics and Geometry Foundations

### 2.1 Six degrees of freedom, joint space, and Cartesian space

The arm state can be represented by a six-dimensional joint vector

\[
\mathbf q=[q_1,q_2,q_3,q_4,q_5,q_6]^T,
\]

The repository's control interfaces display and validate joints in degrees and send radians as
required by the SDK. A joint-space move, `move_j`, specifies a target `q`, which allows each axis
limit to be checked directly. A Cartesian move, `move_l`, specifies the end-effector pose
`(x,y,z,roll,pitch,yaw)` and requires inverse kinematics, workspace, path, and collision checks.
The installable application's current [Robot adapter](src/uiea_thirdhand_vla/control/robot.py) is
only scaffolding. The joint path, feedback, and validation for the real Startouch bridge live in
[startouch_bridge.py](web-control/server/startouch_bridge.py).

**Knowledge chain:** joint angles → forward/inverse kinematics → end-effector pose →
limits/speed/freshness → CAN motion. Reject the command when any link is invalid; do not clamp it
to the “nearest usable” value.

### 2.2 Coordinate frames and notation

This tutorial uses `T_target_from_source` for a homogeneous transform that converts coordinates
from the source frame into the target frame. The principal frames are:

| Frame | Meaning | Code/evidence |
| --- | --- | --- |
| `robot_base` | Fixed robot base; common frame for 3D targets and workspace bounds | [Type contract](web-control/server/vision/types.py) |
| `robot_flange` | End flange that moves with the joints | [Dual-camera composition](web-control/server/vision/dual_camera.py) |
| `lumos` | Native SEUCM frame of the primary vision camera | [Camera model](web-control/server/vision/camera_models.py) |
| `d435` | D435 depth optical frame; input is axial Z-depth | [Depth registration](web-control/server/vision/depth_registration.py) |
| pixel | Image coordinate `(u,v)`, not metric space | The Lumos mask and registered depth must have the same native image shape |

The current fusion chain is

\[
T_{base\leftarrow lumos}=T_{base\leftarrow flange}T_{flange\leftarrow lumos},\quad
p_{base}=T_{base\leftarrow lumos}T_{lumos\leftarrow d435}p_{d435}.
\]

Every calibration object in this chain needs a direction, units, a content-addressed ID,
validation status, and residual. Writing only “camera pose” is insufficient.

### 2.3 RPY convention

The repository's vision geometry interprets the SDK `(roll,pitch,yaw)` in the fixed order

\[
R=R_z(yaw)R_y(pitch)R_x(roll).
\]

See [rpy_xyz_to_matrix](web-control/server/vision/geometry.py). RPY is not a Rodrigues rotation
vector, and the multiplication order is not interchangeable. A reproducible experiment manifest
must record angle units, active/passive rotation, and row/column-vector conventions. Use a
compound-rotation test to prevent the failure mode in which every single-axis test passes but the
composition is wrong.

### 2.4 Homogeneous transforms and SE(3)

A rigid-body pose belongs to \(SE(3)\):

\[
T=\begin{bmatrix}R&t\\0&1\end{bmatrix},\quad R^TR=I,\quad \det R=1,
\]

Augment `p_source` to `(x,y,z,1)`, then left-multiply it by the transform. The inverse is

\[
T^{-1}=\begin{bmatrix}R^T&-R^Tt\\0&1\end{bmatrix}.
\]

The [geometry module](web-control/server/vision/geometry.py) checks finite values, rotation
orthogonality, determinant, and the final homogeneous row. The
[type module](web-control/server/vision/types.py) also freezes timestamps, covariance, frame, and
`calibration_id`, preventing an unprovenanced 3D point from entering downstream gates.

### 2.5 Intrinsics, distortion, and two camera models

The pinhole intrinsics matrix

\[
K=\begin{bmatrix}f_x&0&c_x\\0&f_y&c_y\\0&0&1\end{bmatrix}
\]

maps a 3D point to a pixel. D435 depth is axial `Z` along the optical axis, not the Euclidean
distance from the optical center. [PinholeCamera.deproject_z](web-control/server/vision/camera_models.py)
explicitly deprojects using axial depth.

The Lumos ultra-wide-angle camera uses SEUCM. For camera point `(X,Y,Z)`, the implementation first
computes `d=sqrt(beta*(X²+Y²)+Z²)` and `s=alpha*d+(1-alpha)*Z`, then projects with
`u=fx*X/s+cx` and `v=fy*Y/s+cy` while returning the valid domain explicitly. Rectifying the whole
image to a pinhole view first sacrifices edge resolution and field of view. The primary algorithm
retains native Lumos pixels; a virtual pinhole view is permitted only as a controlled ablation.
See the [fisheye model study](docs/vision_research/03_FISHEYE_VISION_RESEARCH.md).

### 2.6 Extrinsics and hand–eye calibration

Intrinsics describe one camera; extrinsics describe a rigid relationship between frames. The
complete current chain requires D435→Lumos, Lumos→flange (or base→camera for a fixed camera), and
time-aligned robot poses. We continue to use `T_{target←source}`, meaning that the matrix transforms
a point from the source frame into the target frame.

The input contract of OpenCV `cv2.calibrateHandEye` is `T_{base←gripper}` for each pose (parameter
name `gripper2base`) together with `T_{camera←target}` (`target2cam`). It returns
`T_{gripper←camera}` (`cam2gripper`), not `T_{base←camera}`. In eye-in-hand mounting, the camera is
rigidly attached to the gripper and that returned transform is the fixed extrinsic. For a specific
robot pose, compose it explicitly as
`T_{base←camera}=T_{base←gripper} T_{gripper←camera}`. In eye-to-hand mounting, the camera is fixed
to the base and the desired fixed quantity is `T_{base←camera}`. That case uses a different motion
chain or inverted/swapped inputs; an eye-in-hand return value cannot simply be renamed base→camera.

The current [CoordinateTransforms.calibrate_hand_eye](src/uiea_thirdhand_vla/perception/transforms.py)
passes `T_base_ee` and `T_camera_marker` into that interface but stores the returned camera→gripper
transform directly as `T_base_cam` and claims to return base→camera. This is a frame-labeling and
composition bug. Until the helper is split by mounting mode, its direction/composition is fixed,
and it passes validation on independent held-out poses, it **must not be used for real execution or
as SCI calibration evidence**. The research pipeline's
[calibration audit and dual-camera bundle](web-control/server/vision/dual_camera.py) validate
provenance and compose a new content ID, but the content ID itself does not repair the coordinate
chain.

Hand–eye results must report translational/rotational or reprojection residuals on independent
held-out poses. The current research audit explicitly says that the legacy Lumos calibration
residual is not valid for execution. Do not interpret “the file exists” as `validated=true`. See
the [calibration plan](docs/vision_research/07_CALIBRATION_PLAN.md) for the recollection protocol.

### 2.7 Limits, speed, watchdog, and stop hierarchy

The real Startouch Web boundary uses the following hardware-integrated limits, which also appear
in [fixed_pick_place.yaml](configs/tasks/fixed_pick_place.yaml):

| Axis | Angular range | Nominal maximum speed | Default Web command scale |
| --- | ---: | ---: | ---: |
| J1 | `[-162°, 162°]` | `300°/s` | `5%` |
| J2 | `[-12°, 201°]` | `300°/s` | `5%` |
| J3 | `[-183°, 0°]` | `300°/s` | `5%` |
| J4 | `[-98°, 98°]` | `1000°/s` | `5%` |
| J5 | `[-98°, 98°]` | `1000°/s` | `5%` |
| J6 | `[-164°, 164°]` | `1000°/s` | `5%` |

[configs/robot.yaml](configs/robot.yaml) and [configs/workspace.yaml](configs/workspace.yaml)
define general configuration for the installable application, but their joint ranges differ from
the hardware-integrated Startouch Web ranges. For the real Web entry point, the
`server/config.js`/bridge validation is authoritative. The current `setup_system()` also does not
fully connect the separate workspace block to `Safety`, so one cannot claim that every entry point
uniformly enforces the YAML workspace.

The Startouch bridge additionally enforces a control lock, six-axis finite-value and limit checks,
rejection of an unexpected all-zero target, a stable initial state, active CAN feedback, serialized
motion, and a feedback-staleness watchdog. The default `STARTOUCH_CAN_RX_STALE_SEC=1` causes the
bridge to disconnect and clean up when feedback stops. Reference bounds in
`configs/workspace.yaml` are x `[-0.3,0.5]`, y `[-0.4,0.4]`, and z `[-0.05,0.4]` m, with reference
linear speed `0.5 m/s`, joint speed `90°/s`, and timeout `10 s`. These values become execution
constraints only after the specific control boundary is verified to wire them in.

From weakest to strongest, the stop hierarchy is: task cancellation/stop issuing new commands →
SDK software stop and `cleanup()` → independent hardware emergency stop or power isolation. If the
software path fails, the arm behaves abnormally, or a person enters the workspace, use the hardware
emergency stop immediately; do not wait for a browser response.

---

<a id="tutorial-03-perception"></a>

## 3. Perception and the Primary Vision Research Track

This chapter is organized into six independently testable method units. Each unit specifies a
Problem, Method, Protocol, Metrics, Evidence, and Limits so that it maps directly to the
[claim matrix](docs/research/claim_evidence_matrix.md),
[dataset datasheet](docs/research/dataset_datasheet.md),
[baseline/ablation matrix](docs/research/baseline_ablation_matrix.md),
[figure manifest](docs/research/figure_manifest.md), and
[reproducibility checklist](docs/research/reproducibility_checklist.md).

### 3.1 Method 1: logical camera roles and native imaging models

#### Problem

The primary wide-angle image and metric depth come from different cameras. If identity,
segmentation, and depth each choose an arbitrary RGB source, the result is semantic drift, edge
distortion error, and irreproducible switching of device roles.

#### Method

`canonical_rgb=lumos_rgb`: RTMDet masks, DINOv2 appearance, and identity all use native Lumos
SEUCM pixels. `metric_depth=d435_depth`: D435 pinhole Z-depth provides metric geometry.
`debug_rgb=d435_rgb`: this source displays only a debugging view and never determines instance
identity. The role contracts are in
[online_frames.py](web-control/server/vision/online_frames.py) and
[remind3d.yaml](configs/vision/remind3d.yaml).

#### Protocol

Record device serial numbers and firmware, logical roles, resolution, frame rate, pixel format,
intrinsics ID, and a monotonic timestamp for every frame. Isolate dataset splits by recording
session, scene, and physical instance. Validate SEUCM on held-out center and edge points, and fix
the D435 depth unit in the recording manifest.

#### Metrics

Center/radial-bin reprojection median, P95, and max; invalid-domain ratio; acquisition drop rate;
role error rate; number of primary/debug source switches; mask AP/recall by radial bin.

#### Evidence

Camera-model unit tests and a dated read-only deployment record exist and constitute engineering
verification. The real comparative study remains Planned Evidence. See the
[dataset template](docs/research/dataset_datasheet.md) for the manifest entry and V3 for the planned
preview.

#### Limits

A nonempty single-frame output from official COCO weights does not establish performance on task
classes. Device enumeration, exposure, lighting, and fisheye domain shift remain confounders. The
current calibration chain has not passed execution acceptance.

### 3.2 Method 2: temporal pairing, calibration provenance, and the coordinate chain

#### Problem

Even with correct geometric extrinsics, stale or mismatched RGB, depth, and robot poses produce
wrong 3D points in a moving scene. An unversioned calibration file cannot identify which coordinate
chain produced a result.

#### Method

[LatestFramePairer](web-control/server/vision/online_frames.py) uses monotonic timestamps and
latest-only pairing: it does not wait, interpolate, or invent time. The current configuration
requires RGB–depth skew ≤`50 ms`, frame age ≤`200 ms`, and robot-pose skew ≤`50 ms`; violations
produce reason codes only. Every valid calibration enters
[DualCameraCalibrationBundle](web-control/server/vision/dual_camera.py) with a `sha256:` content ID
and `validated` status.

#### Protocol

Freeze the clock source and units. Record each frame sequence, all three timestamps, the pairing
decision, exclusion reason, calibration checksum, extrinsic direction, and independently validated
residual. Evaluate static versus moving sequences, center versus edge, and separate skew bins.
Never place the same clip in both training and test splits.

#### Metrics

Skew/age P50, P95, and max; pair acceptance rate; mismatch rate; registration pixel error, planar
mm error, and 3D position error by skew bin; calibration-invalidity detection rate.

#### Evidence

Fail-closed tests for timing and calibration are implemented. A-REG-01 remains Planned Evidence,
and its preregistration threshold is not ready. Record that state in the
[claim matrix](docs/research/claim_evidence_matrix.md) instead of deriving a publication threshold
backwards from an engineering budget.

#### Limits

A single-host monotonic clock does not automatically correct hardware-clock offsets between
devices. Remounting a camera, moving a bracket, or updating intrinsics invalidates old extrinsics.
Without a robot pose, appearance identity may still be observed, but no actionable base-frame
target may be generated.

### 3.3 Method 3: D435→Lumos depth registration and z-buffering

#### Problem

D435 depth pixels are not co-registered with the Lumos mask. Looking up depth at the same `(u,v)`
directly assigns background or an occluding surface to the target, especially across a dual-camera
baseline, at image edges, and near depth discontinuities.

#### Method

[register_depth_to_lumos](web-control/server/vision/depth_registration.py) performs these steps in
order: filter invalid/out-of-range Z-depth → deproject with the D435 pinhole model → left-multiply
by `T_lumos_from_d435` → project with Lumos SEUCM → rasterize to the nearest integer pixel. When
multiple source points land on one Lumos pixel, the z-buffer retains the closest surface with
positive Z and records `source_count`, axial `z_m`, Euclidean `range_m`, and the Lumos 3D point.
Finally, a Boolean instance mask selects the point cloud. Missing depth is never fabricated from
the tabletop plane.

#### Protocol

Record synchronized depth of known planes/targets and occlusion boundaries. Fix min/max depth,
resolution, rounding policy, extrinsics ID, and invalid-value policy. Compare no registration, no
temporal gate, no z-buffer, and the complete method; slice results by radial distance and occlusion
boundary.

#### Metrics

Registration coverage, pixel error P50/P95, planar mm error, flying-edge rate, in-mask point-cloud
purity, hole rate, and per-frame/end-to-end P50/P95 latency.

#### Evidence

Synthetic registration tests and microbenchmarks are reported in the
[offline implementation record](docs/vision_research/OFFLINE_IMPLEMENTATION_RESULTS.md). They prove
only implementation behavior and determinism; real accuracy remains Planned Evidence. Future
V1/V3/E1/E2 artifacts must be generated from machine-readable results.

#### Limits

Nearest-pixel projection is a baseline, not an optimal subpixel method. Transparent, reflective,
or black objects and disparity occlusion cause missing depth. A pure NumPy microbenchmark excludes
capture, models, and UI, so it cannot establish end-to-end real-time performance.

### 3.4 Method 4: RTMDet instance masks and DINOv2 descriptors

#### Problem

A detection box includes background and therefore produces an impure target point cloud. A class
and box location alone also cannot preserve the identity of same-class objects after occlusion.

#### Method

The [RTMDet adapter](web-control/server/vision_models/rtmdet.py) requires a nonempty Boolean instance
mask at the native image size and verifies that configured labels exactly match checkpoint metadata.
The [DINO adapter](web-control/server/vision_models/dino.py) maps a mask to patch coverage, pools the
features, and normalizes them into one descriptor per instance. A heavy model is loaded lazily only
when its adapter is instantiated. Current defaults are the official COCO RTMDet-Ins tiny model and
`facebook/dinov2-small`, with `task_checkpoint_validated: false`.

#### Protocol

Build task-specific class and instance annotations and freeze train/validation/test splits. Compare
all models on the same primary image, input scale, thresholds, hardware, and measurement window.
Baselines include YOLOv8n detect, YOLO nano segmentation, RTMDet-tiny-ins, and Mask R-CNN R50-FPN.
Record each weight's SHA-256 and license.

#### Metrics

Per-class box/mask AP and recall, empty-scene false positives, radial-bin metrics, mask coverage,
point-cloud purity, within-/between-class descriptor distance, P50/P95 latency, throughput, and
CPU/GPU/VRAM consumption.

#### Evidence

A real-frame GPU smoke test and online availability constitute dated engineering evidence; see the
[deployment record](docs/vision_research/REMIND3D_DEPLOYMENT_RESULTS.md). At the publication level,
the missing task weights and complete statistics make the evidence Evidence Incomplete, so no
detection-superiority claim is justified. The comparison plan is in the
[baseline matrix](docs/research/baseline_ablation_matrix.md).

#### Limits

COCO classes are not equivalent to the desktop task domain, and one nonempty mask is not recall or
accuracy acceptance. Fisheye edges, truncation, similar appearances, mask drift, and model licensing
must each be reported separately.

### 3.5 Method 5: short-term tracking, work/stable object memory, and reacquisition

#### Problem

A per-frame detection ID is not the identity of a physical instance. Missed detections, occlusion,
exit and re-entry, and multiple similar objects can cause ID switches, fragmented tracks, or a
dangerous false merge.

#### Method

The basic [MultiObjectTracker](web-control/server/vision/tracking.py) uses constant-velocity
prediction, same-class gating, a combined-covariance Mahalanobis cost, and global Hungarian
assignment. The research online path adds
[PersistentIdentityMemory](web-control/server/vision/identity.py): appearance similarity has weight
`0.8`, short-term 3D has weight `0.2`, and the memory retains at most 8 work prototypes and 12 stable
prototypes. Low-confidence or low-visibility observations cannot create or contaminate memory. The
current timing marks an instance occluded after `300 ms` and inactive after `1.5 s`; reacquisition
requires 2 consecutive confirmations with depth. When the difference between near-optimal global
assignment costs is below the ambiguity margin, the system explicitly returns `AMBIGUOUS`.

#### Protocol

Freeze an occlusion/re-entry test set by physical instance and clip, and keep detections and
descriptors fixed. Compare IoU-only, appearance-only, appearance+3D, work-only, work+stable, and
ambiguity rejection on/off. For every seed, retain frame-by-frame assignments, costs, statuses,
memory-bank states, and rejection reasons.

#### Metrics

HOTA, IDF1, ID switches, fragmentation, reacquisition rate/time, false identity merges, ambiguous
accept/reject events, identity capacity, and memory/latency.

#### Evidence

Synthetic identity replay proves that state-machine output is deterministic and ambiguous cases
are not forced into an assignment. It does not establish real ReID accuracy. A-ID-01, V2, E1, and
E2 still require held-out real sequences, repeated measurements, and intervals; see the
[claim matrix](docs/research/claim_evidence_matrix.md).

#### Limits

Descriptor domain shift, identical-looking objects, long-term lighting changes, and detector
changes can confound the identity contribution. Even after a long-term re-entry retains an ID, its
state begins as tentative; visual similarity must not bypass consecutive confirmation.

### 3.6 Method 6: mask-based 3D pose, covariance, and actionability

#### Problem

A bounding-box center or point-cloud mean is biased by background, edge noise, and outlier depth.
Even with a 3D center, freshness and uncertainty must be quantified before a target can be
considered for a downstream action.

#### Method

[estimate_instance_pose](web-control/server/vision/instance_pose.py) erodes the mask by `3 px` by
default, requires at least `80` valid points, rejects outliers using coordinate-wise medians and
`3.5×MAD`, transforms into `robot_base`, takes a median center, and adds a `0.002 m` noise floor to
the sample covariance. The identity layer requires valid calibration, pose age ≤`200 ms`, maximum
position standard deviation ≤`0.025 m`, and at least 2 pose hits. The general
[Safety](web-control/server/vision/safety.py) layer also checks calibration agreement, point count,
workspace bounds, and explicit reachability. The online page additionally forces
`actionable:false` and execution false.

#### Protocol

Use static and repeated-placement sequences with ground truth, sliced by material, distance, radial
position, and occlusion. Compare the bounding-box center, mask mean, mask median, and
erosion/MAD/noise-floor ablations. Freeze calibration, workspace, freshness, and reachability rules;
record rejected samples rather than deleting failures.

#### Metrics

3D position error and per-axis bias, static jitter, covariance calibration/coverage, valid point
count, actionability acceptance/rejection rate, false-pass rate, rejection-reason distribution,
and P50/P95 latency.

#### Evidence

Unit and synthetic tests cover sparse depth, outliers, covariance, and fail-closed reasons. Real
base-frame accuracy remains Planned Evidence. Planned previews V1/V3/F1 become results only after
they link a manifest and exact generation command.

#### Limits

Covariance represents the spread of observed points and does not automatically include every
systematic extrinsic error. There is currently no accepted complete calibration chain or collision
planner. `actionable` describes perception conditions; it is not robot execution authorization.

---

<a id="tutorial-04-vla-interaction"></a>

## 4. VLA, Voice, and Human–Machine Interaction

### 4.1 Advice, not execution authority

[VLAClient](src/uiea_thirdhand_vla/reasoning/vla_client.py) sends an image and structured context to
an Anthropic, DeepSeek, or OpenAI-compatible provider and returns `VLARecommendation`: action,
target, confidence, reasoning, recovery, or clarification. The
[tools](src/uiea_thirdhand_vla/reasoning/vla_tools.py) exposed to the model can only select an object,
request clarification, and recommend recovery. There is no joint, CAN, or SDK tool. Secrets are
read only from environment variables; see [.env.example](.env.example). They must never enter logs,
datasets, or Git.

The current packaged FSM consumes a recommendation when multiple targets are present. An API
failure falls back to the first detection. That behavior is suitable only for an experimental
framework with no real control authority and is not a safe VLA execution policy. A research path
should record timeouts, unknown targets, low confidence, and unsupported actions as refusal or
clarification, never as an implicit choice of the first object.

### 4.2 ASR, NLU, TTS, and Voice Bridge are two separate paths

| Path | Current status | Data flow | Control privilege |
| --- | --- | --- | --- |
| `src/.../interaction` | Planned/framework | ASR → NLU `Intent` → FSM; text → TTS | ASR/NLU/TTS methods are not fully implemented |
| Jetson Voice Bridge | Experimental; isolated tests partly Verified | WhisperASR (audio) → ClaudeAgent → response + candidate | Does not import RobotExecutor or connect to robot `/ws` |
| Browser text input | Implemented in Voice Protocol v1 | `text.submit` enters ClaudeAgent directly without ASR | Shares the candidate, preview, and confirmation boundary with voice input |

The [ASR/TTS configuration](configs/asr_tts.yaml) describes faster-whisper, Chinese, 16 kHz, local
NLU, and edge-tts, but configuration does not imply the modules are complete. The production-style
Bridge's final-only baseline sends no partial transcript and plays no TTS; `assistant.response`
displays text only. See [Voice Protocol v1](web-control/docs/voice-protocol-v1.md) and the
[Voice Bridge README](web-control/voice-bridge/README.md) for protocol and deployment details.

### 4.3 Structured candidates, preview, and confirmation

```text
audio/text/image
  → transcript / grounded context
  → structured intent.candidate
  → schema + whitelist + range validation
  → local 3D preview and audit log
  → explicit human confirmation
  → deterministic local safety validation
  → supervised platform consideration (still no execution at present)
```

Candidate handling uses deterministic validation that remains local and rule-based. A Voice v1
candidate contains `candidateId`, `intent`, `tool`, `sourceText`,
`requiresConfirmation`, and `args`. The web whitelist covers only restricted status/preset/gripper
candidates. Arbitrary joint angles, raw servo, network configuration, and similar intents must stay
disabled. Even after a user clicks Confirm, the current prototype only updates the local 3D preview
and log; it does not send anything to robot `/ws`. Unsupported intents, unknown parameters, stale
candidates, disconnection, model timeout, or multiple concurrent sessions must be rejected
explicitly.

### 4.4 Falsifiable questions for the secondary VLA research track

Track B compares direct free-form text output (an offline-only unsafe baseline), a structured
candidate, candidate+preview, and candidate+preview+human confirmation+local validation. Metrics
include task/intent accuracy, schema validity, unsupported-action rate, unsafe-action interception,
human correction, refusal quality, recovery success, and end-to-end latency. The free-form baseline
must never connect to an actuator, CAN, or a real robot. See the
[baseline matrix](docs/research/baseline_ablation_matrix.md) for the protocol.

Recordings, transcripts, images, and cloud prompts can contain personal or site information. A
dataset must document consent, de-identification, access control, retention, third-party API
transfer, and deletion procedures. When the network is unavailable, retain an offline mock or
refuse; do not bypass candidate validation.

---

<a id="tutorial-05-control-safety"></a>

## 5. Control, Orchestration, and Safety

### 5.1 Deterministic orchestration

The main path of [StateMachine](src/uiea_thirdhand_vla/orchestration/state_machine.py) is:

```text
IDLE → DETECT → APPROACH → GRASP → LIFT → TRANSFER → PLACE → RETURN → SUCCESS
          ↘ ERROR ←──────────────────────────────────────────────┘
EMERGENCY_STOP → IDLE (software state transition only; it does not mean a hardware emergency stop has been reset)
```

[CentralControlUnit](src/uiea_thirdhand_vla/orchestration/central_control.py) is a facade between
the FSM and camera, detector, robot, gripper, and safety components. Joint/pose commands undergo
local checks before reaching an adapter. The current FSM's `IDLE` state automatically enters
`DETECT`, and the control adapter is not a real-hardware implementation. Therefore the packaged
`full` mode must not be used on unattended hardware. The real fixed A/B workflow uses a separate runner, fixed
configuration, and manual confirmation at every step; see
[FIXED_PICK_PLACE.md](web-control/FIXED_PICK_PLACE.md).

### 5.2 Control adapters and CAN ownership

The real path has exactly one CAN owner:

```text
Browser /ws → proxy.js → startouch-bridge.js → startouch_bridge.py
             validation     child lifecycle      SDK + can0 + feedback
```

Outside simulate/dry-run mode, the bridge attempts a nonblocking lock on
`/tmp/startouch-web-<interface>.lock` using `flock`; failure rejects the connection. The fixed-point
launcher also
scans real controller processes, locks, worktree file use, branch, CAN UP/1 Mbps state, taught
points, segment-to-segment jumps, and the log directory. A resource lock cannot exclude every
incorrect program outside this repository, so on-site process auditing and a hardware emergency
stop remain necessary.

### 5.3 Layered gates and fail closed

| Layer | Required condition | Failure behavior | Implementation |
| --- | --- | --- | --- |
| Input | Six joints/pose/timestamp are finite and have correct shape/units | Reject message | [bridge](web-control/server/startouch_bridge.py), [vision types](web-control/server/vision/types.py) |
| Resource | Exclusive CAN lock, stable bridge state, no concurrent motion | Do not connect or enqueue | [Startouch bridge](web-control/server/startouch_bridge.py) |
| Motion | Joint limits, speed/time, no unexpected all-zero target | Reject target | [Node config](web-control/server/config.js) |
| Camera | Correct logical roles, fresh frames, skew within limits | Report blocker only | [online frames](web-control/server/vision/online_frames.py) |
| Geometry | Valid calibration, sufficient depth, synchronized robot pose | Do not produce a trusted base pose | [dual camera](web-control/server/vision/dual_camera.py) |
| Identity | Unambiguous, confirmed, fresh, covariance within limits | `actionable:false` | [identity](web-control/server/vision/identity.py) |
| Authorization | Task checkpoint, safety fields, human gate, and execution switch | Reasons such as `robot_execution_disabled` | [grasp authorization](web-control/server/grasp-authorization.js) |

The online status page sanitizes source objects again and forces them non-actionable. The
[configuration](configs/vision/remind3d.yaml) must retain `stop_and_look_only: true`,
`task_checkpoint_validated: false`, and `robot_execution_enabled: false`. These blockers are the
correct safe result, not errors to “fix.”

### 5.4 Software stop versus hardware emergency stop

- **Task stop**: prevents later stages; it does not guarantee that ongoing physical motion is
  immediately de-energized.
- **Software stop**: asks the bridge to call SDK `cleanup()` and disable motors, then releases the
  lock. It depends on a functioning process, operating system, CAN path, and SDK. A page may stop
  only the process group it owns.
- **Hardware emergency stop/power isolation**: independent of the browser, network, and code; this
  is the first choice when people or equipment are at risk.

If a Stop button, Ctrl+C, or software emergency-stop request does not produce an explicit completion
acknowledgment, treat the stop as unconfirmed: use the hardware emergency stop, isolate power, and
inspect logs/CAN/physical state. Do not restart while the cause is unknown.

### 5.5 Why control is not the current SCI novelty

The Startouch bridge, fixed-point runner, and resource gates are infrastructure that makes vision
and VLA experiments supervised and reproducible. A paper cannot relabel a vendor SDK wrapper,
fixed A/B points, or existing safety checks as a vision-algorithm contribution. Optional Track C
studies how perception uncertainty changes candidates, refusals, and recovery; the robot is only a
supervised validation platform.

---

<a id="tutorial-06-code-map"></a>

## 6. Code Map and Runtime Interfaces

### 6.1 Selected directory tree

```text
TH-Fanxy/
├── src/uiea_thirdhand_vla/       # installable experimental Python framework
│   ├── config/ perception/ reasoning/ interaction/
│   ├── orchestration/ control/ logging/ web/
├── web-control/                  # Startouch hardware boundary, cameras, vision, voice, and web UI
│   ├── server/{vision,vision_models}/
│   ├── web/  voice-bridge/  scripts/  demo/
├── configs/                      # robot/camera/workspace/VLA/Web/task/vision YAML
├── scripts/                      # deployment, replay models, fixed demo, and diagnostic entry points
├── tests/                        # offline docs/core/web/vision-deployment contracts
└── docs/                         # architecture, APIs, safety, vision research, and SCI evidence layer
```

### 6.2 `src/uiea_thirdhand_vla`: installable application

| Module | Responsibility/interface | Dependencies | Safety boundary and deep link |
| --- | --- | --- | --- |
| `config` | Merge YAML; Pydantic configuration models | PyYAML/Pydantic | The loader currently suppresses parse exceptions; [code](src/uiea_thirdhand_vla/config/loader.py) |
| `perception` | Camera, SEUCM, ArUco/YOLO, pixel↔base | OpenCV/NumPy/optional Ultralytics | Default identity hand–eye transform is not valid for hardware; [module](src/uiea_thirdhand_vla/perception/) |
| `reasoning` | `reason()`/`reason_sync()` → `VLARecommendation` | Cloud API/HTTP/Pillow | Advisory only; [client](src/uiea_thirdhand_vla/reasoning/vla_client.py) |
| `interaction` | `ASREngine`, `NLUEngine`, and `TTSEngine` contracts | voice extras | Current methods are incomplete; [module](src/uiea_thirdhand_vla/interaction/) |
| `orchestration` | FSM, CCU, task base | perception/control | Deterministic transitions; packaged full starts automatically; [module](src/uiea_thirdhand_vla/orchestration/) |
| `control` | Robot/Gripper/Safety adapters | No vendor SDK wiring at present | Not evidence of real control; [module](src/uiea_thirdhand_vla/control/) |
| `logging` | Run metadata, transitions, optional frames | Standard library/OpenCV | Logs must not contain secrets; [module](src/uiea_thirdhand_vla/logging/) |
| `web` | FastAPI app/static/API router files | web extras | Routers/WS are not mounted in the current app; [server](src/uiea_thirdhand_vla/web/server.py) |

### 6.3 `web-control`: hardware, vision, and interaction boundaries

| Module | Responsibility/interface | Dependencies | Safety boundary and deep link |
| --- | --- | --- | --- |
| `server/proxy.js` | Static UI, `/ws`, camera and vision HTTP | Node/Express/ws | Validation before motion; vision execution forced false; [code](web-control/server/proxy.js) |
| Startouch bridge | JSON Lines, CAN preflight, SDK state/trajectory/gripper | vendor SDK/SocketCAN | Per-interface lock, feedback watchdog, cleanup; [Python](web-control/server/startouch_bridge.py) |
| camera bridge | D435 owner, MJPEG, optional online-model events | pyrealsense2/OpenCV | Does not open CAN/robot; [code](web-control/server/camera_bridge.py) |
| `vision` | Geometry, registration, tracking, identity, pose, safety, replay | NumPy/SciPy | Pure computation; rejects invalid/stale/ambiguous input; [directory](web-control/server/vision/) |
| `vision_models` | RTMDet, DINO, online/replay adapters | Torch/MMDetection/Transformers | Lazy heavy imports, execution false; [directory](web-control/server/vision_models/) |
| Lumos HTTP | `/health`, `/frame.jpg`, `/camera_lumos` | OpenCV/V4L2 | Camera read-only, frame sequence and monotonic header; [service](web-control/server/lumos_http_server.py) |
| Voice Bridge | `/v1/voice`, audio/text candidates | websockets/existing voice_agent | No RobotExecutor or robot WS; [README](web-control/voice-bridge/README.md) |
| fixed runner/demo | simulate/dry-run/real, loopback page | bridge/YAML | Stepwise confirmation, resource preflight, 30% hard cap; [guide](web-control/FIXED_PICK_PLACE.md) |

### 6.4 `configs`: configuration is not acceptance evidence

| File/deep link | Responsibility/interface | Dependency/reader | Safety boundary |
| --- | --- | --- | --- |
| [robot.yaml](configs/robot.yaml) | General model, CAN, TCP, home, gripper | packaged config loader/models | Ranges differ from the hardware-integrated Web ranges |
| [camera.yaml](configs/camera.yaml) | Lumos device, pixels, SEUCM/depth fields | packaged Camera/models | Actual defaults still require wiring verification |
| [workspace.yaml](configs/workspace.yaml) | Base-frame bounds, tabletop, speed, timeout | packaged config contract | Do not assume every entry point applies it uniformly |
| [asr_tts.yaml](configs/asr_tts.yaml) | ASR/NLU/TTS/microphone | packaged interaction | Interaction is not fully implemented |
| [vla.yaml](configs/vla.yaml) | Provider/model/image/session/trigger | VLA client/FSM | Advisory layer with no execution authority |
| [web.yaml](configs/web.yaml) | `0.0.0.0:8000`, WS/video | packaged FastAPI | Routers/WS are not mounted |
| [fixed_pick_place.yaml](configs/tasks/fixed_pick_place.yaml) | Points, limits, speed, lift, confirmation, validation count | fixed runner/demo | Real mode remains gated by the bridge and human process |
| [remind3d.yaml](configs/vision/remind3d.yaml) | Roles, models, timing, identity, pose, budgets, safety | vision/vision_models/launcher | Permissive v1 config; execution fixed false |
| [active_view.yaml](configs/vision/active_view.yaml) | Dry-run observation-proposal parameters | active-view dry-run modules | `active_view_execution_enabled:false`; this is not motion capability |

### 6.5 `scripts` and supported entry points

| Entry point/deep link | Responsibility/interface | Dependencies | Safety status |
| --- | --- | --- | --- |
| [packaged CLI](src/uiea_thirdhand_vla/__main__.py) | `thirdhand-vla` / `python -m`; `camera/detect/pick_place/web/full` | Python extras/configs | Experimental; not a hardware guide |
| [setup_ubuntu.sh](web-control/scripts/setup_ubuntu.sh) | Check environment and run `npm ci` | Ubuntu/Node/npm/optional SDK | L0; does not modify system packages |
| [start_ubuntu.sh](web-control/scripts/start_ubuntu.sh) | Start the Node Web stack | Node, optional SDK/CAN/camera | L2 simulate or supervised L4 hardware |
| [bootstrap_remind3d_env.sh](scripts/vision/bootstrap_remind3d_env.sh) | Print/install a separate CUDA model environment | Conda/pip/CUDA | L0; for the model host |
| [vision replay](web-control/server/vision/replay.py) / [identity replay](web-control/server/vision_models/offline_replay.py) | Deterministic synthetic geometry/identity replay | NumPy/SciPy/fixture | L1, no hardware |
| [smoke_remind3d_models.py](scripts/vision/smoke_remind3d_models.py) | RTMDet+DINO resource/contract smoke | model env/local image weights | L1/L3, read-only image and GPU |
| [start_dual_camera_online.sh](scripts/vision/start_dual_camera_online.sh) | Safe lifecycle on port 3100 | Lumos HTTP/D435/model env/Node | L3, fixed simulate/fake CAN/no gripper |
| [verify_dual_camera_online.py](scripts/vision/verify_dual_camera_online.py) | One-second sampling and atomic readiness JSON | HTTP status/Python | L3, read-only |
| [demo_fixed_pick_place.sh](scripts/demo_fixed_pick_place.sh) | Manual fixed-point demo wrapper | branch/CAN/owner/points/path/lift/YAML/bridge | The tutorial's only L4 entry point; defaults to `manual` with per-step confirmation from configuration |
| [open_fixed_pick_place_control.sh](scripts/open_fixed_pick_place_control.sh) | Loopback 8766 operator page | Python/demo runner | Experimental, not a tutorial entry point; auto route lacks a hard gate |
| [fixed_pick_place.py](web-control/scripts/fixed_pick_place.py) | Low-level simulate/dry-run/real runner | YAML/Startouch bridge | May be called directly for L2 simulate/dry-run; real mode is internal to the wrapper only |
| [teach_fixed_point.py](web-control/scripts/teach_fixed_point.py) | Read/validate/atomically save J1–J6 points | real bridge/YAML | L4; backs up the old YAML |
| [check_hardware.py](scripts/check_hardware.py), [calibrate_camera.py](scripts/calibrate_camera.py), [teach_points.py](scripts/teach_points.py) | Early script scaffolds | Currently print using only the standard library | Planned; do not perform complete automated checks/calibration/teaching |

### 6.6 `tests`: what they verify and what they do not

| Area | Responsibility/interface | Dependencies | Safety meaning |
| --- | --- | --- | --- |
| [tests/docs](tests/docs/) | README, links, identity, schema contracts | pytest | Prevents documentation from presenting plans as results |
| [tests/web](tests/web/) | Fixed demo and UI safety source contracts | pytest | Does not start real CAN |
| [tests/vision_deployment](tests/vision_deployment/) | Static/unit environment, launch, and bridge contracts | pytest | Enforces fake CAN and execution false |
| [server/tests/vision](web-control/server/tests/vision/) | SE(3), SEUCM, registration, tracking, memory, safety | NumPy/SciPy/pytest | Pure offline core |
| [server/tests/vision_models](web-control/server/tests/vision_models/) | Model adapter/replay/online fake | pytest; lazy heavy-model loading | Unit tests do not establish task-model effectiveness |
| [server/test](web-control/server/test/) | Node protocol/browser/vision smoke | Node/npm | mock/simulate, no real motion |

### 6.7 `docs`: sources of facts and evidence

| Area | Responsibility/interface | Dependency | Deep link |
| --- | --- | --- | --- |
| Architecture/setup/API/modules | Two boundaries, system dependencies, interface contracts | Must be checked against current source | [architecture](docs/architecture.md), [setup](docs/setup_guide.md), [web API](docs/web_api.md) |
| `vision_research` | Design, audits, implementation/deployment records, acceptance plan | Dated and may become stale after deployment changes | [current decision](docs/vision_research/14_FINAL_TECHNICAL_DECISION.md) |
| `research` | Claim/dataset/experiment/result/figure/reproduction contracts | Machine-readable artifacts | [evidence hub](docs/research/README.md) |
| Safety documents | Startouch and fixed-demo operational boundaries | On-site supervision | [Web README](web-control/README.md), [fixed demo](web-control/FIXED_PICK_PLACE.md) |

### 6.8 Environment-variable index

| Variable | Default/example | Purpose and safety note |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `OPENAI_BASE_URL` | Local `.env` only | Cloud VLA; never commit or include in a dataset |
| `THIRDHAND_WEB_HOST` / `THIRDHAND_WEB_PORT` | `0.0.0.0` / `8000` | Override names declared by `.env.example`; current loader/server do not read them, so do not rely on them |
| `STARTOUCH_PYTHON` / `STARTOUCH_SDK_PATH` | LumosTouch env / `~/arm/startouch_sdk` | The external SDK does not enter the repository |
| `STARTOUCH_CAN_INTERFACE` | `can0` | Offline tests must replace this with a fake name such as `thirdhand-test` |
| `STARTOUCH_SIMULATE` / `STARTOUCH_DRY_RUN` | `0` / `0` | simulate does not import the SDK; dry-run checks imports but does not control hardware |
| `STARTOUCH_SPEED_SCALE` | `0.05` | Web scale is clamped to `[0.01,1]`; the real fixed runner has a separate `0.30` hard cap |
| `STARTOUCH_REQUIRE_CAN_RX` / `STARTOUCH_CAN_RX_STALE_SEC` | `1` / `1` | Do not casually disable the feedback watchdog in real operation |
| `WEB_HOST` / `WEB_PORT` | `0.0.0.0` / `3000` | Startouch Node listener |
| `CAMERA_ENABLED` / `CAMERA_PYTHON` | enabled / REMIND env | D435 bridge and model Python |
| `CAMERA_YOLO_MODEL` / `CAMERA_CALIB_FILE` | Local weights/local calibration | File existence does not establish task/calibration acceptance |
| `VISION_ONLINE_ENABLED` / `VISION_CONFIG` | `0` / REMIND YAML | Read-only online-model switch and configuration |
| `LUMOS_HTTP_HOST` / `LUMOS_HTTP_PORT` | `0.0.0.0` / `3001` | Lumos camera-only HTTP |
| `LUMOS_SNAPSHOT_URL` / `LUMOS_STREAM_URL` | loopback `:3001` | Online-model snapshot/browser MJPEG sources |
| `VOICE_HOST` / `VOICE_PORT` | `127.0.0.1` / `3001` (mock) | Mutually exclusive with Lumos TCP on the same host |

See the [Web README](web-control/README.md) for additional bridge tuning variables. Without an
acceptance record, never use tuning to bypass stale-state, initial-state matching, or speed gates.

### 6.9 HTTP, REST, and WebSocket

| Boundary/transport | Paths and default bind | Authentication | Control privilege and safety gates | Stop semantics | Maturity |
| --- | --- | --- | --- | --- | --- |
| packaged FastAPI HTTP/WS | Configured as `0.0.0.0:8000`; documentation lists `/api/robot/*`, `/api/camera/*`, `/api/task/*`, `/ws` | No effective authentication wiring is visible in the current app; CORS is `*` | Router files exist, but `create_app()` does not mount them, so the running app cannot obtain actual control privilege | Only task/robot stop contracts exist in interface files; a running app cannot rely on them | Experimental interface contract, not a usable production API |
| Startouch Node HTTP | `0.0.0.0:3000`; `/`, `/diag`, `/camera`, `/camera_lumos`, `/camera_lumos_vision`, `/api/vision/status` | None | Static pages and read-only vision status; actual control uses `/ws` on the same service | HTTP routes provide no hardware emergency stop | Experimental; controlled networks only |
| Startouch Node WebSocket | `ws://<host>:3000/ws` | None; there is also no per-client ownership/authorization | Every connected client can submit the exact command set accepted by the shared bridge: `connect`, `disconnect`, `servo`, `preset`, `gripper`, `software_stop`, `status`, `ping`, `estop`, `grasp_object`, `estop_camera`, `camera_refresh`. Motion still passes joint-limit, stable-initial-state, CAN feedback/watchdog, motion-active, and queue-serialization checks, but these are concurrency safety gates—not access control or caller ownership | `software_stop` invokes an SDK software stop; `estop` is only its alias and is **not a hardware emergency stop**; `disconnect` cleans up the shared bridge; `estop_camera` stops only the camera bridge | Real control boundary; even on a controlled network, clients affect one another. L4 relies on the on-site procedure to ensure one operator client; the software does not currently enforce it. Unauthenticated—never expose to an uncontrolled network |
| Lumos HTTP | `0.0.0.0:3001`; `/health`, `/frame.jpg`, `/camera_lumos` | None | Camera-only and read-only; frames carry sequence/monotonic headers and gain no robot privilege | Ctrl+C/process termination stops only the camera service | L3 read-only; rebind to loopback as shown in this tutorial |
| Voice Bridge WebSocket | Default `0.0.0.0:3001/v1/voice`, subprotocol `thirdhand.voice.v1` | None | audio/text → response/candidate; by design has no RobotExecutor and does not connect to robot `/ws` | `session.stop`/disconnect ends only the voice session and does not stop the robot | Experimental candidate layer; controlled networks only, and cannot share TCP 3001 with Lumos on one host |
| fixed demo HTTP | `127.0.0.1:8766`; GET `/api/status`; POST `/api/start`, `/api/start-auto`, `/api/stop`, `/api/continue` | None, but loopback by default | Owns only the runner it starts; `/api/start` is manual, `/api/continue` releases the next step, and `/api/start-auto` can start three automatic cycles | `/api/stop` stops only the runner owned by the page; it neither terminates unrelated controllers nor replaces a hardware emergency stop | Experimental and not a tutorial entry point; `/api/start-auto` still lacks an implementation-level hard gate when `validated_real_cycles: 0` and `require_step_confirmation: true`, so it is disabled for L4 |

`grasp_object` currently fails closed through an authorizer with `execution=false` and cannot trigger
a grasp. `estop_camera` closes only the camera bridge; `camera_refresh` requests camera state only.
The presence of a command name in the protocol does not grant execution privilege, and no software
stop message is equivalent to an independent hardware emergency stop or power isolation. The
Startouch bridge's per-CAN-interface `flock` excludes other controller processes only; it does not
exclude another browser client within the same Node process. Multiple clients can affect the shared
connection and robot state.

### 6.10 Model and runtime-artifact policy

Model weights (`*.pt`, `*.pth`, `*.onnx`), Hugging Face/cache contents, the vendor SDK, and API keys
are local deployment assets. Record source, license, and SHA-256 in a manifest; do not commit them.
There is no authoritative in-repository download URL for a project-specific RTMDet checkpoint, so
an unrelated weight must not be substituted and presented as the task model. See the
[model asset policy](docs/model_assets.md).

Logs, PID files, taught-point backups, calibration output, captured frames, complete datasets,
readiness reports, and generated figures are also runtime artifacts. Store them in a controlled
artifact store or gitignored directory. Small de-identified deterministic test fixtures may be
versioned. Every publication figure must be generated from machine-readable JSON/CSV, never edited
manually.

---

<a id="tutorial-07-hands-on"></a>

## 7. L0–L4 Hands-On Tutorial

Each level grants an independent scope of authorization. Completing L2 does not authorize L3,
much less physical motion. Commands run from the repository root unless stated otherwise. Before
starting, record `git rev-parse HEAD` and `git status --short`; do not overwrite calibration,
configuration, or another person's runtime artifacts in a dirty working tree. In every new
terminal, first enter any directory inside this checkout and then run
`cd "$(git rev-parse --show-toplevel)"`. The multi-terminal procedures below repeat that command
explicitly.

### L0: reading, installation, and preparation (no hardware privilege)

**Prerequisites:** Ubuntu 20.04/22.04 and Python ≥3.10; the Web stack additionally requires
Node ≥18/npm. See [pyproject.toml](pyproject.toml) and the [setup guide](docs/setup_guide.md) for
complete dependencies.

```bash
git clone https://github.com/Chenxi-Li24/UIEAclub_ThirdHand_VLA.git
cd UIEAclub_ThirdHand_VLA
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e ".[core,dev,web]"
python -c "import uiea_thirdhand_vla; print(uiea_thirdhand_vla.__version__)"
node --version
npm --version
```

To understand the model environment without installing it:

```bash
bash scripts/vision/bootstrap_remind3d_env.sh --print-plan
```

**Expected observations:** the package imports, version commands work, and the environment plan
shows a separate `thirdhand-remind3d` without modifying LumosTouch/system Python.

**Forbidden:** fill in and commit an API key; add downloaded weights to Git; present a configuration
default as a calibration or acceptance result; start CAN, the real SDK, or a camera service at L0.

**Stop conditions:** Python/Node versions are unsupported, a dependency comes from an unauditable
source, or installation attempts to overwrite the system/existing robot environment. Repair the
isolated environment first; do not use `--break-system-packages`.

**Evidence to retain:** commit, OS/Python/Node/npm versions, pip lock/checksum, installation command
and stderr, and model source/license/hash if acquired.

### L1: offline verification and deterministic replay (no hardware privilege)

**Prerequisites:** complete L0. It is not necessary to prove that no process owns real `can0`
because the following commands explicitly use a fake interface or pure computation, but the fake
interface override must never be removed.

```bash
.venv/bin/ruff check src/ tests/
.venv/bin/mypy src/
STARTOUCH_CAN_INTERFACE=thirdhand-test \
  .venv/bin/python -m pytest tests/ -q --ignore=tests/e2e/
PYTHONPATH=web-control/server \
  .venv/bin/python -m pytest \
  web-control/server/tests/vision \
  web-control/server/tests/vision_models -q
```

Geometry/gate replay and identity replay:

```bash
PYTHONPATH=web-control/server .venv/bin/python -m vision.replay \
  --manifest web-control/server/tests/vision/fixtures/synthetic_replay.json \
  --output /tmp/thirdhand-vision-replay.json
PYTHONPATH=web-control/server .venv/bin/python -m vision_models.offline_replay \
  --manifest web-control/server/tests/vision_models/fixtures/remind3d_observations.json \
  --output /tmp/thirdhand-identity-replay.json
```

**Expected observations:** tests pass; repeated runs on the same input produce byte-stable or
semantically identical metrics; output includes a calibration ID, frames, identity/registration/
Dry Run metrics, and rejection reasons. Fixture numbers validate the computational pipeline only.

**Forbidden:** report `/tmp` fixture numbers as real-camera accuracy; write a fake `calibration_id`
into a deployment; remove monotonic-time, relative-path, or execution-field rejection checks.

**Stop conditions:** any test fails, output contains NaN or an absolute escaping path, two replays
differ, or a CAN/Startouch/WebSocket action dependency appears. Diagnose the offline cause; do not
connect hardware “to see whether it works.”

**Evidence to retain:** complete commands, exit codes, pytest/JUnit output, both JSON files and their
SHA-256, dependency lock, seed, and commit.

### L2: simulated/dry-run Web UI and voice mock (no real CAN motion)

**Prerequisites:** complete L1; ports 3000/3001 are not occupied by unrelated processes. The
simulated Web stack does not require the vendor SDK.

```bash
STARTOUCH_SIMULATE=1 web-control/scripts/setup_ubuntu.sh
CAMERA_ENABLED=0 STARTOUCH_SIMULATE=1 \
  web-control/scripts/start_ubuntu.sh
```

Open `http://127.0.0.1:3000`. Verify that the six-joint model, connect/servo/preset, gripper, and
software stop change simulated state only. To verify a dry-run that can import but cannot control
the SDK, a matching SDK ABI must already be available:

```bash
CAMERA_ENABLED=0 STARTOUCH_DRY_RUN=1 \
STARTOUCH_SDK_PATH="$HOME/arm/startouch_sdk" \
  web-control/scripts/start_ubuntu.sh
```

Fixed-point software validation uses the repository fixture and must never include `--real`:

```bash
.venv/bin/python web-control/scripts/fixed_pick_place.py \
  --simulate --config tests/fixtures/fixed_pick_place_test.yaml
STARTOUCH_SDK_PATH="$HOME/arm/startouch_sdk" \
  "$HOME/miniconda3/envs/LumosTouch/bin/python" \
  web-control/scripts/fixed_pick_place.py \
  --dry-run --config tests/fixtures/fixed_pick_place_test.yaml
```

Voice Protocol automated smoke (exits) and interactive mock (stays running):

```bash
cd "$(git rev-parse --show-toplevel)"
npm --prefix web-control/server run test:voice-protocol
VOICE_HOST=127.0.0.1 VOICE_PORT=3001 node web-control/server/test/voice-mock.js
```

**Expected observations:** the simulated Web UI reports simulated/dry-run status only; the protocol
smoke receives audio/text events in order; the mock displays a candidate and, after browser
confirmation, still updates only the preview/log.

**Forbidden:** simultaneously enable normal hardware mode; forward a voice candidate to `/ws`;
replace the test fixture with real taught points; expose an unauthenticated mock to the Internet.

**Stop conditions:** any process attempts to open `can0`, a candidate directly triggers a robot
command, a port resolves to the wrong host, or software stop cannot terminate the simulated
process. End processes you started with Ctrl+C and preserve their logs.

**Evidence to retain:** Node/Python versions, protocol output, browser/mock screenshots labeled as
simulation, candidate/confirmation/refusal logs, ports, and PIDs.

### L3: online dual-camera read-only service (camera privilege, no motion privilege)

**Prerequisites:** on-site permission to read Lumos and D435; the exact model environment prepared
according to the [model asset policy](docs/model_assets.md); visible USB devices; free ports
3001/3100; explicit acceptance that the launcher binds 3100 to `0.0.0.0`. Robot execution
configuration must remain false.

In a dedicated terminal, start the camera-only Lumos service, which has no CAN/Startouch dependency:

```bash
cd "$(git rev-parse --show-toplevel)"
LUMOS_HTTP_HOST=127.0.0.1 LUMOS_HTTP_PORT=3001 \
  "$HOME/miniconda3/envs/thirdhand-remind3d/bin/python" \
  web-control/server/lumos_http_server.py
```

In a second terminal, run read-only preflight, start the service, and execute the short verifier:

```bash
cd "$(git rev-parse --show-toplevel)"
curl --fail http://127.0.0.1:3001/health
bash scripts/vision/start_dual_camera_online.sh --background
bash scripts/vision/start_dual_camera_online.sh --status
"$HOME/miniconda3/envs/thirdhand-remind3d/bin/python" \
  scripts/vision/verify_dual_camera_online.py \
  --base-url http://127.0.0.1:3100 \
  --duration-seconds 60 \
  --output /tmp/thirdhand-dual-camera-readiness.json
```

Open `http://127.0.0.1:3100/camera-test.html`. At the end, stop only the port-3100 process whose
ownership the launcher verified, then use Ctrl+C in the Lumos terminal:

```bash
bash scripts/vision/start_dual_camera_online.sh --stop
```

**Expected observations:** roles are strictly Lumos canonical RGB, D435 metric depth, and D435
debug RGB; both sequences advance, the model is ready, status is non-stale, and
`robotExecutionEnabled` remains false. When valid calibration, a robot pose, or a task checkpoint
is missing, the target remains non-actionable. That is the correct result.

**Forbidden:** start a second D435 owner; connect a real Startouch controller; edit the execution
flag; filter blockers out of output; expose 3100 to an uncontrolled network; call the read-only page
a grasp validation.

**Stop conditions:** incorrect roles, a stalled/regressing sequence, stale state, model failure,
GPU reserved >`7.2 GiB`, P95 latency >`300 ms`, or any execution true/CAN/robot/gripper I/O.
Immediately stop services owned by this task without killing unrelated PIDs.

**Evidence to retain:** readiness JSON and SHA-256, state samples, configuration/model/calibration
hashes, USB/driver/GPU versions, start/end times, blocker histogram, logs, and an explicit statement
of zero robot execution. Historical deployment numbers without intervals/statistical methods must
be labeled Evidence Incomplete rather than publication results.

### L4: supervised real hardware (explicit human gates)

**Prerequisites—all must hold before continuing:** L0–L3 evidence has been reviewed; Ubuntu/SDK ABI
matches; `can0` is UP at 1 Mbps; exactly one controller owner exists; points were taught locally and
reviewed one by one; neither the 15% demo speed nor 30% hard cap has been raised; the 25 cm lift path
was physically verified clear; the hardware emergency stop/power isolation is within reach; a
second person or equivalent on-site supervision is present; and the unvalidated count in
`configs/tasks/fixed_pick_place.yaml` will not be falsified manually.

First, inspect the interface and competing processes read-only:

```bash
cd "$(git rev-parse --show-toplevel)"
ip -details -statistics link show can0
ps -ef | rg 'startouch_bridge.py|proxy.js|fixed_pick_place.py|teach_fixed_point.py|ros2|move_group'
```

The only L4 launch entry point allowed by this tutorial is the wrapper in its default manual mode.
It checks the expected branch, CAN UP/1 Mbps, a unique controller owner, resource lock, taught
points, segments, 25 cm lift, limits, and configuration before starting the low-level runner:

```bash
bash scripts/demo_fixed_pick_place.sh
```

Keep the default `DEMO_RUN_MODE=manual`. The current configuration has
`validated_real_cycles: 0` and `require_step_confirmation: true`; the wrapper therefore requires
explicit terminal confirmation before every step. Do not use an environment variable to change
the mode or remove confirmation.

Real mode in `web-control/scripts/fixed_pick_place.py` is an internal interface used by the wrapper
and must not be invoked directly by an operator. Direct invocation bypasses branch, CAN, controller
resource, taught-point, path-segmentation, and lift preflight that exist only in the wrapper.
`scripts/open_fixed_pick_place_control.sh` and the `127.0.0.1:8766` page are also only Experimental
and are **not an L4 entry point in this tutorial**. The visible “three automatic cycles” action
confirms only once, calls `/api/start-auto`, and then performs no per-step confirmation. The current
implementation does not hard-reject that route under the unvalidated count and step-confirmation
configuration above. Do not open or use this UI or `/api/start-auto` until an implementation-level
fail-closed gate has been added and audited again.

This is not an unsupervised motion recipe. Do not use any automatic three-cycle entry point, run in
the background, remove confirmation, or reuse the wrapper command when nobody is on site.

**Expected observations:** the terminal reports that wrapper preflight passed and state is stable,
then waits for stdin confirmation at every step. Joint/CAN feedback remains live; each logical
route completes before the next begins; logs are written to `logs/fixed_pick_place/`.

**Forbidden:** open the fixed-demo UI; call `/api/start-auto` or any automatic route; invoke the real
Python runner directly; run the Web controller and fixed runner concurrently; use taught points
from the test fixture for real motion; skip taught-point/limit/branch/lock checks; raise speed;
operate unsupervised or remotely without sight; treat software Stop as a hardware emergency stop.

**Stop conditions:** any `RESOURCE_CONFLICT`, stale CAN, initial-state/feedback mismatch, unexpected
direction/sound/vibration, dropped object, nearby cable, person entering the workspace, broken
confirmation channel, or abnormal log. Press the on-site hardware emergency stop or isolate power;
if software still responds, then use Stop/Ctrl+C. Do not reset until the cause is known.

**Evidence to retain:** operator/observer, commit/config hash, point backup, CAN/SDK/robot versions,
per-stage timeline, speed, software/hardware stop events, complete logs, failure photographs/
descriptions, and the basis for any `validated_real_cycles` update. Never delete failure records.

---

<a id="tutorial-08-research-verification"></a>

## 8. SCI Verification, Troubleshooting, and Publication Path

### 8.1 Three research tracks

| Track | Role | Falsifiable question | Robot role | Current evidence status |
| --- | --- | --- | --- | --- |
| A: vision and 3D perception | Primary | Do timing/calibration/registration/instance memory/uncertainty improve held-out perception and safe rejection? | Read-only pose or supervised validation platform | Some engineering results; most SCI comparisons are Planned Evidence/Evidence Incomplete |
| B: verifiable VLA | Secondary | Does candidate+preview+confirmation+validator intercept more unsafe requests than weakly constrained baselines? | Offline baselines have no actuator; hardware is only a supervised platform | Planned Evidence |
| C: integrated vision–VLA | Optional | Does propagation of perception uncertainty improve long-horizon refusal, correction, and recovery? | Supervised system demonstration, not low-level control innovation | Planned Evidence |

### 8.2 From a claim to an auditable result

```text
falsifiable hypothesis
  → preregistered protocol/threshold/statistical plan
  → versioned dataset datasheet + split SHA-256
  → experiment manifest (commit/command/env/models/calibration/seeds)
  → raw machine-readable result records
  → baseline/ablation aggregation + uncertainty/statistics
  → generated figure/table + exact command
  → claim matrix + failure/threat review
  → methods/results/limitations in paper
```

[Experiment manifest v1](docs/research/schemas/experiment-manifest.schema.json) requires a schema
version, experiment/hypothesis/track, a 40-character commit, command array, environment, dataset,
models, calibration, seeds, UTC times, and artifacts.
[Result record v1](docs/research/schemas/result-record.schema.json) requires metric/value/unit/
aggregation/sample_count/confidence_interval/slice/source_artifact. Version 1 is intentionally
permissive: nested objects such as `hardware`, `models`, and `artifacts` do not enforce domain-specific
fields. Do not tighten the schema ad hoc in this tutorial; experiment protocols and the
reproducibility checklist supply missing domain details.

### 8.3 Dataset and protocol freeze

Complete a separate [dataset datasheet](docs/research/dataset_datasheet.md) for each corpus: hardware/
firmware, logical roles, clock and skew, calibration ID/residual, scene/object/material, annotation
and review policy, split/count/hash, leakage prevention, privacy/consent, license, retention, and
known bias. Synthetic, replay, live, and hardware-motion data must remain separate and must not be
silently pooled.

Training/validation/test splits should isolate session, scene, physical object identity, and
temporal clip so that adjacent frames or the same instance cannot leak. Transparent/black/reflective
objects, center/edge, occlusion/re-entry, stale/missing input, and calibration faults must remain as
test slices and failure-taxonomy categories.

### 8.4 Baselines, ablations, and metrics

| Research unit | Baseline/ablation | Primary metrics |
| --- | --- | --- |
| mask | YOLOv8n detect, YOLO-seg, RTMDet-ins, Mask R-CNN | box/mask AP/recall, radial, point purity, latency/resource |
| registration | none, no timestamp gate, full z-buffer | pixel/mm error, coverage, flying edge, 3D error/jitter |
| identity | IoU, appearance, appearance+3D, work/stable, ambiguity on/off | HOTA, IDF1, switch, fragment, reacquisition, false merge |
| pose/gate | bbox/mean/median, erosion/MAD/covariance/gate ablations | 3D error, jitter, coverage, false pass/rejection |
| VLA | free-form offline, candidate, +preview, +confirm+validator | accuracy, unsupported, interception, correction, refusal, recovery, latency |
| integrated | no uncertainty propagation versus full chain | completion, grounding, interception, recovery, end-to-end cost |

Hold split/calibration/model hash/hardware/input/seed/window fixed across comparisons, and change
only one factor per ablation. For classification/event proportions, report sample size and an
appropriate interval, such as a preregistered bootstrap or binomial interval. For continuous or
long-tailed latency, report P50/P95 and intervals. Choose the statistical unit according to object/
scene independence; where needed, use pairing/stratification and record multiple-comparison,
missing-value, and outlier policies. Do not report only a mean or the best seed.

### 8.5 Evidence status and preregistration readiness

| Situation | Correct label | May support an abstract claim? |
| --- | --- | --- |
| No measurement exists; only a plan/threshold location exists | Planned Evidence / 待补实验证据 | No |
| A smoke/sample/partial result exists, but sample size, CI, statistical method, or provenance is insufficient | Evidence Incomplete / 待补充证据 | No |
| No result exists and protocol/threshold/statistical plan is not frozen | Planned Evidence; separately record preregistration incomplete | No |
| Manifest/source/sample count/CI or justified null/statistical method/figure command are complete | Reportable evidence only as recorded by research review | Only after review |

Engineering Verified and “reportable scientific evidence” are not interchangeable. Keep failed
hypotheses, negative results, and protocol deviations in the
[claim matrix](docs/research/claim_evidence_matrix.md); do not delete them.

### 8.6 Figure-preview registry

Every row below is **Planned Evidence / 待补实验证据**. The rows describe future artifacts, not
blank result figures, and must never be populated with invented values. Source and generation-command
requirements are governed by the [figure manifest](docs/research/figure_manifest.md).

| ID | Planned content | Minimum source | Release gate |
| --- | --- | --- | --- |
| V1 | Lumos mask + D435 depth + base-frame 3D | Synchronized frames, calibration, mask, registered points, manifest | Command reproduces the panel without manual figure editing |
| V2 | Identity before/during/after occlusion and reacquisition | Held-out clip, IDs/cost/memory/annotations | Selection rule and identity truth frozen |
| V3 | Registration error, radial residuals, uncertainty | Correspondences, radial bins, covariance | Units/aggregation/exclusion/calibration ID complete |
| L1 | instruction→context→candidate→preview→confirmation/refusal | De-identified scenario and validator log | No secret or implication of successful execution |
| E1 | Baseline + confidence intervals | All result records, n, CI, slice | Matches preregistered baseline/interval method |
| E2 | Ablation table/curve | One-delta variants, seeds, source JSON/CSV | Controls complete |
| E3 | Accuracy–latency–resource trade-off | accuracy/P50/P95/FPS/CPU/GPU/VRAM | Hardware and measurement windows comparable |
| F1 | Paired success/failure cases | Predeclared selection rule and failure taxonomy | No cherry-picking; limitations visible alongside results |

### 8.7 Failure cases and validity threats

At minimum, report fisheye-edge domain shift, depth holes/flying edges, calibration drift, temporal
mismatch, false merging of similar instances, long-term lighting change, detector change,
out-of-domain task checkpoint, prompt/model drift, human-evaluator bias, network/API failure, GPU
thermal/resource variation, and the simulation-to-real gap. Internal validity concerns include
split leakage, non-independent frames, tuning on the test set, missing values, and selective
reporting. External validity concerns include a single hardware setup/site/object class. Construct
validity asks whether a proxy metric truly represents safety/completion. Statistical validity covers
small samples, intervals, multiple comparisons, and denominator definitions.

### 8.8 Troubleshooting: symptom → diagnosis → safe decision → recovery → evidence

| Symptom | Safe diagnosis | Decision | Recovery | Evidence that must be retained |
| --- | --- | --- | --- | --- |
| `can0 already controlled`/lock owner | Inspect PID, cmdline, cwd, and lock read-only; do not kill by pattern | Stop this connection/motion attempt | Let the real owner perform normal cleanup; verify lock release, then audit again | PID/cmdline/lock, time, owner log |
| Stale CAN feedback/initial-state mismatch | Check `ip -details -statistics`, bridge event, physical power/cable | Software stop; use hardware emergency stop if risk exists | Repair CAN/SDK, then repeat preflight from a low-risk state | RX counters, errors, cleanup/emergency-stop record |
| Lost Lumos or D435 role | Check `/health`, USB ID, status roles/sequences; do not guess from `/dev/videoN` | Stop L3 or degrade to non-actionable | Restore a single camera owner; verify roles and sequences again | USB/firmware, role map, before/after samples |
| Frame stale/skew exceeded | Inspect monotonic age, queues, pairing reasons, system load | Keep non-actionable; do not repeat an old frame | Clear the blocking consumer, restart only the read-only service you own, rerun verifier | Skew/age distribution, sequences, restart reason |
| Calibration invalid/mismatched | Check direction, hash, validated residual, and mounting change | Stop 3D/motion; RGB identity observation may continue | Recollect under the calibration plan, validate on a held-out set, and issue a new ID | Old/new artifact hashes, residual, operator |
| Invalid/insufficient depth | Check range, zero/NaN, mask erosion, valid-point count, material | Reject target; never substitute the tabletop plane | Change observation conditions/recalibrate and reacquire; do not lower thresholds to hide the fault | Depth/mask slice, point count, reason |
| Identity ambiguous/risk of false merge | Inspect global/alternative assignment costs, appearance/3D gate, memory quality | Reject/request clarification; do not guess an ID | Obtain a new view only through explicitly authorized read-only/active-view dry-run and confirm consecutively | Assignment, bank state, clip, annotation |
| Port occupied or wrong host | Use `ss -ltnp`; distinguish host/TCP; Voice and Lumos cannot both own 3001 on one host | Do not kill an unknown service or switch to an arbitrary public port | Stop a process you own, or change the explicit configured port and synchronize the UI | Listener PID, host/transport, configuration diff |
| Robot `/ws` failure | Distinguish Startouch `/ws` from Voice `/v1/voice`; inspect subprotocol/events | Do not resend motion or bypass confirmation as fallback | After reconnecting, request `status` first; have a human reassess the expired candidate | Close code, last command ID, robot state |
| Voice WebSocket/LLM failure | Check `thirdhand.voice.v1`, path, ping/pong, error code | Candidate invalid; never turn text into direct control | Reproduce with offline mock; after recovery, create a new session and do not replay old audio | Session/message IDs, event order, error code |
| Missing/incompatible weights | Verify local path, label metadata, SHA-256, license/cache | Model unavailable; execution locked | Obtain correct weights from a reviewed source or retrain; rerun smoke | Source/license/hash/config/model smoke |
| GPU OOM/insufficient capacity | Inspect reserved/allocated, device, concurrent models, input scale | Stop online models; do not move to CPU and claim the same protocol's performance | Reduce preregistered load/scheduling or change hardware, then compare again | GPU/driver, memory trace, configuration, latency |
| P95 latency exceeds limit | Decompose capture/pair/model/register/UI; inspect latest-only and thermal state | Keep non-actionable and terminate readiness | Locate bottleneck, freeze the change, and rerun a sufficiently long window | Raw per-frame times, P50/P95/n/CI |

### 8.9 Reproduction and paper-writing path

1. Select a falsifiable claim in the [claim matrix](docs/research/claim_evidence_matrix.md), then
   complete a preregistered protocol, exact threshold, and statistical plan.
2. Complete the [dataset datasheet](docs/research/dataset_datasheet.md), freeze the manifest/split/
   checksum, and finish privacy, consent, license, and leakage review.
3. Select exact variants from the [baseline/ablation matrix](docs/research/baseline_ablation_matrix.md).
   Generate a v1 experiment manifest and result records for every run, retaining failed runs too.
4. Generate the required V1–F1 figures/tables from machine-readable sources and register each
   command, commit, input hash, and output hash.
5. Complete every item in the [reproducibility checklist](docs/research/reproducibility_checklist.md).
   Have an independent reviewer rebuild the aggregate from commands and explain numerical drift.
6. Recommended writing order: Methods (models/algorithms/hypotheses) → Protocol/Dataset → Results
   (including intervals and failures) → Ablations → Threats/Limitations → Safety/Ethics → Abstract.
   Use only conclusions backed by a complete evidence chain in the abstract.

### 8.10 Glossary and documentation index

| Term | Meaning in this tutorial |
| --- | --- |
| canonical RGB | The sole Lumos RGB source that determines segmentation, appearance, and identity |
| metric depth | D435 pinhole Z-depth measured in meters |
| registration | Transform/project/z-buffer the D435 point cloud into native Lumos pixels |
| persistent identity | An instance ID combining appearance, short-term 3D, work/stable prototypes, and explicit ambiguity rejection |
| actionability | A perception target satisfies current freshness/calibration/identity/pose conditions; this is not execution authorization |
| fail closed | On incomplete, stale, or ambiguous input, return a refusal reason instead of guessing or allowing by default |
| Dry Run | Produces only candidates/reports and neither contains nor invokes an execution transport |
| hardware emergency stop | Hardware emergency stop/power isolation independent of the software path |

Further reading: [module contracts](docs/module_guide.md),
[Web API contracts](docs/web_api.md),
[fixed-point safety audit](docs/fixed_pick_place_audit.md),
[vision acceptance plan](docs/vision_research/13_BENCHMARK_AND_ACCEPTANCE_PLAN.md),
[vision implementation gate](docs/vision_research/IMPLEMENTATION_GATE.md),
[offline implementation record](docs/vision_research/OFFLINE_IMPLEMENTATION_RESULTS.md), and
[deployment record](docs/vision_research/REMIND3D_DEPLOYMENT_RESULTS.md).

## License

Repository code is licensed under the MIT License; see [LICENSE](LICENSE). Models, the vendor SDK,
datasets, and third-party assets may use different licenses. Complete the license/NOTICE and data
governance review for each item before publication.
