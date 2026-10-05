# Projection wiring verification — 2026-10-05

## Patch-specific evidence

- Regression: expected RED on ignored calibrated upright, then 3/3 GREEN.
- Tests use the real pipeline and geometry with a static inference fixture.
- Saved RGB-D replay: 4/5 geometry checks passed; original processing rejected
  all five with `bottle_height_unreliable`. Remaining replay rejection:
  `table_plane_normal_mismatch` (not bypassed).
- Independent review: no Critical or deployment-blocking Important findings.
  Constructor injection, configurable live root and non-vacuous track assertions
  were checked. Shared geometry/display projection freezing remains documented.
- Live service: new bridge loaded, camera and inference ready; current saved
  calibration hash unchanged; original live bridge hash unchanged.
- Latest live sample: 10/12 distinct frames ready, selected bottle 1;
  calibrated direction stable; final candidate width 23.32 mm.
- Physical approval false; robot control false; no motion/gripper commands.

## Broader tests — not a full-suite pass

- Independent deployment root Node: 132/132 pass.
- Independent deployment root Python: 145 pass, 49 subtests pass, 2 fail:
  `test_depth_evidence_projects_only_with_physically_approved_handeye`
  (existing Projection test double lacks projection_allowed), and
  `test_unified_foundation_has_no_machine_specific_runtime_paths`
  (three existing absolute-path references outside this patch).
- A mixed-context run of deployment vision fixtures against the live library
  produced 72 failures and 5 errors, 115 passes. The deployment fixture config
  allows width above 72 mm and the live library rejects it. This run is invalid
  as a compatibility success claim; every failure is retained in vision-tests.log.
- Re-running the existing live vision suite against its own checkout produced
  169 passes and 23 failures, without loading this new compatibility bridge.
  Every failure name and traceback is retained in live-vision-tests.log.

Live vision failures by name (prefix skills/manipulation/bottlegrasp/tests/vision):

- geometry/test_debug_geometry.py::test_debug_geometry_writes_ranked_json_and_visualization
- perception/test_grounded_sam.py::test_model_provenance_names_configured_models_and_versions
- test_debug_pipeline.py::test_debug_pipeline_accepts_stable_target_id_not_spatial_ordinal
- test_nearfield_guard.py::test_real_l2_fixture_round_trips_through_json_and_passes_unchanged
- test_nearfield_guard.py::test_reference_tracking_accepts_only_the_exact_perspective_aspect_reasons
- test_nearfield_guard.py::test_any_extra_rejection_reason_still_blocks_reference_tracking
- test_nearfield_guard.py::test_unauthorized_candidate_cannot_create_initial_reference
- test_nearfield_guard.py::test_motion_without_pose_keeps_rgb_identity_but_fails_projection
- test_nearfield_guard.py::test_evaluation_uses_rgb_and_frozen_anchor_without_current_depth
- test_nearfield_guard.py::test_target_loss_fails_rgb_and_projection
- test_nearfield_guard.py::test_wrong_detection_id_fails_closed
- test_nearfield_guard.py::test_twenty_millimetre_anchor_translation_rejects_unchanged_mask
- test_nearfield_guard.py::test_width_ratio_is_diagnostic_only_and_cannot_reject_matching_position
- test_nearfield_guard.py::test_reference_points_behind_camera_are_not_visible
- test_nearfield_guard.py::test_partially_clipped_reference_fails_closed
- test_nearfield_guard.py::test_nonproduction_rgb_grid_is_rejected_before_projection
- test_nearfield_guard.py::test_empty_mask_and_appearance_conflict_fail_rgb
- test_observer.py::test_observer_cli_is_camera_denied_by_default
- test_observer.py::test_observer_cli_exposes_separate_camera_start_timeout
- test_observer.py::test_saved_l2_width_fixture_matches_full_geometry_within_one_centimeter
- test_observer.py::test_real_l2_producer_motion_contract_fixture_is_fail_closed
- test_observer.py::test_real_l2_fixed_z_producer_contract_separates_xy_from_plan_z
- test_offline_validation.py::test_offline_validation_covers_selection_and_failure_matrix

Full logs reside in the diagnostic artifact directory and were not committed.
Local review copies: [root Python](root-python-tests.log),
[live vision](live-vision-tests.log), [mixed-context run](vision-tests.log).

## Remaining scope

This patch wires calibration into geometry only. It does not solve raw masked
depth background contamination, prove physical calibration accuracy, establish
a measured TCP, validate paths, change safety thresholds, or enable gripping.
The startup environment override is not a newly installed boot service.
