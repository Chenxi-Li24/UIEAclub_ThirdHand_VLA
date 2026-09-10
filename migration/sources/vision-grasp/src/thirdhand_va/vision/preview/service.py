"""Latest-frame preview orchestration with fused/raw/offline recovery."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
import logging
import threading
import time

from thirdhand_va.vision.visualization import (
    encode_jpeg,
    render_offline_frame,
    render_preview_banner,
)

from .source import FrameSource, SourceFrame


LOGGER = logging.getLogger(__name__)
SourceFactory = Callable[[], FrameSource]


class PreviewMode(str, Enum):
    STARTING = "starting"
    FUSED = "fused"
    RAW_FALLBACK = "raw_fallback"
    OFFLINE = "offline"
    STOPPED = "stopped"


@dataclass(frozen=True, slots=True)
class PreviewFrame:
    sequence: int
    jpeg: bytes
    mode: PreviewMode
    source_name: str
    source_received_monotonic_ns: int
    published_monotonic_ns: int
    observed_at_ms: int

    def __post_init__(self) -> None:
        if self.sequence < 0:
            raise ValueError("sequence must be non-negative")
        if not self.jpeg:
            raise ValueError("jpeg must not be empty")
        if min(
            self.source_received_monotonic_ns,
            self.published_monotonic_ns,
            self.observed_at_ms,
        ) < 0:
            raise ValueError("preview timestamps must be non-negative")


@dataclass(frozen=True, slots=True)
class PreviewStatus:
    mode: PreviewMode
    source_name: str | None
    last_sequence: int | None
    last_frame_at_ms: int | None
    relay_frame_age_ms: float | None
    reconnect_count: int


class PreviewService:
    """Prefer fused frames, fall back to raw, and never queue stale frames."""

    def __init__(
        self,
        primary_factory: SourceFactory,
        fallback_factory: SourceFactory | None = None,
        *,
        reconnect_interval_s: float = 2.0,
        offline_fps: float = 2.0,
        offline_size: tuple[int, int] = (640, 480),
        jpeg_quality: int = 85,
        clock_ns: Callable[[], int] = time.monotonic_ns,
        wall_time_ms: Callable[[], int] = lambda: int(time.time() * 1_000),
        jpeg_encoder: Callable[..., bytes] = encode_jpeg,
    ) -> None:
        if not callable(primary_factory):
            raise TypeError("primary_factory must be callable")
        if fallback_factory is not None and not callable(fallback_factory):
            raise TypeError("fallback_factory must be callable")
        if not 0.1 <= float(reconnect_interval_s) <= 60.0:
            raise ValueError("reconnect_interval_s must be within [0.1, 60]")
        if not 0.1 <= float(offline_fps) <= 10.0:
            raise ValueError("offline_fps must be within [0.1, 10]")
        width, height = offline_size
        if width < 64 or height < 64:
            raise ValueError("offline_size dimensions must be at least 64 pixels")
        if isinstance(jpeg_quality, bool) or not 1 <= jpeg_quality <= 100:
            raise ValueError("jpeg_quality must be within [1, 100]")
        self._primary_factory = primary_factory
        self._fallback_factory = fallback_factory
        self._reconnect_ns = int(float(reconnect_interval_s) * 1_000_000_000)
        self._offline_interval_ns = int(1_000_000_000 / float(offline_fps))
        self._offline_size = (int(width), int(height))
        self._jpeg_quality = jpeg_quality
        self._clock_ns = clock_ns
        self._wall_time_ms = wall_time_ms
        self._jpeg_encoder = jpeg_encoder

        self._condition = threading.Condition()
        self._latest: PreviewFrame | None = None
        self._sequence = -1
        self._mode = PreviewMode.STARTING
        self._source_name: str | None = None
        self._reconnect_count = 0
        self._primary: FrameSource | None = None
        self._fallback: FrameSource | None = None
        self._next_primary_attempt_ns = 0
        self._next_fallback_attempt_ns = 0
        self._next_offline_frame_ns = 0
        self._stop = threading.Event()
        self._worker: threading.Thread | None = None

    def start(self) -> None:
        with self._condition:
            if self._worker is not None and self._worker.is_alive():
                return
            if self._stop.is_set():
                raise RuntimeError("preview service cannot restart after stop")
            self._worker = threading.Thread(
                target=self._run,
                name="vision-preview-service",
                daemon=True,
            )
            self._worker.start()

    def run_once(self) -> bool:
        """Perform one deterministic source/recovery step for tests and workers."""

        if self._stop.is_set():
            return False
        now_ns = int(self._clock_ns())
        if self._primary is None and now_ns >= self._next_primary_attempt_ns:
            self._primary = self._try_open(self._primary_factory, "primary")
        if self._primary is not None:
            try:
                source_frame = self._primary.read()
            except Exception as error:
                self._note_failure("primary", error)
                self._close_source("_primary")
                self._next_primary_attempt_ns = (
                    int(self._clock_ns()) + self._reconnect_ns
                )
            else:
                source_name = self._primary.name
                self._close_source("_fallback")
                self._publish(source_frame, PreviewMode.FUSED, source_name)
                return True

        if (
            self._fallback_factory is not None
            and self._fallback is None
            and now_ns >= self._next_fallback_attempt_ns
        ):
            self._fallback = self._try_open(self._fallback_factory, "fallback")
        if self._fallback is not None:
            try:
                source_frame = self._fallback.read()
            except Exception as error:
                self._note_failure("fallback", error)
                self._close_source("_fallback")
                self._next_fallback_attempt_ns = (
                    int(self._clock_ns()) + self._reconnect_ns
                )
            else:
                rendered = render_preview_banner(
                    source_frame.image_rgb,
                    title="VISION OFFLINE - RAW CAMERA",
                    detail="retrying fused stream",
                )
                fallback_frame = SourceFrame(
                    rendered,
                    source_frame.received_monotonic_ns,
                )
                self._publish(
                    fallback_frame,
                    PreviewMode.RAW_FALLBACK,
                    self._fallback.name,
                )
                return True

        now_ns = int(self._clock_ns())
        if now_ns < self._next_offline_frame_ns:
            return False
        width, height = self._offline_size
        offline = render_offline_frame(
            width,
            height,
            "fused and raw streams unavailable; retrying",
        )
        self._publish(
            SourceFrame(offline, now_ns),
            PreviewMode.OFFLINE,
            "offline",
        )
        self._next_offline_frame_ns = now_ns + self._offline_interval_ns
        return True

    def wait_for_frame(
        self,
        after_sequence: int,
        timeout_s: float,
    ) -> PreviewFrame | None:
        if timeout_s < 0:
            raise ValueError("timeout_s must be non-negative")
        deadline = time.monotonic() + timeout_s
        with self._condition:
            while self._latest is None or self._latest.sequence <= after_sequence:
                if self._stop.is_set():
                    return None
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._condition.wait(remaining)
            return self._latest

    def status(self) -> PreviewStatus:
        with self._condition:
            latest = self._latest
            age_ms = None
            if latest is not None:
                age_ms = max(
                    0.0,
                    (int(self._clock_ns()) - latest.published_monotonic_ns)
                    / 1_000_000,
                )
            return PreviewStatus(
                mode=self._mode,
                source_name=self._source_name,
                last_sequence=None if latest is None else latest.sequence,
                last_frame_at_ms=None if latest is None else latest.observed_at_ms,
                relay_frame_age_ms=age_ms,
                reconnect_count=self._reconnect_count,
            )

    def stop(self) -> None:
        self._stop.set()
        with self._condition:
            worker = self._worker
            self._condition.notify_all()
        if worker is not None and worker is not threading.current_thread():
            worker.join(timeout=4.0)
            if worker.is_alive():
                self._close_source("_primary")
                self._close_source("_fallback")
                worker.join(timeout=1.0)
            if worker.is_alive():
                raise RuntimeError("preview service worker did not stop")
        self._close_source("_primary")
        self._close_source("_fallback")
        with self._condition:
            self._worker = None
            self._mode = PreviewMode.STOPPED
            self._source_name = None
            self._condition.notify_all()

    def _run(self) -> None:
        try:
            while not self._stop.is_set():
                if not self.run_once():
                    self._stop.wait(0.02)
        finally:
            self._close_source("_primary")
            self._close_source("_fallback")

    def _try_open(
        self,
        factory: SourceFactory,
        role: str,
    ) -> FrameSource | None:
        source: FrameSource | None = None
        try:
            source = factory()
            source.open()
            return source
        except Exception as error:
            if source is not None:
                try:
                    source.close()
                except Exception:
                    pass
            self._note_failure(role, error)
            retry_at = int(self._clock_ns()) + self._reconnect_ns
            if role == "primary":
                self._next_primary_attempt_ns = retry_at
            else:
                self._next_fallback_attempt_ns = retry_at
            return None

    def _note_failure(self, role: str, error: Exception) -> None:
        with self._condition:
            self._reconnect_count += 1
        LOGGER.warning(
            "preview source failed role=%s error_type=%s",
            role,
            type(error).__name__,
        )

    def _close_source(self, attribute: str) -> None:
        source = getattr(self, attribute)
        setattr(self, attribute, None)
        if source is not None:
            try:
                source.close()
            except Exception as error:
                LOGGER.warning(
                    "preview source close failed role=%s error_type=%s",
                    attribute.removeprefix("_"),
                    type(error).__name__,
                )

    def _publish(
        self,
        source_frame: SourceFrame,
        mode: PreviewMode,
        source_name: str,
    ) -> None:
        jpeg = self._jpeg_encoder(
            source_frame.image_rgb,
            quality=self._jpeg_quality,
        )
        published_ns = int(self._clock_ns())
        observed_at_ms = int(self._wall_time_ms())
        with self._condition:
            self._sequence += 1
            self._latest = PreviewFrame(
                sequence=self._sequence,
                jpeg=jpeg,
                mode=mode,
                source_name=source_name,
                source_received_monotonic_ns=(
                    source_frame.received_monotonic_ns
                ),
                published_monotonic_ns=published_ns,
                observed_at_ms=observed_at_ms,
            )
            self._mode = mode
            self._source_name = source_name
            self._condition.notify_all()


__all__ = [
    "PreviewFrame",
    "PreviewMode",
    "PreviewService",
    "PreviewStatus",
]
