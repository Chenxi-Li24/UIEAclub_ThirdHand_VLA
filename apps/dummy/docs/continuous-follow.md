# Continuous J1/J4 Follow and Same-Source Recognition

## Ownership and Execution

Dummy owns detection and application scheduling. Robot Service on port 3000
remains the only owner of Startouch SDK/CAN. No relay gateway, lease or second
SDK instance is introduced. A websocket connection can enter continuous follow;
other motion commands are rejected until this mode ends. Disconnecting that
websocket requests a smooth hold, not motor disable or SDK cleanup.

The detector replaces one observation slot. Duplicate camera frames are ignored;
held, stale and unavailable targets do not authorize new motion. Each fresh
observation is consumed at most once. J1/J4 targets can replace a target while
the robot is moving. Keyword actions first stop following, wait for measured hold,
then execute their ordinary all-joint waypoints. The original J1 envelope is not
reset by pauses or keyword gestures. Idle breathing and automatic Home remain off.

## Robot `/ws` Protocol

All messages retain `request_id` correlation. `follow_start` and `follow_target`
produce `command_status: accepted`, not false claims of target arrival.

```json
{"cmd":"follow_start","stream_id":"one-dummy-run","request_id":"start-1"}
{"cmd":"follow_target","stream_id":"one-dummy-run","sequence":1,"observed_at_ms":0,"joints_deg":[0,0,0,0,0,0],"request_id":"target-1"}
{"cmd":"follow_stop","stream_id":"one-dummy-run","request_id":"stop-1"}
```

`observed_at_ms` must be replaced with the actual frame receive timestamp in epoch
milliseconds, not zero. It is not a hardware camera-capture timestamp. `sequence`
strictly increases over the whole Dummy run, including pauses. Incoming targets
must be at most 500 ms old; future timestamps beyond 50 ms are rejected.
`follow_state` reports activation, fixed non-follow joint targets and stop reason.
The start pose comes from measured feedback, never browser targets.

Only J1/J4 change. J1 stays within +/-85 degrees of the original stream start and
hardware limits. J4 stays within [-35,35] degrees. Other joint targets stay fixed
at the last follow activation pose. Target and every interpolation sample pass the
shared URDF base-plane guard with 40 mm clearance. Missing geometry fails closed.
Simulation disables physical geometry only for explicitly simulated services.

The interpolator caps speed using the existing shared 300/1000 degrees/s reference
and maximum 0.05 scale: J1 15 degrees/s and J4 50 degrees/s. Acceleration ramps
and jerk limiting prevent sudden direction changes. The backend ticks nominally
at 100 Hz; expensive geometry checks may reduce actual frequency, and dt is
capped at 25 ms to prevent a scheduling pause from creating a position jump.
SDK MIT mode additionally applies its internal protective smoothing.

After 500 ms without a valid update, follow decelerates and holds its last checked
sample. `follow_stop` acknowledges completion only after measured position is
within 1 degree and measured velocity below 5 degrees/s, with a 1.5-second bound.
Unconfirmed holds are not reported as reached; Dummy must stop issuing motions.
Dummy waits up to 5 seconds for this terminal reply, covering deceleration as well
as the 1.5-second measured-hold verification, rather than timing out at 2 seconds.
Feedback/CAN failure retains the existing fail-closed SDK cleanup behavior.
Software stop remains distinct from an independent hardware emergency stop.

The exact mesh Z reduction avoids multithreaded BLAS dispatch. Every vertex still
participates; no geometry samples or checks are removed for performance.

## Real Feedback

The state publisher runs during both waypoint and continuous motion, normally at
20 Hz. It publishes measured joint angles with `MOVING`/`IDLE`, not target angles.
Joint waypoint completion now checks measured feedback within 1 degree and reports
`reached:false` when the bounded verification fails. Explicit zero remains allowed;
unexpected all-zero cache samples remain guarded.

## Same-Source Window

The Dummy process owns a local read-only HTTP server, default port 31024:

- `/api/status`: current observation sequence, stream-local frame ID, target,
  detection duration, frame receive age, latest control request and real joints.
- `/api/frame`: one atomic JSON packet containing those fields and the JPEG
  rendered from that same detector frame. No independent camera or model is opened.

