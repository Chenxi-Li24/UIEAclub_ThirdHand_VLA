from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from thirdhand_va.common.contracts import MaskCandidate, RgbdFrame
from thirdhand_va.vision.nearfield_guard import create_reference, evaluate_reference
from thirdhand_va.vision.perception.grounded_sam import masked_rgb_descriptor


FIXTURE = Path(
    "artifacts/vision/observer/l2-height-band-fixture-20260908/frame-mask.npz"
)
CALIBRATION_ID = "sha256:e150d2a6f871075b93f3baea8726f67167670e38d9ad4a968db19e73d8df7bda"


def _scene() -> tuple[RgbdFrame, MaskCandidate, np.ndarray]:
    saved = np.load(FIXTURE)
    rgb = saved["rgb"]
    mask = saved["mask"]
    ys, xs = np.nonzero(mask)
    frame = RgbdFrame(
        sequence=28,
        monotonic_ns=11_782_870_675_244,
        camera_serial="250801DR48FP25002738",
        rgb=rgb,
        depth_m=saved["depth_m"],
        xyz_camera_m=saved["xyz_camera_m"],
    )
    candidate = MaskCandidate(
        detection_id=0,
        label="bottle",
        score=0.8247444033622742,
        bbox_xyxy=(float(xs.min()), float(ys.min()), float(xs.max() + 1), float(ys.max() + 1)),
        mask=mask,
        authorized=True,
        descriptor=masked_rgb_descriptor(rgb, mask, bins=8),
    )
    return frame, candidate, saved["t_base_camera"]


def _reference() -> tuple[RgbdFrame, MaskCandidate, np.ndarray, dict]:
    frame, candidate, transform = _scene()
    reference = create_reference(
        frame,
        candidate,
        transform,
        center_base_xyz_m=(0.449485, -0.009479, 0.119844),
        calibration_id=CALIBRATION_ID,
    )
    return frame, candidate, transform, reference


def test_real_l2_fixture_round_trips_through_json_and_passes_unchanged() -> None:
    frame, candidate, transform, reference = _reference()

    reference = json.loads(json.dumps(reference))
    result = evaluate_reference(frame, candidate, transform, reference)

    assert reference["schema"] == "thirdhand-nearfield-rgb-reference-v1"
    assert reference["center_base_xyz_m"] == [0.449485, -0.009479, 0.119844]
    assert 20 <= reference["body_point_count"] <= 2048
    assert result["rgb_observation_valid"] is True
    assert result["projection_guard_valid"] is True
    assert result["guard_blockers"] == []
    diagnostics = result["diagnostics"]
    assert diagnostics["projected_support_fraction"] >= 0.80
    assert diagnostics["center_error_px"] <= 12.0
    assert diagnostics["expected_center_camera_xyz_m"] is not None
    assert diagnostics["expected_center_uv"] is not None
    assert diagnostics["candidate_reasons"] == []
    assert diagnostics["candidate_bbox_xyxy"] == list(candidate.bbox_xyxy)
    assert diagnostics["candidate_score"] == candidate.score
    assert diagnostics["candidate_mask_area_px"] == int(candidate.mask.sum())
    assert diagnostics["reference_tracking_aspect_only_exception"] is False


def test_reference_tracking_accepts_only_the_exact_perspective_aspect_reasons() -> None:
    frame, candidate, transform, reference = _reference()
    rejected = MaskCandidate(
        detection_id=candidate.detection_id,
        label=candidate.label,
        score=0.71,
        bbox_xyxy=candidate.bbox_xyxy,
        mask=candidate.mask,
        authorized=False,
        reasons=("bottle_aspect_out_of_range", "container_type_not_bottle"),
        descriptor=candidate.descriptor,
    )

    result = evaluate_reference(frame, rejected, transform, reference)

    assert result["rgb_observation_valid"] is True
    assert result["projection_guard_valid"] is True
    assert result["guard_blockers"] == []
    assert result["diagnostics"]["reference_tracking_aspect_only_exception"] is True
    assert result["diagnostics"]["candidate_reasons"] == [
        "bottle_aspect_out_of_range",
        "container_type_not_bottle",
    ]
    assert result["diagnostics"]["candidate_bbox_xyxy"] == list(candidate.bbox_xyxy)
    assert result["diagnostics"]["candidate_score"] == 0.71
    assert result["diagnostics"]["candidate_mask_area_px"] == int(candidate.mask.sum())


