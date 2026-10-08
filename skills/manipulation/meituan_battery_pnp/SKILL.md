---
name: meituan-battery-pnp
description: Use when a Meituan operator requests a battery transfer from named A/B/C/D to T0/P1/P2/P3 in the 1034 conversation panel.
---

# Meituan battery transfer

Read [points.md](points.md) for the operator-taught six-axis contact, BEFORE, and AFTER points, gripper openings, and hold times. BEFORE denotes the taught nominal contact +60 mm pose; AFTER denotes the taught nominal contact +100 mm pose. These are recorded joint targets, not offsets for the executor to solve anew. Do not invent Cartesian XYZ from a screenshot or interpret the gripper percentage as force.

## Natural-language contract

For “把电池 A 运送到 P1”, extract `{"source":"A","destination":"P1"}` and call `plan` in [src/worker.js](src/worker.js). A/B/C/D map to `TASK2_A/B/C/D` for P1/P2/P3. Only A→T0 uses `TASK1_A` and `TASK1_T0`. Keep source and destination variable; never infer a slot from a color word. Vision resolution is currently disconnected.

Example: `node skills/manipulation/meituan_battery_pnp/src/worker.js plan A P1`. `status` reports the supported boundary. The planner reads the current points file each call and returns its SHA-256 digest. This CLI produces a read-only plan and never sends motion.

## Confirmed transfer sequence

1. ZERO → OBSERVE; prepare the gripper at 70%.
2. Send the source `*_BEFORE` taught joints, then the source contact joints.
3. Command 35% opening with a command-local `grasp_feedback_upper:0.4` rule. The shared service completes on its first fresh measured opening below 40% (including values at or below 35%), without waiting for exact 35%. The adapter then requires fresh stable IDLE feedback below 40% for 300 ms before lifting. Preparation and release retain their default exact-opening completion rules.
4. Send the source `*_AFTER` taught joints. Start the 2-second lift hold only after arrival and fresh stable feedback.
5. Cross zones at the source AFTER height and orientation. The horizontal `move_l` target uses destination BEFORE XY and source AFTER Z. Base Z of the planned target and fresh transport feedback must stay at or above the operator-verified 146 mm carrying floor. This floor applies to the cross-zone carrying segment, not the contact approach, release descent, or retreat. The Meituan command explicitly supplies `position_tolerance_m:0.005` and `orientation_tolerance_rad:0.05`; shared defaults stay 0.04/0.4 when omitted. Meituan correlation and arrival checks compare physical rotation angle, not Euler component distance. After matching completion, allow up to 2 seconds for fresh IDLE arrival feedback to settle; a pose still outside tolerance reports its measured position/orientation errors and stops before descent. The overall motion deadline stays 45 seconds.
6. For P1, move directly from the horizontal transfer endpoint to the destination contact joints without a separate P1 BEFORE stop. Keep P1 BEFORE recorded and use its XY for the transfer endpoint. T0/P2/P3 still send the destination `*_BEFORE` joints before contact. Release at 70%. Wait for matching completion, reached feedback, and measured opening before sending the destination `*_AFTER` taught joints. Temporarily, `TASK2_P2_AFTER` resolves to the recorded `TASK2_P2_BEFORE` joint point.
7. Start the 3-second release hold after release feedback and retreat arrival; return to ZERO.

All `*_BEFORE`, contact, and `*_AFTER` steps use their recorded six joint angles. Do not derive +60/+100 mm poses, shorten the taught lift, alter the taught orientation, or re-plan these points with IK. The sole Cartesian segment is the cross-zone transfer; preview its endpoint IK before the single confirmation. Stop on a missing point, unreachable transfer, limit error, stale feedback, floor violation, disconnection, or operator stop; do not silently retry or substitute a different route.

## Runtime execution

The 1034 voice connection uses `?task=meituan`. Shared 3004 exposes `meituan_battery_transfer` only in that context and emits `meituan_battery_pnp@1` with source/destination. [src/executor.js](src/executor.js) is registered by the 1034 web gateway; 9983 does not register this adapter.

The panel waits for read-only preflight and presents one **confirm complete route** action. The confirmed route is deterministic, with no per-step confirmations. Taught joints pass through the 1034 bridge as correlated `servo` commands to the shared 3000 service; the horizontal segment uses its existing `move_l` path. The skill opens neither an SDK controller nor CAN. The adapter waits for matching completion and fresh settled joint, pose, or gripper feedback, then publishes `skill.execution.status` and one final `skill.result`.

[src/sdk-model.js](src/sdk-model.js) uses the running SDK model to check taught joint limits, compute their base-frame poses, and preview the one Cartesian transfer endpoint. Preflight binds point/model digests and the start state; confirmation checks them again. The current shared motion service applies the common joint-speed and wait policy; the skill adds no separate 20/30 mm/s cap.

An accepted opening below 40% does not itself prove battery retention, and reached 70% does not visually prove release. Physical placement remains observable by the operator until vision-to-slot and retention checks are connected.

## Future integration

- Vision input: accept a confirmed `{slot:"A"|"B"|"C"|"D", confidence, frameId}` mapping as a separate resolver. Today a color-only request fails with `vision_resolution_not_connected`; there is no red→A assumption.
- The CLI and manifest remain read-only `plan`/`status`; physical execution is the confirmation-gated 1034 adapter, not a standalone CLI or direct CAN call.
