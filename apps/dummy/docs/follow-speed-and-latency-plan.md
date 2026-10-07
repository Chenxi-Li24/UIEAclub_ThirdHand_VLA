# Dummy Follow Speed And Latency Plan

## Scope

- Person following changes J1/J4 only.
- Keyword gestures may use J1-J6, subject to normal hardware limits.
- Idle breathing must be disabled by default in the unified runtime.
- Normal exit stops all Dummy-owned work, not shared Robot, Vision or Speech services.
- This change is source-only. No hardware motion, service restart or deployment is included.

## Implemented Speed Changes

| Layer | Previous policy | Current policy |
| --- | --- | --- |
| J1 image servo | Local fixed step / 10 deg/s budget | Geometric target; SDK speed mode |
| J4 image servo | Local fixed step / 10 deg/s budget | Geometric target; SDK speed mode |
| J4 range | -1.5 to 4 degrees; 4 degree excursion | -35 to 35 degrees; 35 degree excursion |
| Adapter | Fixed relative-angle clipping / timed 10 deg/s | Full target; no time or speed override |
| Send interval | 0.22 seconds in hardware entrypoint | 0.10 seconds |

J1 retains its 85 degree startup-relative envelope and hardware limits. J4
uses the intersection of its absolute and startup-relative envelopes. Out-of-range
starting poses hold; they do not trigger an immediate return into the envelope.

The controller uses geometric pixel-to-joint corrections, damping and gain.
It no longer consumes the previous 10 deg/s or dt-based correction budget;
detector stalls do not accumulate dt. Stale/held observations remain rejected.
Actual command throughput is still reduced by detection and busy waits.

The adapter requires six finite measured joints and preserves the requested
target. It sends neither `time_sec` nor a speed override. Robot Service applies
SDK speed-mode planning: default J1-J3 15 deg/s and J4-J6 50 deg/s, or a lower
configured service scale. Completion uses a separate 45-second deadline,
not a motion-duration estimate. Explicit zero and calibration scripts share
this policy. Gesture keyframe timestamps validate ordering, not execution time.
See `services/robot/config/README.md` for the runtime SDK reference prerequisite.
No local SDK or deployed services are modified by this source change.

The 0.10 second interval caps request traffic at 10 Hz. It provides a 100 ms
target-update budget without encouraging overlapping calls into a busy SDK.
It does not remove Robot Service's motion-active gate. This parameter change alone does not eliminate
stop-start following.

## Phase Status

The unified runtime, request-ID futures, bounded latest-target scheduling, 2D
depth bypass, exact Z-only geometry checks/cache, final-transcript subscription
and orderly exit are now implemented. The live runtime records observation
sequence, receive age, detection/controller/guard/cycle time and request ID.
All changes are still local source changes, not a hardware deployment.

Continuous SDK retargeting is NOT enabled or exposed as a live follow command.
Source inspection confirmed the API but not its active-splice speed/completion
contract. Planned-sample and measured-speed validation remain required before
replacing the ordinary serial command path. See `runtime-stage-two.md`.

The following list retains the roadmap and acceptance requirements:

1. Instrument the existing loop before tuning further: record source frame ID,
   capture/receive age, detection time, identity decision, controller time, guard
   time, request ID, acceptance/rejection, movement duration and measured joint
   speeds. Distinguish transport success from motion acceptance.
2. Fix reply dispatch using pending futures keyed by request ID. Keep the 200
   event ring for diagnostics only. An ambiguous send must not automatically
   replay motion. Include correlated rejection replies in Robot Service.
3. Split frame reception/detection and motion scheduling. Store one latest
   observation, not a FIFO of old targets. Preserve source timestamps; repeated
   frames and held identities cannot authorize new motion. After waiting for the
   arm, read the latest target and robot state and recompute the correction.
4. Remove synchronous depth HTTP requests from the 2D follow path. Reuse the
   unified Vision Service person/face evidence where its identity contract is
   adequate. If local detection is required, perform it in a cancellable worker,
   once per selected frame, without blocking the motion event loop.
5. Reduce guard cost: reuse loaded geometry, precompute homogeneous vertices,
   use validated conservative collision geometry, and eliminate repeated checks
   of identical state/target pairs. Preserve rejection semantics; do not simply
   disable the guard. Missing assets are startup errors, not reasons to return zero.
6. Establish one in-process scheduler: FOLLOW, GESTURE, HOLDING, STOPPING.
   Final ASR text reaches an explicit keyword event adapter with deduplication.
   Gestures suspend follow, then refresh pose and visual evidence before resuming.
   Disable breathing and implicit startup/loss/exit gestures by default.
7. Introduce opt-in continuous follow updates only after SDK capability checks.
   The inspected SDK exposes `update_joint_waypoint_chunk`, a nonblocking
   future-trajectory replacement API. Assess its switching delay, velocity,
   acceleration and interruption behavior offline first. Add a dedicated Robot
   Service command for bounded follow updates; do not globally remove the busy
   check for ordinary webpage, gesture or grasp commands. All SDK/CAN access
   stays inside Robot Service. Validate planned samples against the service's
   effective per-joint speed caps and verify measured motion before enabling hardware use.
8. Implement graceful exit: inhibit producers, discard unsent Dummy targets,
   finish the current request by request ID, cancel and await owned tasks, close
   owned sockets/readers/models/windows/logs, and release the process lock.
   Replace uninterruptible stdin reads. Do not send global software_stop,
   disconnect SDK, disable motors, close CAN or terminate shared services.
   Forced process termination cannot provide a successful cleanup guarantee.

## Acceptance And Risk

- Offline: ensure geometric targets do not depend on dt, exercise both J4 range boundaries, preserve J1 excursion,
  check all six gesture axes, refuse nonfinite input/missing feedback, verify
  absence of duration/speed overrides through move_joint/servo/zero-preset,
  shared SDK caps and bounded completion waits. Test long event streams,
  stale frames and shutdown races.
- Hardware (separate authorization): clear the workspace, validate axis-response
  signs, measure J1/J4 speeds, loss/reacquisition, keyword arbitration and exit.
  Test that webpage control remains functional after Dummy has exited.
- Removing the local 10 deg/s/step budget permits larger corrections and faster
  J4 travel. Retain hardware limits, fresh
  feedback, workspace checks and independent hardware stop access.
- Default keyword mappings and the integrated runtime are implemented. Local
  offline tests do not establish real ASR quality, axis-response signs, physical
  speed or active SDK splice behavior; those still need separate acceptance.
