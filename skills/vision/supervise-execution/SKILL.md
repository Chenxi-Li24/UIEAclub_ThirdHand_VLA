---
name: vision-supervise-execution
description: Use when an approved physical task needs independent visual checks for target visibility, alignment, grasp progress, or placement success.
---

# Execution Supervision

## Purpose

Configure and observe visual rules for one approved task. The Skill reports evidence to Supervisor; Supervisor owns the stop decision and Robot Service owns command enforcement.

## Use When

- A pick, place, active-view, VLA, ACT or DP execution begins.
- The plan defines target visibility, deviation, clearance or completion rules.
- Post-action evidence is required.

## Operations

- `invoke`: bind rules to taskId, plan revision and targetRef.
- `status`: return current evidence and rule state.
- `cancel`: stop supervision and invalidate its task binding.

## Failure Semantics

Target loss, stale frames, pose revision changes, excessive deviation, unavailable calibration or worker failure must be explicit. A missing Supervisor locks automatic motion; it never silently disables supervision.

## Safety

This manifest is read-only because it configures and reports observation. It does not itself send motion. A stop request is handled through the independent Supervisor and Robot Service.

## Current Status

Contract placeholder only. Worker and schemas are not migrated; Registry must report unavailable.
