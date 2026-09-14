import numpy as np

from thirdhand_va.common.contracts import MaskCandidate, TrackedBottle
from thirdhand_va.vision.selection.stable_selector import (
    StableBottleSelector,
    StableSelectionRequest,
)


def track(stable_id: int, state: str = "confirmed") -> TrackedBottle:
    mask = np.ones((8, 4), dtype=bool)
    return TrackedBottle(
        stable_id=stable_id,
        backend_track_id=100 + stable_id,
        state=state,
        candidate=MaskCandidate(
            detection_id=stable_id,
            label="bottle",
            score=0.9,
            bbox_xyxy=(0, 0, 4, 8),
            mask=mask,
            authorized=True,
        ),
        centroid_xy=(2.0, 4.0),
        depth_supported=True,
    )


def test_selector_uses_exact_stable_id_without_spatial_sorting() -> None:
    selector = StableBottleSelector()
    tracks = (track(3), track(1), track(2))

    result = selector.select(tracks, StableSelectionRequest(2, "req-2"))

    assert result.selected is tracks[2]
    assert result.reasons == ()


def test_selector_rejects_missing_or_nonconfirmed_target() -> None:
    selector = StableBottleSelector()

    assert selector.select((track(1),), StableSelectionRequest(2, "req-2")).reasons == (
        "target_id_not_found",
    )
    assert selector.select((track(2, "lost"),), StableSelectionRequest(2, "req-2")).reasons == (
        "target_lost",
    )
