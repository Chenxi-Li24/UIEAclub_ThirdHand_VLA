from __future__ import annotations

from collections import deque
import time

import cv2
import numpy as np

from thirdhand_va.vision.preview.service import PreviewMode, PreviewService
from thirdhand_va.vision.preview.source import SourceFrame, SourceUnavailable


class FakeClock:
    def __init__(self) -> None:
        self.now_ns = 0
        self.now_ms = 1_000

    def monotonic_ns(self) -> int:
        return self.now_ns

    def wall_time_ms(self) -> int:
        return self.now_ms

    def advance(self, seconds: float) -> None:
        self.now_ns += int(seconds * 1_000_000_000)
        self.now_ms += int(seconds * 1_000)


def frame(value: int, received_ns: int = 0) -> SourceFrame:
    return SourceFrame(
        np.full((24, 32, 3), value, dtype=np.uint8),
        received_ns,
    )


class ScriptedSource:
    def __init__(
        self,
        name: str,
        outcomes=(),
        *,
        open_error: Exception | None = None,
    ) -> None:
        self._name = name
        self.outcomes = deque(outcomes)
        self.open_error = open_error
        self.open_count = 0
        self.close_count = 0

    @property
    def name(self) -> str:
        return self._name

    def open(self) -> None:
        self.open_count += 1
        if self.open_error is not None:
            raise self.open_error

    def read(self) -> SourceFrame:
        if not self.outcomes:
            raise SourceUnavailable("script exhausted")
        outcome = self.outcomes.popleft()
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def close(self) -> None:
        self.close_count += 1


class RepeatingSource(ScriptedSource):
    def __init__(self, name: str, value: int) -> None:
        super().__init__(name)
        self.value = value

    def read(self) -> SourceFrame:
        time.sleep(0.005)
        return frame(self.value, time.monotonic_ns())


class SequenceFactory:
    def __init__(self, sources) -> None:
        self.sources = deque(sources)
        self.calls = 0

    def __call__(self):
        self.calls += 1
        if not self.sources:
            return ScriptedSource(
                "exhausted",
                open_error=SourceUnavailable("factory exhausted"),
            )
        return self.sources.popleft()


def make_service(
    primary,
    fallback=None,
    *,
    clock: FakeClock | None = None,
) -> PreviewService:
    active_clock = clock or FakeClock()
    return PreviewService(
        primary,
        fallback,
        reconnect_interval_s=2.0,
        offline_fps=2.0,
        offline_size=(160, 120),
        clock_ns=active_clock.monotonic_ns,
        wall_time_ms=active_clock.wall_time_ms,
    )


def decode(jpeg: bytes) -> np.ndarray:
    image = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
    assert image is not None
    return image


def test_service_uses_fused_source_without_opening_fallback() -> None:
    primary_source = ScriptedSource("fused", [frame(30)])
    fallback_factory = SequenceFactory([ScriptedSource("raw", [frame(10)])])
    service = make_service(SequenceFactory([primary_source]), fallback_factory)

    assert service.run_once() is True
    latest = service.wait_for_frame(after_sequence=-1, timeout_s=0)

    assert latest is not None
    assert latest.mode == PreviewMode.FUSED
    assert latest.source_name == "fused"
    assert latest.sequence == 0
    assert fallback_factory.calls == 0


def test_service_falls_back_then_retries_and_recovers_fused_source() -> None:
    clock = FakeClock()
    first_primary = ScriptedSource(
        "fused",
        [SourceUnavailable("primary down")],
    )
    recovered_primary = ScriptedSource("fused", [frame(30, 2_000_000_000)])
    fallback_source = ScriptedSource("raw", [frame(10), frame(20)])
    primary_factory = SequenceFactory([first_primary, recovered_primary])
    service = make_service(
        primary_factory,
        SequenceFactory([fallback_source]),
        clock=clock,
    )

    service.run_once()
    fallback_frame = service.wait_for_frame(-1, 0)
    assert fallback_frame is not None
    assert fallback_frame.mode == PreviewMode.RAW_FALLBACK
    assert decode(fallback_frame.jpeg)[:60].mean() != 10
    assert service.status().reconnect_count == 1

    clock.advance(1.0)
    service.run_once()
    assert primary_factory.calls == 1
    assert service.status().mode == PreviewMode.RAW_FALLBACK

    clock.advance(1.0)
    service.run_once()
    recovered = service.wait_for_frame(fallback_frame.sequence, 0)
    assert recovered is not None
    assert recovered.mode == PreviewMode.FUSED
    assert recovered.source_name == "fused"
    assert primary_factory.calls == 2
    assert fallback_source.close_count == 1


def test_service_keeps_only_latest_frame_and_reports_relay_age() -> None:
    clock = FakeClock()
    primary = ScriptedSource("fused", [frame(1), frame(2), frame(3)])
    service = make_service(SequenceFactory([primary]), clock=clock)

    service.run_once()
    service.run_once()
    service.run_once()
    clock.advance(0.050)

    latest = service.wait_for_frame(after_sequence=0, timeout_s=0)
    status = service.status()
    assert latest is not None and latest.sequence == 2
    assert service.wait_for_frame(after_sequence=2, timeout_s=0) is None
    assert status.last_sequence == 2
    assert status.last_frame_at_ms == 1_000
    assert status.relay_frame_age_ms == 50.0


def test_service_publishes_offline_frame_when_both_sources_fail() -> None:
    primary = SequenceFactory([
        ScriptedSource("fused", open_error=SourceUnavailable("down"))
    ])
    fallback = SequenceFactory([
        ScriptedSource("raw", open_error=SourceUnavailable("down"))
    ])
    service = make_service(primary, fallback)

    assert service.run_once() is True
    latest = service.wait_for_frame(-1, 0)

    assert latest is not None
    assert latest.mode == PreviewMode.OFFLINE
    assert latest.source_name == "offline"
    assert decode(latest.jpeg).shape == (120, 160, 3)
    assert service.status().reconnect_count == 2


def test_threaded_service_starts_and_stops_without_leaking_source() -> None:
    source = RepeatingSource("fused", 25)
    service = PreviewService(
        SequenceFactory([source]),
        reconnect_interval_s=2.0,
        offline_size=(160, 120),
    )

    service.start()
    latest = service.wait_for_frame(-1, timeout_s=1.0)
    service.stop()
    service.stop()

    assert latest is not None and latest.mode == PreviewMode.FUSED
    assert service.status().mode == PreviewMode.STOPPED
    assert source.close_count == 1
