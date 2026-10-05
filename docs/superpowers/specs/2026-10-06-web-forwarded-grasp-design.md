# Web-forwarded one-shot bottle grasp

## Intent and accepted definitions

Replace the stale imported grasp entry with our own operator-started complete
sequence: select a stable bottle in the existing web page, press Start once,
acquire valid depth (wrist-first active alignment if necessary), transform the
depth surface point using the current hand-eye projection, approach, close,
lift 0.050 m and hold. No phase confirmations, placement or automatic release.
The user explicitly asked for continuous implementation and only decision-level
questions; routine document-review prompts are omitted, not safety checks.

The user-specified approximate T_flange_grip is identity rotation plus
[0.060, 0, 0] m. Do not claim it is physically measured. Keep the SDK configured
tool transform at [0.17334, 0, 0] m and the current hand-eye extrinsic unchanged.
The surface target is not advanced by half the bottle width. Keep imported
autonomy disabled; do not turn perception's robotControlEnabled marker true.

## Chosen architecture and alternatives

Use a small server-owned coordinator loaded by the existing web gateway, with
a single client of its own public 9983/ws forwarding route. This keeps the
execution alive through ordinary page rendering, reuses existing perception and
wrist-first depth planning, and avoids a second CAN owner. A browser-only loop
would lose reliable ownership on page reload; re-enabling the old bottle-pick
service would retain the wrong gates and placement behavior. Neither is used.

New same-origin APIs are POST /api/grasp/start {stableId,requestId},
POST /api/grasp/stop {sessionId}, GET /api/grasp/status. The old Start button uses
these, not start_vision_grasp. The old Next control is disabled. Selection alone
does not trigger motion, and refresh never starts or repeats a grasp.

## Frames and geometry

Require the current frame_projection policy and calibration IDs to match the
saved artifacts and ready numerical projection. Transform camera_xyz_m by that
frame's T_base_camera; compare the published base point only for corruption,
not physical precision qualification. Preserve the current wrist orientation.
T_base_flange_desired = T_base_grip_desired * inverse(T_flange_grip).
T_base_sdk_desired = T_base_flange_desired * T_flange_sdk_tool.
Apply each compensation once, rotating it with the flange. The live eye-in-hand
camera lost the bottle below its image edge during the original rising 0.100 m
preapproach. The corrected checkpoint is 0.200 m opposite the flange +X direction,
preserving current SDK height during preapproach. Refresh depth at that farther
checkpoint, then lock the bounded final approach (maximum 0.220 m diagonal,
still <=0.005 m segments). Lift is +0.050 m in base Z. This changes the visibility
checkpoint, not the 60 mm TCP, desired contact point, SDK configuration or limits.

The first completed approach/closure missed the bottle with only 1.8 mm gripper
width; the operator confirmed correct height but approximately 60 mm forward
overshoot. Preserve the nominal 60 mm TCP and hand-eye artifacts. Apply a separate
forwardBackoffM=0.060 once to contact and lift, along normalized horizontal flange
+X, with zero base-Z correction. Leave the verified visibility checkpoint unshifted
to avoid moving it toward unreachable near-base poses. Keep the raw depth target in
the audit; this trial correction is not measured TCP/hand-eye qualification.
Reject nonfinite/negative/>100 mm correction or a near-vertical ambiguous axis.

Use short Cartesian segments of at most 0.005 m, preview every segment through
9983/ws, reject nonfinite or out-of-hard-limit IK and discontinuous joint
solutions. Segment start/end and requested grip/flange/SDK points must remain
in their explicitly declared workspace. Endpoint IK is not a collision proof.
Keep actual SDK/library/speed/gain settings unchanged. Check commanded pose
against fresh completion feedback rather than treating send/accept as arrival.

## Execution and ownership

Phases: depth_acquiring, planning, path_checking, opening, preapproach,
target_refresh, approach, closing, lifting, complete (holding). Depth requires
three fresh increasing frames for the same target. Reuse ActiveDepthCoordinator
with a transport adapter that sends its joint steps as servo via 9983/ws, never
through the protected execution socket or CAN. Bound alignment steps/budgets.

One session and one outstanding command. Request IDs make starts idempotent.
During a grasp, unrelated manual motion/connect/disconnect commands and the
separate depth session are rejected; software stop and emergency stop remain
available. Correlate completion and errors with request IDs. The trusted internal
socket is bound using an unpublished per-gateway nonce, not a client source tag.
Recheck ownership at actual sends, including queued and language sends; reject
acquisition when a prior executor is active. Lock vision selection mutations.

The hash-bound existing bridge intentionally pauses robot_state during motion.
Require fresh healthy hard-limit-valid feedback before each bounded segment and
after its matching completion. For an accepted motion only, permit that expected
quiet interval until its command deadline (15 seconds), without pretending to
monitor joints continuously. Any invalid received state, connection loss or
missing terminal feedback still stops. Completion waits for a later valid IDLE
sequence, including depth-alignment servo; accepted alone never advances a phase.

Refresh the locked target after preapproach and recheck the contact/lift plan.
Abort on target switch/loss before contact commitment. During the final bounded
approach and closure, expected camera occlusion is not replaced by another
target; use the locked point and fresh robot feedback. Gripper closure to zero
may stop against the bottle rather than reach zero: infer contact only from
fresh stable nonzero width in the physical bottle-width range, never acceptance
alone. The image-derived width is approximate and is not an additional contact
qualification gate; valid contact remains 8..70 mm, excluding empty/full-open.
Do not claim measured force or verified grip strength. If contact is not
observed, do not lift. A complete motion sequence is not proof of bottle success;
inspect the resulting camera view and report the observed physical outcome.

## Exceptions and deployment

On stale/invalid robot feedback, motion timeout, disconnect or ambiguous motion
completion, request software stop once and terminate without auto-reconnect.
If stop cannot be confirmed, keep the session uncertain and interlocked rather
than release control to another actor. Unknown errors after sent/accepted motion
are uncertainty, not evidence that the motion stopped.
Software stop disables the existing SDK and may remove holding torque; use it
for active/uncertain motion, not as cleanup of an idle rejected request. On an
idle plan/target/contact failure, end the session while preserving holding.

Implement on Xavier/grasp-validation-prototype in the independent remote
checkout. Do not overwrite the local root or unrelated dirty remote files.
Patch only fresh hash-checked web server/frontend sections, save recovery copies,
and restart only the web gateway once it is idle. Keep Robot Service, its single
bridge and Vision Service running. Do not alter measured/approved flags.

## Verification

Red/green tests cover rotated 60 mm compensation, no center advance or double
correction, invalid projection, path IK continuity, command correlation,
stale feedback, lost target, stop during motion, idle-failure holding, duplicate
start and sequential contact/lift. Use real local WebSockets with simulated
upstream feedback, never hardware in tests. Run the project's full Node command
and report any existing failures. Review the complete patch before live motion.
Live evidence records config ID, target/depth, frame IDs, hand-eye/policy IDs,
path samples, commands/completions, actual final pose and observed bottle result.
