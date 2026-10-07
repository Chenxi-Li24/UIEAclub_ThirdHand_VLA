# Dummy Runtime: Latest-Target Scheduling

## Implemented Chain

1. Vision Service owns the camera; Dummy subscribes to its raw MJPEG stream.
2. The owned MJPEG reader keeps one newest decoded frame. It drains complete
   buffered JPEGs before decoding, bounds its buffer, and closes/joins at exit.
3. The owned detection worker runs outside the asyncio motion loop. In 2D mode
   it does not request the depth HTTP endpoint. Detection still uses the existing
   local person/face logic; formal Vision Service identity migration is separate.
4. The runtime replaces one observation slot. It checks frame receive age,
   target validity and held/repeated observations; a held identity preserves a
   lock but cannot authorize another motion. MJPEG receive time is NOT camera
   capture time, so upstream/network backlog cannot be fully measured here.
5. The single motion scheduler waits for fresh idle feedback, reads the latest
   observation, then computes J1/J4 correction. Immediately before sending it
   rechecks the latest target against the freshly measured joints.
6. The controller computes geometric correction without a Dummy speed/step cap;
   J1 retains the startup-relative 85 degree envelope, J4 uses the intersection
   of absolute [-35,35] and startup-relative +/-35 degree bounds.
7. Workspace checks use the identical rigid-transform Z result without allocating
   all XYZ/homogeneous results. A 128-entry exact-input cache avoids rechecking
   identical poses. This is a base-plane guard, not full-path collision planning.
8. TouchR1Adapter applies joint limits without setting speed or segment duration, then
   sends one correlated command directly to Robot Service on 3000. SDK/CAN stays
   in Robot Service. Acceptance is distinct from terminal completion.
   Robot Service uses SDK speed mode (default J1-J3: 15 deg/s, J4-J6: 50 deg/s).
   The adapter completion deadline defaults to 45 seconds. Keyword keyframe
   timestamps validate ordering only; SDK speed mode determines segment time.
9. Request-ID futures dispatch replies independently of the 200-event log ring.
   Service and bridge validation errors now retain the request ID. Unmatched
   errors cannot complete another request. Failed/ambiguous sends are not retried.
10. Final ASR events arrive through the Speech Service's local read-only transcript
    fan-out. Exact mapped commands enter a bounded queue, expire after three
    seconds, and are deduplicated. One gesture finishes before follow resumes;
    gesture keyframes may change all six joints through the same adapter.

## Entry Points And Dependencies

`apps/run_head_body_follow.py`, `apps/run_person_follow.py`, `apps/run_dummy.py`
and `apps/run_dume_follow_touch_r1.py` all use `PersonFollowRuntime`. They no
longer import a parallel personality motion loop or require Mink for 2D following.
Use the project's vision Python environment, prepared detector weights and URDF
meshes. Speech must include `/v1/transcripts` and the
`thirdhand.transcripts.v1` subprotocol. It accepts loopback subscribers only.
Remote Dummy users need an SSH tunnel for that transcript port; do not expose
the private fan-out by dropping its loopback restriction.

From the repository root, a camera-only dry-run is:

```bash
local/runtimes/vision-python/bin/python apps/dummy/apps/run_dummy.py --no-keywords --max-frames 100
```

Without `--no-keywords` it also subscribes to final ASR; without
`--enable-motion` it never connects Robot Service. Real motion requires explicit
operator approval and adding `--enable-motion`. No automatic zero/Home is sent.
The legacy `--skip-home` argument remains accepted but is no longer necessary.

The follow-stack launcher is different: it may start Robot Service and explicitly
connect SDK even without launching Dummy motion. Its `--no-start` option disables
service creation, not SDK connection. Prefer the direct dry-run above for passive
testing. When launching motion, the stack launcher now stays in the foreground,
waits for its Dummy child, and forwards Ctrl+C/SIGTERM to that child only. Shared
services remain running. All motion-enabled production aliases share one process lock.

## Exit Contract

Ctrl+C and SIGTERM set a stop event. The runtime refuses new motion, clears queued
keywords, finishes the already-issued bounded segment when feedback is available,
cancels/awaits the transcript task, closes/joins reception and detection, releases
detectors and closes only its own Robot Service socket. The process lock is released
by its context manager. The shared robot remains usable by the webpage.

