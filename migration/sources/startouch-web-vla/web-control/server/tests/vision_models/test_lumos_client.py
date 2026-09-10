from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading

import cv2
import numpy as np
import pytest

from vision.types import FrameStamp
from vision_models.contracts import ModelContractError
from vision_models.lumos_client import LumosSnapshotClient


def jpeg_bytes() -> bytes:
    bgr = np.zeros((8, 8, 3), dtype=np.uint8)
    bgr[:, :, 2] = 200
    encoded, jpeg = cv2.imencode(".jpg", bgr)
    assert encoded
    return jpeg.tobytes()


def serve(headers: dict[str, str], body: bytes, status: int = 200):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            self.send_response(status)
            for name, value in headers.items():
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def test_client_decodes_rgb_and_preserves_server_provenance() -> None:
    body = jpeg_bytes()
    server, thread = serve(
        {
            "Content-Type": "image/jpeg",
            "X-Lumos-Sequence": "7",
            "X-Lumos-Monotonic-Ns": "123000000",
        },
        body,
    )
    try:
        client = LumosSnapshotClient(
            f"http://127.0.0.1:{server.server_port}/frame.jpg",
            timeout_s=1.0,
        )
        frame = client.read(after_sequence=6)
        assert frame is not None
        assert frame.stamp == FrameStamp("lumos_rgb", 7, 123_000_000)
        assert frame.image_rgb.shape == (8, 8, 3)
        assert float(frame.image_rgb[:, :, 0].mean()) > 190.0
        assert client.read(after_sequence=7) is None
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2.0)


def test_client_rejects_missing_provenance_headers() -> None:
    body = jpeg_bytes()
    server, thread = serve({"Content-Type": "image/jpeg"}, body)
    try:
        client = LumosSnapshotClient(
            f"http://127.0.0.1:{server.server_port}/frame.jpg",
            timeout_s=1.0,
        )
        with pytest.raises(ModelContractError, match="provenance"):
            client.read(after_sequence=-1)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2.0)


def test_client_rejects_remote_http_without_explicit_opt_in() -> None:
    with pytest.raises(ModelContractError, match="loopback"):
        LumosSnapshotClient("http://192.168.58.68:3001/frame.jpg", timeout_s=1.0)


def test_client_rejects_error_response_and_oversized_declared_payload() -> None:
    server, thread = serve(
        {"Content-Type": "application/json"},
        b'{"ready":false}',
        status=503,
    )
    try:
        client = LumosSnapshotClient(
            f"http://127.0.0.1:{server.server_port}/frame.jpg",
            timeout_s=1.0,
        )
        with pytest.raises(ModelContractError, match="503"):
            client.read(after_sequence=-1)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2.0)

    body = jpeg_bytes()
    server, thread = serve(
        {
            "Content-Type": "image/jpeg",
            "X-Lumos-Sequence": "1",
            "X-Lumos-Monotonic-Ns": "1",
        },
        body,
    )
    try:
        client = LumosSnapshotClient(
            f"http://127.0.0.1:{server.server_port}/frame.jpg",
            timeout_s=1.0,
            max_payload_bytes=32,
        )
        with pytest.raises(ModelContractError, match="payload"):
            client.read(after_sequence=-1)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2.0)
