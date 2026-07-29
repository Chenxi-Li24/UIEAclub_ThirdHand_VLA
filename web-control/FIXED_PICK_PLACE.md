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
- Real mode is hard-limited to a speed scale of 5% and requires
  `--confirm-each-step`.
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
  --real --speed-scale 0.05 --confirm-each-step
```

The sequence is:

```text
MOVE_HOME -> MOVE_PRE_PICK -> MOVE_PICK -> CLOSE_GRIPPER
-> MOVE_LIFT -> MOVE_PRE_PLACE -> MOVE_PLACE -> OPEN_GRIPPER
-> MOVE_RETREAT -> RETURN_HOME -> COMPLETE
```

Per-run logs are saved under `logs/fixed_pick_place/`.

## Stop and recovery

Press Ctrl+C or type `STOP` at a confirmation prompt. The runner stops issuing
new steps, requests SDK cleanup, and exits non-zero. Before retrying, inspect
the latest log, verify `can0`, confirm no Startouch/web/ROS control process is
running, inspect the physical arm and workspace, and reconnect only after the
cause is understood.
