"""Independently testable frame sources for the read-only Vision preview."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import hashlib
from pathlib import Path
import threading
import time
from typing import Any, Protocol
from urllib.request import Request, urlopen
from urllib.parse import urlsplit

import cv2
import numpy as np
from numpy.typing import NDArray


class SourceUnavailable(RuntimeError):
    """A preview source could not be opened or did not produce a frame."""


@dataclass(frozen=True, slots=True)
class SourceFrame:
    image_rgb: NDArray[np.uint8]
    received_monotonic_ns: int
    frame_id: int | None = None
    source_monotonic_ns: int | None = None
    observed_at_ms: int | None = None

    def __post_init__(self) -> None:
        image = np.asarray(self.image_rgb)
        if image.dtype != np.uint8 or image.ndim != 3 or image.shape[2] != 3:
            raise ValueError("image_rgb must be a uint8 RGB image")
        if self.received_monotonic_ns < 0:
            raise ValueError("received_monotonic_ns must be non-negative")
        provenance = (
            self.frame_id,
            self.source_monotonic_ns,
            self.observed_at_ms,
        )
        if any(value is not None and value < 0 for value in provenance):
            raise ValueError("source provenance values must be non-negative")


class FrameSource(Protocol):
    @property
    def name(self) -> str: ...

    def open(self) -> None: ...

    def read(self) -> SourceFrame: ...

    def close(self) -> None: ...


CaptureFactory = Callable[[str, int, tuple[int, ...]], Any]


def _default_capture_factory(
    url: str,
    backend: int,
    params: tuple[int, ...],
) -> Any:
    return cv2.VideoCapture(url, backend, list(params))


def _validate_timeout(name: str, value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 100 <= value <= 30_000:
        raise ValueError(f"{name} must be an integer within [100, 30000]")
    return value


class OpenCvMjpegSource:
    """Decode an HTTP(S) MJPEG stream through OpenCV's FFmpeg backend."""

    def __init__(
        self,
        url: str,
        *,
        name: str = "mjpeg",
        open_timeout_ms: int = 1_500,
        read_timeout_ms: int = 1_500,
        capture_factory: CaptureFactory = _default_capture_factory,
        clock_ns: Callable[[], int] = time.monotonic_ns,
    ) -> None:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("MJPEG source URL must use HTTP or HTTPS")
        if not name.strip():
            raise ValueError("source name must not be empty")
        self.url = url
        self._name = name.strip()
        self.open_timeout_ms = _validate_timeout("open_timeout_ms", open_timeout_ms)
        self.read_timeout_ms = _validate_timeout("read_timeout_ms", read_timeout_ms)
        self._capture_factory = capture_factory
        self._clock_ns = clock_ns
        self._capture: Any | None = None

    @property
    def name(self) -> str:
        return self._name

    def open(self) -> None:
        if self._capture is not None and self._capture.isOpened():
            return
        self.close()
        params = (
            cv2.CAP_PROP_OPEN_TIMEOUT_MSEC,
            self.open_timeout_ms,
            cv2.CAP_PROP_READ_TIMEOUT_MSEC,
            self.read_timeout_ms,
        )
        try:
            capture = self._capture_factory(self.url, cv2.CAP_FFMPEG, params)
        except Exception as error:
            raise SourceUnavailable("MJPEG source open failed") from error
        if not capture.isOpened():
            capture.release()
            raise SourceUnavailable("MJPEG source open failed")
        self._capture = capture

    def read(self) -> SourceFrame:
        if self._capture is None or not self._capture.isOpened():
            raise SourceUnavailable("MJPEG source is not open")
        try:
            ok, image_bgr = self._capture.read()
        except Exception as error:
            raise SourceUnavailable("MJPEG frame read failed") from error
        if not ok or image_bgr is None:
            raise SourceUnavailable("MJPEG frame read failed")
        image = np.asarray(image_bgr)
        if image.dtype != np.uint8 or image.ndim != 3 or image.shape[2] != 3:
            raise SourceUnavailable("MJPEG frame must be an 8-bit BGR image")
        image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        return SourceFrame(image_rgb.copy(), int(self._clock_ns()))

    def close(self) -> None:
        capture, self._capture = self._capture, None
        if capture is not None:
            capture.release()


