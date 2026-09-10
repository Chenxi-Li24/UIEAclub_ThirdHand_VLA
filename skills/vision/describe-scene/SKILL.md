---
name: vision-describe-scene
description: Use when a task needs a structured, read-only summary of the current RGB-D scene before selecting an object or planning an action.
---

# Scene Description

## Purpose

Return a structured description of visible objects, spatial relations, uncertainty, frame freshness, and relevant hazards. This Skill is read-only and must not request active-view or robot motion.

## Use When

- The user asks what is visible.
- The orchestrator needs scene context before choosing another Skill.
- Object selection is ambiguous and a semantic summary may clarify it.

Do not use as a substitute for precise detection, stable target identity, grasp geometry, or execution supervision.

## Input And Output

Input should reference a current `frameRef` or request the latest synchronized RGB-D frame. Output must include the frame timestamp, detected semantic classes, spatial relations, confidence, uncertainty, and warnings. Large image or depth payloads remain in Vision Service storage.

## Dependencies

Requires Vision Service and XVisio ready. A stale frame, missing calibration, or unavailable camera returns failure instead of a guessed description.

## Safety

The worker cannot call Robot Service, change camera pose, open `can0`, or authorize motion.

## Current Status

Contract placeholder only. `src/worker.js` and schemas are not migrated, so Registry must report `implementation_not_migrated`.
