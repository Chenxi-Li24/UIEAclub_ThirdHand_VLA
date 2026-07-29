# Fixed Pick and Place development audit

Audit date: 2026-07-29 (Asia/Shanghai)

## Final demo entry and latest validation

Current task settings:

- workflow: `home_transit_ab`
- vertical lift above A and B: 0.250 m
- motion speed scale: 0.15
- requested cycles per launch: 3
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

Real points are intentionally unset in
`configs/tasks/fixed_pick_place.yaml`. They must be obtained by physical
teaching. The simulation fixture is isolated under `tests/fixtures/` and is
documented as forbidden for real mode.

## Verification completed

- Python compilation: passed.
- Git whitespace/error check: passed.
- Standard-library automated tests: 9 passed.
- Tests cover normal sequence, missing/invalid/all-zero/non-finite/out-of-limit
  points, timeout, gripper failure, operator abort, Ctrl+C cleanup, dry-run
  orchestration, point-file backup/update, and exclusive lock conflict.
- Full `STARTOUCH_SIMULATE=1` sequence: passed.
- Full Startouch SDK `dry_run=True` sequence: passed, including gripper state
  completion and SDK destruction/cleanup.
- SDK import in LumosTouch Python: passed.
- Passive J1-J6 CAN query: passed without constructing `SingleArm` or enabling
  motors. At audit time the angles were approximately
  `[26.021, 139.283, -53.145, -89.034, -2.109, 0.186]` degrees and all six
  motor feedback error codes were zero.
- `can0` and process inspection found no active Startouch web, bridge, ROS, or
  other robot-control process.

No real joint, Cartesian, or gripper motion was executed. The SDK exposes
gripper feedback through `SingleArm`, but no separate proven passive gripper
reader was found; the existing `test_gripper_raw.py` sends multiple real
gripper commands and was not run.

## Remaining gated work

The seven real waypoints are not taught, so real execution is correctly blocked.
The next physical stage requires:

1. An operator beside the arm, clear workspace, and reachable hardware
   E-stop/power disconnect.
2. Web/manual low-speed positioning followed by safe point recording.
3. A separate passive gripper-status method or an explicitly approved,
   supervised SDK connection.
4. Explicit `CONFIRM_REAL_ARM_TEST` approval before any real motion.
5. Step-confirmed <=5% small-range run, then empty full sequence, object run,
   and three-repeat validation.
