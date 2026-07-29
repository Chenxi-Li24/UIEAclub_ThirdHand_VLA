# Fixed-point Pick and Place

This command-line workflow reuses `server/startouch_bridge.py`, the same
hardware-tested Startouch SDK bridge used by the web control. It does not use
vision, Cartesian IK, ROS, or the unfinished VLA control wrappers.

## Safety model

- The real point file starts with every waypoint unset. Real joint angles are
  never guessed.
- Every point must contain six finite, non-zero joint angles inside the
  hardware-tested Startouch limits.
- The existing bridge retains CAN preflight, stable-state checks, motion
  serialization, all-zero rejection, CAN receive monitoring, and its exclusive
  `/tmp/startouch-web-can0.lock`.
- Real mode is hard-limited to the operator-verified speed scale of 30%.
  The current configuration still requires `--confirm-each-step` until three
  consecutive complete real cycles succeed.
- An error or Ctrl+C stops the remaining sequence and requests the bridge's
  SDK `cleanup()` path. This software stop is not a substitute for a reachable
  hardware E-stop or power disconnect.

Do not run the web controller and this command at the same time.

## Teach the seven points

Use the existing web controller to jog the arm to each safe point, disconnect
the web controller, then record the current J1-J6 state:

```bash
cd ~/arm/UIEAclub_ThirdHand_VLA-fixed-pick-place
~/miniconda3/envs/LumosTouch/bin/python \
  web-control/scripts/teach_fixed_point.py home
```

Repeat for `pre_pick`, `pick`, `lift`, `pre_place`, `place`, and `retreat`.
Before each write, the complete old YAML file is copied to:

```text
configs/tasks/.fixed_pick_place_backups/
```

Use `--print-only` to read and validate without saving. The tool refuses an
all-zero state, NaN/infinity, an incorrect joint count, or an out-of-limit
state.

## Software-only verification

```bash
cd ~/arm/UIEAclub_ThirdHand_VLA-fixed-pick-place

~/miniconda3/envs/LumosTouch/bin/python \
  web-control/scripts/fixed_pick_place.py \
  --simulate --config tests/fixtures/fixed_pick_place_test.yaml

STARTOUCH_SDK_PATH=~/arm/startouch_sdk \
~/miniconda3/envs/LumosTouch/bin/python \
  web-control/scripts/fixed_pick_place.py \
  --dry-run --config tests/fixtures/fixed_pick_place_test.yaml
```

The fixture contains simulation-only points and must never be used with
`--real`.

## First real run

Only after all seven real points have been taught, the work area is clear, a
human is beside the arm, a hardware E-stop/power disconnect is immediately
reachable, and no other control process is running:

```bash
cd ~/arm/UIEAclub_ThirdHand_VLA-fixed-pick-place
~/miniconda3/envs/LumosTouch/bin/python \
  web-control/scripts/fixed_pick_place.py \
  --real --speed-scale 0.30 --confirm-each-step
```

The current supervised A/B launch runs one cycle and uses 25 cm raised transfer
points. Each logical route is submitted as one continuous SDK path:

```text
OPEN -> HOME -> A_UP -> A -> ADAPTIVE_GRASP_A -> A_UP -> B_UP -> B -> OPEN
-> B_UP -> HOME -> B_UP -> B -> ADAPTIVE_GRASP_B -> B_UP -> A_UP
-> A -> OPEN -> A_UP -> HOME
```

Per-run logs are saved under `logs/fixed_pick_place/`.

The one-click entry is:

```bash
cd /home/nieqingcao/arm/UIEAclub_ThirdHand_VLA-fixed-pick-place
bash scripts/demo_fixed_pick_place.sh
```

The Ubuntu-local Start/Stop page is:

```bash
cd /home/nieqingcao/arm/UIEAclub_ThirdHand_VLA-fixed-pick-place
bash scripts/open_fixed_pick_place_control.sh
```

It binds only to `127.0.0.1:8766` and does not connect to `can0` while idle.
The Start button launches the guarded one-click entry. The Stop button sends
SIGINT only to the page-owned process group; the runner executes SDK cleanup
and motor disable, and the arm remains at its current pose. It does not offer
any function to terminate an unrelated controller.

When `--confirm-each-step` is active, the page shows
`WAITING_CONFIRMATION` and enables the yellow “执行下一步” button. Each click
writes exactly one confirmation to the owned runner. Closing the confirmation
channel is handled as a clean operator abort with cleanup rather than an
uncaught `EOFError`.

For smooth motion, each logical route is interpolated into points no farther
than 12° apart and submitted as one SDK `set_joint_waypoints` call. This keeps
the bounds check without forcing the arm to decelerate to zero at every
interpolation point.

## Stop and recovery

Press Ctrl+C or type `STOP` at a confirmation prompt. The runner stops issuing
new steps, requests SDK cleanup, and exits non-zero. Before retrying, inspect
the latest log, verify `can0`, confirm no Startouch/web/ROS control process is
running, inspect the physical arm and workspace, and reconnect only after the
cause is understood.
