---
name: policy-act
description: Use when an approved task needs an ACT checkpoint to propose bounded, versioned action chunks from current observations.
---

# ACT Policy

## Purpose

Load a declared ACT checkpoint and produce finite action chunks for a specific task, plan revision and observation revision.

## Contract

Input references `frameRef`, `robotStateRef`, targetRef, checkpoint hash and requested horizon. Output records checkpoint identity, action units, timing, confidence and validity envelope.

Task Engine and Robot Service validate every chunk before execution. A new chunk cannot extend the user's authorized action range implicitly.

## Safety

Reject missing or mismatched checkpoints, stale observations, discontinuous first actions, out-of-range joints, excessive speed and unavailable supervision. Cancel clears queued chunks. Interruption requires a new plan and authorization.

## Dependencies

Requires Robot, Vision, Supervisor, Startouch, XVisio and verified `policy.act` checkpoint assets.

## Current Status

Only prior contract/loader prototypes exist in migration sources. The formal worker and checkpoint are absent, so Registry must report unavailable.
