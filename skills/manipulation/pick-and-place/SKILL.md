---
name: manipulation-pick-and-place
description: Use when the user requests a supervised pick of a stable target and placement at an approved destination.
---

# Supervised Pick And Place

## Purpose

Coordinate observation, target selection, grasp planning, one-time authorization, execution supervision, gripper control and result verification for a single target.

## Required Flow

1. Resolve a fresh stable `TargetRef`.
2. Call `plan` only; do not move.
3. Return an immutable `thirdhand.task-plan.v1` and concrete risk list.
4. Display the plan and obtain one user authorization.
5. Validate authorization, plan revision, target pose revision and service health.
6. Start independent supervision.
7. Execute through Robot Service.
8. Verify grasp and placement, then return a versioned result.

## Safety Invariants

The Skill never opens `can0` or imports the SDK directly. Robot Service checks joint limits, speed, continuity, fresh feedback, all-zero targets, gripper range and Supervisor state before every physical segment.

Any plan, target, calibration, dependency or action-range change invalidates authorization. Stop or interruption never auto-resumes.

## Dependencies

Requires Robot, Vision and Supervisor services plus Startouch and XVisio devices. Destination geometry and calibration revision must be explicit.

## Current Status

The web, Vision Service and Robot Service adapters are migrated. The supervised
bottle workflow lives in `skills/manipulation/bottlegrasp` and is exposed
through the loopback bottle-pick runtime on port 8766. Physical execution remains
locked until the approved calibration, v3 depth evidence, validated placement
path and explicit supervised-motion authorization are all present.
