# Measured-TCP Bottle Pick Commissioning Design

**Date:** 2026-08-24
**Status:** Approved by user for implementation planning
**Project:** `PinZiZhuaQuSkill`

## Goal

Enable a supervised, low-speed, end-to-end real-robot workflow for selecting an upright opaque bottle by stable ID, grasping it, placing it upright at one fixed point, and returning to Home. Replace the unsafe base-frame constant grasp offset with an explicit measured flange-to-TCP transform. Keep every commissioning and production module independently runnable and debuggable from VS Code Remote-SSH.

## Scope and success criteria

The supported scene is deliberately narrow:

- one Lumos Ego STD RGB-D fisheye camera rigidly mounted on the robot flange;
- one Startouch-controlled arm with a two-finger gripper;
- one to five upright, opaque, separated bottles with clear visible contours;
- bottle executable diameter at the selected grasp band no greater than `0.072 m`;
- one fixed placement point on the table;
- every task begins from measured Home and ends at measured Home;
- motion speed scale remains `0.05` during commissioning;
- all approach and retreat motion near a bottle or table is axis-constrained and vertical in robot base coordinates;
- a complete run is successful only after measured gripper contact, measured release, retreat, measured Home, and confirmed depower/idle state.

The system is ready for one supervised full trial only when all of these are true:

1. the hand-eye physical validation reports maximum 3D consistency/error no greater than `10 mm`;
2. an explicit `T_flange_tcp` artifact is measured and validated; no base-frame constant offset is used;
3. the selected bottle grasp band has reliable table-relative height and width;
4. the empty-gripper pick and placement corridors have passed low-speed validation;
5. the fixed placement point and the allowed startup-to-Home joint ranges are bound into the same path artifact;
6. configuration activation is content-bound to the approved artifacts and cannot be achieved by changing one boolean.

## Reused mature work

This design reuses ideas and APIs without importing a large robotics runtime:

- OpenCV `4.11.0` already exists in the project environment and exposes `cv2.aruco`. The implementation reuses its official `CharucoBoard`, `CharucoDetector.detectBoard`, sub-pixel ChArUco corners, PnP, and existing `calibrateHandEye` solve. No new marker detector dependency is required. OpenCV `4.5.0+` is Apache-2.0 licensed.
- The local `ThirdHand-XVisio-handeye-web` project is the primary migration source for this exact camera and board. Its `CharucoSpec`, target loader/detector, SDK rectification contract, 24-sample capture contract, HORAUD hand-eye result, and held-out validation are reused under its MIT license. Only the focused modules and fixtures needed by this Skill are migrated; production code has no runtime dependency on the old project directory.
- ROS-Industrial `industrial_calibration` is used as the reference pattern for collecting synchronized robot pose plus image observations, solving extrinsics, validating residuals, and serializing transforms. It is Apache-2.0 licensed. The project is not added as a runtime dependency.
- MoveIt Task Constructor is used as the architectural reference for a serial, independently gated pick-and-place pipeline. The project keeps its current lightweight Startouch adapter and does not add ROS or MoveIt.
- RoboDK's documented multi-orientation point method is reused for positional TCP calibration: touch one fixed point with the same rigid probe from at least eight sufficiently different flange orientations, solve the flange-to-probe translation and fixed point together, and report every residual. RoboDK is a method reference, not a runtime dependency.
- The local TH-Fanxy implementation supplies the proven motion discipline: raise first, translate at clearance, and make the final approach only along the controlled target axis while preserving orientation.
- The local Startouch SDK remains the only hardware command layer. Its flange pose semantics and TCP compensation formulas are reused instead of inventing a second robot protocol.

References:

- <https://docs.opencv.org/4.x/df/d4a/tutorial_charuco_detection.html>
- <https://opencv.org/license/>
- <https://robodk.com/doc/en/General-Define-Tool-TCP.html>
- <https://github.com/ros-industrial/industrial_calibration>
- <https://moveit.picknik.ai/main/doc/concepts/moveit_task_constructor/moveit_task_constructor.html>
- <https://github.com/AprilRobotics/apriltag> (evaluated, but not added because OpenCV ArUco is already available)