Green rectangles mean fresh locked observations; orange means held/lost candidates.
Yellow circles are the exact filtered 2D points passed to the controller, not TCP.
Held points are gray. White crosses are image centers. `used_by_last_command`
distinguishes an observation already used from one still awaiting control.
Frame IDs are local receive sequence IDs, not guaranteed sensor hardware IDs.
`motion_enabled:false` distinguishes a dry run: `robot_joints_deg` is null and
`preview_joints_deg` contains simulated angles. A dry run never reports simulated
angles as measured feedback. The window labels it `DRY RUN` explicitly.

With Dummy running, start the native Ubuntu window:

```bash
"$VISION_PYTHON" apps/dummy/apps/visualize_person_follow_window.py
```

The window polls the same-source packet at 5 Hz and never connects to Robot Service.
Closing it only closes the viewer. Dummy exit closes detector threads, its keyword
subscription, its HTTP server and its Robot websocket; shared services stay running.
After having seen a running Dummy, the viewer exits when its API stays offline for
2 seconds. Thus exiting Dummy does not leave its recognition viewer polling forever.
`--telemetry-port 0` disables the viewer API explicitly.

## Resource Overrides and Startup

Paths stay relative to the checkout by default. A fork without local payloads can
read existing prepared resources using explicit environment variables:

```bash
export DUMMY_URDF_PATH="$RESOURCE_ROOT/assets/robot/startouch-v3/FastTouchV3.SLDASM.urdf"
export DUMMY_FACE_MODEL="$RESOURCE_ROOT/apps/dummy/models/blaze_face_short_range.tflite"
export DUMMY_YOLO_MODEL="$YOLO_WEIGHTS"
export DUMMY_SPEECH_WS="ws://127.0.0.1:3005/v1/transcripts"
export STARTOUCH_FOLLOW_URDF="$DUMMY_URDF_PATH"
"$VISION_PYTHON" apps/dummy/apps/run_head_body_follow.py --enable-motion
```

`RESOURCE_ROOT`, `VISION_PYTHON` and `YOLO_WEIGHTS` are operator-provided paths.
Robot startup also requires its normal SDK/module/Python resource variables.
Never start another hardware Robot Service while an existing one owns CAN.
Deploying this change requires upgrading Robot Service and Dummy together.

## Acceptance Checks

1. Simulated end-to-end tests: targets update while moving, J1/J4 only; keyword
   actions finish; Dummy exit leaves Robot connected and allows normal gripper use.
2. Unit tests: stale/replayed data, shared speed caps, reversal, original excursion
   envelope and intermediate geometry rejection.
3. On-site supervised test: small movements first, real feedback during motion,
   then larger angles and reversals without waypoint-completion pauses.
4. Cover camera loss, websocket closure and Ctrl+C; check measured hold and ability
   to use ordinary web controls afterward. Do not use process kill as an emergency stop.
5. Compare observation sequence and request ID in the window to runtime diagnostics.
   Distinguish receive-age metrics from actual end-to-end camera latency.

## Deployment Measurements (2026-10-06)

Offline acceptance passed 173 Node tests and 216 Python tests. Python checks used
the original checkout's existing URDF payload through test-process-only overrides
where the fork had no local mesh copy; no tests were skipped for missing geometry.

The first supervised small movement received 64 real moving-state updates, at a
median interval of 51.5 ms, and measured hold was confirmed. Ordinary small waypoint
commands also emitted moving feedback, rather than only a final position.

The initial live-follow run exposed a 2-second client stop timeout; the 5-second
wait and equivalent mesh reduction fixed it. A subsequent 20-second live sample
received 399 real states, including 352 while moving: median interval 50.3 ms,
maximum 59.5 ms. The 84 distinct target replies seen by the sampler had a median
confirmation time of 4.5 ms and maximum 12.1 ms. Target loss/reacquisition did not
terminate Dummy. These figures are local command/feedback timings, not camera
capture-to-motion latency or guaranteed future timing under other system loads.

A supervised Dummy exit completed in 1.8 seconds. Robot Service remained connected,
healthy and idle; an ordinary same-pose joint command succeeded afterward. Shared
vision, speech and web services were not stopped. Recheck exit and hold whenever the
SDK, runtime or motion policy changes.
