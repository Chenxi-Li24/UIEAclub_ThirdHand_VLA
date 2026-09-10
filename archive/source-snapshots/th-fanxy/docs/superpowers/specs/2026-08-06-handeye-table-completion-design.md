# Hand-Eye and Table Calibration Completion Design

Date: 2026-08-06

Status: approved for implementation by the user's request to complete the remaining gates

## 1. Goal

Complete the two blockers left after the validated Lumos/D435 relative extrinsic:
`handeye_validation_missing` and `table_validation_missing`. The result is a
content-addressed camera/table evidence foundation for active-view planning. Calibration
capture remains read-only: it may read camera frames and the existing robot status stream,
but it must not import the Startouch SDK, open CAN, or send motion commands.

The legacy files under `/home/nieqingcao/calibration` remain diagnostic seeds only. Their
audit found missing independent validation, RPY values passed to Rodrigues, ambiguous D435
transform direction, a pinhole treatment of Lumos SEUCM, and an implausible table normal.
They cannot authorize motion.

## 2. Accepted approach

Use the already validated schema-v2 dual-camera candidate as the immutable camera source.
Capture a new D435 eye-in-hand dataset with correct SDK RPY conversion and held-out samples,
then derive `T_flange_from_lumos` through the validated `T_lumos_from_d435`. After hand-eye
passes, capture the same ChArUco board lying flat at several desktop locations and fit a
base-frame plane with independent held-out validation.

This preserves the completed relative calibration, replaces only invalid legacy evidence,
and avoids trusting unrepeatable matrices or recalibrating camera intrinsics.

## 3. Module boundaries

### 3.1 Candidate capture adapter

`vision_models.calibration_completion` loads the schema-v2 dual-camera candidate through
the existing strict loader and exposes only the D435 pinhole model, zero distortion, and
candidate content ID required by hand-eye capture. It does not solve calibration or access
hardware.

### 3.2 Hand-eye capture and solve

The existing `calibration_capture` module continues to detect ChArUco and atomically append
one JPEG, one stable read-only robot state, and one `T_d435_from_board`. The existing
`calibration_pipeline` solver uses OpenCV PARK/TSAI/HORAUD and ranks candidates only on
held-out samples.

Collect exactly 15 distinct poses while the board stays fixed: 12 fit and 3 validation
samples, assigned deterministically every fifth sample. Fit poses must span at least 30 mm
translation and 15 degrees rotation. Every sample requires at least 24 detected ChArUco
points and D435 reprojection RMSE no more than 1.5 px. The held-out static-board position
P95 must be no more than 10 mm and reprojection RMSE no more than 1 px.

### 3.3 Table capture and solve

`vision_models.table_calibration` consumes typed table samples only. For each sample it
composes:

```text
T_base_from_board =
  T_base_from_flange @ T_flange_from_d435 @ T_d435_from_board
```

The ChArUco board must lie flat on the desktop. Board corners are transformed into the base
frame. Six fit samples estimate the plane with robust SVD after median/MAD rejection; two
held-out samples validate signed point-to-plane distance. The normal is oriented toward
positive base Z and must be within 15 degrees of base Z. Fit RMSE must be no more than 5 mm
and held-out P95 no more than 8 mm. The output contains the plane, all source IDs, metrics,
`validated`, reasons, and a content ID.

### 3.4 Evidence builder

`vision_models.calibration_completion` combines:

- the schema-v2 relative candidate and its ten-pose validation report;
- the independently validated D435 hand-eye result;
- the independently validated table result.

It derives `T_flange_from_lumos = T_flange_from_d435 @ inv(T_lumos_from_d435)`, computes the
aggregate Lumos median/P95 and radial-edge P95 from retained validation observations, and
writes the exact camera/table schemas already consumed by `load_active_view_foundation`.
No metric is invented: if a required value cannot be derived from retained observations,
the builder refuses to finalize.

### 3.5 Workflow and page

A Python workflow CLI owns status transitions and filesystem writes. A narrow Node API
spawns only allowlisted CLI actions. A separate `calibration-completion.html` page shows the
D435 preview, current phase, quality metrics, blockers, and one phase-specific button. It
never contains joints, Cartesian targets, or motion controls.

State flow:

```text
handeye_collect -> handeye_solve -> table_collect -> finalize -> foundation_validated
```

The page instructs the operator when the board must remain fixed, when the robot must be
manually repositioned, and when the board must be placed flat. Duplicate robot poses or
board locations are rejected instead of consuming progress.

## 4. Safety and failure behavior

- Calibration capture reads `ws://127.0.0.1:3000/ws` with `{cmd:"status"}` only.
- The workflow has no robot, CAN, gripper, servo, preset, or `move_l` dependency.
- Robot state requires three stable readings; moving or stale state is rejected.
- Camera/candidate/content IDs are frozen at the first sample and checked on every action.
- Images and manifests are atomic and content-addressed; symlinks, remote URLs, non-finite
  values, duplicate IDs, and changed sources fail closed.
- Solving never deletes accepted captures. A rejected solve reports exact reasons and
  returns to the relevant capture phase.
- Completing the foundation enables geometry consumption only. Real observation motion
  still requires the separate short-lived approval artifact, per-step confirmation,
  physical emergency-stop readiness, and cleared workspace. Autonomous grasp remains off.

## 5. Verification

Tests cover candidate adaptation, capture provenance, pose/location diversity, hand-eye
held-out gates, robust plane fitting, table held-out gates, evidence schema/content IDs,
tamper rejection, API allowlists, browser behavior, and the no-motion import/command
boundary. Live acceptance additionally requires 15 successful hand-eye poses, 8 successful
table samples, both held-out gates passing, and `load_active_view_foundation` accepting the
generated camera/table pair.

