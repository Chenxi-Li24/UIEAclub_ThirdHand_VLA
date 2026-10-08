# Fixed TCP Demo

Run from this folder:

```bash
cd apps/fixed_tcp_demo
python fixed_tcp_demo.py
```

The default mode is dry-run and does not send motion commands. It asks the
already-running port-3000 Robot Service to use its existing StarTouch SDK instance,
with the configured fixed gripper-tip point
`[0.48, 0.0, 0.36]` meters, moves through the same planning path without
sending hardware commands, checks IK for a dramatic RCM cone trajectory, and
writes CSV logs.

Run the commands above from the project root. The client does not create a
second SDK instance, start services, or enable motors. Even a nonexecuting
plan requires a separately connected port-3000 owner and reads its actual
state. Use FakeArm tests for hardware-free verification.

The 9983 preset section contains a `go around` button. Clicking it is an
explicit real-motion request; it is not an offline preview or an automatic
startup action. Stop with the separate software-stop control; an independent
hardware E-stop is still required. This migration has only been tested with
fake hardware; the inherited physical-review claims below are historical.

The fixed point is the gripper far-tip TCP, not the flange. ThirdHand's URDF
places the gripper fingers at `x=0.15584m` from `gripper_base`; the installed
StarTouch SDK is configured for the TypeLJ gripper tool at `x=0.17334m`, and
`get_ee_pose_euler()` / `solve_ik()` use that tool point.

Real hardware run, after confirming the work area is clear:

```bash
python fixed_tcp_demo.py --execute --no-dry-run
```

The hardware sequence is:

1. Require port 3000 to have a connected, healthy StarTouch SDK on `can0`.
2. Run the existing `FixedTcpDemo` action inside that port-3000 Python bridge.
3. Move to all-zero joints `[0,0,0,0,0,0]` over 3 seconds.
4. Move smoothly to the screened fixed-tip center pose over 6 seconds.
5. Lock the configured fixed gripper-tip point.
6. Precheck the full continuous fixed-point ray-wrapping trajectory for IK,
   joint limits, workspace, and known SDK collision-risk zones.
7. Send the whole prechecked 50 Hz joint waypoint trajectory once in SDK time
   mode over 60 seconds, so the SDK's internal waypoint backend performs one
   continuous motion instead of stop-start Python servo steps.
8. On normal completion, return smoothly to all-zero home joints over 4 seconds.
9. Stop sending new commands; port 3000 keeps its SDK connection for subsequent commands.

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
with its configured transition time, and contracts once before the arm returns home; the
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

Stop with `Ctrl+C` or the 9983 software-stop control. Port 3000 stops its SDK
control process; the demo does not send Home on exceptions or interrupts, only
after a normal completed demo. Closing the command client also requests a stop.

The demo program itself never opens `can0`. Port 3000 remains the only SDK/CAN owner.

Every physical stage (zero, center, orbit and return) uses port 3000's ordinary
bounded waypoint speed policy, including a configured scale below 0.05. The
separate Dummy continuous-follow speed policy is unchanged. Fixed timing fields
are retained as historical/planning parameters, not speed overrides. The nominal
trajectory duration and monitor target timeline are not guaranteed physical
completion times after SDK retiming. Actual SDK timing/stopping and geometry
still require separately authorized hardware verification.

Software stop permanently cancels that run. A new connection is refused while
the old motion worker has not finished; reconnect cannot revive its cancellation
event. This does not make software stop an independent hardware emergency stop.

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
