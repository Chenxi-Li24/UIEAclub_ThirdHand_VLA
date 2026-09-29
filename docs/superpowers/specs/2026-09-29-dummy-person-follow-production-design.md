# Dummy Person-Follow Production Design

Date: 2026-09-29

## Purpose

Upgrade Dummy from a standalone person-follow demo into a modular ThirdHand application that
uses the existing Vision and Robot services, produces auditable decisions, and can be tested on
the real Touch R1 without bypassing the official robot API.

Success means one operator-selected person can be followed through the Lumos eye-in-hand camera,
all physical motion reaches the arm exclusively through the Robot Service on port 3000, every
decision and transition is logged, and stale, ambiguous, conflicting, or cancelled sessions fail
closed.

## Fixed Runtime Boundaries

The development topology is:

```text
Lumos camera
  -> Vision Service :3100
  -> Dummy / Person-Follow application
  -> debug execution gateway :31023
  -> Robot Service :3000
  -> vendor SDK -> can0 -> Touch R1
```

- Port 3100 owns camera capture, person perception, target state, and vision evidence. It never
  imports the Startouch SDK, opens CAN, or emits physical commands.
- Port 31023 is a temporary, loopback-only development gateway. It validates and rate-limits a
  narrow command set before forwarding accepted commands to port 3000. It never imports the SDK or
  opens CAN.
- Port 3000 remains the only physical robot authority. Every real joint move, state read, software
  stop, acknowledgement, and completion event uses its official API.
- Dummy owns personality and follow-session orchestration. It cannot address CAN or instantiate a
  second robot controller.
- After acceptance, and only after explicit operator approval, the validated follow execution
  policy may be merged into port 3000.

## Reuse Decisions

Extend the deployed repository rather than porting the old local `web-control/` layout wholesale.

Reuse behind narrow adapters:

- `services/vision/` process ownership, health endpoints, frame acquisition, and camera bridge;
- `services/robot/` execution gateway, token, motion policy, robot controller, and bridge;
- `apps/dummy/` lifecycle, gesture library, single-instance behavior, WebSocket client, and config;
- current 31023 concepts: loopback binding, allowed commands, relative-step bound, rate limit,
  request ID preservation, and forwarding to port 3000;
- existing SEUCM geometry, tracking, identity, authorization, provenance, and audit concepts.

Replace or substantially revise:

- Haar, frame difference, wave lock, and center ranking as the authoritative person selector;
- the current `PersonLockTracker`, which has no stable identity and can relock to another person;
- fixed `pixel * kp` gaze control as the production control law;
- unstructured `print()` messages as the operational audit trail;
- commands without session, proposal, evidence, expiry, and request correlation.

Old detectors and proportional control remain named diagnostic baselines only. Their outputs are
never actionable unless an explicit test-only configuration says so.

## Module Structure

Each module has one responsibility and communicates through immutable contracts.

### Vision service

`services/vision/python/person_follow/` contains:

- `camera_view.py`: validated SEUCM virtual-pinhole mapping and native-ray backprojection;
- `detector.py`: RTMDet person detector adapter;
- `tracker.py`: BoT-SORT-style short-term tracking adapter;
- `reid.py`: OSNet/FastReID session appearance evidence;
- `identity.py`: target lifecycle and ambiguity handling;
- `contracts.py`: immutable frame, detection, track, and `PersonTarget` contracts;
- `pipeline.py`: composition only, with no model-specific business rules;
- `logging.py`: structured event emission shared by Python modules.

The first deployable detector may use the existing YOLO adapter as a compatibility backend while
RTMDet assets are benchmarked. Backend selection is configuration, not a contract change.

### Dummy application

`apps/dummy/src/dummy/person_follow/` contains:

- `session.py`: start, select, cancel, target-lost, and terminal states;
- `controller.py`: stop-look-move-verify orchestration;
- `jacobian.py`: measured image Jacobian, damped pseudoinverse, conditioning, and bounds;
- `proposal.py`: immutable motion proposals;
- `verifier.py`: checks whether completed motion reduced visual error;
- `gateway_client.py`: the only Dummy dependency on the 31023 protocol;
- `logging.py`: structured application events.

Personality gestures remain outside this package. They request the same motion ownership as follow
and cannot execute concurrently with an active follow step.

### Debug execution gateway

The 31023 gateway is divided into protocol/schema validation, ownership, authorization policy,
port-3000 adapter, event correlation, timeout handling, audit logging, and the server entry point.
It accepts high-level `follow_proposal` messages, not arbitrary raw servo commands from Dummy.

## Contracts

### PersonTarget

Every target contains:

```text
frame_id
captured_at_monotonic_ns
received_at_monotonic_ns
calibration_id
track_id
identity_id
identity_status
bbox_xyxy
center_uv
confidence
fresh
actionable
rejection_reasons
```

`identity_status` is `tentative`, `confirmed`, `occluded`, `ambiguous`, or `lost`. Only a
fresh, confirmed, operator-selected identity can be actionable. Held pixels are display memory and
never produce motion.

### FollowProposal

Every proposal contains:

```text
schema_version
session_id
proposal_id
identity_id
frame_id
calibration_id
source_monotonic_ns
expires_monotonic_ns
current_joints_deg
target_joints_deg
allowed_joint_indices
max_delta_deg
time_sec
error_before_px
controller_version
```

