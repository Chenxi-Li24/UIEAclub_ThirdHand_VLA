# Web-Triggered Active Depth Alignment

## Purpose and operator flow

An operator selects one stable bottle target in the `9983` web interface and
then explicitly presses **Start depth alignment**. That single action starts an
automatic visual-servo session whose only objective is to place the same bottle
inside the registered-depth field of view and acquire valid depth. It does not
descend, close the gripper, or start a grasp.

The session uses the fisheye RGB centroid to choose a direction, executes one
small joint step, waits for correlated robot completion and a new stationary
observation, and corrects from measured pixel response. J4-J6 are always tried
first. J1-J3 are considered only when every permitted wrist candidate fails to
reduce angular error or the wrist cumulative budget is exhausted. No random,
alternating, or blind joint search is allowed.

The Vision Service's `robotControlEnabled=false` remains an ownership marker:
vision never sends robot commands. It is not an active-depth blocker. Execution
authority exists only in a protected Robot Service primitive.

## Components and ownership

### Browser UI

The XVisio drawer gains **Start depth alignment** and **Stop alignment** controls
plus a compact status panel. Start is enabled only when a stable target is
selected and no session is active. The panel displays session phase, locked
target ID, current and predicted pixels, current depth validity/ratio, proposed
joint deltas, predicted camera displacement, step count, and terminal reason.

The browser never computes joint targets and never receives an execution token.
It starts or stops a server-owned session through same-origin HTTP and receives
status updates through the existing browser Robot WebSocket. Refreshing or
closing the page requests cancellation; loss of the browser is not trusted as
the only stop mechanism because the server also owns all timeouts.

### Web Gateway active-depth coordinator

A focused `ActiveDepthCoordinator` owns one process-wide session. It consumes:

- current selected-target observations from Vision Service HTTP;
- runtime camera/registration evidence from Vision Service status;
- fresh robot state from the existing background Robot upstream;
- the checked-in `T_flange_camera` mount artifact;
- pure SEUCM, flange-FK, and candidate functions already implemented under
  `apps/web/src/active-depth/`;
- a dedicated protected execution client connected to Robot Service
  `/execution` with the launcher-generated token.

New same-origin routes are:

- `POST /api/active-depth/start` with exactly `{stableId}`;
- `POST /api/active-depth/stop` with exactly `{sessionId}`;
- `GET /api/active-depth/status`.

The coordinator emits `active_depth.status` messages over existing browser
connections. A second start receives `409 session_active`. Start never succeeds
merely because a client supplied a target ID: the ID must equal the current
Vision Service selection and identify one confirmed target in a fresh frame.

### Protected execution transport

The launcher creates the existing 0600 runtime execution-token file and passes
its path to both Robot Service and Web Gateway. Web Gateway reads it once through
the same strict format and permission checks and sends it only as the
`x-thirdhand-execution-token` header on a loopback `/execution` WebSocket. The
token is never returned by an API, logged, or sent to the browser.

The formal `thirdhand.execution-primitive.v1` contract becomes a discriminated
union. Existing `gripper.set` remains unchanged. A new `vision.align.step`
operation contains:

- absolute `targetJointsDeg` and measured `startJointsDeg`, each six finite
  values;
- `sessionId`, `stableId`, `frameId`, `evidenceId`, and `motionEpoch`;
- `tier`, either `wrist` or `arm_fallback`;
- requested `timeoutMs` within the existing bounded interval.

Robot Service validates the primitive again rather than trusting the Web
Gateway. It requires current stationary state and matching `startJointsDeg`,
normal joint limits, no other formal primitive in flight, and a fresh unseen
primitive ID. For `wrist`, J1-J3 must be unchanged and each J4-J6 delta must be
at most 2 degrees. For `arm_fallback`, J4-J6 must be unchanged, each J1-J3 delta
must be at most 1 degree, and the coordinator must have marked the wrist tier
exhausted for this session. The service sends one bounded `move_joint`, reports
accepted/completed/failed/uncertain with the primitive ID, and requests software
stop on timeout or execution-socket loss.

The low-level manual `/ws` route is not used by active depth.

## Candidate hierarchy and limits

Every cycle derives the target ray and a depth-ROI interior-center ray using the
checked-in SEUCM model. It freezes the current target bearing in the base frame,
predicts candidate camera poses from full FK and `T_flange_camera`, and ranks
only strict angular-error improvements.

