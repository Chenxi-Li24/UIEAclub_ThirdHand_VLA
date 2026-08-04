from __future__ import annotations

import numpy as np
import pytest

from lumos_http_server import decode_lumos_frame


def test_decode_accepts_already_converted_bgr_frame():
    frame = np.zeros((12, 16, 3), dtype=np.uint8)
    frame[:, :, 1] = 127
    decoded = decode_lumos_frame(frame, width=16, height=12)
    np.testing.assert_array_equal(decoded, frame)
    assert decoded is not frame


def test_decode_converts_i420_buffer_to_bgr():
    import cv2

    source = np.zeros((12, 16, 3), dtype=np.uint8)
    source[:, :, 0] = 40
    source[:, :, 1] = 100
    source[:, :, 2] = 180
    i420 = cv2.cvtColor(source, cv2.COLOR_BGR2YUV_I420)
    decoded = decode_lumos_frame(i420, width=16, height=12)
    assert decoded.shape == source.shape
    assert np.abs(decoded.astype(int) - source.astype(int)).mean() < 4.0


@pytest.mark.parametrize(
    "frame",
    [
        np.zeros((12, 16), dtype=np.uint8),
        np.zeros((18, 15), dtype=np.uint8),
        np.zeros((12, 16, 4), dtype=np.uint8),
    ],
)
def test_decode_rejects_unexpected_frame_layout(frame):
    with pytest.raises(ValueError, match="unexpected Lumos frame layout"):
        decode_lumos_frame(frame, width=16, height=12)
