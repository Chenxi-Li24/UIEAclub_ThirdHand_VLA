"""Opt-in smoke test for the deployed XVisio depth MJPEG endpoint."""

from __future__ import annotations

import os
from urllib.request import urlopen

import pytest


@pytest.mark.skipif(
    os.environ.get("THIRDHAND_LIVE_TEST") != "1",
    reason="requires the locally running ThirdHand control service",
)
def test_live_depth_endpoint_returns_mjpeg_frame() -> None:
    """Removing the route or depth pipe must turn this into 404/503/timeout."""
    base_url = os.environ.get("THIRDHAND_VA_URL", "http://127.0.0.1:8766")
    with urlopen(f"{base_url}/camera_xvisio_depth", timeout=5) as response:
        assert response.status == 200
        assert response.headers["Content-Type"] == (
            "multipart/x-mixed-replace; boundary=frame"
        )
        assert response.read(9) == b"--frame\r\n"
