# Dummy: Dum-E personality for ThirdHand Touch R1

This experimental application lives in `apps/dummy/` and talks to the existing ThirdHand Robot Service at `ws://127.0.0.1:3000/ws`.
It does not import Startouch SDK and does not open CAN directly.
It is not part of the default launcher profile and must be started explicitly.

## Current boundary

`DummyDirector` composes Vision, Speech and Robot Service into a long-running personality and person-follow loop. It is application-level orchestration, not a device service or a one-shot Skill.

All Dummy motion goes through `TouchR1Adapter` directly to Robot Service `/ws`
on port 3000. There is no Dummy relay server, ownership lease, lease heartbeat
or lease-based authorization. `request_id` remains a command/reply correlation
ID, not a lease or permission token. Robot Service remains the only CAN/SDK owner.

The production person-follow runtime is still an observation-validation scaffold;
it does not generate or execute motions by itself. The working follow loop is
`apps/run_head_body_follow.py` (also wrapped by `run_dume_follow_touch_r1.py`).

## Run

The follow-stack launcher now starts/checks only Robot Service, then connects
through the same adapter used by the follow loop:

```bash
cd $HOME/ThirdHand/UIEAclub_ThirdHand_VLA/apps/dummy
../../local/runtimes/vision-python/bin/python apps/run_follow_stack.py --no-start
../../local/runtimes/vision-python/bin/python apps/run_follow_stack.py --enable-motion
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

For the real camera/person-follow demo, use the `vision-python` runtime. It
contains the OpenCV cascade runtime used for face/upper-body locking.

```bash
cd $HOME/ThirdHand/UIEAclub_ThirdHand_VLA/apps/dummy
../../local/runtimes/vision-python/bin/python apps/run_person_follow.py --enable-motion
```

To open only the color camera + algorithm overlay window on the Ubuntu desktop:

```bash
cd $HOME/ThirdHand/UIEAclub_ThirdHand_VLA/apps/dummy
../../local/runtimes/vision-python/bin/python apps/test_find_person_window.py
```

The `--enable-motion` flag is an intentional operator gate. Without it, the
real-follow entrypoint exits before opening the robot connection. Only use the
flag after the workspace is clear and the operator has explicitly approved
physical motion.

The generic personality loop is still available, but it uses the default
runtime and startup gestures:

```bash
cd $HOME/ThirdHand/UIEAclub_ThirdHand_VLA/apps/dummy
../../local/runtimes/python/bin/python apps/run_dummy.py
```

## Resource paths

URDF, hand-eye calibration and YOLO paths are relative to the repository root,
not the process working directory or the original Ubuntu checkout. Mink resolves
its model path before loading. MediaPipe's `models/...` path remains relative to
`apps/dummy`, as before.

Prepare YOLO person weights at `local/models/vision/yolov8n.pt`, or set
`vision_service.yolo_person_model_path` to an explicit local path. Weights are
not committed to Git; a missing file reports an unavailable detector rather
than automatically downloading a model. A fresh clone still needs its local
model assets and optional Mink/MuJoCo dependencies prepared before hardware use.

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

Wake word currently listens to the ThirdHand speech websocket when available and also accepts typing `ThirdHand` + Enter in the terminal as a deterministic fallback.

## Safety

The adapter retains joint limits, finite-value validation, relative-step
clamping, command intervals, motion-busy checks, workspace geometry checks and
request-matched completion/error handling. Robot Service's own readiness,
fresh-feedback, joint-limit and speed checks are unchanged. The workspace guard
checks targets against the base bottom plane; it is not full collision planning.

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
