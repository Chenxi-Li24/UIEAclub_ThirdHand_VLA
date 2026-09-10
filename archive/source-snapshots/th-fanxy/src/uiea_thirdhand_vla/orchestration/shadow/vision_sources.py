"""Finite local-file sources for checked ThirdHand vision events."""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from pathlib import Path

from pydantic import ValidationError

from ..runtime.adapters import ReplayObservationSource
from ..runtime.models import Observation
from ..runtime.ports import ObservationUnavailable
from .vision_events import VisionEvent, VisionEventAdapter

MAX_EVENT_FILE_BYTES = 16 * 1024 * 1024


class VisionEventSourceError(ValueError):
    """Raised when a local vision event source violates its boundary contract."""


def _checked_regular_file(path: Path) -> Path:
    candidate = Path(path)
    if candidate.is_symlink():
        raise VisionEventSourceError(f"vision event source cannot be a symlink: {candidate}")
    if not candidate.is_file():
        raise VisionEventSourceError(f"vision event source must be a regular file: {candidate}")
    try:
        size = candidate.stat().st_size
    except OSError as exc:
        raise VisionEventSourceError(f"cannot stat vision event source: {exc}") from exc
    if size > MAX_EVENT_FILE_BYTES:
        raise VisionEventSourceError("vision event source exceeds 16 MiB")
    return candidate


def _parse_event(data: bytes, label: str) -> VisionEvent:
    try:
        return VisionEvent.model_validate_json(data)
    except (ValidationError, ValueError) as exc:
        raise VisionEventSourceError(f"cannot parse vision event {label}: {exc}") from exc


class VisionJsonlReplaySource:
    """Read one finite, ordered event log into the runtime replay source."""

    def __init__(self, path: Path, adapter: VisionEventAdapter) -> None:
        source_path = _checked_regular_file(path)
        try:
            lines = source_path.read_bytes().splitlines()
        except OSError as exc:
            raise VisionEventSourceError(f"cannot read vision event source: {exc}") from exc
        if not lines:
            raise VisionEventSourceError("vision event replay cannot be empty")
        events: list[VisionEvent] = []
        for number, line in enumerate(lines, start=1):
            if not line.strip():
                raise VisionEventSourceError(f"cannot parse vision event line {number}: blank")
            try:
                event = VisionEvent.model_validate_json(line)
            except (ValidationError, ValueError) as exc:
                raise VisionEventSourceError(
                    f"cannot parse vision event line {number}: {exc}"
                ) from exc
            events.append(event)
        for left, right in zip(events, events[1:]):
            if right.source_sequence <= left.source_sequence:
                raise VisionEventSourceError(
                    "vision event source sequences must be strictly increasing"
                )
        observations = tuple(adapter.to_observation(event) for event in events)
        self._replay = ReplayObservationSource(observations)

    def next_observation(self, after_sequence: int | None) -> Observation:
        return self._replay.next_observation(after_sequence)


class LatestVisionEventSource:
    """Poll one explicit local file until it holds a stable newer event."""

    def __init__(
        self,
        path: Path,
        adapter: VisionEventAdapter,
        *,
        timeout_s: float,
        poll_s: float = 0.01,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if not math.isfinite(timeout_s) or timeout_s < 0.0:
            raise VisionEventSourceError("timeout_s must be finite and non-negative")
        if not math.isfinite(poll_s) or poll_s <= 0.0:
            raise VisionEventSourceError("poll_s must be finite and positive")
        self._path = _checked_regular_file(path)
        self._adapter = adapter
        self._timeout_s = timeout_s
        self._poll_s = poll_s
        self._clock = clock
        self._sleeper = sleeper

    def next_observation(self, after_sequence: int | None) -> Observation:
        deadline = self._clock() + self._timeout_s
        while True:
            data = self._stable_bytes()
            if data is not None:
                event = _parse_event(data, str(self._path))
                if after_sequence is None or event.source_sequence > after_sequence:
                    return self._adapter.to_observation(event)
            if self._clock() >= deadline:
                boundary = "the current sequence" if after_sequence is None else str(after_sequence)
                raise ObservationUnavailable(
                    f"no stable vision event newer than {boundary} before timeout"
                )
            self._sleeper(self._poll_s)

    def _stable_bytes(self) -> bytes | None:
        first = self._read_with_signature()
        second = self._read_with_signature()
        if first is None or second is None or first != second:
            return None
        return first[1]

    def _read_with_signature(self) -> tuple[tuple[int, int, int], bytes] | None:
        _checked_regular_file(self._path)
        try:
            before = self._path.stat()
            data = self._path.read_bytes()
            after = self._path.stat()
        except OSError:
            return None
        before_key = (before.st_ino, before.st_size, before.st_mtime_ns)
        after_key = (after.st_ino, after.st_size, after.st_mtime_ns)
        if before_key != after_key or len(data) != after.st_size:
            return None
        return after_key, data


__all__ = [
    "LatestVisionEventSource",
    "VisionEventSourceError",
    "VisionJsonlReplaySource",
]
