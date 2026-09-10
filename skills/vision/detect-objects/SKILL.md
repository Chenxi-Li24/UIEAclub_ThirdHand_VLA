---
name: vision-detect-objects
description: Use when a task needs object classes, labels, confidence, and stable target references from the current RGB-D scene.
---

# Object Detection

## Purpose

Detect and classify objects and return stable `TargetRef` values maintained by Vision Service. Labels such as L1 or R3 are attributes of a tracked target, not a replacement for target identity.

## Use When

- The user names an object class or printed label.
- A manipulation plan needs an unambiguous target.
- The orchestrator must present selectable detections on the live image.

## Input And Output

Input may include class filters, label text, confidence threshold, region of interest, and a `frameRef`. Output contains zero or more `thirdhand.target-ref.v1` records plus optional pose and mask references.

Never fabricate a target when no observation meets the threshold. Multiple matches remain ambiguous until the user or policy selects one.

## Dependencies

Requires Vision Service, XVisio, calibration and the configured detector/classifier. OCR or open-vocabulary models must be declared when used.

## Safety

This Skill is read-only. It cannot move the arm for a better view. Any active-view request must become a separately planned and authorized physical-motion operation.

## Current Status

Contract placeholder only. Worker and schemas are not migrated; Registry must report unavailable.
