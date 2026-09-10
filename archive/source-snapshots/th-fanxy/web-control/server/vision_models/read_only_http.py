"""Bounded HTTP JPEG retrieval shared by read-only calibration tools."""

from __future__ import annotations

from urllib.request import Request, urlopen

MAX_FRAME_BYTES = 16 * 1024 * 1024


def extract_first_jpeg(payload: bytes) -> bytes:
    start = payload.find(b"\xff\xd8")
    if start < 0:
        raise ValueError("camera response does not contain a JPEG start marker")
    end = payload.find(b"\xff\xd9", start + 2)
    if end < 0:
        raise ValueError("camera response does not contain a complete JPEG")
    return payload[start : end + 2]


def fetch_jpeg(url: str, timeout_s: float = 3.0) -> bytes:
    request = Request(url, headers={"Cache-Control": "no-cache", "User-Agent": "ThirdHandCalib/1"})
    buffer = bytearray()
    with urlopen(request, timeout=timeout_s) as response:
        while len(buffer) <= MAX_FRAME_BYTES:
            chunk = response.read(65536)
            if not chunk:
                break
            buffer.extend(chunk)
            start = buffer.find(b"\xff\xd8")
            end = buffer.find(b"\xff\xd9", max(0, start + 2)) if start >= 0 else -1
            if start >= 0 and end >= 0:
                return bytes(buffer[start : end + 2])
    if len(buffer) > MAX_FRAME_BYTES:
        raise ValueError("camera frame exceeds 16 MiB")
    return extract_first_jpeg(bytes(buffer))


__all__ = ["MAX_FRAME_BYTES", "extract_first_jpeg", "fetch_jpeg"]
