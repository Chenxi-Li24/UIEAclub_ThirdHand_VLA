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
SDK's tool-frame motion API. No active motion/API target changes are part of
this work. The later optional command adapter is dormant and tested with
synthetic transports.

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
normalization does not unlock physical movement.

## Frame snapshots and optional command adapter — 2026-10-06

The independent bridge now freezes one immutable projection before inference.
Geometry receives a separate numpy copy. The same original frame consumes the
single-slot snapshot for displayed base coordinates; publication never queries
a newer pose to replace it. Snapshot identity includes frame sequence, timestamp,
camera serial, exact frame object, projector owner, calibration and policy IDs.
An invalid feedback update increments an invalidation epoch; recovery cannot
revive an earlier snapshot. Failed inference clears the pending snapshot.

Final freshness/identity/epoch validation and the detection-event write share
the feedback lock. Invalidations therefore linearize before the write (base
coordinates, the top-level grasp pose and its old evidence ID are cleared;
ready status becomes uncertain with a rejection reason), or after it.
The lock is held during output, so slow
consumers can delay feedback processing. Downstream consumers must still check
timestamps; this is not a guarantee of physical accuracy or freshness at use.
The optional `frame_projection` detection metadata exposes the exact captured
matrix and its provenance for read-only replay. It is not a motion approval.

`tools/frames/canonical_robot_client.js` provides an OPT-IN WebSocket client for
future supervised action integration. It requires `framePolicyPath` and the
existing WebSocket dependencies. Construction does not connect. It normalizes
raw SDK-tool feedback to flange poses and converts canonical `move_l` targets
back with `T_base_sdk_tool_target = T_base_flange_target @ T_flange_sdk_tool`.
Cartesian targets require fresh, healthy, stationary canonical feedback;
malformed/replayed/double-converted feedback clears its cached state. Non-
Cartesian low-level commands retain the original adapter semantics and require
the existing external execution/controller approvals.

This client is NOT installed into an active action runner or the default
factory. No executable bottle trajectory has been generated; no grip TCP is
assumed equal to the SDK's nominal tool. The original shared Robot service,
default process backend and CAN owner have not been changed or started.

Regression records are under `artifacts/diagnostics/readonly-followup-xfRuW1/`.
The original same-frame 5mm synthetic mismatch and publication/identity issues
were observed RED before implementation. Canonical-client RED initially
revealed an invalid test handshake timestamp; the corrected fixture was rerun
against the old transport and failed for actual missing conversion/validation,
then passed against the new opt-in client. Full-suite and deployment results
must be read from the fresh logs; numerical tests do not imply physical approval.

Initial frame-freeze deployment capture:
`artifacts/diagnostics/readonly-followup-8jddl6/`.
The restarted independent Vision/state-relay pair produced30 distinct frames,
all30 with ready projection and selected-bottle depth/base coordinates;4 were
detection-stability warmup frames and26 were ready. Every projection identity
matched its detection frame, policy and calibration. Reprojecting the30 camera
points with each recorded frozen matrix gave a maximum residual5.56e-17m.
This verifies software consistency, not measured physical localization error.
Selected depth ranged0.19785–0.21398m. No robot/gripper commands were sent;
Robot reported moving=false before/after. Original calibration and shared
camera-bridge hashes remained unchanged.

A separate30-event local WebSocket timing capture observed frame-to-receipt
ages87.28–247.63ms and feedback receipt gaps99.16–101.66ms, with no socket
errors. These are observations, not a hard output-backpressure bound. The HTTP
polling sample's receipt age includes its polling delay and is not publication
latency. Downstream motion consumers must still enforce freshness at use.

The current J3 margin is0.49178deg, below the configured3deg stop margin;
the maximum configured-Home difference is32.6543deg. Actual grip TCP remains
unmeasured, physical handeye approval remains pending, and action execution
remains false. Do not generate an executable flange path by substituting the
SDK's nominal173.34mm tool or the old base-axis offset for a measured grip TCP.

