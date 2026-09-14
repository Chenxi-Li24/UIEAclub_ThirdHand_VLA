from __future__ import annotations

import http.client
import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from thirdhand_va.vision.preview.server import (
    PreviewAccessPolicy,
    PreviewHttpServer,
)
from thirdhand_va.vision.preview.service import PreviewService
from thirdhand_va.vision.preview.source import ImageReplaySource


@pytest.fixture
def running_preview(tmp_path: Path):
    image_path = tmp_path / "preview.png"
    image = np.full((120, 160, 3), (20, 80, 160), dtype=np.uint8)
    assert cv2.imwrite(str(image_path), image)
    service = PreviewService(
        lambda: ImageReplaySource(image_path, fps=30.0, name="fixture"),
        offline_size=(160, 120),
    )
    service.start()
    assert service.wait_for_frame(-1, 1.0) is not None
    server = PreviewHttpServer(service, host="127.0.0.1", port=0)
    address = server.start()
    try:
        yield service, server, address
    finally:
        server.stop()
        service.stop()


@pytest.fixture
def running_token_preview(tmp_path: Path):
    image_path = tmp_path / "preview.png"
    image = np.full((120, 160, 3), (20, 80, 160), dtype=np.uint8)
    assert cv2.imwrite(str(image_path), image)
    service = PreviewService(
        lambda: ImageReplaySource(image_path, fps=30.0, name="fixture"),
        offline_size=(160, 120),
    )
    service.start()
    assert service.wait_for_frame(-1, 1.0) is not None
    token = "A" * 32
    policy = PreviewAccessPolicy.lan(
        access_token=token,
        allowed_networks=("127.0.0.0/8",),
    )
    server = PreviewHttpServer(
        service,
        host="127.0.0.1",
        port=0,
        access_policy=policy,
    )
    address = server.start()
    try:
        yield service, server, address, token
    finally:
        server.stop()
        service.stop()


def request(address, method: str, path: str):
    connection = http.client.HTTPConnection(*address, timeout=2.0)
    connection.request(method, path)
    response = connection.getresponse()
    body = response.read()
    result = response.status, dict(response.getheaders()), body
    connection.close()
    return result


def read_one_part(response: http.client.HTTPResponse):
    assert response.readline() == b"--frame\r\n"
    headers: dict[str, str] = {}
    while True:
        line = response.readline()
        if line == b"\r\n":
            break
        name, value = line.decode("ascii").split(":", 1)
        headers[name.lower()] = value.strip()
    jpeg = response.read(int(headers["content-length"]))
    assert response.read(2) == b"\r\n"
    return headers, jpeg


def test_server_rejects_non_loopback_binding(tmp_path: Path) -> None:
    image_path = tmp_path / "preview.png"
    assert cv2.imwrite(str(image_path), np.zeros((64, 64, 3), np.uint8))
    service = PreviewService(lambda: ImageReplaySource(image_path))

    with pytest.raises(ValueError, match="loopback"):
        PreviewHttpServer(service, host="0.0.0.0", port=0)


def test_lan_policy_requires_token_network_and_specific_bind_address() -> None:
    policy = PreviewAccessPolicy.lan(
        access_token="A" * 32,
        allowed_networks=("192.168.58.0/24",),
    )

    policy.validate_bind("192.168.58.68")
    with pytest.raises(ValueError, match="unspecified"):
        policy.validate_bind("0.0.0.0")
    assert policy.allows("192.168.58.125", "A" * 32) is True
    assert policy.allows("192.168.58.125", "B" * 32) is False
    assert policy.allows("192.168.59.10", "A" * 32) is False


def test_lan_policy_rejects_short_tokens() -> None:
    with pytest.raises(ValueError, match="128 bits"):
        PreviewAccessPolicy.lan(
            access_token="short",
            allowed_networks=("192.168.58.0/24",),
        )


def test_lan_server_requires_token_for_health_and_routes(
    running_token_preview,
) -> None:
    _, _, address, token = running_token_preview

    assert request(address, "GET", "/health")[0] == 403
    assert request(address, "GET", "/health?token=wrong")[0] == 403
    assert request(address, "GET", f"/health?token={token}")[0] == 200
    assert request(address, "GET", f"/?token={token}")[0] == 404
    assert request(address, "POST", f"/health?token={token}")[0] == 405


def test_health_is_read_only_and_unknown_routes_have_no_ui(running_preview) -> None:
    _, _, address = running_preview

    status, headers, body = request(address, "GET", "/health")
    payload = json.loads(body)

    assert status == 200
    assert headers["Cache-Control"] == "no-store"
    assert payload["status"] == "ok"
    assert payload["mode"] == "fused"
    assert payload["source"] == "fixture"
    assert payload["last_sequence"] >= 0
    assert payload["relay_frame_age_ms"] >= 0
    assert payload["reconnect_count"] == 0
    assert payload["clients"] == 0
    assert payload["read_only"] is True
    assert request(address, "POST", "/health")[0] == 405
    assert request(address, "GET", "/")[0] == 404


def test_stream_is_multipart_mjpeg_with_provenance(running_preview) -> None:
    _, _, address = running_preview
    connection = http.client.HTTPConnection(*address, timeout=2.0)
    connection.request("GET", "/stream.mjpg")
    response = connection.getresponse()

    headers, jpeg = read_one_part(response)
    decoded = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)

    assert response.status == 200
    assert response.headers["Content-Type"] == (
        "multipart/x-mixed-replace; boundary=frame"
    )
    assert int(headers["x-thirdhand-frame-id"]) >= 0
    assert int(headers["x-thirdhand-monotonic-ns"]) >= 0
    assert decoded is not None and decoded.shape == (120, 160, 3)
    connection.close()


def test_unread_slow_stream_does_not_block_a_second_viewer(running_preview) -> None:
    _, _, address = running_preview
    slow = http.client.HTTPConnection(*address, timeout=2.0)
    slow.request("GET", "/stream.mjpg")
    slow_response = slow.getresponse()
    assert slow_response.status == 200

    fast = http.client.HTTPConnection(*address, timeout=2.0)
    fast.request("GET", "/stream.mjpg")
    fast_response = fast.getresponse()
    _, jpeg = read_one_part(fast_response)

    assert cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR) is not None
    fast.close()
    slow.close()
