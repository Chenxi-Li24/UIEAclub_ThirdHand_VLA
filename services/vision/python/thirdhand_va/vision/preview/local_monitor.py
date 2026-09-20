"""Native Ubuntu window lifecycle for synchronized Vision streams."""

from __future__ import annotations

from collections.abc import Callable
import threading
from typing import Protocol

import cv2
import numpy as np
from numpy.typing import NDArray

from thirdhand_va.vision.camera import RegisteredDepthCoverage
from thirdhand_va.vision.visualization import (
    DEFAULT_MONITOR_DEPTH_ALPHA,
    compose_monitor_frame,
    render_monitor_notice,
    render_offline_frame,
)

from .source import FrameSource, SourceUnavailable
from .synchronization import TaggedFrameReader


class MonitorWindow(Protocol):
    def show(self, image_rgb: NDArray[np.uint8]) -> bool: ...

    def close(self) -> None: ...


class OpenCvMonitorWindow:
    """One resizable Qt/OpenCV window; Q or Escape requests shutdown."""

    def __init__(self, name: str = "ThirdHand RGB-D Vision Monitor") -> None:
        if not name.strip():
            raise ValueError("window name must not be empty")
        self.name = name.strip()
        self._opened = False

    def show(self, image_rgb: NDArray[np.uint8]) -> bool:
        image = np.asarray(image_rgb)
        if image.dtype != np.uint8 or image.ndim != 3 or image.shape[2] != 3:
            raise ValueError("window image must be a uint8 RGB image")
        if not self._opened:
            cv2.namedWindow(self.name, cv2.WINDOW_NORMAL)
            cv2.resizeWindow(self.name, image.shape[1], image.shape[0])
            self._opened = True
        cv2.imshow(self.name, cv2.cvtColor(image, cv2.COLOR_RGB2BGR))
        key = cv2.waitKey(1) & 0xFF
        if key in {27, ord("q"), ord("Q")}:
            return False
        try:
            return cv2.getWindowProperty(self.name, cv2.WND_PROP_VISIBLE) >= 1
        except cv2.error:
            return False

    def close(self) -> None:
        if not self._opened:
            return
        try:
            cv2.destroyWindow(self.name)
            cv2.waitKey(1)
        except cv2.error:
            pass
        self._opened = False


AlgorithmSourceFactory = Callable[[], FrameSource]


def run_synchronized_monitor(
    algorithm_source_factory: AlgorithmSourceFactory,
    depth_reader: TaggedFrameReader,
    window: MonitorWindow,
    *,
    stop_event: threading.Event,
    match_timeout_s: float = 0.30,
    reconnect_interval_s: float = 1.0,
    depth_alpha: float = DEFAULT_MONITOR_DEPTH_ALPHA,
    depth_coverage: RegisteredDepthCoverage | None = None,
) -> int:
    """Run a local window without owning or controlling either producer."""
    if not 0 <= float(match_timeout_s) <= 2.0:
        raise ValueError("match_timeout_s must be within [0, 2]")
    if not 0.05 <= float(reconnect_interval_s) <= 30.0:
        raise ValueError("reconnect_interval_s must be within [0.05, 30]")
    source: FrameSource | None = None
    depth_reader.start()
    try:
        while not stop_event.is_set():
            try:
                if source is None:
                    source = algorithm_source_factory()
                    source.open()
                algorithm_frame = source.read()
                if algorithm_frame.frame_id is None:
                    raise SourceUnavailable("algorithm frame is missing frame_id")
            except Exception as error:
                if source is not None:
                    source.close()
                    source = None
                offline = render_offline_frame(
                    640,
                    480,
                    f"algorithm stream unavailable: {error}",
                )
                if not window.show(offline):
                    return 0
                stop_event.wait(float(reconnect_interval_s))
                continue

            depth_frame = depth_reader.take(
                algorithm_frame.frame_id,
                timeout_s=float(match_timeout_s),
            )
            if depth_frame is None:
                rendered = render_monitor_notice(
                    algorithm_frame.image_rgb,
                    frame_id=algorithm_frame.frame_id,
                    detail="DEPTH WAITING",
                )
            else:
                try:
                    rendered = compose_monitor_frame(
                        algorithm_frame.image_rgb,
                        depth_frame.image_rgb,
                        frame_id=algorithm_frame.frame_id,
                        alpha=depth_alpha,
                        depth_roi_xyxy=(
                            None
                            if depth_coverage is None
                            else depth_coverage.roi_for_size(
                                algorithm_frame.image_rgb.shape[1],
                                algorithm_frame.image_rgb.shape[0],
                            )
                        ),
                    ).image_rgb
                except ValueError:
                    rendered = render_monitor_notice(
                        algorithm_frame.image_rgb,
                        frame_id=algorithm_frame.frame_id,
                        detail="DEPTH SIZE MISMATCH",
                    )
            if not window.show(rendered):
                return 0
        return 0
    finally:
        if source is not None:
            source.close()
        depth_reader.stop()
        window.close()


__all__ = [
    "MonitorWindow",
    "OpenCvMonitorWindow",
    "run_synchronized_monitor",
]
