# Fixed Pick and Place development audit

Audit date: 2026-07-29 (Asia/Shanghai)

## Final demo entry and latest validation

Current task settings:

- workflow: `home_transit_ab`
- vertical lift above A and B: 0.250 m
- operator-verified motion speed scale and hard limit: 0.30
- manual button: one cycle with step confirmation
- automatic button: exactly three cycles without per-stage confirmation
- every bottle approach is vertical (`HOME -> A_UP -> A` and
  `HOME -> B_UP -> B`); every departure first returns vertically to the
  corresponding raised point
- adaptive grasp stiffness: `kp=2.0`, `kd=0.1`
- step confirmation remains enabled because three consecutive real cycles
  have not yet completed successfully

Ubuntu local launch:

```bash
cd /home/nieqingcao/arm/UIEAclub_ThirdHand_VLA-fixed-pick-place
bash scripts/demo_fixed_pick_place.sh
```

Windows PowerShell remote launch:

```powershell
ssh -t robot-ubuntu "cd /home/nieqingcao/arm/UIEAclub_ThirdHand_VLA-fixed-pick-place && bash scripts/demo_fixed_pick_place.sh"
```

Ubuntu desktop Start/Stop page:

```bash
cd /home/nieqingcao/arm/UIEAclub_ThirdHand_VLA-fixed-pick-place
bash scripts/open_fixed_pick_place_control.sh
```

The dashboard binds to `127.0.0.1:8766`, remains detached from `can0` while
idle, and owns only the demo process it launches. Stop forwards SIGINT to that
owned process, which performs cleanup and motor disable; it does not return
Home automatically and cannot terminate an unrelated process.

The automatic button passes a fixed, launcher-validated tuple:
`automatic-three-cycle`, `CYCLES=3`, and
`REQUIRE_STEP_CONFIRMATION=0`. Unknown modes or altered automatic values fail
at `MODE_CHECK` before CAN or runner startup. The manual button retains its
existing one-cycle confirmation behavior.

## Continuous trajectory improvement

The prior real-run logs show every 12° subcommand alternating
`motion_state=MOVING` and `motion_state=IDLE`, which caused the visible
stop/start motion. The improved runner retains the 12° maximum interpolation
increment but sends all interpolation points for one logical route in one
`set_joint_waypoints` SDK call. Grasp, release and safe A/B raised waypoints
remain deliberate task boundaries.

Software-only coverage verifies:

- each logical route emits one bridge path command;
- every adjacent interpolated joint increment is no greater than 12°;
- empty, malformed, NaN, all-zero and out-of-limit paths are rejected;
- the bridge calls the SDK trajectory function exactly once;
- the dashboard is idle without spawning a robot process;
- Stop signals only the dashboard-owned process group;
- `RESOURCE_CONFLICT` is reported without signalling the conflicting process.
- supervised confirmation is transported through the dashboard-owned stdin;
  the yellow “执行下一步” button confirms one displayed stage at a time;
- a closed confirmation channel becomes a clean operator abort instead of an
  uncaught `EOFError`.
- the real task configuration completes all 20 confirmed logical stages in
  Startouch simulation, including both adaptive grasps and final Home;
- the dashboard drives that same simulation from Start through 20 Continue
  actions to COMPLETE;
- duplicate Start, invalid Continue, process-launch failure, broken
  confirmation pipes, stop-signal races and process-group Stop are covered.

On 2026-07-30 the onsite operator explicitly confirmed that 30% motion speed
had been tested and was acceptable. The speed configuration and hard limit
were therefore raised to 0.30. This confirmation does not prove three
consecutive complete bottle cycles, so one-cycle step confirmation remains
enabled and `validated_real_cycles` remains zero.

On 2026-07-29 at 20:40, the 15%/25 cm real run completed cycle 1
(A→B→A). Adaptive contact was detected at normalized gripper positions 0.749
at A and 0.786 at B. Cycle 2 stopped safely at `ADAPTIVE_GRASP_A`: after the
first return, the unfixtured bottle no longer remained centered at the taught
A point, and the gripper reached about 6.25 mm without contact. Cleanup
disabled the motors and left no control process running. This run is therefore
recorded as failed, not as three-cycle validation.

Relevant logs:

```text
logs/fixed_pick_place/demo-20260729-204025.log
logs/fixed_pick_place/run-20260729-204046.log
```

For reliable unattended repetition, A and B require a physical locating
fixture or another mechanism that guarantees the released bottle remains
centered. The software deliberately does not guess a shifted object position.

## Host and environment

- SSH host: `robot-ubuntu`
- Address/user: `nieqingcao@192.168.58.68`
- Ubuntu hostname: `ubuntu`
- OS: Ubuntu 20.04.6 LTS, Linux 6.14.6-custom x86_64
- Project: `/home/nieqingcao/arm/UIEAclub_ThirdHand_VLA`
- Isolated worktree:
  `/home/nieqingcao/arm/UIEAclub_ThirdHand_VLA-fixed-pick-place`
