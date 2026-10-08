# Bottle Grasp Coordinate Chain and Read-Only Preview

## Integration Status (2026-10-07)

The description below records the intended/earlier deployment workflow, not a
verified capability of the integrated checkout. The saved IK modules exist, but
`/api/va/test/motion-preview` is not wired into the current BottleGrasp server.
The non-lift-only supervised session has no `buildPlan` callback. Do not use the
historical curl/button instructions below as an acceptance test that can pass.

The migrated manual-control camera bridge reads
`configs/vision/evidence/deployment_20261006/handeye-flange-normalized.json`.
The formula remains `T_base_camera = T_base_flange * T_flange_camera`, provided
the input is truly a flange pose, synchronized with the camera frame, and the
calibration mount/serial matches. The saved SDK frame policy refers to old code
and runtime hashes; its bindings need a separate read-only validation before
enabling the migrated relay. Numerical calibration is not physical approval.

No robot restart, camera acquisition, preview execution or real grasp was
performed in this integration. See
`docs/deployment/DEPLOYMENT_TO_MAIN_20261007.md` for current known gaps.

## What the page computes

1. XVisio provides a selected, stable bottle mask and metric RGB-D points in the camera color frame. The bottle geometry estimator fits a table, chooses an upright axis, estimates width/height and a side-grasp point. `bottle_height_unreliable` means estimated height is not greater than width; it is not an execution permission flag and is not ignored.
2. Vision Service subscribes **read-only** to Robot Service `/ws`. It accepts a stationary, healthy `robot_flange` pose in meters/radians only when the telemetry and camera frame monotonic timestamps are within 250 ms. The current six joint angles must agree with the bundled URDF FK to within 10 mm and 0.10 rad. Moving, stale, malformed or mismatched state yields no base point.
3. The eye-in-hand calculation is `T_base_camera = T_base_flange * T_flange_camera` and `p_base = T_base_camera * [p_camera, 1]`. The flange rotation is `Rz(yaw) * Ry(pitch) * Rx(roll)`, with angles in radians. `T_flange_camera` comes from `configs/calibration/lumos-handeye.pending.json`, identified by XVisio serial/registration/mount. It is numerically validated but **physical point error has not been measured**; mathematical consistency alone is not physical calibration approval.
4. The read-only motion-preview endpoint computes pregrasp, final approach, close, lift, fixed-XY transfer/place, release, retreat, and a joint-space return to **zero** `[0,0,0,0,0,0]`. IKPy solves against the six-joint Startouch URDF; each solved frame is checked with FK. The page animates only those joint frames and restores its prior live-sync state after stopping. No frame is sent to Robot Service. This is a **kinematic preview, not collision or full-path validation**.
5. Startup Home is unchanged. The final command in a genuinely authorized execution plan is now the `zero` preset. The controller's legacy internal phase name `return_home` refers to this zero command.

## Why execution can remain unavailable

The single-target supervised preview now has a real `buildExecutionPlan` callback. That builder still requires the frozen multi-frame alignment handoff/action evidence, real robot state, and explicit `execution_enabled`. One visual frame and a kinematic animation cannot fabricate that evidence. Expect `alignment_handoff_evidence_unavailable` and/or `execution_disabled` until the execution workflow is separately commissioned. The preview endpoint does not authorize motion.

## Current deployment finding (2026-09-22)

The live 3000 Robot Service process started before the current `robot-controller.js` and `startouch_bridge.py` changes. Its `flange_position_m` disagrees with six-joint URDF FK by about 150 mm; the emitted state also lacks the current source's `sdk_tool_position_m`. Vision correctly reports `robot_urdf_fk_mismatch`, leaves `base_xyz_m=null` and disables motion preview. The 3100 camera, inference, depth and 9983 page continue to run.

Do **not** restart 3000 or enable execution unattended. First clear the arm workspace, arrange physical supervision and verify an independent emergency stop. After a supervised Robot Service restart, compare read-only `flange_position_m` to URDF FK over several stationary poses; expected translation error is below 10 mm and orientation error below 0.10 rad. Then reselect a bottle, check `base_pose_status=available`, non-null `grip_target_xyz_m`, sensible height/width, and only then play the read-only 3D preview. If `bottle_height_unreliable` persists with a valid transform, inspect mask/table geometry and depth coverage; do not lower the geometry rejection threshold blindly.

## Manual checks

```bash
cd /home/nieqingcao/ThirdHand/UIEAclub_ThirdHand_VLA
./thirdhand status --profile manual-control
curl -s http://127.0.0.1:3100/api/vision/observation
curl -s 'http://127.0.0.1:8766/api/va/test/motion-preview?target_id=1'
PYTHONPATH=services/vision/python local/runtimes/vision-python/bin/python tests/python/vision_service/test_handeye_projection.py
local/runtimes/vision-python/bin/python skills/manipulation/bottlegrasp/apps/bottle_pick/test_kinematic_preview.py
```

On 9983, select a target, press **读取目标**, inspect the diagnostics, then press **播放预览** only when it becomes enabled. The slider scrubs offline joint frames; **停止预览** restores the prior 3D state. A failed preview never moves the physical arm.
