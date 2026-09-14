from __future__ import annotations

import numpy as np

from thirdhand_va.vision.preview.fused_source import SynchronizedCompositeSource
from thirdhand_va.vision.preview.source import SourceFrame


def tagged(frame_id: int, image_rgb: np.ndarray) -> SourceFrame:
    return SourceFrame(
        image_rgb,
        received_monotonic_ns=1_000,
        frame_id=frame_id,
        source_monotonic_ns=900,
        observed_at_ms=800,
    )


def depth_fixture() -> np.ndarray:
    image = np.zeros((120, 180, 3), np.uint8)
    image[50:80, 60:100] = (255, 0, 0)
    return image


class ScriptedSource:
    def __init__(self, frame: SourceFrame) -> None:
        self.frame = frame
        self.open_count = 0
        self.close_count = 0

    @property
    def name(self) -> str:
        return "algorithm"

    def open(self) -> None:
        self.open_count += 1

    def read(self) -> SourceFrame:
        return self.frame

    def close(self) -> None:
        self.close_count += 1


class RecordingDepthReader:
    def __init__(self, frame: SourceFrame) -> None:
        self.frame = frame
        self.requested_ids: list[int] = []
        self.start_count = 0
        self.stop_count = 0

    def start(self) -> None:
        self.start_count += 1

    def take(self, frame_id: int, *, timeout_s: float) -> SourceFrame | None:
        self.requested_ids.append(frame_id)
        return self.frame if self.frame.frame_id == frame_id else None

    def stop(self) -> None:
        self.stop_count += 1


def test_fused_source_composes_only_the_same_frame_id() -> None:
    algorithm_rgb = np.full((120, 180, 3), 100, np.uint8)
    algorithm = ScriptedSource(tagged(41, algorithm_rgb))
    depth = RecordingDepthReader(tagged(41, depth_fixture()))
    source = SynchronizedCompositeSource(
        lambda: algorithm,
        lambda: depth,
        match_timeout_s=0,
    )

    source.open()
    frame = source.read()
    source.close()

    assert frame.frame_id == 41
    assert frame.source_monotonic_ns == 900
    assert frame.observed_at_ms == 800
    assert depth.requested_ids == [41]
    assert frame.image_rgb[60, 80].tolist() != [100, 100, 100]
    assert algorithm.close_count == 1
    assert depth.stop_count == 1


def test_fused_source_marks_waiting_instead_of_reusing_wrong_depth() -> None:
    algorithm_rgb = np.full((120, 180, 3), 100, np.uint8)
    algorithm = ScriptedSource(tagged(42, algorithm_rgb))
    depth = RecordingDepthReader(tagged(41, depth_fixture()))
    source = SynchronizedCompositeSource(
        lambda: algorithm,
        lambda: depth,
        match_timeout_s=0,
    )

    source.open()
    frame = source.read()
    source.close()

    assert depth.requested_ids == [42]
    assert frame.frame_id == 42
    assert frame.image_rgb[60, 80].tolist() == [100, 100, 100]
    assert np.any(frame.image_rgb != 100)