## Coordinate-frame contract

All transforms are homogeneous rigid transforms with an explicit source and destination:

- `T_base_flange`: measured Startouch SDK flange pose;
- `T_flange_camera`: approved eye-in-hand calibration;
- `T_camera_board`: ChArUco/PnP board observation;
- `T_flange_tcp`: measured gripper grasp-center TCP;
- `T_base_tcp_desired`: desired grasp or placement TCP pose;
- `T_base_flange_command = T_base_tcp_desired @ inverse(T_flange_tcp)`.

The former `flange_offset_base_m: [0.0475, 0.0100, 0]` is retained only as rejected historical evidence. It must never participate in commissioning or production motion. A tool offset is defined in the flange frame and rotates with the flange; it is not a fixed translation in the robot base frame.

Every message or artifact carrying a pose also carries `pose_frame`, translation units, rotation convention, and the content IDs of the camera intrinsics, distortion model, hand-eye artifact, tool artifact, and action configuration.

## Module boundaries

The implementation adds or adjusts five cohesive modules without mixing hardware lifecycle into math code.

### 1. Fiducial validation

`src/thirdhand_va/vision/calibration/fiducial.py`

- consumes one RGB-D frame plus camera-model metadata and the immutable `CC200-15-11.25` board profile;
- constructs OpenCV `CharucoBoard((12, 9), 0.015, 0.01125, DICT_5X5_100)` and calls the official `CharucoDetector.detectBoard` API;
- accepts only marker IDs `0..53`, at least `20` markers, at least `30` ChArUco corners, and corner coverage spanning at least `50%` of both physical board axes;
- rejects an incorrect dictionary/board identity, out-of-range or duplicate IDs, clipped observations, stale frames, excessive reprojection error, and RGB/depth disagreement;
- consumes the same manufacturer-SDK-rectified `960 × 960` RGB contract used by the accepted hand-eye dataset: camera serial `250801DR48FP25002738`, model `xv::Seucm-via-CameraModel-project`, frozen `K_rectified`, and bound rectification-LUT hash;
- rejects raw fisheye input, a different crop/scale/LUT, or double-undistortion; the existing SDK projection path performs the only rectification before ChArUco/PnP;
- requires per-frame reprojection RMSE no greater than `1.0 px` and board-plane depth/PnP disagreement no greater than `20 mm`;
- returns an immutable board observation and an overlay image;
- never imports Action code and never commands hardware.

`configs/calibration/charuco-cc200-15-11.25.yaml` is the single board-profile source, migrated from the old project's `charuco_12x9.yaml`. The detector is a focused port of `vision_models/calibration_targets.py` with its MIT provenance retained. Runtime code never guesses among dictionaries. `scripts/vision/debug_fiducial.py` runs the module on an imported historical replay bundle or live-authorized camera and prints detected marker IDs, ChArUco corner count/coverage, reprojection error, depth agreement, pose, and blockers.

### 2. Hand-eye physical validation

`src/thirdhand_va/action/calibration/handeye_physical.py`

- consumes synchronized `T_base_flange`, `T_flange_camera`, and `T_camera_board` observations from at least five sufficiently different safe arm poses;
- transforms the fixed board into the base frame for every observation;
- reports median, maximum deviation, per-axis spread, reprojection error, and depth/PnP disagreement;
- requires at least five accepted observations, at least three distinct rotation axes, maximum base-frame board spread no greater than `10 mm`, and no single accepted sample with stale/mismatched camera or robot identity;
- produces a pending or approved copy of the existing hand-eye artifact without modifying the original evidence.

This stage validates the eye-in-hand chain without needing a guessed gripper offset.

### 3. Tool TCP measurement

`src/thirdhand_va/action/calibration/tool_tcp.py`

