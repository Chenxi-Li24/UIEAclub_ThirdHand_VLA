---
name: vision-inspect-scene
description: Use when the ThirdHand controller needs a fresh, read-only natural-language observation from the existing XVisio RGB stream.
---

# Inspect Scene

## Purpose

Read one newly published JPEG from the existing Vision Service and describe only what is visibly supported. This Skill is the Phase A visual-question-answering path for prompts such as “看看前面有什么”.

## Boundaries

- Read `/camera/xvisio/raw`; never open `/dev/video*`.
- Never start, restart, configure, or move the camera.
- Never call Robot Service, CAN, a motion Skill, or a confirmation endpoint.
- Never turn a visual description into a grasp target or trajectory.
- Return an explicit failure for an unavailable, stale, frozen, or invalid frame.
- Do not fall back from `deepseek-flash` to a text-only model.

## Input

The controller provides the current visual question, the optional previous visual summary needed for a follow-up, and the user language. The full conversation is not forwarded.

## Output

Return a concise natural-language summary plus internal frame provenance and safe trace metadata. The 9983 conversation displays only the controller’s final natural-language answer.

## Trust Rules

Describe visible evidence. Mark blur, occlusion, unreadable text, uncertain brands, or ambiguous identity as uncertain. Never invent unseen content.