- Startouch SDK: `/home/nieqingcao/arm/startouch_sdk`
- Python: `/home/nieqingcao/miniconda3/envs/LumosTouch/bin/python`
  (Python 3.10.20)
- Node/npm: v24.18.0 / 11.16.0
- CAN: `can0`, UP, ERROR-ACTIVE, 1 Mbit/s, zero TX/RX error
  counters at audit time

The existing hardware web control launch command is:

```bash
cd ~/arm/UIEAclub_ThirdHand_VLA
web-control/scripts/start_ubuntu.sh
```

## Preserved baseline

The main project was clean at `f0b63106c0107515fbdc41db67235bf8a8c56853`
(`Add Ubuntu Startouch web control`). It exactly matched its `origin/main`.
The user-specified `upstream/main` had advanced to merge commit `233dd4f`;
the relevant added hardware-control content was already present in the local
baseline.

The SDK was deliberately not modified. Its `main` was at
`9f0bc8f324ccdf866e20c27bbc7ed5007869db46`, with locally modified binary
artifacts:

- `interface_py/startouch.cpython-310-x86_64-linux-gnu.so`
- `src/libstartouch.so`

It also contained untracked files `=24` and `=4.3.1`. These local SDK results
were preserved as found.

The pre-change audit and backup are under:

```text
/home/nieqingcao/arm/backups/fixed-pick-place-20260729-173727/
```

That directory contains commit/status/diff/untracked records for both
repositories, a compressed backup of Python/Shell/YAML/JSON files, Conda
environment information, and only redacted copies of any `.env` files found.

## Reused implementation

The fixed sequence launches and speaks the existing JSON-lines protocol in:

```text
web-control/server/startouch_bridge.py
```

Therefore it retains the existing Startouch SDK import, CAN feedback preflight,
stable initial-state check, six-axis joint limits, non-finite/all-zero target
rejection, single-motion queue, CAN receive watchdog, gripper feedback checks,
exclusive control lock, logging events, signal handling, and SDK `cleanup()`.

The current `home_transit_ab` task contains taught Home, A, B, A-up and B-up
points. Legacy points unused by this workflow may remain unset. Every point
update is backed up under `configs/tasks/.fixed_pick_place_backups/`. The
simulation fixture remains isolated under `tests/fixtures/` and is forbidden
for real mode.

## Verification completed

- Python compilation: passed.
- Git whitespace/error check: passed.
- Standard-library automated tests: 38 passed after the 30% speed-boundary
  update, including acceptance at 0.30 and rejection above 0.30.
- Tests cover normal sequence, missing/invalid/all-zero/non-finite/out-of-limit
  points, timeout, gripper failure, operator abort, Ctrl+C cleanup, dry-run
  orchestration, point-file backup/update, and exclusive lock conflict.
- Full `STARTOUCH_SIMULATE=1` sequence: passed.
- The current real point configuration completed all 20 supervised stages in
  simulation at speed scale 0.30, including both adaptive grasps and final Home.
- Production preflight passed with `SPEED_SCALE=0.3000`, `CYCLES=1`,
  `REQUIRE_STEP_CONFIRMATION=1`, and `DEMO_PREFLIGHT_OK`.
- Full Startouch SDK `dry_run=True` sequence: passed, including gripper state
  completion and SDK destruction/cleanup.
- SDK import in LumosTouch Python: passed.
- Passive J1-J6 CAN query: passed without constructing `SingleArm` or enabling
  motors. At audit time the angles were approximately
  `[26.021, 139.283, -53.145, -89.034, -2.109, 0.186]` degrees and all six
  motor feedback error codes were zero.
- Earlier baseline inspection found no active Startouch web, bridge, ROS, or
  other robot-control process. Resource ownership is rechecked before every
  run because this Ubuntu host is shared.
- Subsequent supervised hardware work completed two full A→B→A cycles at
  15%/25 cm in one attempt; the third cycle placed A→B, then stopped safely
  when the bottle drifted away from the taught B regrasp center. This is not
  recorded as three consecutive successful cycles.

## Remaining gated work

1. Ensure the other manual web controller has been voluntarily released by
   its owner; never terminate it from this demo.
2. Confirm an operator is beside the arm, the work area is clear, and the
   hardware E-stop/power disconnect is reachable.
3. Continue supervised bottle validation at the operator-verified 30% limit
   with step confirmation.
4. Do not exceed 30% or disable step confirmation based only on a partial run.
5. Record unattended mode only after three consecutive real cycles succeed
   with the bottle remaining centered at both physical fixtures.
