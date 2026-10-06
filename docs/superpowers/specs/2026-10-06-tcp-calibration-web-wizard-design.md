# TCP Calibration Web Wizard Design

## Status and intent

This document specifies a supervised, Chinese-language web wizard for measuring
the gripper TCP with a clamped probe and a protected fixed pivot. It is a
calibration data-acquisition and validation feature, not an autonomous motion
feature. The operator manually teaches every contact pose; the application only
reads canonical robot state, records immutable observations, solves the pivot
system, validates independent observations, and manages versioned artifacts.

The feature is complete when its simulated workflow and regression tests pass.
Completion does not mean that the physical TCP has been calibrated, that a
bottle path is safe, or that the robot may grasp. Physical measurement,
eight-pose acquisition, three independent validation poses, activation, and any
later grasp integration remain supervised field operations.

## Repository and isolation

- Repository: `/home/nieqingcao/ThirdHand/deployments/grasp-prototype-1894746-20261004`
- Baseline branch: `Xavier/grasp-validation-prototype`
- Baseline commit: `7fdaabe77ce4b35ccee207be65bcdb758fd11a00`
- Recovery branch: `backup/xavier-before-tcp-web-20261006`
- Feature branch: `feature/tcp-calibration-web-wizard-20261006`
- Worktree: `/home/nieqingcao/ThirdHand/worktrees/tcp-calibration-web-wizard-20261006`

The original checkout and its untracked `artifacts/` directory are not modified.
No push, merge, history rewrite, worktree removal, or physical robot operation
is part of this task.

## Fixed technical choices

The implementation does not add ROS, MoveIt, Ceres, or a complete third-party
calibration framework. It adapts the pure pivot-calibration mathematics and
evidence contracts from local branch
`feature/measured-tcp-bottle-commissioning` in `/home/nieqingcao/th0814/VA`,
especially its `tool_tcp.py` implementation. Code that binds the old workflow
to hand-eye calibration, ChArUco corner 38, camera port 3100, Home motion, or
automatic verification is intentionally excluded.

The mathematical model is the algebraic one-step pivot system:

```text
R_i p_probe + t_i = p_fixed
```

At least eight canonical flange poses are stacked into a linear least-squares
problem. SVD diagnostics expose rank, singular values, orientation coverage,
per-sample residuals, RMS residual, maximum residual, and the worst sample. The
solver produces the probe tip in flange coordinates and the fixed pivot in base
coordinates. Three or more new poses validate the candidate and never
participate in fitting.

SciKit-Surgery Calibration's BSD-3-Clause algebraic one-step pivot calibration
is an independent formula and behavior reference. No large block of its source
is copied. `THIRD_PARTY_NOTICES.md` records its URL, license, access date,
influence, and whether any copied material exists. Universal Robots' TCP
Position Wizard and Mech-Mind's touch-calibration flow inform operator-facing
workflow only.

## Safety boundary and robot transport

The only robot endpoint is `ws://127.0.0.1:3000/ws`, reached by the Web backend
through `CanonicalRobotWebSocketClient`. Browser code never connects to the
robot WebSocket, Startouch SDK, CAN, vendor libraries, or the low-level Python
bridge.

The calibration module may send only:

```json
{ "cmd": "software_stop" }
```

It must not send `move_l`, `servo`, `preset`, `gripper`, Home, contact, rotation,
or any other motion command. A deny-by-default command seam and tests prove that
the module cannot create those commands. Losing connection, freshness, health,
stationary status, policy identity, or monotonic state locks recording and
solving. It does not attempt automatic recovery.

## Coordinate semantics

The current Startouch configuration defines the nominal SDK tool translation as
`[0.17334, 0, 0]` metres. Port 3000 currently supplies the pose of that SDK tool
while legacy fields label it as a flange pose. Raw `tcpPos`, `tcpEuler`,
`flange_position_m`, and `flange_euler_rad` are therefore not accepted as pivot
inputs.

`CanonicalRobotWebSocketClient` must load and bind the existing frame policy,
check its source hashes, and normalize exactly once:

```text
T_base_flange = T_base_sdk_tool * inverse(T_flange_sdk_tool)
```

Every accepted sample contains `pose_frame=robot_flange`, the frame-policy ID,
the canonical flange transform, strictly increasing state sequence and producer
monotonic timestamp, and an operator contact proof. An input carrying prior
normalization metadata at the raw boundary, a missing/mismatched policy, or an
unprovable frame is rejected rather than treated as a flange pose.

