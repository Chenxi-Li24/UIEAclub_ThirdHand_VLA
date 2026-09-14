from __future__ import annotations

from collections import deque
import threading
import time

import numpy as np

from thirdhand_va.vision.preview.source import SourceFrame, SourceUnavailable
from thirdhand_va.vision.preview.synchronization import (
    FrameIdBuffer,
    TaggedFrameReader,
)


def tagged_frame(frame_id: int, value: int = 0) -> SourceFrame:
    return SourceFrame(
        np.full((8, 10, 3), value, np.uint8),
        received_monotonic_ns=frame_id * 10,
        frame_id=frame_id,
        source_monotonic_ns=frame_id * 100,
        observed_at_ms=frame_id * 1_000,
    )


def test_frame_buffer_returns_only_the_requested_frame_identity() -> None:
    buffer = FrameIdBuffer(max_frames=4)
    buffer.put(tagged_frame(20, 20))
    buffer.put(tagged_frame(22, 22))

    assert buffer.take(21, timeout_s=0) is None
    matched = buffer.take(22, timeout_s=0)

    assert matched is not None
    assert matched.frame_id == 22
    assert np.all(matched.image_rgb == 22)


def test_frame_buffer_evicts_old_frames_instead_of_growing_unbounded() -> None:
    buffer = FrameIdBuffer(max_frames=2)
    buffer.put(tagged_frame(1))
    buffer.put(tagged_frame(2))
    buffer.put(tagged_frame(3))

    assert buffer.take(1, timeout_s=0) is None
    assert buffer.frame_ids() == (2, 3)


class ScriptedTaggedSource:
    def __init__(self, outcomes) -> None:
        self.outcomes = deque(outcomes)
        self.open_count = 0
        self.close_count = 0

    @property
    def name(self) -> str:
        return "depth"

    def open(self) -> None:
        self.open_count += 1

    def read(self) -> SourceFrame:
        outcome = self.outcomes.popleft()
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def close(self) -> None:
        self.close_count += 1


def test_tagged_reader_recovers_without_reusing_a_failed_source() -> None:
    failed = ScriptedTaggedSource([SourceUnavailable("connection lost")])
    recovered = ScriptedTaggedSource([tagged_frame(31, 90)])
    sources = deque([failed, recovered])
    reader = TaggedFrameReader(lambda: sources.popleft(), reconnect_interval_s=0.1)

    assert reader.run_once() is False
    assert reader.run_once() is True
    matched = reader.take(31, timeout_s=0)

    assert failed.close_count == 1
    assert recovered.open_count == 1
    assert matched is not None and matched.frame_id == 31
    assert reader.status().reconnect_count == 1


def test_tagged_reader_discards_buffered_frames_after_source_disconnect() -> None:
    source = ScriptedTaggedSource([
        tagged_frame(100, 10),
        SourceUnavailable("producer restarted"),
    ])
    reader = TaggedFrameReader(lambda: source, reconnect_interval_s=0.1)

    assert reader.run_once() is True
    assert reader.run_once() is False

    assert reader.take(100, timeout_s=0) is None


class CloseUnblocksSource:
    def __init__(self) -> None:
        self.read_started = threading.Event()
        self.closed = threading.Event()
        self.close_count = 0

    @property
    def name(self) -> str:
        return "blocking-depth"

    def open(self) -> None:
        pass

    def read(self) -> SourceFrame:
        self.read_started.set()
        self.closed.wait(10.0)
        raise SourceUnavailable("closed while reading")

    def close(self) -> None:
        self.close_count += 1
        self.closed.set()


def test_tagged_reader_closes_a_blocking_source_before_joining_worker() -> None:
    source = CloseUnblocksSource()
    reader = TaggedFrameReader(lambda: source, reconnect_interval_s=0.1)
    reader.start()
    assert source.read_started.wait(0.5)

    started = time.monotonic()
    reader.stop()
    elapsed = time.monotonic() - started

    assert elapsed < 1.0
    assert source.close_count == 1


class CloseUnblocksOpenSource:
    def __init__(self) -> None:
        self.open_started = threading.Event()
        self.closed = threading.Event()
        self.close_count = 0

    @property
    def name(self) -> str:
        return "opening-depth"

    def open(self) -> None:
        self.open_started.set()
        self.closed.wait(10.0)
        raise SourceUnavailable("closed while opening")

    def read(self) -> SourceFrame:
        raise AssertionError("read must not run after interrupted open")

    def close(self) -> None:
        self.close_count += 1
        self.closed.set()


def test_tagged_reader_exposes_opening_source_to_prompt_shutdown() -> None:
    source = CloseUnblocksOpenSource()
    reader = TaggedFrameReader(lambda: source, reconnect_interval_s=0.1)
    reader.start()
    assert source.open_started.wait(0.5)

    started = time.monotonic()
    try:
        reader.stop()
    finally:
        source.closed.set()
    elapsed = time.monotonic() - started

    assert elapsed < 1.0
    assert source.close_count == 1
    reader.stop()
    assert source.close_count == 1
