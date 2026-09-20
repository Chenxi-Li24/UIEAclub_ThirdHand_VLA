"""Serve the synchronized RGB, algorithm, and depth view over the local LAN."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Iterable
import ipaddress
import json
import secrets
import signal
import sys
import threading
from urllib.parse import urlencode, urlsplit

from thirdhand_va.vision.camera import RegisteredDepthCoverage
from thirdhand_va.vision.preview import (
    MultipartMjpegSource,
    PreviewAccessPolicy,
    PreviewHttpServer,
    PreviewService,
    SynchronizedCompositeSource,
    TaggedFrameReader,
)


DEFAULT_ALGORITHM_URL = "http://127.0.0.1:3000/camera_lumos_vision"
DEFAULT_DEPTH_URL = "http://127.0.0.1:3000/camera_xvisio_depth"
DEFAULT_PORT = 8_770
XVISIO_DEPTH_COVERAGE = RegisteredDepthCoverage(
    camera_serial="250801DR48FP25002738",
    reference_size=(640, 480),
    roi_xyxy=(203, 149, 428, 319),
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True)
    parser.add_argument("--allowed-network", required=True)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--access-token")
    parser.add_argument("--algorithm-url", default=DEFAULT_ALGORITHM_URL)
    parser.add_argument("--depth-url", default=DEFAULT_DEPTH_URL)
    parser.add_argument("--depth-alpha", type=float, default=0.35)
    parser.add_argument("--match-timeout-seconds", type=float, default=0.30)
    parser.add_argument("--reconnect-seconds", type=float, default=1.0)
    parser.add_argument("--open-timeout-ms", type=int, default=1_500)
    parser.add_argument("--read-timeout-ms", type=int, default=1_500)
    return parser


def _loopback_http_url(value: str) -> bool:
    parsed = urlsplit(value)
    if parsed.scheme != "http" or not parsed.hostname:
        return False
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        return False
    return (
        address.is_loopback
        and parsed.username is None
        and parsed.password is None
        and bool(parsed.path)
        and not parsed.query
        and not parsed.fragment
    )


def validate_args(args: argparse.Namespace) -> argparse.Namespace:
    try:
        host = ipaddress.ip_address(args.host)
    except ValueError as error:
        raise ValueError("--host must be a specific LAN IP address") from error
    if host.is_loopback or host.is_unspecified or not host.is_private:
        raise ValueError("--host must be a specific LAN IP address")
    try:
        allowed_network = ipaddress.ip_network(
            args.allowed_network,
            strict=False,
        )
    except ValueError as error:
        raise ValueError("--allowed-network must be a valid IP network") from error
    if host not in allowed_network:
        raise ValueError("--host must be inside --allowed-network")
    if isinstance(args.port, bool) or not 1 <= args.port <= 65_535:
        raise ValueError("--port must be within [1, 65535]")
    if not _loopback_http_url(args.algorithm_url) or not _loopback_http_url(
        args.depth_url
    ):
        raise ValueError("upstream URLs must be loopback HTTP endpoints")
    if not 0 <= args.depth_alpha <= 0.65:
        raise ValueError("--depth-alpha must be within [0, 0.65]")
    if not 0 <= args.match_timeout_seconds <= 2.0:
        raise ValueError("--match-timeout-seconds must be within [0, 2]")
    if not 0.05 <= args.reconnect_seconds <= 30.0:
        raise ValueError("--reconnect-seconds must be within [0.05, 30]")
    for name in ("open_timeout_ms", "read_timeout_ms"):
        value = getattr(args, name)
        if isinstance(value, bool) or not 100 <= value <= 30_000:
            option = "--" + name.replace("_", "-")
            raise ValueError(f"{option} must be within [100, 30000]")
    if args.access_token is not None:
        _resolve_token(args.access_token)
    return args


def _resolve_token(value: str | None) -> str:
    token = value or secrets.token_urlsafe(24)
    if len(token.encode("utf-8")) < 22:
        raise ValueError("--access-token must contain at least 128 bits")
    return token


ServiceFactory = Callable[..., PreviewService]
ServerFactory = Callable[..., PreviewHttpServer]


def run(
    args: argparse.Namespace,
    stop_event: threading.Event,
    *,
    service_factory: ServiceFactory = PreviewService,
    server_factory: ServerFactory = PreviewHttpServer,
) -> int:
    token = _resolve_token(args.access_token)

    def fused_factory() -> SynchronizedCompositeSource:
        return SynchronizedCompositeSource(
            lambda: MultipartMjpegSource(
                args.algorithm_url,
                name="algorithm",
                open_timeout_ms=args.open_timeout_ms,
                read_timeout_ms=args.read_timeout_ms,
            ),
            lambda: TaggedFrameReader(
                lambda: MultipartMjpegSource(
                    args.depth_url,
                    name="depth",
                    open_timeout_ms=args.open_timeout_ms,
                    read_timeout_ms=args.read_timeout_ms,
                ),
                reconnect_interval_s=args.reconnect_seconds,
            ),
            match_timeout_s=args.match_timeout_seconds,
            depth_alpha=args.depth_alpha,
            depth_coverage=XVISIO_DEPTH_COVERAGE,
        )

    service = service_factory(
        fused_factory,
        fallback_factory=None,
        reconnect_interval_s=args.reconnect_seconds,
    )
    policy = PreviewAccessPolicy.lan(
        access_token=token,
        allowed_networks=(args.allowed_network,),
    )
    server = server_factory(
        service,
        host=args.host,
        port=args.port,
        access_policy=policy,
    )
    service.start()
    try:
        host, port = server.start()
        query = urlencode({"token": token})
        print(
            json.dumps(
                {
                    "type": "vision_lan_ready",
                    "stream_url": (
                        f"http://{host}:{port}/stream.mjpg?{query}"
                    ),
                    "health_url": f"http://{host}:{port}/health?{query}",
                    "read_only": True,
                    "robot_control_enabled": False,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            flush=True,
        )
        while not stop_event.wait(0.25):
            pass
        return 0
    finally:
        server.stop()
        service.stop()


def main(argv: Iterable[str] | None = None) -> int:
    try:
        args = validate_args(
            build_parser().parse_args(list(argv) if argv is not None else None)
        )
    except Exception as error:
        print(str(error), file=sys.stderr)
        return 2

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
                    "type": "vision_lan_error",
                    "error": str(error),
                    "read_only": True,
                    "robot_control_enabled": False,
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
    raise SystemExit(main())
