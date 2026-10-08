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