The SDK configuration remains unchanged. Calibration stores three distinct
transforms:

1. `T_flange_sdk_tool`, the nominal 173.34 mm SDK tool transform;
2. `T_flange_probe_tip`, solved directly from the pivot observations;
3. `T_flange_grasp_tcp`, derived from the probe tip and caliper measurement.

The actual grasp center is calculated once as:

```text
p_grasp = p_probe - distance_m * tool_axis_flange
```

The probe-tip-to-grasp-plane distance is operator-entered in millimetres with a
measurement uncertainty. No 20 mm value is hard-coded. Tool-axis direction and
sign are explicit inputs validated against supported unit vectors and shown to
the operator. Tests cover zero rotation, X/Y/Z rotations, both distance signs,
single 173.34 mm normalization, and single probe-distance conversion.

## Architecture

The feature is a separate module under `apps/web/src/tcp-calibration/`:

- `contracts.js` validates exact request, sample, state, and artifact schemas.
- `robot-state-source.js` owns the canonical 3000 client, exposes immutable
  snapshots, and provides the sole `software_stop` method.
- `session.js` implements the persisted wizard state machine, monotonic and
  diversity checks, undo/delete/replace behavior, fit/verification separation,
  and idempotency.
- `solver-adapter.js` invokes the Python solver with bounded input/output and
  rejects malformed or non-finite reports.
- `artifact-store.js` performs owner-only atomic writes, content hashing,
  versioned candidate storage, active-manifest switching, backup, and rollback.
- `routes.js` owns same-origin HTTP handling, exact methods and paths, body
  limits, session/revision/idempotency checks, and stable error mapping.

The Python module lives in a focused calibration path and provides pure solver
functions and a JSON command-line adapter. The ported implementation is adapted
to this repository and extended only where required for diagnostics and
independent verification.

`apps/web/src/server.js` receives one small integration seam: creation and
routing of a calibration controller supplied through dependency injection.
Calibration remains unavailable with an explicit reason if its policy,
artifact root, Python interpreter, or robot state source is invalid.

Static assets add a separate `/tcp-calibration.html` entry and focused JS/CSS.
The existing main page receives only a clear “TCP标定” link or button. Calibration
logic is not added to the existing large `main.js`.

## Session and API model

Only one current session exists per artifact root. It has a random session ID,
monotonic revision, idempotency ledger, operator identity, stage, immutable
inputs, fit samples, verification samples, candidate results, and terminal
status. Every state-changing request supplies the session ID, expected revision,
and request ID. Replays return the original result; conflicting reuse fails.

Endpoints are:

- `POST /api/tcp-calibration/sessions`
- `GET /api/tcp-calibration/sessions/current`
- `POST /api/tcp-calibration/samples`
- `DELETE /api/tcp-calibration/samples/:id`
- `POST /api/tcp-calibration/solve`
- `POST /api/tcp-calibration/verification-samples`
- `POST /api/tcp-calibration/finalize`
- `POST /api/tcp-calibration/activate`
- `POST /api/tcp-calibration/rollback`
- `POST /api/tcp-calibration/abort`
- `POST /api/tcp-calibration/software-stop`

Unsafe methods enforce same-origin requests. Request bodies are size-bounded and
must have exact keys. Browser refresh restores the current persisted session.
Disconnecting port 3000 locks all operations except status, abort, and the
best-effort software-stop path.

## Wizard stages

### Stage 0: connection and safety

The page displays connection, freshness, health, stationary state, canonical
pose frame, frame-policy identity, canonical flange pose, and software-stop
control. The operator supplies name, caliper distance and uncertainty, confirms
the tool axis, centered rigid probe, fixed protected pivot, emergency-stop
attendant, and manual-teach-only operation. Missing evidence blocks sampling.

### Stage 1: eight fit poses

An eight-direction coverage guide helps the operator manually touch the same
pivot from varied orientations. “记录当前姿态” records only a fresh, healthy,
stationary, canonical state with increasing sequence and timestamp. Duplicate
or insufficiently separated rotations are rejected. Undo, delete, replacement,
additional samples, and abort are available. Eight accepted poses are the
minimum for solving.

### Stage 2: solve and diagnostics

The page shows both solved points, matrix rank, singular values, coverage,
sample residuals, RMS, maximum residual, and worst sample. Thresholds live in a
single versioned configuration:

