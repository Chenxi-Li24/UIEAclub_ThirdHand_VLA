# Horizontal continuous web grasp

The approved grasp profile uses `orientationMode: horizontal` and
`executionMode: phase_linear`. Grasp roll/pitch are zero in the base frame;
yaw is frozen from the initial measured grasp pose, including across target
refresh. The active measured flange-to-grasp TCP is frozen per session and
its existing 80 mm probe correction is not applied again.

An initially tilted tool fails with `tool_not_horizontal` before depth,
gripper, or motion commands. This is not an automatic leveling routine: an
unqualified camera sweep near the table must not be hidden inside grasp.
The operator must level at a separately checked safe height. Grasp depth
acquisition waits for three fresh static depth frames, up to 15 seconds;
it does not rotate the wrist or run body alignment. Standalone active-depth
controls retain their existing behavior and are not part of this profile.

The preapproach, contact approach, and lift each use one native `move_l`.
The 5 mm intervals remain IK checking samples, not independently stopping
actuator commands. Each native line is rebuilt from fresh measured feedback;
SDK/flange/grasp workspace and joint limits remain checked. Start movement
over 1 mm or joint drift over 0.3 degrees during checking rejects dispatch.
Preapproach monitors target visibility while the command is in flight and
uses the existing confirmed-stop interlock on loss. Contact/lift completion
still requires valid idle feedback; there is no automatic release or home.

The normal robot/SDK ceiling is 10% when explicitly configured with
`STARTOUCH_SPEED_SCALE=0.10`. The default remains 5%. With the existing SDK
300/1000 deg/s velocity references, the requested ceiling is 30 deg/s for
J1–J3 and 100 deg/s for J4–J6, not a guaranteed measured Cartesian speed.
Independent formal-pregrasp and follow limits remain 5%; follow acceleration
and jerk are unchanged. Grasp precision reaches the SDK planner rather than
being silently discarded by the old live-source bridge.

## Live deployment boundaries

The live dirty Robot source is not replaced by the repository Robot version.
A copied runtime overlay changes only the normal speed ceiling, explicit
linear precision forwarding, and independent follow clamp. Deployment must
verify that overlay with the joint-speed Node tests and stdlib Python tests,
then bind its actual source hashes in a new runtime frame policy.

`tcpSourceFramePolicyFile` and `tcpSourceFramePolicyId` explicitly identify
the immutable calibration source policy. Both it and the runtime policy are
hash-checked; the SDK path, tool transform, and all non-runtime-code evidence
must match, including URDF. The runtime policy declares its source policy.
This preserves the original measured TCP candidate ID and acceptance report;
it does not fabricate a new calibration or physical path qualification.

Service cutover requires current idle feedback, no active grasp/calibration,
operator confirmation that the held object is removed and the work area is
clear, and recoverable copies of the original units/configuration. Separate
deployment worktrees preserve concurrent user edits and original production
sources. Actuator tests are not implicit in a successful service restart.

## Verification recorded before deployment

- Focused Node grasp, TCP calibration, and Robot tests: 216 passed.
- Stdlib fake-SDK speed/precision/follow tests: 3 passed in both repository
  Robot and copied live overlay; overlay Node speed tests: 5 passed.
- Full Node baseline: 420 passed, 4 existing `launcher/one-click` failures.
  The launcher test leaves fixture servers running and required terminating
  those exact test-only processes. This is not a full-suite success claim.
- Full pytest could not run: the local runtime has no `pytest`; dependency
  installation failed integrity/TLS checks, which were not bypassed.
- Tests above use fake/simulated devices. Actual motion smoothness, physical
  clearance, and grasp success must be observed separately on hardware.
