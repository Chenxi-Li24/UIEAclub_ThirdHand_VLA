# Read-only depth/table quality deployment — 2026-10-05

Isolated branch: `Xavier/grasp-validation-prototype`; baseline `0dc391e`.
Original live camera bridge and checkout source are not overwritten.
Activation uses `VISION_BRIDGE_SCRIPT=tools/vision/camera_bridge_with_quality.py`
as an absolute path. The previous `camera_bridge_with_projection.py` remains
unchanged and available for rollback. No boot service was installed.

## Changes

- Constrained table RANSAC validates each SVD-refined hypothesis before ranking
  it, and returns the exact refined model whose angle/inliers were scored.
  Invalid dominant hypotheses no longer discard valid alternatives.
- Displayed depth, mask center and point-cloud spread reuse the existing
  3.5-MAD depth filter. Raw valid count/ratio are separately reported.
- Filtered point/ratio shortage clears coordinates and invalidates depth.
  Lost targets remain invalid and cannot emit coordinates.
- `pipeline_with_quality.py` mirrors the existing live pipeline with only its
  geometry import redirected to the independent `geometry_quality` package.
  Unconstrained camera-only geometry remains compatible.
- Existing thresholds are retained: at least250 points, ratio0.055, depth
  0.15–1.2m, table distance8mm, direction15deg, grasp width limit72mm.

## Fresh verification

-9 targeted tests passed, including actual pipeline integration and
  foreground filtering, point shortage, ratio shortage, lost-target cases.
- Saved现场5-frame replay:5/5 geometry passes; before this change4/5.
- Five timing repetitions per captured frame: previous table-fit median
  14.95–15.97ms, new15.05–15.76ms; finite scene2783–2881 points.
  Dense-scene throughput is not established by this sample.
- New live20-frame sample:17 ready; the other3 are selection/stability warmup
  (`selection_not_requested`, then `stability_hits_insufficient` twice).
  All subsequent17 samples ready. Depth0.20038–0.20580m, filtered points755–781
  versus raw1193–1221; cloud Z spread11.68–12.96mm, not localization accuracy.
  Last grasp candidate width23.52mm.
- Robot state subscription sends no commands. Before/after moving=false,
  flange/joint positions and gripper position unchanged. Physical calibration
  approval=false and robot control=false throughout.
- Fresh root Node suite132/132 pass. Root Python145 pass,49 subtests pass,
 2 failures unchanged from baseline:
  `test_depth_evidence_projects_only_with_physically_approved_handeye`
  (old Projection test double lacks `projection_allowed`),
  `test_unified_foundation_has_no_machine_specific_runtime_paths`
  (existing hardcoded runtime paths). This is NOT a full-suite pass.
  Python must have deployment `services/vision/python` on PYTHONPATH;
  omitting it causes `handeye_projection` collection failure.
- Original live bridge SHA256 still
  `72a2eb8a7bd270da4631d6e5584d07128ec39118be231aaa9895331cc3bf62e4`.
  Both saved calibration files still have SHA256
  `d2e322dec9c6dab109212188ccc87b714bbd7f3cd9b0de9f22169cc576764a5b`.

Remote logs/data: `artifacts/diagnostics/quality-1791211431938/{before,after,live}.json`
and `vision.log`; broader suite logs
`artifacts/diagnostics/bottle-1791210025882863205/quality-root-{python,node}-tests.log`.

Regression command from tools/vision, with live services/vision/python on
PYTHONPATH: `TEST_BRIDGE_FILE=camera_bridge_with_quality.py python -m unittest
test_geometry_quality test_projection_runtime`. Replay CLI:
`python replay_geometry_quality.py CAPTURE_DIRECTORY LIVE_CHECKOUT`.

## Still not authorized or validated

No TCP measurement, path test, motion, gripper close, physical handeye approval,
or hardware depth-accuracy claim. Filtered mask center is not a grasp point.
MAD assumes the target depth cluster dominates; it cannot identify foreground
universally when background dominates. Raw tracking median remains unchanged.
Geometry and display currently query projection independently; a shared frozen
frame transform remains required before considering motion authorization.
