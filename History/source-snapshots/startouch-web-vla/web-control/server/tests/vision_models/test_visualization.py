from __future__ import annotations

from types import SimpleNamespace

import cv2
import numpy as np
from vision_models.visualization import build_target_visual, render_target_visuals


def annotation() -> SimpleNamespace:
    mask = np.zeros((80, 120), dtype=bool)
    mask[20:61, 30:91] = True
    return SimpleNamespace(
        detection_id=7,
        label="bottle",
        score=0.95,
        bbox_xyxy=np.array([30.0, 20.0, 91.0, 61.0]),
        mask=mask,
    )


def target(*, actionable: bool = True, pose: object | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        detection_id=7,
        identity_id=12,
        identity_status=SimpleNamespace(value="confirmed"),
        pose=pose,
        registered_depth_points=184,
        actionable=actionable,
        reasons=() if actionable else ("depth_samples_unstable",),
    )


def pose() -> SimpleNamespace:
    return SimpleNamespace(
        xyz_m=np.array([0.342, -0.118, 0.041]),
        covariance_m2=np.diag([0.000004, 0.000009, 0.000016]),
    )


def test_target_visual_contains_contour_id_3d_state_grasp_point_and_permission() -> None:
    visual = build_target_visual(
        annotation(),
        target(pose=pose()),
        grasp_point_px=(63, 44),
        grasp_execution_enabled=True,
    )

    assert visual.identity_id == 12
    assert visual.anchor_px == (60, 40)
    assert visual.grasp_point_px == (63, 44)
    assert visual.grasp_allowed is True
    assert visual.lines == (
        "ID#12 bottle 0.95 | confirmed",
        "XYZ +0.342 -0.118 +0.041 m | sigma<=4.0 mm",
        "DEPTH 184 | GRASP POINT 63,44",
        "GRASP YES",
    )


def test_target_visual_fails_closed_without_execution_gate_or_grasp_preview() -> None:
    locked = build_target_visual(
        annotation(),
        target(pose=pose()),
        grasp_point_px=(63, 44),
        grasp_execution_enabled=False,
    )
    missing_preview = build_target_visual(
        annotation(),
        target(pose=pose()),
        grasp_point_px=None,
        grasp_execution_enabled=True,
    )

    assert locked.grasp_allowed is False
    assert locked.lines[-1] == "GRASP NO | execution_locked"
    assert missing_preview.grasp_allowed is False
    assert missing_preview.lines[-1] == "GRASP NO | grasp_preview_unavailable"


def test_renderer_keeps_native_frame_and_draws_contour_and_requested_labels(monkeypatch) -> None:
    source = np.zeros((80, 120, 3), dtype=np.uint8)
    visual = build_target_visual(
        annotation(),
        target(actionable=False),
        grasp_execution_enabled=False,
    )
    labels: list[str] = []
    original_put_text = cv2.putText

    def recording_put_text(image, text, *args, **kwargs):
        labels.append(text)
        return original_put_text(image, text, *args, **kwargs)

    monkeypatch.setattr(cv2, "putText", recording_put_text)

    rendered = render_target_visuals(source, (visual,), model_ready=True)

    assert rendered.shape == source.shape
    assert rendered.dtype == np.uint8
    assert not np.shares_memory(rendered, source)
    assert np.count_nonzero(rendered) > 0
    assert any(label.startswith("ID#12 bottle") for label in labels)
    assert "XYZ --" in labels
    assert "DEPTH 184 | GRASP POINT --" in labels
    assert "GRASP NO | depth_samples_unstable" in labels


def test_renderer_stacks_dense_target_callouts_without_text_overlap(monkeypatch) -> None:
    source = np.zeros((240, 320, 3), dtype=np.uint8)
    visuals = []
    for detection_id, x_offset in enumerate((0, 16, 32), start=1):
        mask = np.zeros(source.shape[:2], dtype=bool)
        mask[100:141, 80 + x_offset : 121 + x_offset] = True
        candidate_annotation = SimpleNamespace(
            detection_id=detection_id,
            label="bottle",
            score=0.9,
            bbox_xyxy=np.array([80 + x_offset, 100, 121 + x_offset, 141], dtype=float),
            mask=mask,
        )
        candidate_target = SimpleNamespace(
            detection_id=detection_id,
            identity_id=detection_id,
            identity_status=SimpleNamespace(value="confirmed"),
            pose=None,
            registered_depth_points=0,
            actionable=False,
            reasons=("depth_pending",),
        )
        visuals.append(build_target_visual(candidate_annotation, candidate_target))

    id_label_origins: list[tuple[int, int]] = []
    original_put_text = cv2.putText

    def recording_put_text(image, label, origin, *args, **kwargs):
        if label.startswith("ID#"):
            id_label_origins.append(origin)
        return original_put_text(image, label, origin, *args, **kwargs)

    monkeypatch.setattr(cv2, "putText", recording_put_text)

    rendered = render_target_visuals(source, visuals, model_ready=True)

    assert rendered.shape == source.shape
    assert len(id_label_origins) == 3
    ordered_y = sorted(origin[1] for origin in id_label_origins)
    assert all(right - left >= 52 for left, right in zip(ordered_y, ordered_y[1:]))
