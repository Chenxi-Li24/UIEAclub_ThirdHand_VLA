"""Show RGB, algorithm overlays, and synchronized depth on Ubuntu."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Iterable
import json
import os
from pathlib import Path
import signal
import sys
import threading

import cv2

from thirdhand_va.vision.camera import RegisteredDepthCoverage
from thirdhand_va.vision.preview import (
    MultipartMjpegSource,
    OpenCvMonitorWindow,
    TaggedFrameReader,
    run_synchronized_monitor,
)
from thirdhand_va.vision.visualization import (
    compose_monitor_frame,
    render_monitor_notice,
)


DEFAULT_ALGORITHM_URL = "http://127.0.0.1:3000/camera_lumos_vision"
DEFAULT_DEPTH_URL = "http://127.0.0.1:3000/camera_xvisio_depth"
DEFAULT_WINDOW_NAME = "ThirdHand RGB-D Vision Monitor"
XVISIO_DEPTH_COVERAGE = RegisteredDepthCoverage(
    camera_serial="250801DR48FP25002738",
    reference_size=(640, 480),
    roi_xyxy=(203, 149, 428, 319),
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--algorithm-url", default=DEFAULT_ALGORITHM_URL)
    parser.add_argument("--depth-url", default=DEFAULT_DEPTH_URL)
    parser.add_argument("--algorithm-image", type=Path)
    parser.add_argument("--depth-image", type=Path)
    parser.add_argument("--depth-alpha", type=float, default=0.35)
    parser.add_argument("--match-timeout-seconds", type=float, default=0.30)
    parser.add_argument("--reconnect-seconds", type=float, default=1.0)
    parser.add_argument("--open-timeout-ms", type=int, default=1_500)
    parser.add_argument("--read-timeout-ms", type=int, default=1_500)
    parser.add_argument("--window-name", default=DEFAULT_WINDOW_NAME)
    parser.add_argument("--display", default=os.environ.get("DISPLAY") or ":1")
    parser.add_argument(
        "--xauthority",
        default=(
            os.environ.get("XAUTHORITY")
            or f"/run/user/{os.getuid()}/gdm/Xauthority"
        ),
    )
    return parser


def validate_args(args: argparse.Namespace) -> argparse.Namespace:
    image_pair = (args.algorithm_image is not None, args.depth_image is not None)
    if image_pair[0] != image_pair[1]:
        raise ValueError("--algorithm-image and --depth-image must be provided together")
    if image_pair[0]:
        for path in (args.algorithm_image, args.depth_image):
            if not Path(path).is_file():
                raise ValueError(f"offline image does not exist: {path}")
    if not 0 <= args.depth_alpha <= 0.65:
        raise ValueError("--depth-alpha must be within [0, 0.65]")
    return args


WindowFactory = Callable[[str], OpenCvMonitorWindow]


def run(
    args: argparse.Namespace,
    stop_event: threading.Event,
    *,
    window_factory: WindowFactory = OpenCvMonitorWindow,
) -> int:
    window = window_factory(args.window_name)
    if args.algorithm_image is not None:
        return _run_offline(args, stop_event, window)

    algorithm_factory = lambda: MultipartMjpegSource(
        args.algorithm_url,
        name="algorithm",
        open_timeout_ms=args.open_timeout_ms,
        read_timeout_ms=args.read_timeout_ms,
    )
    depth_reader = TaggedFrameReader(
        lambda: MultipartMjpegSource(
            args.depth_url,
            name="depth",
            open_timeout_ms=args.open_timeout_ms,
            read_timeout_ms=args.read_timeout_ms,
        ),
        reconnect_interval_s=args.reconnect_seconds,
    )
    return run_synchronized_monitor(
        algorithm_factory,
        depth_reader,
        window,
        stop_event=stop_event,
        match_timeout_s=args.match_timeout_seconds,
        reconnect_interval_s=args.reconnect_seconds,
        depth_alpha=args.depth_alpha,
        depth_coverage=XVISIO_DEPTH_COVERAGE,
    )


def _read_rgb(path: Path):
    image_bgr = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image_bgr is None:
        raise ValueError(f"offline image cannot be decoded: {path}")
    return cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)


def _run_offline(args, stop_event, window) -> int:
    try:
        algorithm = _read_rgb(Path(args.algorithm_image))
        depth = _read_rgb(Path(args.depth_image))
        if depth.shape != algorithm.shape:
            rendered = render_monitor_notice(
                algorithm,
                frame_id=0,
                detail="DEPTH SIZE MISMATCH",
            )
        else:
            rendered = compose_monitor_frame(
                algorithm,
                depth,
                frame_id=0,
                alpha=args.depth_alpha,
                depth_roi_xyxy=XVISIO_DEPTH_COVERAGE.roi_for_size(
                    algorithm.shape[1],
                    algorithm.shape[0],
                ),
            ).image_rgb
        while not stop_event.is_set():
            if not window.show(rendered):
                return 0
            stop_event.wait(0.05)
        return 0
    finally:
        window.close()


def _configure_x11(args: argparse.Namespace) -> None:
    os.environ["DISPLAY"] = args.display
    os.environ["XAUTHORITY"] = args.xauthority
    runtime_dir = f"/run/user/{os.getuid()}"
    if os.path.isdir(runtime_dir):
        os.environ.setdefault("XDG_RUNTIME_DIR", runtime_dir)


def main(argv: Iterable[str] | None = None) -> int:
    try:
        args = validate_args(
            build_parser().parse_args(list(argv) if argv is not None else None)
        )
        _configure_x11(args)
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
        print(
            json.dumps(
                {
                    "type": "ubuntu_vision_monitor_starting",
                    "display": args.display,
                    "source_mode": (
                        "offline" if args.algorithm_image is not None else "attach"
                    ),
                    "algorithm_url": args.algorithm_url,
                    "depth_url": args.depth_url,
                    "ports_opened": False,
                    "robot_control_enabled": False,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            flush=True,
        )
        return run(args, stop_event)
    except Exception as error:
        print(
            json.dumps(
                {
                    "type": "ubuntu_vision_monitor_error",
                    "error": str(error),
                    "ports_opened": False,
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
