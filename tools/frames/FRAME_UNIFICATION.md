# Canonical flange coordinates — read-only deployment, 2026-10-05

## Contract and evidence

The unmodified shared Robot service publishes `get_ee_pose_euler()` (SDK tool
pose) under legacy flange field names. Its live SDK tool configuration is
`xyz=[0.17334,0,0], rpy=[0,0,0]`. The observed SDK pose matches URDF flange FK
with this configured tool appended exactly; without it the error is173.34mm.
This configured tool is NOT a physically measured bottle-grasp TCP.

Normalize at the independent branch's read-only consumer boundary:

`T_base_flange = T_base_sdk_tool @ inverse(T_flange_sdk_tool)`

`T_flange_camera = T_flange_sdk_tool @ T_sdk_tool_camera_legacy`

Together these preserve `T_base_camera`. Do not subtract the offset in fixed
base axes, convert twice, or feed canonical flange targets directly to the
SDK's tool-frame motion API. No motion/API target changes are part of this work.

The shared Robot HTTP/WebSocket service remains a legacy SDK-tool endpoint;
it was not overwritten. Canonical states are produced by
`tools/handeye/robot_reader.js` and fed to Vision by
`tools/vision/robot_state_relay.js`. They carry a content-bound policy ID and
retain the original SDK tool pose under an explicitly named provenance field.
Legacy ambiguous TCP aliases are removed from these canonical consumer states.

## Files and activation

- New canonical calibration:
  `configs/calibration/handeye-flange-normalized-20261005.json`
  (relative to skills/manipulation/bottlegrasp), SHA256
  `7d531f8e48a83b0c3231affc5dc100f2d805a65616b8879c6943c7e004eb10a2`.
- Policy: `configs/calibration/sdk-tool-frame-policy-20261005.json`, ID
  `sha256:37c1d3ea5e72347ae2affa52f33110ee910d21615d4045e3832fa6984a71c869`.
  It binds SDK config, legacy producer/bridge source and URDF file contents;
  missing/changed bindings or inconsistent tool values reject startup.
- Both readers require `THIRDHAND_ROBOT_FRAME_POLICY` set to that policy file.
- Vision uses the independent `camera_bridge_with_frames.py` override and
  `THIRDHAND_VA_HANDEYE` pointing to the new canonical calibration.
- Projection requires the calibration/feedback policy IDs to match and always
  verifies flange FK, including numerical-only mode. Missing/malformed markers,
  stale state, nonstationary feedback and incorrect FK invalidate cached poses.
- New handeye sessions use normalized feedback and policy-tagged samples.
  Old sessions cannot be resumed as canonical sessions; all originalNPZ files,
  manifests and solved results stay immutable. The15 historical poses have
  separate derived matrices under the diagnostic artifact, not relabeled raw
  NPZ files. Their JSON is an offline audit export, not a resumable live session.

The activation script restarts only the independent Vision/state-relay pair,
after an idle/read-only check. Rollback restores both the original calibration
environment and the archived legacy relay, not just one side of the transform.
No boot service was installed. A future restart must use the paired environment;
no raw-state/canonical-calibration mixed deployment is valid.

## Verification

-15 original sample transforms: max base-camera matrix delta5.55e-17.
-20 newly captured canonical feedback states:20/20 pass FK/update gates;
  max flange-FK translation delta5.57e-13m, max old/new base-camera matrix
  difference4.89e-13. These are algebraic consistency results, NOT physical
  localization accuracy.
-20-frame live selection sample:3 stability warmup frames, then17/17 ready.
- No motion/gripper commands sent. Robot moving=false before/after; gripper
  feedback unchanged. Flange feedback changed0.0395mm and max joint delta
  0.02186deg, so exact joint equality is not claimed.
-46 targeted tests pass:13 Node (including real socket replay/disconnect
  and Vision-route checks),4 migration,14 projection/geometry/runtime and15
  handeye tests. Relay fixtures now supply the explicit coordinate policy;
  no-policy input is intentionally rejected.
  The existing route test requires `VISION_STATE_ENTRY` set to the absolute
  `tools/vision/vision_server_with_state.js` path. A run omitting it failed
  import; that diagnostic is retained as `targeted-node-missing-env.log`.
- Fresh root Node132/132 pass. Fresh root Python145 pass +49 subtests, with
  the same2 baseline failures:
  `test_depth_evidence_projects_only_with_physically_approved_handeye` and
  `test_unified_foundation_has_no_machine_specific_runtime_paths`.
  This is not a full-suite pass.

Reports/logs: `artifacts/diagnostics/frame-unification-1791215001479/` contains
  policy, derived calibration and15 pose audits, before/after/live snapshots,
  `verification.json`, root test logs, service logs and paired rollback source.

Original saved calibration hashes remain
`d2e322dec9c6dab109212188ccc87b714bbd7f3cd9b0de9f22169cc576764a5b`;
original live camera bridge hash remains
`72a2eb8a7bd270da4631d6e5584d07128ec39118be231aaa9895331cc3bf62e4`.

## Still excluded

Physical handeye approval, measured grip TCP, Home/limit recovery, collision
corridors, path execution and gripper closure remain unapproved. Numerical
normalization does not unlock physical movement. Geometry and display still
query projection independently; shared frame freezing remains required before
any later motion authorization.
