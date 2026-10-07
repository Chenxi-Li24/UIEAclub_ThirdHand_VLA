# Dummy: Dum-E personality for ThirdHand Touch R1

This experimental application lives in `apps/dummy/` and talks to the existing ThirdHand Robot Service at `ws://127.0.0.1:3000/ws`.
It does not import Startouch SDK and does not open CAN directly.
It is not part of the default launcher profile and must be started explicitly.

## Current boundary

`PersonFollowRuntime` composes Vision, final Speech transcripts and Robot Service
into a single motion scheduler. It is application-level orchestration, not a
device service or a one-shot Skill. `DummyDirector` remains legacy library code;
the production entrypoints no longer launch its parallel motion loops.

All Dummy motion goes through `TouchR1Adapter` directly to Robot Service `/ws`
on port 3000. There is no Dummy relay server, ownership lease, lease heartbeat
or lease-based authorization. `request_id` remains a command/reply correlation
ID, not a lease or permission token. Robot Service remains the only CAN/SDK owner.

`apps/run_head_body_follow.py`, `run_person_follow.py`, `run_dummy.py` and
`run_dume_follow_touch_r1.py` use the same runtime. Blocking detection runs in
an owned worker and replaces one latest observation slot. Motion is serialized:
follow uses J1/J4, keyword gestures may use all six joints. No startup/loss/exit
Home, search gesture or idle breathing is issued automatically.

## Run

The default follow target is now a selected **face center**, using the existing
OpenCV YuNet model rather than a torso/body/motion box. Startup selects one face
automatically; short loss pauses, and confirmed loss automatically selects a new
visible face. Prepare its verified local model with `apps/prepare_face_model.py`.
OK-based explicit switching is not connected yet.
See [face-follow.md](docs/face-follow.md) for detection limitations and verification.

The J1/J4 path now uses Robot Service continuous follow, not repeated blocking
waypoint moves. Keyword gestures still use waypoint planning. The live recognition
window subscribes to the running Dummy's observations and performs no detection.
See [continuous-follow.md](docs/continuous-follow.md) for protocol, limits,
resource overrides, startup and exit checks.

The follow-stack launcher now starts/checks only Robot Service, then connects
through the same adapter used by the follow loop:

```bash
cd $HOME/ThirdHand/UIEAclub_ThirdHand_VLA/apps/dummy
../../local/runtimes/dummy-python/bin/python apps/run_follow_stack.py --no-start
../../local/runtimes/dummy-python/bin/python apps/run_follow_stack.py --enable-motion
```

The first command checks an existing service and connects the SDK; connecting
can enable motors even without starting the follow loop. The second starts
Robot Service if necessary and enables following. Omit `--no-start` to allow
service startup without starting the follow loop.

Follow and calibration entrypoints default to `ws://127.0.0.1:3000/ws` and
`http://127.0.0.1:3000/health`. When running Dummy on another machine, set
`--robot-ws ws://<ubuntu-address>:3000/ws` and
`--robot-health http://<ubuntu-address>:3000/health` together. For the generic
personality loop, configure `robot.ws_url` and `robot.health_url` in
`configs/dum_e_touch_r1.yaml`. The `robot` section in
`configs/person_follow_production.yaml` uses the same adapter contract.

For the real camera/person-follow demo, use the `dummy-python` runtime. It
contains OpenCV 5 for the default YuNet face detector.

```bash
cd $HOME/ThirdHand/UIEAclub_ThirdHand_VLA/apps/dummy
../../local/runtimes/dummy-python/bin/python apps/run_person_follow.py --enable-motion
```

To open only the color camera + algorithm overlay window on the Ubuntu desktop:

```bash
cd $HOME/ThirdHand/UIEAclub_ThirdHand_VLA/apps/dummy
../../local/runtimes/dummy-python/bin/python apps/test_find_person_window.py
```

The `--enable-motion` flag is an intentional operator gate. Without it, these
entrypoints run a visual dry-run without opening the robot connection. Only use the
flag after the workspace is clear and the operator has explicitly approved
physical motion.

The generic entrypoint is now another name for the same visual dry-run:

```bash
cd $HOME/ThirdHand/UIEAclub_ThirdHand_VLA/apps/dummy
../../local/runtimes/dummy-python/bin/python apps/run_dummy.py
```

## Resource paths

URDF, hand-eye calibration and YOLO paths are relative to the repository root,
not the process working directory or the original Ubuntu checkout. Mink resolves
its model path before loading. MediaPipe's `models/...` path remains relative to
`apps/dummy`, as before.

The default YuNet weights, optional BlazeFace weights and URDF/STL are delivered through
Git/Git LFS. Run `bash tools/assets/setup_clone.sh` after cloning to verify assets
and prepare dependencies; see [fresh-clone instructions](../../docs/assets/FRESH_CLONE_CN.md).
The optional YOLO body detector still needs `local/models/vision/yolov8n.pt` or an
explicit `vision_service.yolo_person_model_path`; it is not the default face
tracking path. Missing optional weights report an unavailable detector rather
than downloading a model during startup.

## Individual checks

