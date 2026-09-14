#!/usr/bin/env python3
"""Read frames from the preview endpoint and print a compact JSON report."""

from __future__ import annotations

import argparse
from collections.abc import Iterable
import json
import sys
import time

from thirdhand_va.vision.preview import OpenCvMjpegSource


def positive_frames(value: str) -> int:
    parsed = int(value)
    if not 1 <= parsed <= 1_000:
        raise argparse.ArgumentTypeError("frames must be within [1, 1000]")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--url",
        default="http://127.0.0.1:8765/stream.mjpg",
    )
    parser.add_argument("--frames", type=positive_frames, default=5)
    parser.add_argument("--open-timeout-ms", type=int, default=1_500)
    parser.add_argument("--read-timeout-ms", type=int, default=1_500)
    return parser


def run(args: argparse.Namespace) -> dict:
    source = OpenCvMjpegSource(
        args.url,
        name="preview-smoke",
        open_timeout_ms=args.open_timeout_ms,
        read_timeout_ms=args.read_timeout_ms,
    )
    started = time.monotonic()
    source.open()
    latest = None
    try:
        for _ in range(args.frames):
            latest = source.read()
    finally:
        source.close()
    assert latest is not None
    elapsed_s = max(time.monotonic() - started, 1e-9)
    height, width = latest.image_rgb.shape[:2]
    return {
        "url": args.url,
        "frames": args.frames,
        "width": width,
        "height": height,
        "elapsed_seconds": round(elapsed_s, 4),
        "measured_fps": round(args.frames / elapsed_s, 3),
        "last_received_monotonic_ns": latest.received_monotonic_ns,
    }


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        print(json.dumps(run(args), ensure_ascii=False, sort_keys=True))
        return 0
    except Exception as error:
        print(
            json.dumps(
                {
                    "type": "preview_smoke_error",
                    "error": str(error),
                    "error_type": type(error).__name__,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
