"""Process-lifetime frame provenance for reconnecting capture devices."""

from __future__ import annotations

from .types import FrameStamp, InvalidDataError


class FrameStampSequencer:
    """Issue strictly advancing stamps without trusting device-local counters."""

    def __init__(self, source: str) -> None:
        if not isinstance(source, str) or not source.strip():
            raise InvalidDataError("frame source must be a non-empty string")
        self._source = source
        self._frame_id = 0
        self._last_monotonic_ns = -1

    def next_stamp(self, monotonic_ns: int) -> FrameStamp:
        if (
            isinstance(monotonic_ns, bool)
            or not isinstance(monotonic_ns, int)
            or monotonic_ns <= self._last_monotonic_ns
        ):
            raise InvalidDataError("capture timestamp must strictly advance")
        self._frame_id += 1
        self._last_monotonic_ns = monotonic_ns
        return FrameStamp(self._source, self._frame_id, monotonic_ns)
