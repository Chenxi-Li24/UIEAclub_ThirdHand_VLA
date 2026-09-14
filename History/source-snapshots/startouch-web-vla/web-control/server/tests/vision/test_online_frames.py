from __future__ import annotations

import numpy as np
import pytest

from vision.online_frames import (
    CameraRoleMap,
    DepthFrame,
    LatestFramePairer,
    RgbFrame,
)
from vision.types import FrameStamp, InvalidDataError


def test_current_roles_report_excessive_rgb_depth_skew() -> None:
    roles = CameraRoleMap(
        canonical_rgb_source="lumos_rgb",
        metric_depth_source="d435_depth",
        debug_rgb_source="d435_rgb",
        fusion_mode="cross_camera",
    )
    pairer = LatestFramePairer(
        roles=roles,
        max_frame_skew_ns=50_000_000,
        max_frame_age_ns=200_000_000,
    )
    rgb = RgbFrame(
        stamp=FrameStamp("lumos_rgb", 4, 1_000_000_000),
        image_rgb=np.zeros((5, 5, 3), dtype=np.uint8),
    )
    depth = DepthFrame(
        stamp=FrameStamp("d435_depth", 9, 1_070_000_000),
        depth_z_m=np.ones((5, 5), dtype=float),
    )

    pair = pairer.pair(rgb=rgb, depth=depth, now_ns=1_080_000_000)

    assert pair.rgb is rgb
    assert pair.depth is depth
    assert pair.frame_skew_ns == 70_000_000
    assert pair.reasons == ("frame_skew_exceeded",)


def test_pairer_reports_stale_rgb_and_missing_depth_without_inventing_stamp() -> None:
    roles = CameraRoleMap("lumos_rgb", "d435_depth", "d435_rgb", "cross_camera")
    rgb = RgbFrame(
        FrameStamp("lumos_rgb", 2, 1_000_000_000),
        np.zeros((3, 4, 3), dtype=np.uint8),
    )

    pair = LatestFramePairer(roles, 50_000_000, 200_000_000).pair(
        rgb=rgb,
        depth=None,
        now_ns=1_300_000_000,
    )

    assert pair.depth is None
    assert pair.frame_skew_ns is None
    assert pair.fusion_monotonic_ns == 1_000_000_000
    assert pair.reasons == ("depth_unavailable", "camera_frames_stale")


def test_native_aligned_roles_accept_distinct_streams_from_one_device() -> None:
    roles = CameraRoleMap(
        "fisheye_rgbd_rgb",
        "fisheye_rgbd_depth",
        None,
        "native_aligned",
    )
    pairer = LatestFramePairer(roles, 1_000_000, 10_000_000)
    rgb = RgbFrame(
        FrameStamp("fisheye_rgbd_rgb", 11, 4_000_000_000),
        np.zeros((2, 2, 3), dtype=np.uint8),
    )
    depth = DepthFrame(
        FrameStamp("fisheye_rgbd_depth", 11, 4_000_000_000),
        np.full((2, 2), 0.4),
    )

    pair = pairer.pair(rgb, depth, 4_005_000_000)

    assert pair.frame_skew_ns == 0
    assert pair.reasons == ()


def test_frames_copy_arrays_and_reject_wrong_role_or_future_time() -> None:
    source = np.zeros((2, 3, 3), dtype=np.uint8)
    frame = RgbFrame(FrameStamp("lumos_rgb", 1, 100), source)
    source[0, 0] = 255
    assert frame.image_rgb[0, 0].tolist() == [0, 0, 0]
    assert not frame.image_rgb.flags.writeable

    roles = CameraRoleMap("lumos_rgb", "d435_depth", "d435_rgb", "cross_camera")
    wrong = RgbFrame(FrameStamp("d435_rgb", 1, 100), np.zeros((2, 2, 3), np.uint8))
    with pytest.raises(InvalidDataError, match="canonical RGB source"):
        LatestFramePairer(roles, 50, 200).pair(wrong, None, 150)
    with pytest.raises(InvalidDataError, match="future"):
        LatestFramePairer(roles, 50, 200).pair(frame, None, 99)


@pytest.mark.parametrize(
    "value",
    [
        np.zeros((2, 2), dtype=np.uint8),
        np.zeros((2, 2, 4), dtype=np.uint8),
        np.zeros((0, 2, 3), dtype=np.uint8),
    ],
)
def test_rgb_frame_rejects_non_rgb_layout(value: np.ndarray) -> None:
    with pytest.raises(InvalidDataError, match="RGB image"):
        RgbFrame(FrameStamp("lumos_rgb", 1, 100), value)


def test_depth_frame_preserves_zero_and_nan_as_invalid_measurements() -> None:
    depth = np.array([[0.0, np.nan], [0.4, 0.5]], dtype=float)
    frame = DepthFrame(FrameStamp("d435_depth", 3, 100), depth)
    assert frame.depth_z_m[0, 0] == 0.0
    assert np.isnan(frame.depth_z_m[0, 1])
    assert not frame.depth_z_m.flags.writeable


def test_pairer_rejects_replayed_or_backward_rgb_provenance() -> None:
    roles = CameraRoleMap("lumos_rgb", "d435_depth", "d435_rgb", "cross_camera")
    pairer = LatestFramePairer(roles, 50, 200)
    first = RgbFrame(
        FrameStamp("lumos_rgb", 5, 100),
        np.zeros((2, 2, 3), dtype=np.uint8),
    )
    pairer.pair(first, None, 100)

    replayed = RgbFrame(
        FrameStamp("lumos_rgb", 5, 101),
        np.zeros((2, 2, 3), dtype=np.uint8),
    )
    with pytest.raises(InvalidDataError, match="strictly advance"):
        pairer.pair(replayed, None, 101)

    backward_time = RgbFrame(
        FrameStamp("lumos_rgb", 6, 99),
        np.zeros((2, 2, 3), dtype=np.uint8),
    )
    with pytest.raises(InvalidDataError, match="strictly advance"):
        pairer.pair(backward_time, None, 101)
