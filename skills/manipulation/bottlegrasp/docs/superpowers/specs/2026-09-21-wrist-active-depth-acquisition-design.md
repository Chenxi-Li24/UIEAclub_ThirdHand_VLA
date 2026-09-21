# Wrist-only active depth acquisition

## Purpose and boundary

An operator locks a visible bottle by stable ID in the wide RGB view. The
system rotates only J4–J6 in small, separately confirmed steps until that same
bottle yields valid registered depth. A camera-center translation caused by
rotation is acceptable within a measured limit. This mode never moves J1–J3,
closes the gripper, descends to a bottle, or initiates grasp/place. A successful
depth acquisition is not approval for a later grasp.

Current hardware state is not ready for live motion: the formal robot execution
gateway has no token and currently accepts only `gripper.set`, not joint motion;
the hand-eye mount has pending physical validation, and the VA grasp execution
gate is disabled. A separately reviewed authenticated joint-motion primitive
and its authorization policy are prerequisites for live active view. This
feature must not silently switch to the manual WebSocket command route or flip
grasp approval flags.

## Existing inputs and ownership

- Vision Service `GET /api/vision/observation` supplies fresh frame/target IDs,
  RGB centroids, target state, registered depth status, and selection evidence.
- The XVisio 640×480 registered-depth reference ROI is `(203,149,428,319)`.
  Candidate aiming should target an interior margin, not its edge.
- The checked-in SEUCM fisheye model has `unproject`; its native 1280×1280
  pixels map to the 640×480 stream by `u_stream=u_native/2` and
  `v_stream=(v_native-160)/2`. The inverse mapping must be applied before
  unprojecting the observed bottle pixel and desired depth-ROI pixel.
- The robot service provides fresh stationary joint state and a protected
  execution gateway. The checked-in URDF-derived forward kinematics currently
  exposes tool position only; predicting camera-center displacement requires
  full flange pose and the measured `T_flange_camera`.
- The camera is about 11 cm from the flange. Wrist rotation therefore moves the
  camera along an arc rather than holding it at a fixed base-frame position.

## Approach

Prefer fisheye-guided, feedback-corrected wrist acquisition over whole-arm IK. A whole-arm
camera-center-preserving approach would need to move J1–J3, contradict the
operator's requested wrist-only scope, and require a separately validated
collision model. A random or alternating wrist search is rejected. A single
large rotation is also rejected because wrist axis coupling, camera offset,
and unknown target range make its displacement unreliable.

The controller has four explicit states: `observe`, `propose`, `await_operator`,
and `verify`. It locks one stable ID and consumes only fresh observations from
the same camera/registration ID. From the RGB centroid and the desired interior
of the registered-depth ROI, it first unprojects two SEUCM rays and obtains a
signed angular aiming error. Full rotational forward kinematics and the camera
mount orientation map this error to a constrained J4–J6 correction. It chooses
only a candidate predicted to reduce that angular error while respecting all
joint and camera-motion bounds. J6 is used only if its predicted effect helps;
there is no fixed joint sweep or trial-and-error direction search.

After each confirmed motion, the controller compares the observed RGB pixel
change with the fisheye/FK prediction. It updates a bounded local correction
for the next step, rather than treating the first estimate as exact. An
inconsistent response or a failure to reduce error stops the session; it does
not try random alternatives. It predicts each candidate's full camera pose
from the frozen robot model and validated mount transform before proposing it.
It never substitutes projected or stale geometry for a raw depth measurement.

Each proposal displays old/new joint angles, expected pixel direction,
predicted camera-center translation, cumulative wrist rotation, and current
target evidence. Before sending a motion it rechecks the selected stable ID,
latest vision frame, stationary robot state, joint limits, and authorization.
Only the formal protected execution gateway may send the one bounded joint
step after operator confirmation. The controller waits for a correlated
completion and a new stationary state before accepting another observation.

## Limits and stopping

Initial commissioning limits: at most 2° per joint in a step, 10° cumulative
absolute rotation per wrist joint, 5 mm predicted camera-center displacement
per step, and 20 mm cumulative displacement from the starting camera center.
All are upper bounds, not permission to move: a validated safety profile may
set stricter limits. Fail closed if flange pose, mount transform, uncertainty
bound, collision clearance, robot capability, execution token, or fresh state
is missing. An operator must first clear the work area and have an independent
physical E-stop available. Software stop is not a safety-rated E-stop.

Stop with `depth_acquired` only after the same target is confirmed inside the
ROI margin and meets the existing vision depth-validity gate for three
consecutive fresh frames. Stop without moving further if target identity is
lost, depth is not improving, the target leaves RGB view, a candidate exceeds
any bound, a command is rejected/times out, state changes unexpectedly, or the
operator declines a step. On uncertain motion, request software stop, report
uncertainty, and require human inspection; do not automatically reverse or
restart. Exhausting the allowed wrist range reports `not_reachable_by_wrist`.

## Delivery and verification

1. Implement a pure candidate/guard module and replay it against recorded
   RGB observations and robot states. Verify the SEUCM stream/native coordinate
   mapping, ray direction, angular-error sign, predicted pixel movement, and
   bounded correction before covering ROI entry, missing depth, target
   switches, timeouts, joint limits, camera arc bounds, and no-progress cases.
2. Add a simulated adapter for the protected execution gateway. Verify that
   no command is emitted before operator confirmation or with stale evidence;
   failures produce a stop request and no subsequent candidate.
3. Show a read-only preview in the control interface or CLI with current
   target pixel, ROI, proposed joints, camera displacement, and blockers.
4. Live commissioning is a separate implementation and review stage. It needs
   the authenticated joint-motion primitive, mount/FK checks, execution
   authorization, area clearance, and operator step approval. First test one
   tiny empty-workspace wrist motion, compare observed RGB displacement with
   prediction, then proceed with a bottle. No grasp command is part of this
   feature.

Acceptance means recorded/simulated tests pass, the read-only preview reports
current blockers accurately, and later supervised hardware trials show fresh
depth on the locked target within the limits. The current deployment is
expected to remain read-only until its live prerequisites are actually met.
