from __future__ import annotations

import os

import pytest

from thirdhand_va.vision.preview import OpenCvMjpegSource


@pytest.mark.skipif(
    os.environ.get("THIRDHAND_LIVE_TEST") != "1",
    reason="set THIRDHAND_LIVE_TEST=1 to use the existing read-only stream",
)
def test_live_fused_preview_reads_three_fresh_frames() -> None:
    base_url = os.environ.get("THIRDHAND_VA_URL", "http://127.0.0.1:8766")
    source = OpenCvMjpegSource(
        f"{base_url}/camera_lumos_vision",
        name="live-fused-test",
        open_timeout_ms=1_500,
        read_timeout_ms=1_500,
    )
    source.open()
    try:
        frames = [source.read() for _ in range(3)]
    finally:
        source.close()

    assert all(frame.image_rgb.shape == (480, 640, 3) for frame in frames)
    assert frames[0].received_monotonic_ns < frames[-1].received_monotonic_ns
