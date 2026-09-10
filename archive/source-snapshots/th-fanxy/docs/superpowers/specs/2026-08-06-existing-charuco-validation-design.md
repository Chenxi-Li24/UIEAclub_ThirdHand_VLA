# Existing ChArUco Validation Target Design

## Goal

Reuse the laboratory's existing DFOPTIX `CC200-15-11.25` board for held-out
Lumos/D435 legacy-extrinsic validation without coupling the geometry validator
to one target family or enabling robot motion.

## Verified physical target

The user-supplied board photograph was checked with OpenCV 4.11:

- `DICT_5X5_100` detects all 54 marker IDs (`0..53`); `DICT_4X4_50` detects
  only one false candidate.
- The board is 9 rows by 12 columns. OpenCV's `CharucoBoard` constructor takes
  `(columns, rows)`, so the correct value is `(12, 9)`, not `(9, 12)`.
- Square length is `0.015 m`; marker length is `0.01125 m`.
- The correct board definition recovers all 88 ChArUco chessboard corners from
  the photograph.

The old calibration scripts confirm the metric lengths and dictionary but
several pass `(9, 12)` to OpenCV. That orientation error must not be copied.

## Architecture

`calibration_targets.py` owns target configuration and detection. It exposes a
single keyed-correspondence result containing stable feature IDs, metric 3-D
points, and observed 2-D pixels. `AprilGridTarget` and `CharucoTarget` implement
the same detector contract; ChArUco is the default for current hardware while
AprilGrid remains an optional adapter.

The dual-camera validator consumes only the generic correspondence result. It
solves the board pose with the D435 pinhole model, transforms those points with
the isolated legacy seed, and scores their projection with the native Lumos
SEUCM model. It never imports camera drivers or a motion SDK.

## Data flow and gates

1. Fetch Lumos and raw D435 JPEGs concurrently over loopback HTTP.
2. Detect the configured target independently in both images.
3. Match stable ChArUco corner IDs visible in both images; require at least 24.
4. Require D435 reprojection RMSE at most `1.5 px` and aggregate Lumos P95 at
   most `4.0 px` across at least 10 distinct board poses.
5. Store images, hashes, per-pose metrics, and a content-addressed summary.
6. Keep `executable: false`; hand-eye and table validation remain independent
   blockers even when the camera-to-camera candidate passes.

## Failure handling and testing

Malformed target files, wrong dictionaries/dimensions, insufficient shared
features, image/calibration size mismatches, duplicate sample IDs, changed
candidate IDs, or tampered manifests fail closed. Unit tests generate a real
OpenCV ChArUco image and require 88 keyed corners, verify generic cross-camera
matching, and prove that ten good observations validate only the relative
extrinsic while never authorizing execution.

