# Fixed Pick and Place automatic three-cycle button design

Date: 2026-07-30  
Status: user-approved design

## Goal

Add a separate Ubuntu-local dashboard button that starts exactly three
automatic A-to-B-to-A Pick and Place cycles. The operator presses Start once
and does not need to press the existing Continue button between stages.

The existing supervised step-by-step mode remains available and unchanged.
This change adds software capability only; installing or opening the updated
dashboard must not start or enable the arm.

## User interface

The action panel will contain:

1. `手动逐步演示` for the existing supervised mode;
2. `一键自动循环 3 次` for the new automatic mode;
3. `执行下一步`, enabled only while a manual run awaits confirmation;
4. `停止并失能`, enabled while either mode owns a running process.

The automatic button shows a confirmation dialog stating that it will run
three complete cycles at 30% speed. The dialog requires the operator to
confirm that the bottle is at A, the workspace is clear, an onsite person is
present, and the physical E-stop is usable.

While a run is owned, both Start buttons are disabled. Status responses include
the selected mode so the page can display whether the active process is manual
or automatic.

## Control architecture

The dashboard adds a dedicated `POST /api/start-auto` endpoint. The existing
`POST /api/start` endpoint continues to start manual mode. Both endpoints call
one process-owning controller method with an explicit mode; the controller
still permits at most one owned demo process.

Automatic mode passes narrowly scoped environment values to
`scripts/demo_fixed_pick_place.sh`:

- mode: automatic;
- cycle override: exactly 3;
- step confirmation: disabled.

Manual mode passes no override and therefore continues to use the task
configuration: one cycle with per-stage confirmation.

The shell launcher validates the mode and cycle override before motion. It
prints the selected mode, speed, cycle count, and confirmation state in the
preflight log. Invalid or inconsistent overrides fail before the runner starts.

The Python runner receives an explicit cycle override and an explicit
automatic-mode flag. Real automatic mode is accepted only when all of these
conditions hold:

- the request came through the validated automatic launcher path;
- cycles equal exactly 3;
- speed does not exceed the existing 0.30 real-arm hard limit;
- the normal real-point, joint-limit, CAN, worktree, and resource checks pass.

No point, lift height, gripper parameter, interpolation bound, or trajectory
shape changes as part of this feature.

## Execution and stopping

After preflight, automatic mode keeps the existing safety message and
three-second countdown. It then executes three copies of the current 20-stage
sequence:

`Home -> A-up -> A -> grasp A -> A-up -> B-up -> B -> release -> B-up -> Home
-> B-up -> B -> grasp B -> B-up -> A-up -> A -> release -> A-up -> Home`

Each logical movement route remains one continuous SDK path. Grasp, release,
vertical approach, vertical lift, and Home remain intentional task boundaries.

The existing Stop button sends SIGINT only to the dashboard-owned process
group. Normal completion, failure, browser-requested Stop, Ctrl+C, and signal
termination all retain the cleanup and motor-disable path. The process never
automatically returns Home after an emergency stop; it stops and disables at
the current position.

If another process owns the arm, `can0`, or the worktree, the launcher prints
`RESOURCE_CONFLICT`, does not signal the other process, and exits.

## Failure reporting and logs

Any failed stage aborts the remaining stages and cycles. The dashboard displays
the failed stage and reason from the launcher log. Successful automatic
completion prints `PICK AND PLACE COMPLETE`; failure prints
`PICK AND PLACE FAILED`.

All preflight, mode, cycle progress, bridge events, cleanup results, and final
status remain under `logs/fixed_pick_place/`.

## Test strategy

Implementation follows test-driven development. Tests will first demonstrate
the missing behavior, then cover:

- the page contains separate manual and automatic buttons;
- `/api/start-auto` starts one owned process with only the approved automatic
  environment values;
- duplicate manual/automatic Start requests are rejected while either mode is
  running;
- automatic mode cannot use Continue and manual mode still can;
- Stop signals only the owned automatic process group;
- the launcher rejects unknown modes, non-three cycle overrides, and speeds
  above 0.30 before runner launch;
- the runner executes exactly 60 stages for three full cycles without reading
  confirmation input;
- a middle-cycle failure aborts later work and executes cleanup;
- dashboard-driven Start-to-Complete simulation succeeds for automatic mode;
- the full existing manual-mode regression suite remains green.

Verification will include Python compilation, Bash syntax checks, whitespace
checks, all automated tests, a complete three-cycle simulation at the current
real point configuration, and preflight-only execution. Hardware motion is not
part of software verification and requires a separate onsite operator action.
