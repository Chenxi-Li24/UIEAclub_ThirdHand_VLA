# Active-View Browser Dry-Run Demo Design

Date: 2026-08-06

## Goal

Provide an operator-visible, interactive demonstration of the completed active-view
workflow before physical calibration and motion evidence exist. The demo must exercise
the production camera-test rendering contract and ID-only interaction contract while
remaining incapable of camera, robot, gripper, or network control.

## Selected approach

The existing `camera-test.html` accepts an explicit `?demo=1` query parameter. In this
mode it loads a separate browser-only demo transport. Normal mode remains unchanged.

The demo transport implements the same narrow interface used by the page:

- obtain the latest sanitized vision-status snapshot;
- submit `start_active_view`, `confirm_active_view_step`, and `cancel_active_view`
  messages containing identifiers only;
- notify the page when a new snapshot is ready.

No demo-specific branch belongs inside perception, planning, authorization, or robot
control modules. The page renderer consumes either live or demo snapshots without
knowing how they were produced.

## Safety boundary

Demo mode is fail-closed and visibly different from live mode:

- a persistent banner states that all data and motion are simulated;
- the safety header always shows `robotExecutionEnabled = false` and
  `activeViewExecutionEnabled = false`;
- no `WebSocket`, `fetch`, camera stream, Startouch bridge, robot command, gripper
  command, or backend API is created by the demo transport;
- commands with coordinates, joint arrays, unknown keys, malformed IDs, or unknown
  command types are rejected locally;
- the terminal state is `grasp_preview`; the demo has no grasp-execution control;
- leaving `?demo=1` destroys the in-memory demo state because nothing is persisted.

## Demonstrated workflow

The initial snapshot contains one fresh, confirmed tabletop target with RTMDet mask
metadata, REMIND memory diagnostics, and DINO prototype similarity. The operator can:

1. start an active-view session for the displayed identity;
2. inspect a coarse observation proposal bound to demo evidence IDs;
3. confirm the first simulated observation step;
4. inspect identity verification and an initially insufficient D435 depth sample;
5. confirm one bounded refinement step;
6. reach `grasp_preview` with stable D435 samples and acceptable central coverage;
7. cancel from any non-terminal phase and observe a fail-closed `aborted` state.

Each confirmation advances exactly one logical step. There is no timer-driven automatic
progression and no simulated claim that physical motion succeeded.

## Components

### Demo state machine

A standalone JavaScript module owns deterministic demo snapshots, validates ID-only
commands, and exposes `snapshot()`, `send(command)`, and `subscribe(listener)`.

### Page transport adapter

The camera-test page selects live transport by default and demo transport only when the
query parameter is exactly `demo=1`. Both transports feed the existing `render(status)`
function. Demo mode replaces both camera images with clearly labelled synthetic panels.

### Test launcher

An isolated loopback launcher serves static files on an unused port and prints the exact
demo URL. It never starts the proxy, camera bridge, or Startouch bridge.

## Error handling

Invalid commands return a rejected result with a bounded reason and do not change state.
A repeated confirmation, mismatched identity/session/proposal, or command in a terminal
phase is rejected. Any internal invariant failure transitions to `aborted` and retains
both execution locks as false.

## Verification

Tests must prove:

- demo mode creates no network or actuator-capable transport;
- the deterministic state machine reaches `grasp_preview` only after two distinct
  confirmations;
- every outbound command is ID-only;
- cancellation and malformed commands are fail-closed;
- the UI displays the simulation banner, identity diagnostics, D435 quality progression,
  evidence summary, per-step confirmation, and no grasp execution button;
- normal mode still uses the live endpoints and existing browser tests remain green.

The launcher is additionally checked for loopback-only binding and for absence of robot,
camera, CAN, and Startouch startup paths.

## Non-goals

- generating physical calibration evidence;
- validating real camera geometry, depth accuracy, observation paths, or grasp success;
- bypassing any calibration, identity, execution, or operator-confirmation gate;
- replacing the existing deterministic control verifier or real staged-validation plan.
