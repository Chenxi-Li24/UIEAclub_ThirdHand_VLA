# Fixed TCP Demo

Run from this folder:

```bash
cd /home/nieqingcao/ThirdHand/UIEAclub_ThirdHand_VLA/fixed_tcp_demo
python fixed_tcp_demo.py
```

The default mode is dry-run and does not send motion commands. It initializes the
StarTouch SDK in dry-run mode, uses the configured fixed gripper-tip point
`[0.48, 0.0, 0.36]` meters, moves through the same planning path without
sending hardware commands, checks IK for a dramatic RCM cone trajectory, and
writes CSV logs.

The fixed point is the gripper far-tip TCP, not the flange. ThirdHand's URDF
places the gripper fingers at `x=0.15584m` from `gripper_base`; the installed
StarTouch SDK is configured for the TypeLJ gripper tool at `x=0.17334m`, and
`get_ee_pose_euler()` / `solve_ik()` use that tool point.

Real hardware run, after confirming the work area is clear:

```bash
python fixed_tcp_demo.py --execute --no-dry-run
```

The hardware sequence is:

1. Check `can0`.
2. Initialize StarTouch SDK.
3. Move to all-zero joints `[0,0,0,0,0,0]` over 3 seconds.
4. Move smoothly to the screened fixed-tip center pose over 6 seconds.
5. Lock the configured fixed gripper-tip point.
6. Precheck the full continuous fixed-point ray-wrapping trajectory for IK,
   joint limits, workspace, and known SDK collision-risk zones.
7. Send the whole prechecked 50 Hz joint waypoint trajectory once in SDK time
   mode over 60 seconds, so the SDK's internal waypoint backend performs one
   continuous motion instead of stop-start Python servo steps.
8. On normal completion, return smoothly to all-zero home joints over 4 seconds.
9. Stop sending new commands and call SDK `cleanup()`.

To use a different fixed point:

```bash
python fixed_tcp_demo.py --fixed-xyz 0.48 0.0 0.36
```

The default point `[0.48, 0.0, 0.36]` is on the robot center axis. It was chosen
for smoothness: it was selected by a dry-run grid scan because it keeps extra margin from the wrist and J4 foldback zones after real-hardware collision review while keeping the full motion sequence free of IK fallback warnings. The
gripper far-tip stays fixed there while the tool ray sweeps around the largest
remote-center multi-motion sequence that passes the full precheck. The program
requests a 50 degree cone by default, then automatically reduces the angle until
all waypoints pass IK, joint limits, workspace checks, and local collision-risk
guards. It shows clockwise cone, cardinal cross, irregular shell, flower
envelope, nod/shake, spiral breathe, counterclockwise cone, and a final flower
envelope. The whole demo expands once at startup, blends between motion sets
with `--transition-sec`, and contracts once before the arm returns home; the
individual sets do not stop-and-restart at their boundaries. Strict mathematical
`+/-X`, `+/-Y`, `+/-Z`
ray poses would require a 90 degree cone and are not safe for this arm near the
documented wrist/foldback zones, so this demo uses the largest center-axis cone
that passed the SDK IK and local collision-risk precheck. If a target machine
rejects 35 degrees, the script automatically retries smaller cones.

To restore the old behavior and lock the current measured TCP XYZ:

```bash
python fixed_tcp_demo.py --use-current-tcp
```

Stop with `Ctrl+C`. The program stops sending new commands and calls SDK
`cleanup()`; it does not send Home on exceptions or interrupts, only after a
normal completed demo.

Dangerous parameters are at the top of `demo.py` in `DemoConfig`.
For a gentler first real test, run:

```bash
python fixed_tcp_demo.py --execute --no-dry-run --max-cone-deg 25 --duration-sec 20
```

For the current large exhibition profile, just run:

```bash
python fixed_tcp_demo.py --execute --no-dry-run
```

Logs are written to:

```text
logs/fixed_tcp_demo_YYYYMMDD_HHMMSS.csv
```

Watch `error_mm`, `ik_status`, and `loop_hz` first if the arm does not move or
the TCP point does not hold.
