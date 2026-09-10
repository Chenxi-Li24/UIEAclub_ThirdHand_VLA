# Startouch-Compatible Shadow Boundary Design

Status: approved by delegated user authority on 2026-08-07.

## Purpose

Validate orchestration commands against the existing Startouch bridge command shape while making
real execution structurally impossible. This completes interface dry-run only; it does not connect
to CAN, import the Startouch SDK, start the bridge, move the arm, operate the gripper, or control a
camera.

## Safety Invariants

1. `robot_execution_enabled` is a literal `false` in every config, request, receipt, trace, and
   summary.
2. The shadow package must not import `startouchclass`, `can`, `socket`, `subprocess`, ROS, camera
   libraries, or `web-control` implementation modules.
3. Only `fake` and `shadow` executor kinds exist; neither can cause a world change.
4. The shadow executor serializes a preview artifact and returns a dry-run receipt. Progress still
   requires a newer replayed/read-only observation proving the expected effect.
5. Any request for real execution, missing unit/frame, out-of-range value, unvalidated calibration,
   unknown command, or mismatched contract is rejected before serialization.

## Components

### Command preview models

Frozen models cover the subset required by Pick and Place:

- joint waypoint preview: six radians, duration, speed percentage;
- linear pose preview: xyz metres, Euler radians, frame, calibration ID, duration, tolerances;
- gripper preview: normalized position or metres, not both;
- request ID, episode, step, attempt, policy and contract versions.

The preview mirrors names and units from the existing bridge but is not imported by it. Bounds are
copied into checked configuration with provenance and tested against representative bridge
commands.

### Shadow executor

`StartouchShadowExecutor` implements the runtime executor protocol with `kind="shadow"` and
`can_execute_world=False`. An injected `PreviewResolver` maps an exact-version Skill request to
frozen joint, linear, or gripper previews; no resolver may read robot state or invent a default
pose. The executor writes canonical JSON previews to an explicit local directory using
content-addressed filenames and returns `ReceiptStatus.COMPLETED` only to mean serialization
completed. Its evidence kind is `shadow_command_preview`, never `robot_motion`.

### Capability gate

`ExecutionCapability` is created only by a factory that accepts `mode="fake"` or `mode="shadow"`.
There is intentionally no real-mode factory, environment-variable escape hatch, SDK adapter, or
network transport in this delivery.

## Acceptance

1. AST isolation tests forbid hardware, process, and network imports.
2. A real-execution flag cannot be represented by the public models.
3. Valid Pick/Place previews round-trip deterministically and contain explicit units, frames,
   versions, bounds, and evidence IDs.
4. Invalid or unsafe previews are rejected without writing an artifact.
5. A shadow receipt alone cannot advance the supervisor.
