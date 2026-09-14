"""Run the Ubuntu preview relay consumed by Windows VS Code."""

from __future__ import annotations

import argparse
from collections.abc import Iterable
import json
import logging
from pathlib import Path
import signal
import sys
import threading

from thirdhand_va.vision.preview import (
    ImageReplaySource,
    OpenCvMjpegSource,
    PreviewHttpServer,
    PreviewService,
)


DEFAULT_PRIMARY_URL = "http://127.0.0.1:3000/camera_lumos_vision"
DEFAULT_FALLBACK_URL = "http://127.0.0.1:3000/camera_xvisio_raw"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--primary-url", default=DEFAULT_PRIMARY_URL)
    parser.add_argument("--fallback-url", default=DEFAULT_FALLBACK_URL)
    parser.add_argument("--replay-image", type=Path)
    parser.add_argument("--replay-fps", type=float, default=5.0)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8_765)
    parser.add_argument("--open-timeout-ms", type=int, default=1_500)
    parser.add_argument("--read-timeout-ms", type=int, default=1_500)
    parser.add_argument("--reconnect-seconds", type=float, default=2.0)
    parser.add_argument("--jpeg-quality", type=int, default=85)
    return parser


def _url(address: tuple[str, int], path: str) -> str:
    host, port = address
    formatted_host = f"[{host}]" if ":" in host else host
    return f"http://{formatted_host}:{port}{path}"


def run(
    args: argparse.Namespace,
    stop_event: threading.Event | None = None,
) -> int:
    stop = stop_event or threading.Event()
    if args.replay_image is not None:
        replay_path = Path(args.replay_image)
        if not replay_path.is_file():
            raise ValueError(f"replay image does not exist: {replay_path}")
        primary_factory = lambda: ImageReplaySource(
            replay_path,
            fps=args.replay_fps,
            name="replay",
        )
        fallback_factory = None
        source_mode = "replay"
    else:
        primary_factory = lambda: OpenCvMjpegSource(
            args.primary_url,
            name="fused",
            open_timeout_ms=args.open_timeout_ms,
            read_timeout_ms=args.read_timeout_ms,
        )
        fallback_factory = lambda: OpenCvMjpegSource(
            args.fallback_url,
            name="raw",
            open_timeout_ms=args.open_timeout_ms,
            read_timeout_ms=args.read_timeout_ms,
        )
        source_mode = "attach"

    service = PreviewService(
        primary_factory,
        fallback_factory,
        reconnect_interval_s=args.reconnect_seconds,
        jpeg_quality=args.jpeg_quality,
    )
    server = PreviewHttpServer(service, host=args.host, port=args.port)
    try:
        service.start()
        address = server.start()
        print(
            json.dumps(
                {
                    "type": "preview_ready",
                    "address": {"host": address[0], "port": address[1]},
                    "stream_url": _url(address, "/stream.mjpg"),
                    "health_url": _url(address, "/health"),
                    "source_mode": source_mode,
                    "read_only": True,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            flush=True,
        )
        while not stop.wait(0.2):
            pass
        return 0
    finally:
        server.stop()
        service.stop()


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    stop_event = threading.Event()
    previous_handlers: dict[int, signal.Handlers] = {}

    def request_stop(_signum, _frame) -> None:
        stop_event.set()

    try:
        if threading.current_thread() is threading.main_thread():
            for signum in (signal.SIGINT, signal.SIGTERM):
                previous_handlers[signum] = signal.getsignal(signum)
                signal.signal(signum, request_stop)
        return run(args, stop_event)
    except Exception as error:
        print(
            json.dumps(
                {
                    "type": "preview_error",
                    "error": str(error),
                    "error_type": type(error).__name__,
                    "read_only": True,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
            flush=True,
        )
        return 2
    finally:
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    raise SystemExit(main())
