# Directional Joint Control Design

Status: user-approved design; not implemented or deployed

Date: 2026-08-16

## Objective

Add reusable, confirmation-gated directional joint commands to the experimental
Language control path. These commands are generic robot primitives, not part of
`pick_and_place_bottle@1` and not a Coke task policy.

The camera is rigidly mounted to the gripper. Direction words are interpreted
from the camera/gripper first-person view, while whole-assembly lift validation
uses the robot base frame's vertical axis.

## Non-goals and protected systems

- Do not modify, overwrite, restart, or redeploy formal web/robot service 3000.
- Do not modify the Startouch SDK, CAN configuration, or the formal 3000 bridge.
- Do not modify the accepted 9981 web process or its 3002 Voice process during
  development and preview testing.
- Do not change `manual_joint_control@1`.
- Do not add a global multi-browser execution lock in this change.
- Do not add Cartesian IK, Coke policy, autonomous trajectories, or LLM-generated
  joint sequences.

## Contract

Add a separate primitive contract named `directional_joint_control@1`.

Every candidate must use the existing candidate envelope and include a
`candidateId`, `traceId`, original source text, expiry, and
`requiresConfirmation: true`. Existing candidate TTL, replay protection, and
session ownership rules remain unchanged.

The contract exposes these actions:

| Action | Default relative target change |
|---|---|
| `turn.left` | J1 `+20 deg` |
| `turn.right` | J1 `-20 deg` |
| `lift.up` | J2 `+20 deg`, J3 `-20 deg` |
| `lift.down` | J2 `-20 deg`, J3 `+20 deg` |
| `wrist.pitch.up` | J4 `-20 deg` |
| `wrist.pitch.down` | J4 `+20 deg` |
| `wrist.yaw.left` | J5 `+20 deg` |
| `wrist.yaw.right` | J5 `-20 deg` |
| `wrist.roll.clockwise` | J6 `+20 deg` |
| `wrist.roll.counterclockwise` | J6 `-20 deg` |

Each action carries a positive finite `deltaDeg`. When the user does not state
an angle, Language emits `deltaDeg: 20`. When the user states an angle, that
angle replaces the default. Vague magnitudes such as "more" or "a lot" must
produce a clarification question rather than an invented value.

No centimetre field or centimetre-to-degree conversion is exposed.

## Language interpretation

The 3003 Voice process adds a directional control tool and prompt examples.
Language selects a predefined action and magnitude; it never creates an
arbitrary multi-joint sequence.

The PC LLM must understand both Chinese and English text requests. The selected
robot action and numeric parameters must be identical for equivalent Chinese
and English input. English ASR, response-language selection, and TTS behavior
are outside the scope of this feature.

Examples:

- "往左一点", "向左转", "看向左边" -> `turn.left`, 20 degrees.
- "向右转 30 度" -> `turn.right`, 30 degrees.
- "抬高" -> `lift.up`, 20 degrees for both configured joints.
- "夹爪向左摆" or "腕部向左" -> `wrist.yaw.left`, 20 degrees.
- "画面顺时针旋转" -> `wrist.roll.clockwise`, 20 degrees.
- "turn left" or "look to the left" -> `turn.left`, 20 degrees.
- "turn right by 30 degrees" -> `turn.right`, 30 degrees.
- "raise the gripper" -> `lift.up`, 20 degrees for both configured joints.
- "swing the wrist left" -> `wrist.yaw.left`, 20 degrees.
- "rotate the camera clockwise" -> `wrist.roll.clockwise`, 20 degrees.

An unqualified "left" means whole-arm J1 turning. Wrist movement requires the
user to say "wrist" or "gripper". Explicit commands such as "J1 增加 20 度"
continue through the existing `manual_joint_control@1` path.

## Target computation and execution

The 9982 Node service owns candidate validation, preview, and expansion to one
complete six-joint target. It reads a fresh six-joint state from formal 3000,
applies the selected relative changes, preserves every unaffected joint, and
sends one existing full `move_joint` request through the existing 3000 upstream
WebSocket.