Tier 1 enumerates deterministic signed J4-J6 candidates at 2, 1, 0.5, and 0.25
degrees. Tier 2 runs only after Tier 1 returns no valid improvement or reaches
its cumulative budget; it enumerates deterministic signed J1-J3 candidates at
1, 0.5, and 0.25 degrees. Tie order is stable by tier, joint number, sign, then
smaller angular error. Joints from different tiers are never changed in one
primitive.

Hard bounds for the whole session are:

- J4-J6: at most 2 degrees per joint per step and 10 degrees cumulative per
  joint from session start;
- J1-J3: at most 1 degree per joint per step and 5 degrees cumulative per joint
  from session start;
- predicted camera-center displacement: at most 5 mm per step and 20 mm from
  session start;
- at most 20 completed motion steps and 90 seconds elapsed;
- one motion primitive in flight.

Unknown target range means the predicted pixel is labelled
`rotation_only_bearing`; camera translation is bounded but is never presented as
an exact target projection. An arm-fallback candidate is not permission to
violate the robot joint limits or configured workspace constraints.

## Automatic state machine

States are `idle`, `observing`, `proposing`, `executing`, `settling`,
`verifying`, and terminal `depth_acquired`, `stopped`, `blocked`, `failed`, or
`uncertain`.

1. `observing` requires a fresh confirmed instance with the locked stable ID,
   camera and registration evidence matching the mount artifact, and a fresh
   stationary six-joint robot state.
2. If the same target is inside the ROI margin and `depth_valid=true`, increment
   a consecutive-frame counter. Three distinct increasing frame IDs complete
   with `depth_acquired`; any invalid frame resets the counter.
3. Otherwise `proposing` evaluates the wrist tier, then the arm-fallback tier
   only if wrist is exhausted. No improving valid candidate terminates as
   `blocked:not_reachable`.
4. `executing` sends exactly one protected primitive and accepts only correlated
   statuses. Rejection is `failed`; timeout, disconnect, or ambiguous feedback
   is `uncertain` and triggers software stop.
5. `settling` waits for a new fresh stationary robot state whose joints match
   the target within tolerance. It then requires a vision frame newer than the
   command completion frame.
6. `verifying` compares measured pixel movement with the predicted direction
   and requires the SEUCM angular error to decrease by at least 0.001 rad. Wrong
   sign, no progress, target switch, or loss terminates without another motion.
7. A valid response returns to `observing` and automatically starts the next
   cycle until success or a hard bound is reached.

The operator Stop button is idempotent. During motion it requests software stop
and ends as `stopped` only after correlated stop confirmation; if confirmation
is unavailable the result is `uncertain`. Starting a grasp remains a separate
operator action after alignment completes.

## Failure handling and runtime visibility

The session fails closed for malformed pixels, stale timestamps, duplicated or
decreasing frame IDs, target identity changes, invalid FK/mount matrices,
missing execution token, robot state mismatch, joint-limit violations, command
replay, camera displacement excess, or service disconnect. Error payloads expose
stable machine-readable reasons and a short Chinese UI message without secrets.

Web Gateway health reports active-depth readiness separately from Vision
Service ownership and grasp execution gates. Readiness includes execution-token
availability, Robot Service connection/state freshness, Vision Service health,
mount presence, and whether a session is active. It must not report ready merely
because `robotControlEnabled` is false or true.

## Verification and commissioning

Testing proceeds without hardware first:

1. Extend contract and Robot Service tests for both operations, invalid union
   shapes, replay, stale start joints, wrong-tier deltas, joint limits, timeout,
   disconnect, and one-in-flight behavior.
2. Test the candidate hierarchy, deterministic wrist-first ordering, fallback
   activation, cumulative budgets, camera displacement, no-progress, and depth
   completion over three increasing frames.
3. Test Web Gateway HTTP/WS behavior with fake Vision and Execution services,
   including start/stop idempotency, token secrecy, target switch, reconnect,
   and browser status rendering.
4. Run the complete Node suite and preserve unrelated failures separately.
5. Commission in hardware with the gripper open and an empty swept workspace:
   first one wrist step, then one arm-fallback step, comparing predicted and
   observed pixel direction before enabling the automatic loop. Keep the
   physical E-stop reachable. Hardware commissioning is not part of automated
   tests and never issues a grasp command.

Acceptance requires all simulated tests to pass, the web UI to show a complete
automatic session trace, Robot Service to reject every out-of-contract step,
and a supervised hardware run to end in `depth_acquired` or a truthful terminal
blocker without any grasp action.
