# Dummy: Dum-E personality for ThirdHand Touch R1

This experimental application lives in `apps/dummy/` and talks to the existing ThirdHand Robot Service at `ws://127.0.0.1:3000/ws`.
It does not import Startouch SDK and does not open CAN directly.
It is not part of the default launcher profile and must be started explicitly.

## Current boundary

`DummyDirector` composes Vision, Speech and Robot Service into a long-running personality and person-follow loop. It is application-level orchestration, not a device service or a one-shot Skill.

The current adapter still sends legacy Robot Service motion commands directly. Until person-follow and gestures use the plan, authorization and Skill execution chain, do not add this application to the default one-click startup.

## Run

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

The adapter sends bounded absolute joint targets through Robot Service `move_joint`; configuration clamps each relative command. The real follow entrypoint also holds an exclusive process lock so a second Dummy controller cannot compete for the arm. Keep a hardware stop or physical power cut reachable for real robot tests.

## Migration plan

1. **Directory migration (complete):** keep the application under `apps/dummy`, preserve its internal Python package, and make application-owned model paths independent of the working directory.
2. **Contract adaptation:** replace ad hoc Vision health/MJPEG parsing with the formal Vision Service target and stable identity contracts.
3. **Capability split:** move reusable person-follow and gesture primitives into `skills/interaction/person-follow` and `skills/manipulation/gesture`; keep personality state and lifecycle in this application.
4. **Authorization:** route every physical action through TaskPlan, one-time authorization and Robot Service `/execution`; remove direct legacy motion commands from `TouchR1Adapter`.
5. **Lifecycle integration:** add an opt-in launcher profile only after authorization, cancellation, stale-target and software-stop tests pass. Do not include it in the default or manual-control profiles.
6. **Hardware acceptance:** validate target loss, reacquisition, joint limits, command rate, operator cancellation and hardware stop behavior with a cleared workspace.

Completion requires all of the following:

- no process outside Robot Service opens `can0` or imports Startouch SDK;
- stable target identity is preserved between Vision evidence and motion authorization;
- motion stops on stale vision, target change, authorization expiry or operator cancellation;
- offline tests pass without camera or robot hardware;
- real-hardware tests require an explicit operator-selected profile.
