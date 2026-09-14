#!/usr/bin/env python3
"""Capture read-only Lumos/D435 image folders for Kalibr bag creation."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import cv2
import numpy as np

SERVER_ROOT = Path(__file__).resolve().parents[2] / "web-control" / "server"
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

from vision_models.read_only_http import extract_first_jpeg, fetch_jpeg  # noqa: E402


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _png(jpeg: bytes) -> bytes:
    encoded = np.frombuffer(extract_first_jpeg(jpeg), dtype=np.uint8)
    image = cv2.imdecode(encoded, cv2.IMREAD_GRAYSCALE)
    if image is None or image.ndim != 2 or min(image.shape) < 2:
        raise ValueError("camera JPEG cannot be decoded")
    ok, png = cv2.imencode(".png", image)
    if not ok:
        raise ValueError("camera frame cannot be encoded as PNG")
    return png.tobytes()


def write_pair(
    output: Path,
    *,
    lumos_timestamp_ns: int,
    d435_timestamp_ns: int,
    lumos_jpeg: bytes,
    d435_jpeg: bytes,
) -> dict[str, int]:
    for value in (lumos_timestamp_ns, d435_timestamp_ns):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError("camera timestamps must be positive integer nanoseconds")
    root = Path(output)
    _atomic_write(root / "cam0" / f"{lumos_timestamp_ns}.png", _png(lumos_jpeg))
    _atomic_write(root / "cam1" / f"{d435_timestamp_ns}.png", _png(d435_jpeg))
    return {
        "lumos_timestamp_ns": lumos_timestamp_ns,
        "d435_timestamp_ns": d435_timestamp_ns,
        "capture_skew_ns": abs(lumos_timestamp_ns - d435_timestamp_ns),
    }


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")


def write_manifest(
    output: Path,
    records: list[dict[str, int]],
    *,
    lumos_url: str,
    d435_url: str,
    purpose: str,
) -> Path:
    if purpose not in {"fit", "validation"}:
        raise ValueError("calibration purpose must be fit or validation")
    payload: dict[str, Any] = {
        "schema_version": 1,
        "camera_order": {"cam0": "lumos_rgb", "cam1": "d435_rgb_raw"},
        "kalibr_topics": ["/cam0/image_raw", "/cam1/image_raw"],
        "kalibr_models": ["eucm-none", "pinhole-none"],
        "sources": {"lumos": lumos_url, "d435": d435_url},
        "purpose": purpose,
        "records": records,
        "robot_or_motion_access": False,
    }
    payload["content_id"] = f"sha256:{hashlib.sha256(_canonical(payload)).hexdigest()}"
    path = Path(output) / "manifest.json"
    _atomic_write(
        path,
        json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=True).encode("ascii") + b"\n",
    )
    return path


def _loopback_url(value: str, name: str, allow_remote: bool) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "http" or not parsed.hostname:
        raise ValueError(f"{name} must be an HTTP URL")
    if not allow_remote and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError(f"{name} must be loopback unless --allow-remote is set")
    return value


def _timed_fetch(url: str) -> tuple[int, bytes]:
    started = time.time_ns()
    jpeg = fetch_jpeg(url)
    finished = time.time_ns()
    return (started + finished) // 2, jpeg


def capture_dataset(
    output: Path,
    *,
    lumos_url: str,
    d435_url: str,
    count: int,
    frequency_hz: float,
    purpose: str,
) -> Path:
    if isinstance(count, bool) or not isinstance(count, int) or count < 20:
        raise ValueError("calibration dataset requires at least 20 image pairs")
    if not np.isfinite(frequency_hz) or not 0.5 <= frequency_hz <= 10.0:
        raise ValueError("capture frequency must be within [0.5, 10] Hz")
    root = Path(output)
    if root.exists() and any(root.iterdir()):
        raise ValueError("output dataset directory must be empty")
    records = []
    period = 1.0 / frequency_hz
    next_capture = time.monotonic()
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="kalibr-capture") as executor:
        for index in range(count):
            lumos_future = executor.submit(_timed_fetch, lumos_url)
            d435_future = executor.submit(_timed_fetch, d435_url)
            lumos_timestamp, lumos_jpeg = lumos_future.result()
            d435_timestamp, d435_jpeg = d435_future.result()
            records.append(
                write_pair(
                    root,
                    lumos_timestamp_ns=lumos_timestamp,
                    d435_timestamp_ns=d435_timestamp,
                    lumos_jpeg=lumos_jpeg,
                    d435_jpeg=d435_jpeg,
                )
            )
            print(
                f"pair {index + 1}/{count} "
                f"skew={records[-1]['capture_skew_ns'] / 1_000_000.0:.1f} ms",
                flush=True,
            )
            next_capture += period
            remaining = next_capture - time.monotonic()
            if remaining > 0.0:
                time.sleep(remaining)
    return write_manifest(
        root,
        records,
        lumos_url=lumos_url,
        d435_url=d435_url,
        purpose=purpose,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--lumos-url", default="http://127.0.0.1:3001/frame_raw.jpg")
    parser.add_argument("--d435-url", default="http://127.0.0.1:3100/camera_d435_raw")
    parser.add_argument("--count", type=int, default=480)
    parser.add_argument("--frequency-hz", type=float, default=4.0)
    parser.add_argument("--purpose", choices=("fit", "validation"), default="fit")
    parser.add_argument("--allow-remote", action="store_true")
    arguments = parser.parse_args()
    lumos_url = _loopback_url(arguments.lumos_url, "Lumos URL", arguments.allow_remote)
    d435_url = _loopback_url(arguments.d435_url, "D435 URL", arguments.allow_remote)
    manifest = capture_dataset(
        arguments.output,
        lumos_url=lumos_url,
        d435_url=d435_url,
        count=arguments.count,
        frequency_hz=arguments.frequency_hz,
        purpose=arguments.purpose,
    )
    print(f"manifest={manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
