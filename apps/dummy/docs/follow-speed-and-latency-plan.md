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
| J1 image servo | 0.55 degrees/correction | 10 degrees/second times control dt |
| J4 image servo | 0.08 degrees/correction | 10 degrees/second times control dt |
| J4 range | -1.5 to 4 degrees; 4 degree excursion | -35 to 35 degrees; 35 degree excursion |
| Adapter | Fixed relative-angle clipping | Full target; speed-limited duration |
| Send interval | 0.22 seconds in hardware entrypoint | 0.10 seconds |

J1 retains its 85 degree startup-relative envelope and hardware limits. J4
uses the intersection of its absolute and startup-relative envelopes. Out-of-range
starting poses hold; they do not trigger an immediate return into the envelope.

The controller uses degrees, seconds and a speed budget `abs(delta) <= speed * dt`.
Detector stalls cannot accumulate unlimited dt: the default maximum control dt is
0.25 seconds. The current hardware loop passes its requested period explicitly;
actual command throughput is still reduced by detection and busy waits.

The adapter requires six finite measured joints, preserves the requested target,
and computes `duration >= 2 * max(abs(target - measured)) / max_speed_deg_s`.
For the SDK's documented single-segment quintic with zero endpoint velocity,
the peak/average speed ratio is 1.875; factor 2 is conservative. Explicit durations
can lengthen but never shorten this value. Requests exceeding the server's 30
second ceiling are refused rather than silently accelerated by server clipping.
SDK waypoint modification or motion outside the expected single-segment shape
requires trajectory/feedback verification; a duration calculation alone does not
certify measured motor peak speed.

The 0.10 second interval caps request traffic at 10 Hz. It provides a 100 ms
target-update budget without encouraging overlapping calls into a busy SDK.
It does not remove Robot Service's motion-active gate or the configured minimum
motion duration (0.20 seconds in the adapter, with service constraints also
applying). This parameter change alone does not eliminate
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
   stays inside Robot Service. Validate planned samples against 10 degrees/second
   for each joint and verify measured motion before enabling hardware use.
8. Implement graceful exit: inhibit producers, discard unsent Dummy targets,
   finish the current request by request ID, cancel and await owned tasks, close
   owned sockets/readers/models/windows/logs, and release the process lock.
   Replace uninterruptible stdin reads. Do not send global software_stop,
   disconnect SDK, disable motors, close CAN or terminate shared services.
   Forced process termination cannot provide a successful cleanup guarantee.

## Acceptance And Risk

- Offline: vary dt, exercise both J4 range boundaries, preserve J1 excursion,
  check all six gesture axes, refuse nonfinite input/missing feedback, verify
  duration forwarding through move_joint/servo/zero-preset, and reject server
  duration truncation. Test long event streams, stale frames and shutdown races.
- Hardware (separate authorization): clear the workspace, validate axis-response
  signs, measure J1/J4 speeds, loss/reacquisition, keyword arbitration and exit.
  Test that webpage control remains functional after Dummy has exited.
- Increasing J4 range increases physical travel. Retain hardware limits, fresh
  feedback, workspace checks and independent hardware stop access.
- Default keyword mappings and the integrated runtime are implemented. Local
  offline tests do not establish real ASR quality, axis-response signs, physical
  speed or active SDK splice behavior; those still need separate acceptance.
