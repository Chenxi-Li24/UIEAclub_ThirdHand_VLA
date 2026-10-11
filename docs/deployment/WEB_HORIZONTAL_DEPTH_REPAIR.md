# Horizontal active-depth and motion-aware vision repair

Scope: the existing Xavier web-grasp experiment only. Original source directories,
measured TCP artifact c484cb00, hand-eye matrices and robot SDK speed configuration
remain unchanged. Deploy only Web and Vision code; do not restart the robot SDK.

## Behavior

- Both one-click grasp and the independent Depth Alignment button share the
  horizontal coordinator and the existing Web9983 WebSocket client. The legacy
  formal executor's independent 5% limit remains unchanged; it no longer determines
  readiness of the horizontal depth entry point running on the normal 10% service.
- Roll/pitch remain level. Depth recovery uses 1-degree maximum yaw steps, within
  10 degrees of the starting heading; optical sideways/vertical corrections and
  backward moves are at most 5 mm. Camera displacement is at most 10 mm per step
  and 40 mm from its starting position. No forward motion without measured depth.
- Bearing-only corrections do not fabricate target distance. Three increasing,
  depth-valid frames, fresh feedback and matching calibrated projection are
  required before returning horizontal acquired depth; image centering is not
  required when measured depth is already available. The legacy formal coordinator
  keeps its centered-depth behavior. Existing workspace/joint checks
  and SDK IK checks still apply. This is not a collision-avoidance certification.
- The grasp uses the heading reached after each depth acquisition, including the
  preapproach checkpoint, then holds it through contact/lift.
- Motion feedback, including terminal-only pose changes, increments the vision
  epoch and resets segmentation memory. During motion each inference starts from
  fresh detection. Occluded/lost/retired tracks retain internal identity but are
  not painted over current RGB. Three fresh stationary feedback messages end
  motion mode. With no base-depth anchor, continuity requires overlapping masks,
  at most 40 pixels of per-frame displacement and consistent appearance. Multiple
  plausible matches or a visibility gap lock the selected identity until release
  and reselection; appearance alone cannot bridge that gap. These are conservative
  association checks, not proof of physical identity.
  Zero/out-of-range sensor depth cannot create a base anchor or a tracking point.
- Relay metadata distinguishes actual motion and stale feedback from velocity
  noise. A velocity-only spike still invalidates calibrated coordinates under
  the original stationary rule, but does not repeatedly reset a static camera's
  segmentation. Only genuinely stationary feedback can settle motion mode.
- Post-motion correlation may settle for up to 3 seconds. Stale depth, target loss,
  wrong frame bindings and unconfirmed stops remain terminal failures. An
  unconfirmed stop retains control ownership until a confirmed stop. Closing the
  coordinator retries stopping and rejects transport teardown if still uncertain.
  Captures and correlated robot projections must follow motion completion, using
  producer monotonic timestamps, not inference-publication times.
- Vision Python implementations resolve from the isolated checkout even when
  camera/model/resource paths intentionally refer to the original deployment.

## Verification boundary

Run Node Web/Vision/Robot regression tests and Python motion/overlay unit tests
without hardware calls. Check the existing Web gateway and live RGB-D observations
after Web/Vision restart. Restart only when the workflows and robot are idle.
Do not start depth motion, grasp or gripper commands as part of deployment.
Hardware depth-acquisition/grasp acceptance remains a separate explicit test.

## 2026-10-08 usable-depth follow-up

The failed bottle session had usable depth about 126 pixels below image center,
but kept alternating horizontal corrections until IK rejected a waypoint. The
horizontal planner now proposes no correction for valid depth. Temporary invalid
projection waits passively for synchronized evidence within the existing depth
timeout, rather than treating velocity noise as missing depth. The parent grasp
also publishes the child's terminal depth status instead of retaining `moving`.
Only Web needs restarting for this follow-up; Vision and Robot stay running.

Four new regressions failed before the change and pass after it. The focused
coordinator suite passes 84/84; the Node suite excluding `one-click.test.js` passes
449/449. Full `npm run test:node` reports 456/460 passing, with these existing
macOS launcher fixture failures, outside this repair:

- `one-click ensures formal and Meituan profiles in order, then validates shared vision`
- `missing Meituan worktree is reported without running anything in its place`
- `one-click restores a missing listener on the same trusted vision entry and preserves calibration`
- `repair refuses a lookalike entry outside the deployments directory without signaling it`

