---
name: policy-vla
description: Use when an approved task needs a VLA model to propose versioned action candidates from current visual and language context.
---

# VLA Policy

## Purpose

Produce candidate actions or action chunks for Task Engine review. The VLA is a policy provider, not the central task-planning LLM and not a hardware controller.

## Contract

Input references the approved task, current `frameRef`, `robotStateRef`, targetRef and policy version. Output contains bounded candidate actions, confidence, model identity and observation revisions.

Candidates are never sent directly to CAN. Task Engine binds them to a plan revision; Robot Service performs final limits and continuity checks.

## Safety

A model change, stale observation, target revision change, missing Supervisor or candidate outside the authorized envelope invalidates execution. The Skill must support cancel and may not auto-recover a stopped task.

## Dependencies

Requires Robot, Vision, Supervisor, Startouch, XVisio and a verified `policy.vla` model asset.

## Current Status

No accepted worker or VLA weight is present. Registry must report both `implementation_not_migrated` and missing model; fake output cannot be marked ready.
