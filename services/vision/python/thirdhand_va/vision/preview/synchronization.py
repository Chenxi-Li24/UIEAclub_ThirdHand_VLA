"""Bounded frame-ID synchronization for independent read-only streams."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
import threading

from .source import FrameSource, SourceFrame, SourceUnavailable


class FrameIdBuffer:
    """Keep a bounded set of tagged frames and wait for an exact identity."""

    def __init__(self, *, max_frames: int = 12) -> None:
        if isinstance(max_frames, bool) or not 1 <= int(max_frames) <= 256:
            raise ValueError("max_frames must be within [1, 256]")
        self._max_frames = int(max_frames)
        self._frames: OrderedDict[int, SourceFrame] = OrderedDict()
        self._condition = threading.Condition()
        self._closed = False

    def put(self, frame: SourceFrame) -> None:
        if frame.frame_id is None:
            raise ValueError("synchronized frames require frame_id")
        with self._condition:
            if self._closed:
                return
            self._frames[frame.frame_id] = frame
            self._frames.move_to_end(frame.frame_id)
            while len(self._frames) > self._max_frames:
                self._frames.popitem(last=False)
            self._condition.notify_all()

    def take(self, frame_id: int, *, timeout_s: float) -> SourceFrame | None:
        if frame_id < 0:
            raise ValueError("frame_id must be non-negative")
        if timeout_s < 0:
            raise ValueError("timeout_s must be non-negative")
        with self._condition:
            matched = self._frames.pop(frame_id, None)
            if matched is not None:
                self._discard_older_than(frame_id)
                return matched
            if self._frames and max(self._frames) > frame_id:
                self._discard_older_than(frame_id)
                return None
            if timeout_s == 0 or self._closed:
                return None
            received = self._condition.wait_for(
                lambda: (
                    frame_id in self._frames
                    or self._closed
                    or (bool(self._frames) and max(self._frames) > frame_id)
                ),
                timeout=timeout_s,
            )
            if not received or self._closed:
                return None
            matched = self._frames.pop(frame_id, None)
            self._discard_older_than(frame_id)
            return matched

    def frame_ids(self) -> tuple[int, ...]:
        with self._condition:
            return tuple(self._frames)

    def clear(self) -> None:
        with self._condition:
            self._frames.clear()
            self._condition.notify_all()

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._condition.notify_all()

    def _discard_older_than(self, frame_id: int) -> None:
        for stale_id in tuple(self._frames):
            if stale_id < frame_id:
                self._frames.pop(stale_id, None)


@dataclass(frozen=True, slots=True)
class TaggedReaderStatus:
    connected: bool
    last_frame_id: int | None
    reconnect_count: int
    last_error: str | None


SourceFactory = Callable[[], FrameSource]


class TaggedFrameReader:
    """Continuously read one tagged source into an exact-ID buffer."""

    def __init__(
        self,
        source_factory: SourceFactory,
        *,
        max_frames: int = 12,
        reconnect_interval_s: float = 1.0,
    ) -> None:
        if not 0.05 <= float(reconnect_interval_s) <= 30.0:
            raise ValueError("reconnect_interval_s must be within [0.05, 30]")
        self._source_factory = source_factory
        self._reconnect_interval_s = float(reconnect_interval_s)
        self._buffer = FrameIdBuffer(max_frames=max_frames)
        self._stop = threading.Event()
        self._state_lock = threading.Lock()
        self._source_lock = threading.Lock()
        self._source: FrameSource | None = None
        self._worker: threading.Thread | None = None
        self._connected = False
        self._last_frame_id: int | None = None
        self._reconnect_count = 0
        self._last_error: str | None = None

    def run_once(self) -> bool:
        source: FrameSource | None = None
        try:
            with self._source_lock:
                source = self._source
            if source is None:
                source = self._source_factory()
                with self._source_lock:
                    if self._stop.is_set():
                        source.close()
                        return False
                    self._source = source
                source.open()
                if self._stop.is_set():
                    self._drop_source(source)
                    return False
            frame = source.read()
            if frame.frame_id is None:
                raise SourceUnavailable("tagged source frame is missing frame_id")
        except Exception as error:
            self._drop_source(source)
            if not self._stop.is_set():
                self._buffer.clear()
                with self._state_lock:
                    self._connected = False
                    self._reconnect_count += 1
                    self._last_error = str(error)
            return False
        self._buffer.put(frame)
        with self._state_lock:
            self._connected = True
            self._last_frame_id = frame.frame_id
            self._last_error = None
        return True

    def start(self) -> None:
        with self._state_lock:
            if self._worker is not None and self._worker.is_alive():
                return
            self._worker = threading.Thread(
                target=self._run,
                name="vision-depth-reader",
                daemon=True,
            )
            self._worker.start()

    def take(self, frame_id: int, *, timeout_s: float) -> SourceFrame | None:
        return self._buffer.take(frame_id, timeout_s=timeout_s)

    def status(self) -> TaggedReaderStatus:
        with self._state_lock:
            return TaggedReaderStatus(
                connected=self._connected,
                last_frame_id=self._last_frame_id,
                reconnect_count=self._reconnect_count,
                last_error=self._last_error,
            )

    def stop(self) -> None:
        self._stop.set()
        self._buffer.close()
        self._drop_source()
        with self._state_lock:
            worker = self._worker
        if worker is not None and worker is not threading.current_thread():
            worker.join(timeout=3.5)
            if worker.is_alive():
                raise RuntimeError("tagged frame reader worker did not stop")
        with self._state_lock:
            self._worker = None
            self._connected = False

    def _run(self) -> None:
        try:
            while not self._stop.is_set():
                if not self.run_once():
                    self._stop.wait(self._reconnect_interval_s)
        finally:
            self._drop_source()

    def _drop_source(self, expected: FrameSource | None = None) -> None:
        with self._source_lock:
            if expected is not None and self._source is not expected:
                return
            source, self._source = self._source, None
        if source is not None:
            source.close()


__all__ = [
    "FrameIdBuffer",
    "TaggedFrameReader",
    "TaggedReaderStatus",
]