UrlOpener = Callable[..., Any]


class MultipartMjpegSource:
    """Decode MJPEG while preserving the producer's frame identity headers."""

    _MAX_HEADER_LINE = 8_192
    _MAX_HEADER_COUNT = 32
    _MAX_JPEG_BYTES = 16 * 1024 * 1024

    def __init__(
        self,
        url: str,
        *,
        name: str = "mjpeg",
        open_timeout_ms: int = 1_500,
        read_timeout_ms: int = 1_500,
        opener: UrlOpener = urlopen,
        clock_ns: Callable[[], int] = time.monotonic_ns,
    ) -> None:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("MJPEG source URL must use HTTP or HTTPS")
        if not name.strip():
            raise ValueError("source name must not be empty")
        self.url = url
        self._name = name.strip()
        self.open_timeout_ms = _validate_timeout("open_timeout_ms", open_timeout_ms)
        self.read_timeout_ms = _validate_timeout("read_timeout_ms", read_timeout_ms)
        self._opener = opener
        self._clock_ns = clock_ns
        self._response_lock = threading.Lock()
        self._close_requested = threading.Event()
        self._response: Any | None = None
        self._boundary: bytes | None = None

    @property
    def name(self) -> str:
        return self._name

    def open(self) -> None:
        with self._response_lock:
            if self._response is not None:
                return
            self._close_requested.clear()
        request = Request(self.url, headers={"Accept": "multipart/x-mixed-replace"})
        timeout_s = max(self.open_timeout_ms, self.read_timeout_ms) / 1_000
        response: Any | None = None
        try:
            response = self._opener(request, timeout=timeout_s)
            content_type = response.headers.get("Content-Type", "")
            boundary = self._parse_boundary(content_type)
            with self._response_lock:
                if self._close_requested.is_set():
                    raise SourceUnavailable("multipart MJPEG source open interrupted")
                self._response = response
                self._boundary = boundary
        except Exception as error:
            if response is not None:
                response.close()
            raise SourceUnavailable("multipart MJPEG source open failed") from error

    def read(self) -> SourceFrame:
        if self._response is None or self._boundary is None:
            raise SourceUnavailable("multipart MJPEG source is not open")
        self._seek_boundary()
        headers = self._read_headers()
        content_type = headers.get("content-type", "").lower()
        if content_type != "image/jpeg":
            raise SourceUnavailable("multipart part must contain image/jpeg")
        content_length = self._parse_bounded_int(
            headers,
            "content-length",
            maximum=self._MAX_JPEG_BYTES,
        )
        frame_id = self._parse_bounded_int(headers, "x-thirdhand-frame-id")
        source_monotonic_ns = self._parse_bounded_int(
            headers,
            "x-thirdhand-monotonic-ns",
        )
        observed_at_ms = self._parse_bounded_int(
            headers,
            "x-thirdhand-observed-at-ms",
        )
        jpeg = self._read_exact(content_length)
        expected_sha = headers.get("x-thirdhand-image-sha256", "").lower()
        if len(expected_sha) != 64 or hashlib.sha256(jpeg).hexdigest() != expected_sha:
            raise SourceUnavailable("multipart JPEG SHA-256 mismatch")
        trailer = self._read_exact(2)
        if trailer != b"\r\n":
            raise SourceUnavailable("multipart JPEG trailer is malformed")
        image_bgr = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image_bgr is None:
            raise SourceUnavailable("multipart JPEG decode failed")
        image_rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
        return SourceFrame(
            image_rgb.copy(),
            int(self._clock_ns()),
            frame_id=frame_id,
            source_monotonic_ns=source_monotonic_ns,
            observed_at_ms=observed_at_ms,
        )

    def close(self) -> None:
        self._close_requested.set()
        with self._response_lock:
            response, self._response = self._response, None
            self._boundary = None
        if response is not None:
            response.close()

    @staticmethod
    def _parse_boundary(content_type: str) -> bytes:
        if "multipart/x-mixed-replace" not in content_type.lower():
            raise ValueError("response is not multipart MJPEG")
        for field in content_type.split(";")[1:]:
            key, separator, value = field.strip().partition("=")
            if separator and key.lower() == "boundary":
                boundary = value.strip().strip('"').encode("ascii")
                if boundary:
                    return b"--" + boundary.removeprefix(b"--")
        raise ValueError("multipart boundary is missing")

    def _seek_boundary(self) -> None:
        assert self._response is not None and self._boundary is not None
        for _ in range(4):
            line = self._response.readline(self._MAX_HEADER_LINE + 1)
            if not line:
                raise SourceUnavailable("multipart MJPEG stream ended")
            if len(line) > self._MAX_HEADER_LINE:
                raise SourceUnavailable("multipart boundary line is too long")
            if line.rstrip(b"\r\n") == self._boundary:
                return
        raise SourceUnavailable("multipart boundary was not found")

    def _read_headers(self) -> dict[str, str]:
        assert self._response is not None
        headers: dict[str, str] = {}
        for _ in range(self._MAX_HEADER_COUNT):
            line = self._response.readline(self._MAX_HEADER_LINE + 1)
            if not line:
                raise SourceUnavailable("multipart headers ended unexpectedly")
            if len(line) > self._MAX_HEADER_LINE:
                raise SourceUnavailable("multipart header line is too long")
            if line in {b"\r\n", b"\n"}:
                return headers
            try:
                name, separator, value = line.decode("ascii").partition(":")
            except UnicodeDecodeError as error:
                raise SourceUnavailable("multipart header is not ASCII") from error
            if not separator or not name.strip():
                raise SourceUnavailable("multipart header is malformed")
            headers[name.strip().lower()] = value.strip()
        raise SourceUnavailable("multipart header count exceeded")

    @staticmethod
    def _parse_bounded_int(
        headers: dict[str, str],
        name: str,
        *,
        maximum: int | None = None,
    ) -> int:
        try:
            value = int(headers[name])
        except (KeyError, ValueError) as error:
            raise SourceUnavailable(f"multipart header {name} is invalid") from error
        if value < 0 or (maximum is not None and not 0 < value <= maximum):
            raise SourceUnavailable(f"multipart header {name} is out of range")
        return value

    def _read_exact(self, size: int) -> bytes:
        assert self._response is not None
        chunks: list[bytes] = []
        remaining = size
        while remaining:
            chunk = self._response.read(remaining)
            if not chunk:
                raise SourceUnavailable("multipart payload ended unexpectedly")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)