The first hardware mode permits J1 only. J4 is enabled after single-axis acceptance. J6 is
expressive and is never part of the centering controller. The gateway recomputes limits from fresh
port-3000 state and does not trust joints, limits, or timestamps supplied by Dummy.

Every forwarded motion has a unique `request_id`. Completion and failure must match session,
proposal, and request IDs. Late, duplicate, or unrelated events are logged and ignored.

## Person Perception and Identity

The canonical model input is a calibrated virtual-pinhole view derived from Lumos SEUCM. Native
frame provenance and calibration ID are preserved. The central view is used while tracking;
left/right views may be enabled only for reacquisition.

RTMDet-tiny is the intended detector. ByteTrack is the benchmark; BoT-SORT-style tracking with
camera-motion compensation is the selected route. OSNet/FastReID supplies session appearance
evidence.

Identity means the operator-selected person in this session, not permanent biometric identity.
After a long disappearance or ambiguous crossing, confirmation is required. Face databases are out
of scope.

## Control Law

The accepted first hardware mode is stop-look-move-verify:

1. Require fresh, ready, idle state from port 3000.
2. Discard frames captured during the previous motion.
3. Obtain a new confirmed target after settling.
4. Compute a bounded proposal from a measured local J1/J4 image Jacobian.
5. Execute one small step through 31023 to 3000.
6. Wait for matching completion and fresh idle state.
7. Obtain a post-motion frame for the same identity.
8. Verify that image-error norm decreased by the configured margin.

The controller uses a damped pseudoinverse:

```text
dq = -gain * J^T * inverse(J * J^T + damping^2 * I) * error
```

It rejects non-finite, ill-conditioned, expired, oversized, or identity-mismatched inputs. Two
consecutive error-expanding moves abort the session. Held and stale targets never cause motion.

Continuous velocity servoing is a separate gate. It requires a timestamped, preemptible joint-jog
contract with a command watchdog in port 3000; repeated `move_joint` calls are not continuous
servoing.

## Ownership, Cancellation, and Safety

- Dummy holds one follow-session lock.
- Port 31023 grants one short owner lease and rejects concurrent proposals while motion is active.
- Manual stop, software stop, and hardware emergency stop are never blocked.
- The gateway never uses `force` or disables unrelated operator safety controls.
- Port 3000 currently has shared clients, so hardware tests require a visible operator and cleared
  workspace. Port 31023 cannot claim network-wide exclusivity that port 3000 does not enforce.
- Stale frames, identity change, expiry, stale robot/CAN state, disconnect, timeout, limit
  violation, audit failure, or cancellation abort fail closed.

## Structured Logging

All new modules emit JSON Lines to stdout and an append-only run log. Human-readable summaries may
also appear, but JSON is authoritative.

Each event has stable keys:

```text
timestamp_utc
monotonic_ns
level
component
event
run_id
session_id
frame_id
identity_id
proposal_id
request_id
state_before
state_after
reason_code
latency_ms
```

Events cover service lifecycle, model load, frame accept/drop, detection summary, identity change,
target rejection, proposal creation/rejection, forwarding, robot acknowledgement, completion,
failure, verification, abort, and cancellation.

Logs exclude raw images, secrets, tokens, environment values, and unbounded arrays. Joint vectors
are rounded and bounded. Repeated frame events are rate-limited; state changes and safety rejections
are never suppressed.

## Configuration

- `configs/vision.yaml`: camera model, virtual view, detector, tracker, and ReID;
- `apps/dummy/configs/dum_e_touch_r1.yaml`: personality and follow behavior;
- a development gateway config: port 31023 policy and port-3000 endpoint;
- port-3000 motion policy remains owned by `services/robot`.

Defaults fail closed. Models, calibration, approvals, and logs stay outside Git and are identified
by version/hash in the run log.

## Testing and Acceptance

Offline tests cover contracts, SEUCM mapping, invalid calibration, recorded detector/tracker
lifecycles, ambiguity, stale/repeated frames, Jacobian damping and bounds, proposal expiry and
correlation, cancellation, structured logs, and source-boundary rules proving Vision and Dummy do
not import the SDK or CAN modules.

Simulation and fault injection cover the complete 3100 to Dummy to 31023 to simulated-3000 chain,
lost acknowledgement, late completion, wrong request ID, busy robot, stale state, disconnect,
audit failure, duplicate proposal, gesture/follow conflict, and cancellation during every state.

Supervised hardware gates require an onsite operator, cleared workspace, reachable physical
emergency stop, low speed, and one change at a time:

1. read-only live detection and identity;
2. J1 positive/negative calibration pulses;
3. bounded J1 stop-look verification;
4. J1 target-loss and cancellation tests;
5. J1/J4 stop-look verification;
6. search and reacquisition without ambiguous auto-relock;
7. personality gestures under shared ownership;
8. continuous servo only after a separate port-3000 watchdog review.

Each gate produces a versioned JSON report. Tuning cannot bypass stale, identity, ownership, limit,
or operator-stop gates.

## Merge Gate for Port 3000

No follow code is merged into port 3000 until the operator reviews acceptance evidence and
explicitly approves integration. The merge reuses the tested authorization policy and state
machine, replaces only the development gateway transport with an in-process Robot Service adapter,
and preserves contracts and logs.

The merged feature stays default-disabled and requires an explicit runtime profile. Rollback is
disabling that profile; existing manual control remains unchanged.
