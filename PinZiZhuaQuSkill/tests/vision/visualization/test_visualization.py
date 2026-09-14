from dataclasses import replace

import numpy as np

from thirdhand_va.common.contracts import (
    GraspPoseCamera,
    MaskCandidate,
    TrackedBottle,
    VisionDecision,
)
from thirdhand_va.vision.visualization import (
    RenderMetrics,
    add_depth_legend,
    encode_jpeg,
    render_depth_heatmap,
    render_overlay,
)


def candidate(detection_id: int, x0: int, selected: bool = False) -> MaskCandidate:
    mask = np.zeros((120, 240), dtype=bool)
    mask[30:105, x0 : x0 + 35] = True
    return MaskCandidate(
        detection_id=detection_id,
        label="bottle",
        score=0.9,
        bbox_xyxy=(x0, 30, x0 + 35, 105),
        mask=mask,
        authorized=True,
    )


def ready_decision() -> VisionDecision:
    items = (candidate(1, 20), candidate(2, 100), candidate(3, 180))
    pose = GraspPoseCamera(
        point_m=(0.0, 0.0, 0.45),
        axis=(0.0, 1.0, 0.0),
        approach=(0.0, 0.0, 1.0),
        width_m=0.06,
        position_std_m=(0.001, 0.001, 0.002),
        valid_points=1200,
        depth_valid_ratio=0.87,
    )
    tracks = tuple(
        TrackedBottle(
            stable_id=index,
            backend_track_id=100 + index,
            state="confirmed",
            candidate=item,
            centroid_xy=(x, 67.0),
            depth_supported=True,
        )
        for index, (item, x) in enumerate(
            zip(items, (37.0, 117.0, 197.0)), start=1
        )
    )
    return VisionDecision(
        status="ready",
        frame_id=8,
        target=items[1],
        pose=pose,
        stable_hits=4,
        window_size=5,
        candidates=items,
        request_id="req-2",
        selected_stable_id=2,
        tracks=tracks,
        captured_monotonic_ns=800,
        camera_serial="250801DR48FP25002738",
        registration_id="xvisio-sdk:250801DR48FP25002738",
        motion_epoch=0,
        evidence_id="sha256:" + "a" * 64,
    )


def test_overlay_visualizes_masks_ranks_selection_and_status() -> None:
    rgb = np.zeros((120, 240, 3), dtype=np.uint8)
    decision = ready_decision()

    rendered = render_overlay(
        rgb, decision, RenderMetrics(fps=12.5, latency_ms=41.0)
    )

    assert rendered.image.shape == rgb.shape
    assert np.any(rendered.image[decision.target.mask] != rgb[decision.target.mask])
    assert {"1", "2", "3"}.issubset(rendered.labels)
    assert "SELECT 2" in rendered.labels
    assert "READY 4/5" in rendered.labels
    assert "robot_control_enabled=false" in rendered.labels
    assert "hardware_validation_pending" in rendered.labels
    assert rendered.panel_lines == (
        "SELECT 2 | READY 4/5",
        "DEPTH 0.450 m 87% | FPS 12.5 | 41.0 ms",
        "robot_control_enabled=false",
        "hardware_validation_pending",
    )
    assert encode_jpeg(rendered.image).startswith(b"\xff\xd8")


def test_rejected_overlay_never_carries_stale_ready_label() -> None:
    previous = ready_decision()
    rejected = VisionDecision(
        status="rejected",
        frame_id=9,
        target=None,
        pose=None,
        reasons=("target_track_lost",),
        stable_hits=0,
        window_size=5,
        candidates=previous.candidates,
        request_id="req-2",
        selected_stable_id=2,
        tracks=previous.tracks,
        captured_monotonic_ns=900,
        camera_serial=previous.camera_serial,
        registration_id=previous.registration_id,
        motion_epoch=0,
        evidence_id="sha256:" + "b" * 64,
    )

    rendered = render_overlay(
        np.zeros((120, 240, 3), dtype=np.uint8),
        rejected,
        RenderMetrics(fps=8.0, latency_ms=70.0),
    )

    assert not any(label.startswith("READY") for label in rendered.labels)
    assert "BLOCKED target_track_lost" in rendered.labels


def test_overlay_reports_detector_and_segmenter_latency() -> None:
    rendered = render_overlay(
        np.zeros((120, 240, 3), dtype=np.uint8),
        ready_decision(),
        RenderMetrics(
            fps=4.0,
            latency_ms=240.0,
            dino_ms=95.5,
            sam_ms=132.25,
        ),
    )

    assert "DINO 95.5 ms | SAM2 132.2 ms" in rendered.panel_lines