No shutdown path sends `software_stop`, `disconnect`, motor disable, CAN down or
shared service termination. This normal exit is not an emergency stop. A stalled
or disconnected robot can make completion uncertain; the runtime reports an error
and does not replay the motion. SIGKILL/power loss cannot guarantee cleanup, and
already-issued motion can continue independently of the Dummy process.

## Remaining Continuous-Trajectory Work

Ordinary Robot Service motion remains serial and busy-gated. A 10 Hz scheduler
does not imply 10 physical retargets/second: the SDK segment and feedback
round-trip still impose pauses. This stage reduces stale targets, blocking work
and unnecessary depth traffic, not every source of stop-start motion.

Inspected Startouch SDK exposes `update_joint_waypoint_chunk(waypoints,
time_sec=None, speed_percent=None, switch_delay_sec=0.05)`. It updates future
samples nonblockingly. The wrapper lacks an explicit whole-chunk completion
signal. Its planner reports rows containing relative time, six joint angles,
TCP pose, gripper and planning time. Any future streaming route must retain the
shared Robot Service speed policy, including at an active splice.

Before enabling a dedicated continuous-follow command:

- Validate six finite joint targets, J1/J4-only changes, hardware/envelope bounds,
  observation expiry and a bounded update horizon inside Robot Service.
- Keep continuous stream state separate from ordinary motion; ordinary commands
  must not replace an active stream, and unrelated clients must not retarget it.
- Check planned sample timestamps and all six per-sample velocities against
  the service's effective per-joint caps, including the preserved prefix and new splice, not only
  an isolated rest-to-rest segment.
- Confirm completion using fresh measured position/velocity and bounded timeouts.
  Closing Dummy must finish only its last bounded tail without depowering shared
  hardware. Never globally disable the ordinary motion-busy check.
- Validate actual motor peak speeds, acceleration/jerk, target loss, keyword
  handover and exit in separately authorized cleared-workspace tests.

That live continuous channel is intentionally not implemented as an unverified
shortcut in this phase. There is no claim that deployed hardware is now smooth.

## Offline Validation

The CI Dummy test step includes request correlation, latest-target scheduling,
keyword arbitration, stale/duplicate frames, receive/decode cleanup, geometry
equivalence, range constraints and shared speed policy. Speech tests run an actual loopback
WebSocket server with fake ASR. Robot tests use `STARTOUCH_SIMULATE=1` only.
No SDK import, real camera or CAN is required by these added tests.

## Validation Record (2026-10-05)

- Windows targeted Dummy/Speech/simulated-chain regression: 116 passed.
- Ubuntu isolated source snapshot: 226 Python/Dummy tests passed, with 58
  subtests; all 162 Node tests passed.
- Additional static tests using the existing local URDF/meshes read-only:
  12 workspace-guard, follow-clamping and person-lock tests passed.
- Dummy motion and keyword execution reached the simulated 3000 bridge; after
  Dummy exited, a separate client still obtained valid state and moved the
  simulated gripper.
- The full Python suite has Windows-only pipe/shebang/dependency limitations;
  its Linux run above provides the complete platform regression result.
- No real motor, camera or ASR-model acceptance test was performed. The deployed
  Ubuntu project and running services were not changed. Temporary test snapshots
  are disposable. These counts describe the pre-merge runtime stage, not the
  subsequent shared-speed-policy regression.

## Shared Speed Policy Update

The former Dummy 10 deg/s budget and duration formula were removed after
integrating the remote SDK speed-mode changes. Legacy speed settings are no
longer consumed by the image controller/adapter; production configurations no
longer advertise them. Requests use the Robot Service policy, including its
lower configured scales, with no per-command Dummy override. SDK configuration
requirements are documented in `services/robot/config/README.md`.
The follow-stack supervisor gives its child 60 seconds to finish a bounded
45-second completion wait and close readers/workers. Neither change modifies
the deployed Ubuntu SDK or starts real hardware. Hardware acceptance remains
separate, especially for larger follow targets and faster J4 movements.

Shared-policy regression used a disposable Ubuntu source snapshot, not the
deployed project. The final results were 171 full Node tests passed; 148 full
Python tests and 58 subtests passed; 133 Dummy adapter/controller/legacy tests
passed with the existing URDF/meshes read-only; 25 Robot Service tests passed
again after removing redundant legacy duration arguments. CI source-boundary
audit also passed. Simulation confirmed follow/keyword completion and that a
separate robot client remains usable after Dummy exits. No real motor speed
or camera/ASR acceptance was performed.