The first two differ on `/var` versus `/private/var`; the latter two encounter
`ENOENT` in Linux-specific process inspection. The two leaked fake vision children
created by that test run were stopped so the full runner could exit. No live
robot service was involved in those tests.

## 2026-10-08 preapproach IK follow-up

The 200 mm preapproach retreat sent the current nearly folded arm backward into
a region rejected by the SDK IK solver before the first grasp command. The
horizontal configuration now uses a 100 mm preapproach. Measured TCP, current
SDK preapproach height, level roll/pitch, yaw, 5 mm maximum path samples, 5-degree
joint continuity check and requested 10% speed remain unchanged.

Read-only IK previews through Web9983 checked the actual current pose and measured
target: all 46 preapproach/contact/lift samples had valid joint solutions, with
maximum adjacent joint change 4.654 degrees. This is a kinematic check for that
snapshot, not a collision check or completed physical grasp. Every new grasp still
checks its own fresh target/path. Only Web/config is updated; Robot/Vision are not
restarted and deployment does not start grasping.

The new measured-TCP checkpoint regression fails with the previous 200 mm
configuration and passes with 100 mm. Focused geometry/coordinator/horizontal/TCP
gateway tests pass 94/94. Full Node regression reports 460/464 passing; the same
four macOS launcher fixture failures listed above remain outside this change.

## 2026-10-08 in-motion projection follow-up

The preapproach watchdog previously requested stationary calibrated evidence
while the arm was moving. Twenty evidence retries expired and invoked the existing
Web software stop, which disables motors; this is not a confirmed hardware E-stop.
The watchdog now reads one complete current RGB detection frame through the same
Web9983 status endpoint. It checks fresh timestamps, the unchanged selected stable
ID and a unique confirmed track without requiring depth/projection evidence.

Before motion and after reaching the checkpoint, the original correlated
calibrated snapshot/depth requirements still apply. Stale or lost targets, selection
changes, communication failures, command timeouts and explicit stop retain their
existing fail-closed behavior. This patch does not alter Robot/SDK software stop
semantics or implement a torque-preserving hardware pause. It prevents expected
in-motion projection invalidation from incorrectly entering that stop path.
Deployment restarts only Web; it does not reconnect, level or move the robot.

The reproduced projection-loss regression now completes without software stop.
Stale RGB, lost identity and selection-switch regressions still confirm exactly
one stop. Focused tests pass 59/59; full Node regression reports 466/470 passing,
with only the same four macOS launcher fixture failures listed above.

## 2026-10-08 fixed initial-depth target follow-up

The grasp now freezes the base-frame bottle target, measured TCP and horizontal
heading from the initial three calibrated depth frames. The compatible
`target_refresh` checkpoint requires only fresh RGB target identity; it no longer
requires another calibrated depth snapshot, resets the initial depth count, or
starts a second active-depth correction after preapproach. Its UI label is now
"确认固定目标". Contact and lift remain planned against the original base target.

This is a stationary-bottle workflow, not dynamic object following. Fresh target
identity, timestamp/selection checks, horizontal pose checks, actual-start path
sampling, joint limits/continuity, command completion and gripper contact checks
remain enforced. Only Web is restarted; deployment does not start a grasp or
restart/reconnect the Robot or Vision service. Other deployed i18n changes remain
untouched.

A single passive, 1.5-second bounded calibrated snapshot may still prove that
the same bottle moved more than the existing 40 mm threshold; this fails with
`target_moved` before approach. Missing depth/projection evidence does not block
the cached target. Even a usable small depth variation never replaces the locked
contact, lift, heading or TCP. No depth correction or re-aiming is issued.
Fresh RGB identity is checked again after that passive read, including its
timeout/missing-depth branches, so the wait cannot authorize an approach with an
expired identity frame.

Five checkpoint regressions, the same-ID movement regression and delayed missing-
depth RGB-expiry regression failed before their fixes and pass after them. Local
focused tests pass 104/104, including the socket/TCP end-to-end fixture. Remote
focused tests pass 103/103. The remote test named "HTTP target selection and one
start traverse actual gateway sockets to measured TCP contact and lift" is blocked
by `frame_policy_source_changed` while loading its checked-in policy fixture,
before any coordinator execution. The deployment's existing runtime-rebound
calibration is not overwritten to make that fixture pass.

Full local Node regression reports 473/477 passing. The same four macOS launcher
fixture failures named above remain; no additional failure was introduced. Only
the two temporary fake vision children from this test run were stopped so the
runner could exit. No physical grasp test was started by this change.