- green: RMS `<= 0.002 m` and maximum `<= 0.004 m`;
- yellow: RMS `(0.002, 0.003] m` or maximum `(0.004, 0.005] m`;
- red: RMS `> 0.003 m`, maximum `> 0.005 m`, rank `< 6`, or insufficient
  coverage.

Red blocks validation. Yellow recommends deleting the worst sample and
collecting a replacement without silently changing the data set.

### Stage 3: independent validation

The operator records at least three new manual pivot contacts. They are never
added to the fit set. The page displays predicted base-frame tip positions,
errors relative to the fitted fixed point, validation RMS and maximum error,
and evidence of arc drift across rotation axes. Maximum error above `0.005 m`
blocks approval. This stage is camera-, hand-eye-, ChArUco-, and port-3100-free.

### Stage 4: derive the grasp TCP

The page shows the SDK nominal tool, probe-tip TCP, and derived grasp-center TCP
side by side with the signed direction and distance. Finalization requires
confirmation that the caliper value and axis are correct, the probe has been
removed, and the gripper is back in production configuration.

### Stage 5: save pending

Finalization atomically writes a content-addressed/versioned pending artifact
and a `configs/calibration/gripper-tcp.pending.json` reference, or an equivalent
repository-local runtime path selected by configuration. The immutable artifact
contains schema, robot identity, policy ID, all source samples, solver and
verification reports, measurement and uncertainty, thresholds, operator,
timestamps, software version, and content hash. Production configuration is not
changed.

### Stage 6: activate and rollback

Activation is a separate explicit action that re-displays the complete result,
requires a new expected revision and confirmation, preserves the previous
active manifest, writes a versioned calibration file, and atomically switches an
active manifest that references only a validated artifact. Rollback can switch
to the immediately previous validated version. Real activation is outside this
task; tests and demonstration use a temporary artifact root.

## Persistence and recovery

Writes use a temporary file in the destination directory, `fsync`, restrictive
permissions, atomic rename, and directory synchronization where supported.
Content hashes cover canonical JSON excluding only the hash field itself.
Versioned artifacts are never overwritten. Current-session and active-manifest
references are replaceable pointers whose targets remain immutable.

On restart, invalid, truncated, mismatched, or impossible session data fails
closed and exposes a recoverable status; it is never silently reset. Abort is
terminal and preserves evidence. Activation and rollback verify target hashes
before changing the manifest.

## Testing strategy

All hardware-facing tests use fake WebSockets, synthetic canonical states,
temporary directories, and a fake or pure solver. No test connects to the real
robot, camera, SDK, CAN, or vendor runtime.

Python solver tests cover exact synthetic recovery; 0.5, 1, 2, and 5 mm noise;
eight-pose success; fewer than eight samples; duplicate, single-axis, weakly
separated, and rank-deficient sets; residual diagnostics; validation isolation;
and comparison against independently generated SciKit-Surgery-compatible
reference fixtures.

Node tests cover canonical policy and frame rejection, one-time 173.34 mm
normalization, monotonic/fresh/stationary gates, measurement conversion exactly
once, session mutation and recovery, deleting/replacing an outlier, pending
atomicity, activation/rollback, origin and idempotency enforcement, disconnect
locking, software stop, and the absence of all motion-producing commands.

Browser tests cover the Chinese stage structure, disabled controls, state
restoration, diagnostic rendering, three-transform comparison, confirmation
gates, and safe disconnect behavior. An end-to-end simulated workflow traverses
stages 0–6 against a fake 3000 WebSocket and temporary artifact root.

Existing full Node and Python suites are run at completion. The baseline is
recorded honestly: Node passed 192/192 at the initial worktree commit; the root
Python command failed during collection because
`tests/python/vision_service/test_handeye_projection.py` could not import
`handeye_projection`. This pre-existing environment/path failure is reported
separately unless it is explicitly brought into scope.

## Out of scope

- Physical calibration, motion, probe contact, or activation.
- Camera or hand-eye calibration and ChArUco validation.
- Bottle-vision averaging or forward target smoothing.
- Approach distance, `forwardBackoffM`, grasp state-machine changes, or replacing
  the current 60 mm experiment value.
- Editing the SDK's 173.34 mm tool configuration.
- Publishing, merging, or deploying the feature.

The resulting active-artifact interface makes later grasp integration possible,
but consuming it is a separate branch and supervised validation task.

