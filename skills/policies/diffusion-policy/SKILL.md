---
name: policy-diffusion-policy
description: Use when an approved task needs a diffusion-policy model to propose bounded action candidates from current observations.
---

# Diffusion Policy

## Purpose

Generate versioned candidate trajectories for an already scoped task. Sampling diversity must remain inside the approved workspace, action and time envelope.

## Contract

Input references taskId, plan revision, targetRef, observation revisions, model hash, random seed policy and candidate count. Output includes ranked candidates, units, timestamps, confidence and rejection reasons.

The worker does not choose authorization and cannot access CAN. Task Engine selects a candidate; Robot Service revalidates it immediately before execution.

## Safety

Reject unverifiable model assets, stale observations, candidates outside limits, discontinuous starts and missing Supervisor. Log model hash and sampling parameters for reproducibility. Never retry physical motion automatically after interruption.

## Dependencies

Requires Robot, Vision, Supervisor, Startouch, XVisio and a verified `policy.dp` model asset.

## Current Status

No accepted implementation or model weight is present. Registry must report unavailable; placeholder or random trajectories are never production output.