- defines the operational TCP as the center between closed fingers at the intended bottle grasp height;
- uses the standard multi-orientation point/pivot equation `R_base_flange_i @ t_flange_probe + p_base_flange_i = p_base_fixed` and solves `t_flange_probe` plus the unknown fixed point by linear least squares;
- consumes at least eight measured flange poses in which a rigid pointed calibration probe, clamped symmetrically by the gripper, touches one protected stationary reference point from sufficiently different safe orientations;
- converts probe-tip TCP to the operational grasp-center TCP using the caliper-measured probe-tip-to-grasp-plane distance along the fixed gripper tool axis;
- defines `R_flange_tcp` from the existing Startouch gripper frame/URDF convention and validates that convention with a high-clearance axis-motion observation against the fixed board; pivot calibration does not claim to solve orientation;
- treats the existing Startouch V3 URDF/STL geometry only as a nominal seed and collision-envelope source until physical dimensions agree with caliper measurements;
- requires repeatability no worse than `5 mm` and verification error no greater than `10 mm`;
- stores translation and rotation in the flange frame, plus gripper envelope dimensions and the exact measurement evidence;
- never emits a base-frame offset.

`scripts/action/debug_tool_tcp.py` replays the measurements without a robot. `scripts/action/commission_tool_tcp.js` captures one operator-taught pose at a time; it never autonomously seeks or touches the reference point, and it returns Home/depower after every measurement set.

### 4. Bottle geometry and collision envelope

`src/thirdhand_va/vision/geometry/bottle_grasp_band.py`

- estimates the table plane from non-target depth points;
- transforms the target mask cloud into base coordinates with the approved hand-eye chain;
- computes a vertical width profile and chooses a continuous body band between `35%` and `65%` of reliable bottle height;
- requires at least `20 mm` of continuous graspable vertical band, sufficient finger-to-table clearance, executable width no greater than `72 mm`, and stable center/height across at least five stationary frames;
- rejects clipped, occluded, sparse, or physically implausible bottle height rather than substituting a guessed height.

`src/thirdhand_va/action/safety/tool_envelope.js`

- models the measured gripper/TCP envelope conservatively;
- checks every waypoint and straight-line segment against workspace limits, the table plane, non-target bottle clouds, and the target exclusion rules;
- permits target intersection only during the validated final vertical approach and gripper closure interval.

### 5. Commissioned path and activation

`src/thirdhand_va/action/commissioning/staged_pick_place.js`

- builds a serial plan from measured current state and immutable evidence;
- exposes a maximum stage level and cannot skip prerequisite evidence;
- emits exactly one correlated command at a time;
- verifies measured completion before advancing;
- records the command, planned pose, actual pose, gripper proof, robot-state boundary, and operator result;
- returns Home and confirms stop/depower whenever it is safe to do so; after a close/contact failure it enters manual recovery and never automatically releases a possibly held bottle.

`src/thirdhand_va/action/runtime/activation_manifest.js`

- binds the approved hand-eye, tool TCP, bottle constraints, fixed placement path, Home definition/ranges, speed, and code/config content IDs;
- is the only source allowed to set production readiness;
- rejects the legacy hand-eye v1 collision report and all artifacts created by a lower commissioning level.

## Board and measurement specification

The project reuses the user's manufactured Dafan Vision `CC200-15-11.25` optical-film/aluminium ChArUco board instead of generating or printing a new marker. The supplied manufacturer specification defines:

- physical substrate: `200 × 150 mm`;
- active checker area: `180 × 135 mm`;
- checker layout: `12 × 9` squares;
- square length: `15.00 mm`;
- marker outer length: `11.25 mm`;
- nominal manufacturing accuracy: `±5 μm`.

The earlier hand-eye project already established the same identity and coordinate convention: all `54` markers have consecutive IDs `0..53`, and the standard `12 × 9` `CharucoBoard` provides `88` internal ChArUco corners. The supplied product image independently reproduces the same result under the installed OpenCV `4.11.0`. Larger `5X5` dictionaries are supersets and are not selected; the smallest matching dictionary is pinned explicitly as `DICT_5X5_100`.

Board coordinates use OpenCV's returned object points as the authority: origin at the outer checker corner adjacent to ChArUco corner ID `0`, `+X` along the 12-square direction, `+Y` along the 9-square direction, and `+Z` by the right-hand rule. ChArUco corner ID `38`, object coordinate `[0.090, 0.060, 0.000] m`, is the named visual reference for high-clearance verification; it avoids asking an operator to estimate the geometric board center.