Final fresh regression:87 focused tests pass (37 Node,31 Vision,4 migration,
15 handeye), root Node132/132 pass, and root Python145 pass +49 subtests with
the same2 baseline failures listed above. The portability failure reports9
absolute-home-path findings; these include the already committed machine-bound
policy and earlier documentation paths, not new paths introduced by this patch.
An initial final-run invocation used a wrong migration test filename and omitted
the root Python vision-module import path; both command errors were preserved
separately and the corrected full commands were rerun. See `verified-final-*.log`
and `verified-final-results.json` under `readonly-followup-xfRuW1`.

The opt-in client's14 synthetic-transport tests include dormant construction,
immutable policy identity/provenance, replay-cache invalidation, stale/moving/
unhealthy/disconnected feedback rejection, wrong-policy/double-converted target
rejection, and non-object/array container rejection before command reservation.
Content bindings are checked at construction; this is not a live file-change
monitor. It remains inactive pending measured geometry and supervised integration.

Final deployment, including top-level pose invalidation, was captured in
`artifacts/diagnostics/readonly-followup-Kf5JBw/`. Its30 distinct frames include
one pre-selection frame and29 selected-bottle frames. All29 selected frames
have valid filtered depth;28 have ready base coordinates and one correctly
rejects nonstationary/unhealthy feedback. That rejected event has no top-level
pose/evidence ID or target base coordinates, and is uncertain with the explicit
rejection reason. Overall projection statuses are29 ready and one rejected;
detection statuses are23 ready,6 uncertain,1 searching. No fail-closed violation
was found. The29 projected target points have a maximum same-matrix residual
5.56e-17m; depth spans0.19586–0.20901m. Robot reported moving=false before/after,
but feedback had small joint changes; exact equality is not claimed.

The final separate stream capture is
`artifacts/diagnostics/readonly-final-stream-rMJm6j/`:30 events,57 feedback
samples, frame-to-receipt age141.20–420.90ms, feedback gaps99.70–101.08ms, no
socket errors. Some received images exceed250ms age despite fresh current
feedback. This readonly display must NOT be treated as a freshness-qualified
motion input; an eventual action consumer must reject old image evidence at
use. Physical approval and actual TCP/path validation remain absent. The shared
Robot service was not restarted, and no motion/gripper command was sent.

## Home/grasp request preflight and live capability compatibility

The operator explicitly requested return-Home and bottle grasp. A real
read-only connection exposed an additional `preview_ik` capability in the live
service's handshake. The original strict six-command client rejected that
seven-command response, leaving protocol readiness false. The opt-in client
now permits exactly this known read-only extension: seven unique advertised
commands including `preview_ik` are passed to the original handshake validator
with that extension removed. All required command, nonce, version, frame,
units, replay, completion-correlation and software-stop-boundary checks remain.
Unknown, duplicate or missing capabilities still reject the handshake, and
`send()` still cannot dispatch `preview_ik` or other additional commands.

The regression was observed RED (16/17 tests) then GREEN (17/17). The live
read-only retry obtained fresh healthy stationary canonical feedback. Its
no-write Home preflight returned `startup_home_not_validated`, because the
current pose is not Home and no approved startup corridor/joint range exists.
J3 remains0.49178deg from the upper limit, below the configured3deg margin.
Grasp preview remains non-executable with no verified grip transform, no
physically approved handeye and no executable supervised plan. Physical action
authorization does not substitute for these missing measurements/path evidence.

Artifacts: `artifacts/diagnostics/home-grasp-preflight-1RUhiV/` (initial failed
handshake, RED/Green and baseline logs) and
`artifacts/diagnostics/home-grasp-preflight-fixed-2AQZfc/` (live retry and final
regression). No Home/movement/gripper command was dispatched. The shared Robot
service, local checkout, active Vision processes and CAN owner were unchanged.
The shared service currently ignores `time_sec` and uses configured SDK speed;
this frame adapter is NOT a qualification of real trajectory timing or a bypass
of Home, physical calibration, grip geometry or collision-path approval.

Fresh final regression after the compatibility fix:90 focused tests pass
(40 Node,31 Vision,4 migration,15 handeye), root Node132/132 pass, and root
Python145 pass +49 subtests with the same2 baseline failures named earlier.
The capability change was reviewed without finding an important regression;
no reviewer or test result constitutes approval for a physical Home/grasp path.