`lift.up` and `lift.down` are atomic multi-joint actions. J2 and J3 must be
included in the same full target and must never be sent as sequential commands.
J4 remains unchanged because the equal and opposite J2/J3 changes preserve the
modelled end orientation around their shared local Y axis.

No new command, bridge behavior, or SDK functionality is added to formal 3000.

## Validation and safety

Before enabling the Execute button, all of these conditions must be true:

- 9982 is connected to formal 3000.
- SDK and CAN status are healthy.
- Robot state age is at most 500 ms.
- Robot state is `IDLE` and no current action is active in the existing control
  path.
- Every computed target remains within the existing mechanical joint limits.
- The preview calculation succeeds.

For `lift.up` and `lift.down`, forward kinematics must validate the requested
direction before confirmation. Let the predicted base-frame translation be
`(dx, dy, dz)` and horizontal displacement be `sqrt(dx^2 + dy^2)`:

- `lift.up` requires `dz > 0`.
- `lift.down` requires `dz < 0`.
- Both require `abs(dz) >= sqrt(dx^2 + dy^2)`, so the motion is primarily
  vertical rather than primarily forward or sideways.

This check is forward-kinematics validation only; it does not introduce IK.
The accepted URDF calculation showed that repeated J2 `+20` / J3 `-20` steps
eventually stop being primarily upward even while mechanical limits remain
valid, so mechanical limits alone are insufficient.

All actions run at fixed speed scale `0.05`. Language and the browser cannot
change speed.

Every action requires an explicit Execute click. The confirmation card displays
the semantic action, current and target values for all changed joints, each
delta, speed, limit result, and directional preview result. Preview never sends
a robot command. Existing explicit software stop behavior remains the only
confirmation exception.

On timeout, upstream disconnect, SDK/CAN loss, mismatched completion, or target
verification failure:

- never report success;
- never automatically retry a relative action;
- request software stop;
- mark the result failed or uncertain; and
- block the next Language action until an operator checks state.

Software stop is not a physical emergency stop.

## Staging topology

Develop and test only from:

`/home/nieqingcao/th0814/thirdhand-language9981/language-sync-20260814-221750`

Keep the accepted chain unchanged:

`9981 web -> 3002 Voice -> formal 3000`

Run the new feature independently:

`9982 web -> 3003 Voice -> formal 3000`

Initial 9982 directional real execution remains disabled by a dedicated runtime
flag. Candidate generation, validation, confirmation rendering, and 3D/model
preview are tested first. Real execution is enabled only after a separate,
explicit operator authorization with the operator beside the arm and the
physical emergency stop available.

## Test and acceptance plan

Automated tests must cover:

- every allowed action and sign mapping;
- equivalent Chinese and English text requests producing identical candidates;
- default 20-degree magnitude and explicit-angle override;
- vague-magnitude clarification;
- contract rejection of unknown actions, invalid angles, expired candidates,
  replay, and mismatched confirmation identifiers;
- all mechanical joint-limit failures;
- atomic six-joint target generation for lift actions;
- forward-kinematics rejection when lift direction is wrong or not primarily
  vertical;
- stale state, non-IDLE state, upstream disconnect, timeout, and uncertain
  completion;
- confirmation-before-command and preview-without-command;
- no regression in existing J1-J6 single-joint, gripper, Home, status, stop,
  Voice, and right-side controls.

The first physical acceptance, when separately authorized, tests each action
and its inverse one at a time at speed 0.05. The operator verifies the preview,
clicks Execute personally, observes motion, and confirms the inverse returns to
the starting state before testing the next action.

## Promotion and rollback

The user reviews and physically accepts 9982/3003 before any promotion. Only
after explicit promotion approval may the accepted code replace the
corresponding 9981/3002 test components. Formal 3000 remains untouched.

The pre-change 9981/3002 source, launch parameters, and processes remain the
rollback baseline until post-promotion health checks pass.