The existing 24-sample eye-in-hand dataset is immutable calibration evidence, not something to reproduce from scratch. Its recorded overall reprojection RMSE is `0.1474 px`; held-out translation consistency is `4.922 mm` RMSE and `7.541 mm` maximum; held-out rotation consistency is `0.9169 deg` RMSE. These numerical results remain pending until the new physical validation passes. Implementation imports its board profile, camera/LUT identity, representative replay fixtures, and held-out metrics into `PinZiZhuaQuSkill` with content hashes and provenance. Unit tests also generate canonical boards through OpenCV's official board renderer and prove parity between the old OpenCV `4.14.0` evidence and the installed `4.11.0` runtime. No runtime or test command relies on an absolute path outside `PinZiZhuaQuSkill`.

The board is fixed flat to the table, away from the bottle working area and table edge, and must not move during one observation set. Its printed face must remain clean and non-reflective under the active lighting. The overlay displays marker IDs, ChArUco corner IDs and coverage, board axes/origin, reprojection error, RGB/depth center, and the predicted base-frame board pose.

## Commissioning levels

Each level is an independently runnable VS Code entry, ends with a report, and unlocks only the next level.

### Level 0 — offline and camera-only

- verify the immutable board profile against imported historical replay and OpenCV-rendered regression fixtures;
- place the physical board flat and verify the live detection overlay;
- replay all frame transforms and paths;
- no robot connection.

Pass: imported historical replay preserves its recorded ChArUco/PnP results; live frames contain only IDs `0..53`, at least `20` markers and `30` ChArUco corners with required coverage in each of at least `30` stable frames; reprojection RMSE is no greater than `1.0 px`, and depth/PnP disagreement is no greater than `20 mm`.

### Level 1 — hand-eye high-clearance consistency

- robot starts at measured Home;
- capture five to eight safe, high-clearance views of the stationary board;
- no gripper command and no descent near the table;
- return Home and depower after each pose set.

Pass: required pose diversity and maximum transformed board spread no greater than `10 mm`.

### Level 2 — measured tool TCP

- clamp a straight rigid pointed probe symmetrically in the empty gripper and measure its tip-to-operational-grasp-plane distance with a caliper;
- operator-teach at least eight different orientations touching one protected stationary point; the program only records measured poses and never drives into contact;
- solve positional TCP with the multi-orientation point method, then remove the probe;
- perform a separate no-contact high-clearance verification over ChArUco corner ID `38`, first at the production orientation and then at a deliberately changed safe orientation.

Pass: repeatability no greater than `5 mm`, final 3D verification error no greater than `10 mm`, no collision/contact.

### Level 3 — empty-gripper corridors

- validate Home to safe height, pick XY at safe height, vertical pregrasp, retreat, transfer, fixed place XY, vertical place, and Home;
- gripper may open/close only in free space;
- no bottle is present.

Pass: every segment reaches its measured endpoint, respects the tool envelope, and returns to measured Home.

### Level 4 — soft single-bottle trial

- one empty lightweight soft plastic bottle, no other bottles;
- validate target ID, high observation, vertical descent without closure, then return Home;
- on a separate run, perform grasp, lift only, replace at the original point, and return Home;
- on the final Level 4 run, grasp, transfer, upright fixed-point placement, retreat, and Home.

Pass: no contact before final approach, contact width is within the approved range, lift retains the bottle, release is measured, bottle remains upright, and Home is measured.

### Level 5 — supervised complete workflow

- user selects one stable bottle ID;
- the complete production state machine runs at commissioning speed;
- success generates the activation manifest but does not silently raise speed.

After Level 5, the formal L interface may use the same workflow. Any camera mount change, tool change, config/code hash change, or failed safety proof invalidates readiness.

## Production motion stages

The production plan is serial and immutable:

