from __future__ import annotations

import hashlib
import io
from pathlib import Path
import threading

import cv2
import numpy as np
import pytest

from thirdhand_va.vision.preview.source import (
    ImageReplaySource,
    MultipartMjpegSource,
    OpenCvMjpegSource,
    SourceUnavailable,
)


class CaptureStub:
    def __init__(self, *, opened: bool, frames=()) -> None:
        self.opened = opened
        self.frames = list(frames)
        self.release_count = 0

    def isOpened(self) -> bool:
        return self.opened

    def read(self):
        if not self.frames:
            return False, None
        return self.frames.pop(0)

    def release(self) -> None:
        self.release_count += 1
        self.opened = False


class CaptureFactoryStub:
    def __init__(self, capture: CaptureStub) -> None:
        self.capture = capture
        self.calls: list[tuple[str, int, tuple[int, ...]]] = []

    def __call__(self, url: str, backend: int, params: tuple[int, ...]):
        self.calls.append((url, backend, params))
        return self.capture


def make_source(capture: CaptureStub) -> OpenCvMjpegSource:
    return OpenCvMjpegSource(
        "http://127.0.0.1:3000/camera_lumos_vision",
        capture_factory=CaptureFactoryStub(capture),
        clock_ns=lambda: 123,
    )


def test_mjpeg_source_opens_ffmpeg_with_timeouts_and_returns_rgb() -> None:
    bgr = np.array([[[1, 2, 3]]], dtype=np.uint8)
    capture = CaptureStub(opened=True, frames=[(True, bgr)])
    factory = CaptureFactoryStub(capture)
    source = OpenCvMjpegSource(
        "http://127.0.0.1:3000/camera_lumos_vision",
        name="fused",
        open_timeout_ms=700,
        read_timeout_ms=900,
        capture_factory=factory,
        clock_ns=lambda: 123,
    )

    source.open()
    frame = source.read()

    assert source.name == "fused"
    assert factory.calls == [(
        "http://127.0.0.1:3000/camera_lumos_vision",
        cv2.CAP_FFMPEG,
        (
            cv2.CAP_PROP_OPEN_TIMEOUT_MSEC,
            700,
            cv2.CAP_PROP_READ_TIMEOUT_MSEC,
            900,
        ),
    )]
    assert frame.image_rgb.tolist() == [[[3, 2, 1]]]
    assert frame.received_monotonic_ns == 123


def test_mjpeg_source_rejects_non_http_urls_and_invalid_timeouts() -> None:
    with pytest.raises(ValueError, match="HTTP"):
        OpenCvMjpegSource("file:///tmp/frame.mjpg")
    with pytest.raises(ValueError, match="open_timeout_ms"):
        OpenCvMjpegSource("http://127.0.0.1/stream", open_timeout_ms=99)
    with pytest.raises(ValueError, match="read_timeout_ms"):
        OpenCvMjpegSource("http://127.0.0.1/stream", read_timeout_ms=30_001)


def test_mjpeg_source_releases_capture_when_open_fails() -> None:
    capture = CaptureStub(opened=False)
    source = make_source(capture)

    with pytest.raises(SourceUnavailable, match="open failed"):
        source.open()

    assert capture.release_count == 1


def test_mjpeg_source_failed_read_raises_source_unavailable() -> None:
    source = make_source(CaptureStub(opened=True, frames=[(False, None)]))
    source.open()

    with pytest.raises(SourceUnavailable, match="frame read failed"):
        source.read()


def test_mjpeg_source_requires_open_and_close_is_idempotent() -> None:
    capture = CaptureStub(opened=True)
    source = make_source(capture)

    with pytest.raises(SourceUnavailable, match="not open"):
        source.read()
    source.open()
    source.close()
    source.close()

    assert capture.release_count == 1


def test_image_replay_returns_independent_rgb_frames(tmp_path: Path) -> None:
    path = tmp_path / "frame.png"
    bgr = np.full((8, 10, 3), (1, 2, 3), dtype=np.uint8)
    assert cv2.imwrite(str(path), bgr)
    source = ImageReplaySource(
        path,
        fps=60.0,
        clock_ns=lambda: 456,
        sleeper=lambda _: None,
    )

    source.open()
    first = source.read()
    second = source.read()
    first.image_rgb[:] = 0

    assert source.name == f"replay:{path.name}"
    assert second.image_rgb.shape == (8, 10, 3)
    assert second.image_rgb[0, 0].tolist() == [3, 2, 1]
    assert second.received_monotonic_ns == 456


