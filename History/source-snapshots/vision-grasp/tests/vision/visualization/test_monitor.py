from __future__ import annotations

import numpy as np
import pytest

from thirdhand_va.vision.visualization.monitor import (
    MonitorFrame,
    compose_monitor_frame,
    render_monitor_notice,
)


def test_monitor_compositor_blends_depth_only_on_colored_valid_pixels() -> None:
    algorithm = np.full((140, 240, 3), 100, np.uint8)
    depth = np.zeros_like(algorithm)
    depth[60:100, 80:120] = (255, 0, 0)
    original_algorithm = algorithm.copy()
    original_depth = depth.copy()

    result = compose_monitor_frame(
        algorithm,
        depth,
        frame_id=42,
        alpha=0.40,
        valid_threshold=12,
    )

    assert np.array_equal(algorithm, original_algorithm)
    assert np.array_equal(depth, original_depth)
    assert result.image_rgb.shape == algorithm.shape
    assert result.image_rgb[80, 100].tolist() == [162, 60, 60]
    assert result.image_rgb[80, 160].tolist() == [100, 100, 100]
    assert result.valid_pixels == 1_600
    assert result.valid_ratio == pytest.approx(1_600 / (140 * 240))
    assert result.frame_id == 42
    assert np.any(result.image_rgb[:36, -180:] != algorithm[:36, -180:])


def test_monitor_compositor_keeps_hardware_depth_roi_fixed_when_pixels_move() -> None:
    algorithm = np.full((140, 240, 3), 100, np.uint8)
    left_depth = np.zeros_like(algorithm)
    left_depth[50:90, 70:110] = (255, 0, 0)
    right_depth = np.zeros_like(algorithm)
    right_depth[60:100, 140:170] = (0, 255, 0)

    left_result = compose_monitor_frame(
        algorithm,
        left_depth,
        frame_id=43,
        alpha=0.35,
        depth_roi_xyxy=(48, 28, 191, 111),
    )
    right_result = compose_monitor_frame(
        algorithm,
        right_depth,
        frame_id=44,
        alpha=0.35,
        depth_roi_xyxy=(48, 28, 191, 111),
    )

    assert left_result.depth_roi_xyxy == (48, 28, 191, 111)
    assert right_result.depth_roi_xyxy == (48, 28, 191, 111)
    assert left_result.image_rgb[28, 120].tolist() == [255, 255, 0]
    assert right_result.image_rgb[111, 120].tolist() == [255, 255, 0]


def test_monitor_compositor_keeps_hardware_depth_roi_visible_when_blending_is_off() -> None:
    algorithm = np.full((140, 240, 3), 100, np.uint8)
    depth = np.zeros_like(algorithm)
    depth[50:100, 70:170] = (255, 0, 0)

    result = compose_monitor_frame(
        algorithm,
        depth,
        frame_id=44,
        alpha=0.0,
        depth_roi_xyxy=(48, 28, 191, 111),
    )

    assert result.depth_roi_xyxy == (48, 28, 191, 111)
    assert result.image_rgb[28, 120].tolist() == [255, 255, 0]
    assert result.image_rgb[70, 120].tolist() == [100, 100, 100]


def test_monitor_frame_preserves_the_previous_constructor_contract() -> None:
    image = np.zeros((10, 10, 3), np.uint8)

    frame = MonitorFrame(
        image_rgb=image,
        frame_id=1,
        valid_pixels=0,
        valid_ratio=0.0,
    )

    assert frame.depth_roi_xyxy is None


def test_monitor_compositor_rejects_mismatched_registered_depth_size() -> None:
    algorithm = np.zeros((120, 160, 3), np.uint8)
    depth = np.zeros((60, 80, 3), np.uint8)

    with pytest.raises(ValueError, match="registered depth heatmap"):
        compose_monitor_frame(algorithm, depth, frame_id=9)


def test_monitor_notice_keeps_camera_visible_when_depth_is_waiting() -> None:
    algorithm = np.full((120, 180, 3), 90, np.uint8)
    original = algorithm.copy()

    rendered = render_monitor_notice(
        algorithm,
        frame_id=15,
        detail="DEPTH WAITING",
    )

    assert np.array_equal(algorithm, original)
    assert rendered.shape == algorithm.shape
    assert np.array_equal(rendered[50, 90], algorithm[50, 90])
    assert np.any(rendered[-30:] != algorithm[-30:])