1. measured Home;
2. open gripper;
3. raise vertically to safe transit height with current orientation;
4. move horizontally at safe height to target XY;
5. rotate to the approved grasp orientation only in a validated obstacle-free high-clearance zone;
6. descend vertically to pregrasp;
7. final vertical approach to the TCP grasp pose;
8. close and verify contact width;
9. lift vertically;
10. transfer at safe height to fixed placement XY;
11. descend vertically to the dynamic placement Z;
12. open and verify release;
13. retreat vertically;
14. return through the validated Home corridor;
15. verify all six Home joints and confirm stop/depower.

No stage may blend translation and orientation changes near an object. The planner must verify that the safe transit height clears the measured bottle top and the complete tool envelope, not merely the flange point.

## Failure behavior

- Any stale/missing frame, pose-frame mismatch, board mismatch, artifact mismatch, Home mismatch, tool-envelope violation, unexpected robot state, or uncorrelated completion fails closed before motion.
- Before grasp contact, failure requests a correlated software stop; return Home occurs only if the validated recovery corridor remains safe.
- After possible contact, the system never opens the gripper or moves to Home automatically. It enters `manual_recovery`, reports whether an object may be held, and waits for explicit operator recovery.
- Timeouts require a confirmed stop/depower proof. A disconnected process or missing acknowledgement is not treated as a successful stop.
- Old incident reports remain evidence but can never approve a new hand-eye, TCP, or path artifact.

## VS Code and independent debugging

Each core module has one pure offline debugger and, where required, a separate explicitly authorized real-hardware entry. Proposed F5 entries:

- `Vision: Debug Fiducial (Replay)`
- `Vision: Validate Fiducial (Live Camera Only)`
- `Action: Debug Hand-Eye Physical Solve (Offline)`
- `Action: Commission Hand-Eye Views (Real, Level 1)`
- `Action: Debug Tool TCP Solve (Offline)`
- `Action: Commission Tool TCP (Real, Level 2)`
- `Action: Validate Empty Corridors (Real, Level 3)`
- `Action: Validate Soft Bottle (Real, Level 4)`
- `VA: Supervised Complete Pick Place (Real, Level 5)`

Every real entry prompts for its level-specific inputs, prints the exact planned waypoints before connection, and writes a timestamped report under `artifacts/action/commissioning/`. Offline debuggers use recorded fixtures and expose inputs as JSON so the user can edit them and set breakpoints without starting the full system.

## Testing strategy

Development follows test-first cycles.

- Python unit tests cover the migrated ChArUco detector against historical/synthetic fixtures, rectified-camera identity, PnP/depth agreement, hand-eye consistency statistics, multi-pose TCP solve, table plane, bottle grasp band, and transform algebra.
- JavaScript unit tests cover tool-envelope intersections, stage prerequisites, immutable motion plans, artifact hashes, Home gates, correlated completions, stop proof, and manual recovery.
- Contract tests replay Python vision outputs through JavaScript Action consumers.
- Integration tests run all commissioning levels against simulated camera/robot adapters and prove that levels cannot be skipped.
- The previous collision report is a permanent regression fixture: tests must fail if a `47.5 mm` base offset, horizontal orientation sweep, or low hover stage reappears.
- Hardware tests remain opt-in and require exact environment authorization plus the level artifact from the previous stage.

## User responsibilities

The user does not edit coordinates or approval booleans. During commissioning, the user only:

1. supplies the `CC200-15-11.25` board and checks that its face is clean and undamaged;
2. fixes the board flat and keeps it stationary for one observation set;
3. confirms the arm starts at Home, the area is clear, and the emergency stop is available;
4. provides a straight rigid pointed probe and protected fixed reference point, teaches the requested contact poses, and measures the probe extension when prompted;
5. places or removes the single soft test bottle as prompted;
6. observes each real stage and uses the emergency stop if motion is unexpected.

All transforms, hashes, artifacts, configuration activation, logs, overlays, and VS Code entries are produced by the system.

## Non-goals

- arbitrary clutter or touching bottles;
- transparent bottles or unreliable depth surfaces;
- bottles wider than the executable gripper limit;
- arbitrary placement targets;
- autonomous recovery while a bottle may be held;
- high-speed production optimization;
- adding ROS/MoveIt as a runtime dependency;
- claiming physical success from offline tests alone.
