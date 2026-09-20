from __future__ import annotations

from io import BytesIO
import importlib.util
import os
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
WORKER = ROOT / "skills" / "vision" / "inspect-scene" / "src" / "worker.py"


def load_worker():
    assert WORKER.is_file(), "inspect-scene worker is missing"
    spec = importlib.util.spec_from_file_location("inspect_scene_worker", WORKER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def mjpeg_part(jpeg: bytes, *, sequence: int, captured_at_ms: int | None = None) -> bytes:
    headers = [
        b"--frame\r\n",
        b"Content-Type: image/jpeg\r\n",
        f"Content-Length: {len(jpeg)}\r\n".encode("ascii"),
        f"X-ThirdHand-Sequence: {sequence}\r\n".encode("ascii"),
    ]
    if captured_at_ms is not None:
        headers.append(f"X-ThirdHand-Captured-At-Ms: {captured_at_ms}\r\n".encode("ascii"))
    return b"".join(headers) + b"\r\n" + jpeg + b"\r\n"


class Response:
    def __init__(self, payload: bytes):
        self.stream = BytesIO(payload)

    def readline(self, size: int = -1) -> bytes:
        return self.stream.readline(size)

    def read(self, size: int = -1) -> bytes:
        return self.stream.read(size)

    def close(self) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


def test_parses_jpeg_sequence_and_source_timestamp():
    worker = load_worker()
    jpeg = b"\xff\xd8scene\xff\xd9"

    frame = worker.read_mjpeg_frame(
        Response(mjpeg_part(jpeg, sequence=42, captured_at_ms=9_900)),
        received_at_ms=10_000,
    )

    assert frame.jpeg == jpeg
    assert frame.sequence == 42
    assert frame.captured_at_ms == 9_900
    assert frame.frame_age_ms == 100
    assert frame.timestamp_source == "stream-header"


def test_marks_delivery_time_fallback_explicitly():
    worker = load_worker()
    frame = worker.read_mjpeg_frame(
        Response(mjpeg_part(b"\xff\xd8x\xff\xd9", sequence=7)),
        received_at_ms=12_345,
    )

    assert frame.captured_at_ms == 12_345
    assert frame.frame_age_ms == 0
    assert frame.timestamp_source == "mjpeg-delivery"


def test_rejects_repeated_sequence_as_frozen():
    worker = load_worker()
    source = worker.MjpegFrameSource(
        "http://127.0.0.1:3100/camera/xvisio/raw",
        opener=lambda *_args, **_kwargs: Response(
            mjpeg_part(b"\xff\xd8x\xff\xd9", sequence=11)
        ),
        clock_ms=lambda: 20_000,
    )

    with pytest.raises(worker.FrameCaptureError) as error:
        source.next_frame(previous_sequence=11)

    assert error.value.code == "frozen_frame"
    assert "http" not in str(error.value).lower()


def test_rejects_oversized_or_invalid_jpeg():
    worker = load_worker()
    oversized = (
        b"--frame\r\nContent-Type: image/jpeg\r\n"
        + f"Content-Length: {worker.MAX_JPEG_BYTES + 1}\r\n".encode("ascii")
        + b"X-ThirdHand-Sequence: 1\r\n\r\n"
    )
    with pytest.raises(worker.FrameCaptureError) as too_large:
        worker.read_mjpeg_frame(Response(oversized), received_at_ms=1)
    assert too_large.value.code == "frame_too_large"

    invalid = mjpeg_part(b"not-a-jpeg", sequence=2)
    with pytest.raises(worker.FrameCaptureError) as bad_jpeg:
        worker.read_mjpeg_frame(Response(invalid), received_at_ms=1)
    assert bad_jpeg.value.code == "invalid_frame"


def test_retention_keeps_twenty_recent_jpegs_and_expires_old_files(tmp_path: Path):
    worker = load_worker()
    now = 200_000.0
    retention = worker.ImageRetention(
        tmp_path,
        max_files=20,
        max_age_seconds=24 * 60 * 60,
        clock=lambda: now,
    )
    old = tmp_path / "old.jpg"
    old.write_bytes(b"old")
    os.utime(old, (now - 90_000, now - 90_000))

    for sequence in range(1, 23):
        retention.save(b"\xff\xd8x\xff\xd9", sequence=sequence)

    files = sorted(tmp_path.glob("*.jpg"), key=lambda path: path.stat().st_mtime)
    assert len(files) == 20
    assert not old.exists()
    assert not any("000001" in path.name or "000002" in path.name for path in files)