def test_any_extra_rejection_reason_still_blocks_reference_tracking() -> None:
    frame, candidate, transform, reference = _reference()
    rejected = MaskCandidate(
        detection_id=candidate.detection_id,
        label=candidate.label,
        score=candidate.score,
        bbox_xyxy=candidate.bbox_xyxy,
        mask=candidate.mask,
        authorized=False,
        reasons=(
            "bottle_aspect_out_of_range",
            "container_type_not_bottle",
            "mask_too_small",
        ),
        descriptor=candidate.descriptor,
    )

    result = evaluate_reference(frame, rejected, transform, reference)

    assert result["rgb_observation_valid"] is False
    assert result["projection_guard_valid"] is False
    assert "candidate_not_authorized" in result["guard_blockers"]
    assert result["diagnostics"]["reference_tracking_aspect_only_exception"] is False


def test_unauthorized_candidate_cannot_create_initial_reference() -> None:
    frame, candidate, transform = _scene()
    rejected = MaskCandidate(
        detection_id=candidate.detection_id,
        label=candidate.label,
        score=candidate.score,
        bbox_xyxy=candidate.bbox_xyxy,
        mask=candidate.mask,
        authorized=False,
        reasons=("bottle_aspect_out_of_range", "container_type_not_bottle"),
        descriptor=candidate.descriptor,
    )

    with np.testing.assert_raises_regex(ValueError, "authorized"):
        create_reference(
            frame,
            rejected,
            transform,
            center_base_xyz_m=(0.449485, -0.009479, 0.119844),
            calibration_id=CALIBRATION_ID,
        )


def test_motion_without_pose_keeps_rgb_identity_but_fails_projection() -> None:
    frame, candidate, _transform, reference = _reference()

    result = evaluate_reference(frame, candidate, None, reference)

    assert result["rgb_observation_valid"] is True
    assert result["projection_guard_valid"] is False
    assert result["guard_blockers"] == ["pose_unavailable"]
    assert result["diagnostics"]["expected_center_camera_xyz_m"] is None
    assert result["diagnostics"]["expected_center_uv"] is None


def test_evaluation_uses_rgb_and_frozen_anchor_without_current_depth() -> None:
    frame, candidate, transform, reference = _reference()
    no_depth = RgbdFrame(
        sequence=frame.sequence + 1,
        monotonic_ns=frame.monotonic_ns + 1,
        camera_serial=frame.camera_serial,
        rgb=frame.rgb,
        depth_m=np.full_like(frame.depth_m, np.nan),
        xyz_camera_m=np.full_like(frame.xyz_camera_m, np.nan),
    )

    result = evaluate_reference(no_depth, candidate, transform, reference)

    assert result["rgb_observation_valid"] is True
    assert result["projection_guard_valid"] is True
    assert result["guard_blockers"] == []


def test_target_loss_fails_rgb_and_projection() -> None:
    frame, _candidate, transform, reference = _reference()

    result = evaluate_reference(frame, None, transform, reference)

    assert result["rgb_observation_valid"] is False
    assert result["projection_guard_valid"] is False
    assert result["guard_blockers"] == ["target_lost"]
    assert result["diagnostics"]["reference_tracking_aspect_only_exception"] is False


def test_wrong_detection_id_fails_closed() -> None:
    frame, candidate, transform, reference = _reference()
    wrong = MaskCandidate(
        detection_id=7,
        label=candidate.label,
        score=candidate.score,
        bbox_xyxy=candidate.bbox_xyxy,
        mask=candidate.mask,
        authorized=True,
        descriptor=candidate.descriptor,
    )

    result = evaluate_reference(frame, wrong, transform, reference)

    assert result["rgb_observation_valid"] is False
    assert result["projection_guard_valid"] is False
    assert "target_id_mismatch" in result["guard_blockers"]


