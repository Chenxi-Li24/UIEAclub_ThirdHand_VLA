"""Select one confirmed bottle by its user-visible stable ID."""

from __future__ import annotations

from dataclasses import dataclass

from thirdhand_va.common.contracts import TrackedBottle


@dataclass(frozen=True, slots=True)
class StableSelectionRequest:
    stable_id: int
    request_id: str

    def __post_init__(self) -> None:
        if not 1 <= self.stable_id <= 5:
            raise ValueError("stable_id must be in [1, 5]")
        if not self.request_id:
            raise ValueError("request_id must not be empty")


@dataclass(frozen=True, slots=True)
class StableSelectionResult:
    selected: TrackedBottle | None
    reasons: tuple[str, ...]


class StableBottleSelector:
    def select(
        self,
        tracks: tuple[TrackedBottle, ...],
        request: StableSelectionRequest,
    ) -> StableSelectionResult:
        matches = [track for track in tracks if track.stable_id == request.stable_id]
        if not matches:
            return StableSelectionResult(None, ("target_id_not_found",))
        track = matches[0]
        if track.state != "confirmed":
            return StableSelectionResult(None, (f"target_{track.state}",))
        return StableSelectionResult(track, ())


__all__ = [
    "StableBottleSelector",
    "StableSelectionRequest",
    "StableSelectionResult",
]