```bash
../../local/runtimes/python/bin/python apps/test_robot_state.py
../../local/runtimes/python/bin/python apps/test_motion.py --joint 5 --deg 0.5
../../local/runtimes/python/bin/python apps/test_gestures.py nod
../../local/runtimes/python/bin/python apps/test_gestures.py head_tilt
../../local/runtimes/python/bin/python apps/test_gestures.py droop
../../local/runtimes/python/bin/python apps/test_gestures.py perk_up
../../local/runtimes/python/bin/python apps/test_gestures.py wiggle
../../local/runtimes/python/bin/python apps/test_tracker.py
../../local/runtimes/python/bin/python apps/visualize_camera_web.py --host 0.0.0.0 --port 18080
../../local/runtimes/python/bin/python apps/test_wake_word.py
../../local/runtimes/python/bin/python apps/test_follow.py
```

Keywords subscribe to `ws://127.0.0.1:3004/v1/transcripts` with subprotocol
`thirdhand.transcripts.v1`. This is a loopback-only read-only fan-out of final ASR
results, not another microphone session. Deploy the Speech Service change with
Dummy. `ThirdHand`, `nod`, `wiggle`, `tilt` and their configured Chinese equivalents
are exact commands; partial transcripts and duplicate message IDs are ignored.
On Ubuntu, the terminal also accepts these commands followed by Enter. Keyword
events expire after three seconds instead of executing a backlog after motion.

## Safety

The adapter retains joint limits, finite-value validation,
command intervals, motion-busy checks, workspace geometry checks and
request-matched completion/error handling. Robot Service's own readiness,
fresh-feedback, joint-limit and speed checks are unchanged. The workspace guard
checks targets against the base bottom plane; it is not full collision planning.

## Follow speed and range

The J1/J4 image servo computes a geometric correction from pixel error, gain
and calibrated axis response. Dummy no longer clips it to a local 10 deg/s
budget or a fixed step size. J1 keeps its 85 degree excursion envelope; J4 has absolute limits of
[-35, 35] degrees and a 35 degree excursion envelope around the startup pose.
Their intersection with hardware limits remains enforced. A pose outside the
follow envelope holds rather than snapping back into it.

Dummy sends joint targets without `time_sec` or a speed override. Robot Service
uses the shared SDK speed-mode policy: default maximum J1-J3 15 deg/s and J4-J6
50 deg/s; a lower service speed scale stays lower. This applies to following,
all six gesture axes, explicit zero and calibration scripts. Keyword keyframe
timestamps retain ordering, but no longer prescribe segment duration or easing.
The SDK plans segment time. The adapter uses a separate bounded completion
deadline, `robot.motion_completion_timeout_s: 45.0`, not an endpoint-duration
estimate. Legacy adapter `time_sec` arguments are accepted but ignored.
See [Robot speed policy and SDK prerequisite](../../services/robot/config/README.md)
before deployment; Robot Service refuses hardware connection if the local SDK's
velocity reference does not match. No SDK runtime file is patched by this change.

The minimum send interval is 0.10 seconds (at most 10 commands/second). The
working hardware loop also caps its requested rate at 10 Hz. This is a rate
ceiling, not a promise of 10 Hz physical retargeting: the current service still
rejects motion replacement while a joint trajectory is active. Hardware speeds,
especially after SDK waypoint adjustments, require feedback-based acceptance;
offline policy tests do not establish measured motor speeds. Removing the local
step budget permits larger follow corrections; validate gains and axis signs
before running hardware. Following still waits for each trajectory to finish.

See [the follow speed and latency plan](docs/follow-speed-and-latency-plan.md)
and [the runtime implementation guide](docs/runtime-stage-two.md) for the current
implementation, remaining SDK work, lifecycle requirements and acceptance checks.

Press Ctrl+C or send SIGTERM to the Dummy process to exit. New commands stop
immediately; the current bounded command may finish before the process closes
its own detection worker, MJPEG reader, transcript subscription and robot socket.
This does not stop Robot/Vision/Speech/Web, disconnect SDK, disable motors or
close CAN. Do not use `./thirdhand stop` when the intention is to stop only Dummy.

The real follow entrypoint still holds a local process lock against duplicate
Dummy follow loops. This is not an ownership lease and does not prevent the
webpage or another client from sending commands. Do not run competing motion
controllers at the same time. Keep a hardware stop or physical power cut
reachable for real robot tests; software stop is not a hardware emergency stop.

## Migration plan

1. **Directory migration (complete):** keep the application under `apps/dummy`, preserve its internal Python package, and make application-owned model paths independent of the working directory.
2. **Contract adaptation:** replace ad hoc Vision health/MJPEG parsing with the formal Vision Service target and stable identity contracts.
3. **Capability split:** move reusable person-follow and gesture primitives into `skills/interaction/person-follow` and `skills/manipulation/gesture`; keep personality state and lifecycle in this application.
4. **Transport adaptation (complete):** use only `TouchR1Adapter -> Robot Service :3000/ws` for Dummy motion. Do not reintroduce a separate relay or lease service.
5. **Lifecycle integration:** add an opt-in launcher profile only after cancellation, stale-target and software-stop tests pass. Do not include it in the default or manual-control profiles.
6. **Hardware acceptance:** validate target loss, reacquisition, joint limits, command rate, operator cancellation and hardware stop behavior with a cleared workspace.

Completion requires all of the following:

- no process outside Robot Service opens `can0` or imports Startouch SDK;
- stable target identity is preserved between Vision evidence and motion commands;
- motion stops on stale vision, target change or operator cancellation;
- offline tests pass without camera or robot hardware;
- real-hardware tests require an explicit operator-selected profile.
