from __future__ import annotations

from http.server import ThreadingHTTPServer
import threading
import urllib.request
from pathlib import Path

import cv2
import numpy as np
import pytest

from lumos_http_server import decode_lumos_frame, discover_lumos_device, make_handler


def test_device_discovery_uses_xvisio_capture_interface_after_uvc_reenumeration(tmp_path):
    sys_class = tmp_path / "video4linux"
    dev_root = tmp_path / "dev"
    sys_class.mkdir()
    dev_root.mkdir()
    for name, product, index in (
        ("video0", "Intel(R) RealSense(TM) Depth Camera 435", "0"),
        ("video6", "XVisio vSLAM: XVisio vSLAM", "0"),
        ("video7", "XVisio vSLAM: XVisio vSLAM", "1"),
    ):
        entry = sys_class / name
        entry.mkdir()
        (entry / "name").write_text(product, encoding="utf-8")
        (entry / "index").write_text(index, encoding="utf-8")
        (dev_root / name).touch()

    assert discover_lumos_device(sys_class, dev_root) == str(dev_root / "video6")


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


def test_snapshot_endpoint_returns_jpeg_with_exact_capture_provenance():
    image = np.zeros((8, 8, 3), dtype=np.uint8)
    image[:, :, 1] = 180
    encoded, jpeg = cv2.imencode(".jpg", image)
    assert encoded

    class FakeCapture:
        running = True
        def wait_for_snapshot(self, after_sequence, timeout):
            assert after_sequence == -1
            assert timeout == 5.0
            return jpeg.tobytes(), 7, 123_000_000

        def status(self):
            return {"ready": True, "sequence": 7}

    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(FakeCapture()))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{server.server_port}/frame.jpg",
            timeout=2.0,
        ) as response:
            body = response.read()
            assert response.status == 200
            assert response.headers.get_content_type() == "image/jpeg"
            assert response.headers["X-Lumos-Sequence"] == "7"
            assert response.headers["X-Lumos-Monotonic-Ns"] == "123000000"
            assert body == jpeg.tobytes()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2.0)
