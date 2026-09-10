"""Frame-aligned RGB, algorithm, and depth composition as a preview source."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from thirdhand_va.vision.camera import RegisteredDepthCoverage
from thirdhand_va.vision.visualization import (
    DEFAULT_MONITOR_DEPTH_ALPHA,
    compose_monitor_frame,
    render_monitor_notice,
)

from .source import FrameSource, SourceFrame, SourceUnavailable


class DepthFrameReader(Protocol):
    """Small synchronization boundary needed by the fused source."""

    def start(self) -> None: ...

    def take(self, frame_id: int, *, timeout_s: float) -> SourceFrame | None: ...

    def stop(self) -> None: ...


AlgorithmSourceFactory = Callable[[], FrameSource]
DepthReaderFactory = Callable[[], DepthFrameReader]


class SynchronizedCompositeSource:
    """Expose one composite frame without ever blending mismatched depth."""

    def __init__(
        self,
        algorithm_source_factory: AlgorithmSourceFactory,
        depth_reader_factory: DepthReaderFactory,
        *,
        match_timeout_s: float = 0.30,
        depth_alpha: float = DEFAULT_MONITOR_DEPTH_ALPHA,
        depth_coverage: RegisteredDepthCoverage | None = None,
    ) -> None:
        if not callable(algorithm_source_factory) or not callable(
            depth_reader_factory
        ):
            raise TypeError("source factories must be callable")
        if not 0 <= float(match_timeout_s) <= 2.0:
            raise ValueError("match_timeout_s must be within [0, 2]")
        if not 0 <= float(depth_alpha) <= 0.65:
            raise ValueError("depth_alpha must be within [0, 0.65]")
        self._algorithm_source_factory = algorithm_source_factory
        self._depth_reader_factory = depth_reader_factory
        self._match_timeout_s = float(match_timeout_s)
        self._depth_alpha = float(depth_alpha)
        self._depth_coverage = depth_coverage
        self._algorithm: FrameSource | None = None
        self._depth_reader: DepthFrameReader | None = None

    @property
    def name(self) -> str:
        return "rgbd-fused"

    def open(self) -> None:
        if self._algorithm is not None:
            return
        algorithm = self._algorithm_source_factory()
        depth_reader = self._depth_reader_factory()
        try:
            algorithm.open()
            depth_reader.start()
        except Exception:
            try:
                algorithm.close()
            finally:
                depth_reader.stop()
            raise
        self._algorithm = algorithm
        self._depth_reader = depth_reader

    def read(self) -> SourceFrame:
        algorithm_source = self._algorithm
        depth_reader = self._depth_reader
        if algorithm_source is None or depth_reader is None:
            raise SourceUnavailable("synchronized composite source is not open")
        algorithm = algorithm_source.read()
        if algorithm.frame_id is None:
            raise SourceUnavailable("algorithm frame is missing frame_id")
        depth = depth_reader.take(
            algorithm.frame_id,
            timeout_s=self._match_timeout_s,
        )
        image_rgb = self._compose(algorithm, depth)
        return SourceFrame(
            image_rgb,
            algorithm.received_monotonic_ns,
            frame_id=algorithm.frame_id,
            source_monotonic_ns=algorithm.source_monotonic_ns,
            observed_at_ms=algorithm.observed_at_ms,
        )

    def close(self) -> None:
        algorithm, self._algorithm = self._algorithm, None
        depth_reader, self._depth_reader = self._depth_reader, None
        try:
            if algorithm is not None:
                algorithm.close()
        finally:
            if depth_reader is not None:
                depth_reader.stop()

    def _compose(
        self,
        algorithm: SourceFrame,
        depth: SourceFrame | None,
    ):
        assert algorithm.frame_id is not None
        if depth is None or depth.frame_id != algorithm.frame_id:
            return render_monitor_notice(
                algorithm.image_rgb,
                frame_id=algorithm.frame_id,
                detail="DEPTH WAITING",
            )
        if depth.image_rgb.shape != algorithm.image_rgb.shape:
            return render_monitor_notice(
                algorithm.image_rgb,
                frame_id=algorithm.frame_id,
                detail="DEPTH SIZE MISMATCH",
            )
        roi = (
            None
            if self._depth_coverage is None
            else self._depth_coverage.roi_for_size(
                algorithm.image_rgb.shape[1],
                algorithm.image_rgb.shape[0],
            )
        )
        return compose_monitor_frame(
            algorithm.image_rgb,
            depth.image_rgb,
            frame_id=algorithm.frame_id,
            alpha=self._depth_alpha,
            depth_roi_xyxy=roi,
        ).image_rgb


__all__ = ["DepthFrameReader", "SynchronizedCompositeSource"]