def test_depth_heatmap_marks_metric_depth_and_blacks_invalid_pixels() -> None:
    depth = np.array([[np.nan, 0.2], [0.6, 1.0]], dtype=np.float32)

    heatmap = render_depth_heatmap(depth, min_depth_m=0.15, max_depth_m=1.2)

    assert heatmap.shape == (2, 2, 3)
    assert heatmap[0, 0].tolist() == [0, 0, 0]
    assert heatmap[0, 1].tolist() != heatmap[1, 1].tolist()


def test_depth_legend_leaves_images_that_are_too_narrow_unchanged() -> None:
    rgb = np.full((40, 80, 3), 24, dtype=np.uint8)

    rendered = add_depth_legend(
        rgb,
        min_depth_m=0.15,
        max_depth_m=1.2,
    )

    np.testing.assert_array_equal(rendered, rgb)


def test_overlay_fuses_registered_depth_without_hiding_rgb_visual_tracking() -> None:
    rgb = np.full((120, 240, 3), 24, dtype=np.uint8)
    depth = np.full((120, 240), np.nan, dtype=np.float32)
    depth[10:115, 10:230] = 0.55

    rendered = render_overlay(
        rgb,
        ready_decision(),
        RenderMetrics(fps=8.0, latency_ms=90.0),
        depth_m=depth,
        min_depth_m=0.15,
        max_depth_m=1.2,
        depth_alpha=0.30,
    )

    # Valid registered depth is visibly blended into the RGB image while an
    # invalid pixel outside the ROI stays as the original RGB value.
    assert rendered.image[110, 15].tolist() != rgb[110, 15].tolist()
    assert rendered.image[110, 5].tolist() == rgb[110, 5].tolist()
    assert "DEPTH ROI" in rendered.labels
    assert {"1", "2", "3"}.issubset(rendered.labels)


def test_overlay_default_makes_depth_visible_inside_candidate_masks() -> None:
    rgb = np.full((120, 240, 3), 48, dtype=np.uint8)
    depth = np.full((120, 240), np.nan, dtype=np.float32)
    depth[20:110, 10:230] = 0.55
    decision = ready_decision()

    without_depth = render_overlay(
        rgb,
        decision,
        RenderMetrics(fps=8.0, latency_ms=90.0),
    )
    with_depth = render_overlay(
        rgb,
        decision,
        RenderMetrics(fps=8.0, latency_ms=90.0),
        depth_m=depth,
        min_depth_m=0.15,
        max_depth_m=1.2,
    )

    # This point is inside candidate 1 but away from its contour and rank text.
    pixel = (85, 29)
    depth_contrast = np.linalg.norm(
        with_depth.image[pixel].astype(np.float32)
        - without_depth.image[pixel].astype(np.float32)
    )
    assert depth_contrast >= 100.0
    assert "DEPTH LEGEND" in with_depth.labels


def test_candidate_tint_does_not_overpower_the_depth_layer() -> None:
    rgb = np.full((120, 240, 3), 48, dtype=np.uint8)
    depth = np.full((120, 240), np.nan, dtype=np.float32)
    depth[20:110, 10:230] = 0.55
    decision = ready_decision()
    depth_only_decision = replace(
        decision,
        status="searching",
        target=None,
        pose=None,
        stable_hits=0,
        tracks=(),
        candidates=(),
    )

    depth_only = render_overlay(
        rgb,
        depth_only_decision,
        RenderMetrics(fps=8.0, latency_ms=90.0),
        depth_m=depth,
        min_depth_m=0.15,
        max_depth_m=1.2,
    )
    with_candidates = render_overlay(
        rgb,
        decision,
        RenderMetrics(fps=8.0, latency_ms=90.0),
        depth_m=depth,
        min_depth_m=0.15,
        max_depth_m=1.2,
    )

    pixel = (85, 29)
    tint_delta = np.linalg.norm(
        with_candidates.image[pixel].astype(np.float32)
        - depth_only.image[pixel].astype(np.float32)
    )
    assert tint_delta <= 60.0


def test_overlay_marks_blocked_tracks_without_renumbering() -> None:
    base = ready_decision()
    blocked_track = replace(
        base.tracks[1],
        depth_supported=False,
        blockers=("depth_insufficient",),
    )
    decision = replace(
        base,
        status="uncertain",
        target=blocked_track.candidate,
        pose=None,
        reasons=("depth_insufficient",),
        tracks=(base.tracks[0], blocked_track, base.tracks[2]),
    )

    rendered = render_overlay(
        np.zeros((120, 240, 3), dtype=np.uint8),
        decision,
        RenderMetrics(fps=8.0, latency_ms=60.0),
    )

    assert {"1", "2 BLOCKED depth_insufficient", "3"} <= rendered.labels