class ImageReplaySource:
    """Repeat one local image at a bounded rate for hardware-free debugging."""

    def __init__(
        self,
        path: str | Path,
        *,
        fps: float = 5.0,
        name: str | None = None,
        clock_ns: Callable[[], int] = time.monotonic_ns,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if isinstance(fps, bool) or not 0.0 < float(fps) <= 60.0:
            raise ValueError("fps must be within (0, 60]")
        self.path = Path(path)
        self.fps = float(fps)
        self._name = name or f"replay:{self.path.name}"
        self._clock_ns = clock_ns
        self._sleeper = sleeper
        self._image_rgb: NDArray[np.uint8] | None = None
        self._last_read_ns: int | None = None
        self._interval_ns = int(1_000_000_000 / self.fps)

    @property
    def name(self) -> str:
        return self._name

    def open(self) -> None:
        if not self.path.is_file():
            raise SourceUnavailable("replay image open failed")
        image_bgr = cv2.imread(str(self.path), cv2.IMREAD_COLOR)
        if image_bgr is None:
            raise SourceUnavailable("replay image open failed")
        self._image_rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
        self._last_read_ns = None

    def read(self) -> SourceFrame:
        if self._image_rgb is None:
            raise SourceUnavailable("replay source is not open")
        now_ns = int(self._clock_ns())
        if self._last_read_ns is not None:
            remaining_ns = self._last_read_ns + self._interval_ns - now_ns
            if remaining_ns > 0:
                self._sleeper(remaining_ns / 1_000_000_000)
                now_ns = int(self._clock_ns())
        self._last_read_ns = now_ns
        return SourceFrame(self._image_rgb.copy(), now_ns)

    def close(self) -> None:
        self._image_rgb = None
        self._last_read_ns = None


__all__ = [
    "FrameSource",
    "ImageReplaySource",
    "MultipartMjpegSource",
    "OpenCvMjpegSource",
    "SourceFrame",
    "SourceUnavailable",
]