def test_image_replay_rejects_bad_fps_and_unreadable_path(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="fps"):
        ImageReplaySource(tmp_path / "frame.png", fps=0)
    source = ImageReplaySource(tmp_path / "missing.png")
    with pytest.raises(SourceUnavailable, match="image open failed"):
        source.open()


class MultipartResponseStub(io.BytesIO):
    def __init__(self, body: bytes) -> None:
        super().__init__(body)
        self.headers = {"Content-Type": "multipart/x-mixed-replace; boundary=frame"}


def jpeg_bytes(bgr: np.ndarray) -> bytes:
    ok, encoded = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, 100])
    assert ok
    return encoded.tobytes()


def multipart_part(
    jpeg: bytes,
    *,
    frame_id: int,
    monotonic_ns: int,
    observed_at_ms: int,
    sha256: str | None = None,
) -> bytes:
    digest = sha256 or hashlib.sha256(jpeg).hexdigest()
    return (
        b"--frame\r\n"
        b"Content-Type: image/jpeg\r\n"
        + f"Content-Length: {len(jpeg)}\r\n".encode("ascii")
        + f"X-ThirdHand-Frame-Id: {frame_id}\r\n".encode("ascii")
        + f"X-ThirdHand-Monotonic-Ns: {monotonic_ns}\r\n".encode("ascii")
        + f"X-ThirdHand-Observed-At-Ms: {observed_at_ms}\r\n".encode("ascii")
        + f"X-ThirdHand-Image-Sha256: {digest}\r\n\r\n".encode("ascii")
        + jpeg
        + b"\r\n"
    )


def test_multipart_source_decodes_sequential_frames_with_upstream_identity() -> None:
    first_jpeg = jpeg_bytes(np.full((12, 16, 3), (10, 20, 30), np.uint8))
    second_jpeg = jpeg_bytes(np.full((12, 16, 3), (40, 50, 60), np.uint8))
    response = MultipartResponseStub(
        multipart_part(
            first_jpeg,
            frame_id=41,
            monotonic_ns=4_100,
            observed_at_ms=410,
        )
        + multipart_part(
            second_jpeg,
            frame_id=42,
            monotonic_ns=4_200,
            observed_at_ms=420,
        )
    )
    calls: list[tuple[str, float]] = []

    def opener(request, *, timeout: float):
        calls.append((request.full_url, timeout))
        return response

    source = MultipartMjpegSource(
        "http://127.0.0.1:3000/camera_depth",
        name="depth",
        open_timeout_ms=700,
        read_timeout_ms=900,
        opener=opener,
        clock_ns=lambda: 9_999,
    )

    source.open()
    first = source.read()
    second = source.read()
    source.close()

    assert calls == [("http://127.0.0.1:3000/camera_depth", 0.9)]
    assert (first.frame_id, second.frame_id) == (41, 42)
    assert first.source_monotonic_ns == 4_100
    assert first.observed_at_ms == 410
    assert first.received_monotonic_ns == 9_999
    assert first.image_rgb.shape == (12, 16, 3)
    assert np.allclose(first.image_rgb[4, 4], [30, 20, 10], atol=2)
    assert np.allclose(second.image_rgb[4, 4], [60, 50, 40], atol=2)
    assert response.closed


def test_multipart_source_rejects_payload_whose_integrity_header_is_wrong() -> None:
    jpeg = jpeg_bytes(np.full((8, 10, 3), 80, np.uint8))
    response = MultipartResponseStub(
        multipart_part(
            jpeg,
            frame_id=7,
            monotonic_ns=70,
            observed_at_ms=700,
            sha256="0" * 64,
        )
    )
    source = MultipartMjpegSource(
        "http://127.0.0.1:3000/camera_depth",
        opener=lambda _request, timeout: response,
    )
    source.open()

    with pytest.raises(SourceUnavailable, match="SHA-256"):
        source.read()


def test_multipart_source_closes_response_when_shutdown_interrupts_open() -> None:
    response = MultipartResponseStub(b"")
    opener_started = threading.Event()
    release_open = threading.Event()
    errors: list[Exception] = []

    def opener(_request, *, timeout: float):
        opener_started.set()
        release_open.wait(2.0)
        return response

    source = MultipartMjpegSource(
        "http://127.0.0.1:3000/camera_depth",
        opener=opener,
    )

    def open_source() -> None:
        try:
            source.open()
        except Exception as error:
            errors.append(error)

    worker = threading.Thread(target=open_source)
    worker.start()
    assert opener_started.wait(0.5)
    source.close()
    release_open.set()
    worker.join(1.0)

    assert not worker.is_alive()
    assert len(errors) == 1
    assert isinstance(errors[0], SourceUnavailable)
    assert response.closed