def test_twenty_millimetre_anchor_translation_rejects_unchanged_mask() -> None:
    frame, candidate, transform, reference = _reference()

    result = evaluate_reference(
        frame,
        candidate,
        transform,
        reference,
        expected_translation_m=(0.0, 0.020, 0.0),
    )

    assert result["rgb_observation_valid"] is True
    assert result["projection_guard_valid"] is False
    assert any(
        blocker in result["guard_blockers"]
        for blocker in ("projected_position_mismatch", "projected_support_mismatch")
    )


def test_width_ratio_is_diagnostic_only_and_cannot_reject_matching_position() -> None:
    frame, candidate, transform, reference = _reference()
    reference["reference_mask_to_body_width_ratio"] *= 0.70

    result = evaluate_reference(frame, candidate, transform, reference)

    assert result["diagnostics"]["width_ratio"] > 1.15
    assert result["diagnostics"]["width_ratio_diagnostic_only"] is True
    assert result["diagnostics"]["width_ratio_outside_reference_tolerance"] is True
    assert "projected_width_mismatch" not in result["guard_blockers"]
    assert result["projection_guard_valid"] is True


def test_reference_points_behind_camera_are_not_visible() -> None:
    frame, candidate, transform, reference = _reference()
    behind = transform.copy()
    behind[:3, 3] += transform[:3, 2] * 0.50

    result = evaluate_reference(frame, candidate, behind, reference)

    assert result["projection_guard_valid"] is False
    assert "projected_target_out_of_view" in result["guard_blockers"]
    assert result["diagnostics"]["projected_visible_fraction"] == 0.0


def test_partially_clipped_reference_fails_closed() -> None:
    frame, candidate, transform, reference = _reference()
    camera_x_in_base = transform[:3, 0]

    result = evaluate_reference(
        frame,
        candidate,
        transform,
        reference,
        expected_translation_m=(camera_x_in_base * 3.20).tolist(),
    )

    visible = result["diagnostics"]["projected_visible_fraction"]
    assert 20 / reference["body_point_count"] < visible < 0.65
    assert result["projection_guard_valid"] is False
    assert "projected_target_clipped" in result["guard_blockers"]


def test_nonproduction_rgb_grid_is_rejected_before_projection() -> None:
    frame, candidate, transform, reference = _reference()
    small_frame = RgbdFrame(
        sequence=frame.sequence,
        monotonic_ns=frame.monotonic_ns,
        camera_serial=frame.camera_serial,
        rgb=np.zeros((240, 320, 3), dtype=np.uint8),
        depth_m=np.full((240, 320), np.nan, dtype=np.float32),
        xyz_camera_m=np.full((240, 320, 3), np.nan, dtype=np.float32),
    )
    small_candidate = MaskCandidate(
        detection_id=candidate.detection_id,
        label=candidate.label,
        score=candidate.score,
        bbox_xyxy=(0, 0, 1, 1),
        mask=np.zeros((240, 320), dtype=bool),
        authorized=True,
        descriptor=candidate.descriptor,
    )

    with np.testing.assert_raises_regex(ValueError, "640x480"):
        evaluate_reference(small_frame, small_candidate, transform, reference)


def test_empty_mask_and_appearance_conflict_fail_rgb() -> None:
    frame, candidate, transform, reference = _reference()
    empty = MaskCandidate(
        detection_id=candidate.detection_id,
        label=candidate.label,
        score=candidate.score,
        bbox_xyxy=candidate.bbox_xyxy,
        mask=np.zeros_like(candidate.mask),
        authorized=True,
        descriptor=candidate.descriptor,
    )
    conflicting = MaskCandidate(
        detection_id=candidate.detection_id,
        label=candidate.label,
        score=candidate.score,
        bbox_xyxy=candidate.bbox_xyxy,
        mask=candidate.mask,
        authorized=True,
        descriptor=-candidate.descriptor,
    )

    empty_result = evaluate_reference(frame, empty, transform, reference)
    conflict_result = evaluate_reference(frame, conflicting, transform, reference)

    assert "mask_empty" in empty_result["guard_blockers"]
    assert "appearance_mismatch" in conflict_result["guard_blockers"]
    assert empty_result["rgb_observation_valid"] is False
    assert conflict_result["rgb_observation_valid"] is False
