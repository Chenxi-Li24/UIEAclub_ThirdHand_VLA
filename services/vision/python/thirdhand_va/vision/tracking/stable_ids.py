"""Deterministic user-visible bottle IDs and request-bound reservations."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from thirdhand_va.common.config import VisionConfig
from thirdhand_va.common.contracts import MaskCandidate, TrackedBottle

from .norfair_adapter import NorfairTrackerAdapter, Point3, tracking_centroid


@dataclass(slots=True)
class _TrackRecord:
    backend_track_id: int
    candidate: MaskCandidate
    centroid_xy: tuple[float, float]
    last_seen_ns: int
    hits: int = 1
    stable_id: int | None = None
    state: str = "tentative"
    depth_supported: bool = False
    blockers: tuple[str, ...] = field(default_factory=tuple)
    world_point: Point3 | None = None


class StableTrackManager:
    def __init__(
        self,
        *,
        adapter: NorfairTrackerAdapter,
        confirmation_hits: int,
        lost_timeout_ms: int,
        capacity: int = 5,
        ambiguity_margin: float = 0.05,
    ) -> None:
        if confirmation_hits <= 0 or lost_timeout_ms <= 0 or capacity <= 0 or not (
            0.0 <= ambiguity_margin <= 1.0
        ):
            raise ValueError("stable tracking limits must be positive")
        self._adapter = adapter
        self._confirmation_hits = confirmation_hits
        self._lost_timeout_ns = lost_timeout_ms * 1_000_000
        self._capacity = capacity
        self._ambiguity_margin_m = (
            float(ambiguity_margin) * self._adapter.max_point_distance_m
        )
        self._records: dict[int, _TrackRecord] = {}
        self._reservation: tuple[int, str] | None = None
        self._reserved_world_anchor: Point3 | None = None

    @classmethod
    def from_config(cls, config: VisionConfig) -> "StableTrackManager":
        return cls(
            adapter=NorfairTrackerAdapter.from_config(config),
            confirmation_hits=config.track_confirmation_hits,
            lost_timeout_ms=config.track_lost_timeout_ms,
            capacity=config.max_visible_tracks,
            ambiguity_margin=config.track_ambiguity_margin,
        )

    @property
    def available_ids(self) -> tuple[int, ...]:
        occupied = {
            record.stable_id
            for record in self._records.values()
            if record.stable_id is not None and record.state != "retired"
        }
        if self._reservation is not None:
            occupied.add(self._reservation[0])
        return tuple(value for value in range(1, self._capacity + 1) if value not in occupied)

    @property
    def reservation(self) -> tuple[int, str] | None:
        return self._reservation

    @property
    def reserved_world_anchor_available(self) -> bool:
        return self._reservation is None or self._reserved_world_anchor is not None

    def update(
        self,
        candidates: tuple[MaskCandidate, ...],
        *,
        now_ns: int,
        camera_moving: bool,
        camera_points: Mapping[int, Point3] | None = None,
        world_points: Mapping[int, Point3] | None = None,
        candidate_blockers: Mapping[int, tuple[str, ...]] | None = None,
    ) -> tuple[TrackedBottle, ...]:
        if not isinstance(now_ns, int) or now_ns < 0:
            raise ValueError("now_ns must be a non-negative integer")
        world_points = world_points or {}
        candidates = self._reject_ambiguous_world_associations(candidates, world_points)
        associations = self._adapter.update(
            candidates,
            camera_moving=camera_moving,
            camera_points=camera_points,
            world_points=world_points,
        )
        candidate_blockers = candidate_blockers or {}
        seen: set[int] = set()
        for association in associations:
            world_point = world_points.get(association.candidate.detection_id)
            existing = self._records.get(association.backend_track_id)
            if (
                self._reservation is not None
                and existing is not None
                and existing.stable_id == self._reservation[0]
                and self._reserved_world_anchor is not None
                and world_point is not None
                and _distance(world_point, self._reserved_world_anchor)
                > self._adapter.max_point_distance_m
            ):
                continue
            seen.add(association.backend_track_id)
            record = self._records.get(association.backend_track_id)
            depth_supported = bool(
                association.candidate.authorized
                and (
                    camera_points is None
                    or association.candidate.detection_id in camera_points
                )
            )
            blockers = tuple(
                candidate_blockers.get(
                    association.candidate.detection_id,
                    association.candidate.reasons,
                )
            )
            if record is None:
                record = _TrackRecord(
                    backend_track_id=association.backend_track_id,
                    candidate=association.candidate,
                    centroid_xy=tracking_centroid(association.candidate.mask),
                    last_seen_ns=now_ns,
                    depth_supported=depth_supported,
                    blockers=blockers,
                    world_point=world_point,
                )
                self._records[association.backend_track_id] = record
            else:
                record.candidate = association.candidate
                record.centroid_xy = tracking_centroid(association.candidate.mask)
                record.last_seen_ns = now_ns
                record.hits += 1
                record.depth_supported = depth_supported
                record.blockers = blockers
                if world_point is not None:
                    record.world_point = world_point
            if record.hits >= self._confirmation_hits:
                if record.stable_id is None:
                    available = self.available_ids
                    if available:
                        record.stable_id = available[0]
                    else:
                        record.blockers = tuple(dict.fromkeys(
                            record.blockers + ("unnumbered_capacity_exceeded",)
                        ))
                record.state = "confirmed"
            else:
                record.state = "tentative"
            if (
                self._reservation is not None
                and record.stable_id == self._reservation[0]
                and self._reserved_world_anchor is None
                and record.world_point is not None
            ):
                self._reserved_world_anchor = record.world_point

        to_remove: list[int] = []
        for backend_id, record in self._records.items():
            if backend_id in seen:
                continue
            elapsed = now_ns - record.last_seen_ns
            if elapsed <= self._lost_timeout_ns:
                record.state = "occluded" if record.stable_id is not None else "tentative"
                continue
            reserved = (
                self._reservation is not None
                and record.stable_id == self._reservation[0]
            )
            if reserved:
                record.state = "lost"
                record.blockers = tuple(sorted(set(record.blockers + ("target_lost",))))
            else:
                record.state = "retired"
                to_remove.append(backend_id)
        for backend_id in to_remove:
            self._records.pop(backend_id, None)
        return self._snapshots()

    def reserve(self, stable_id: int, request_id: str) -> bool:
        if not request_id or not isinstance(stable_id, int):
            return False
        if self._reservation == (stable_id, request_id):
            return True
        if self._reservation is not None:
            return False
        record = self._track_by_stable_id(stable_id)
        if record is None or record.state != "confirmed":
            return False
        self._reservation = (stable_id, request_id)
        self._reserved_world_anchor = record.world_point
        return True

    def release(self, request_id: str) -> None:
        if self._reservation is None or self._reservation[1] != request_id:
            return
        stable_id = self._reservation[0]
        self._reservation = None
        self._reserved_world_anchor = None
        for backend_id, record in tuple(self._records.items()):
            if record.stable_id == stable_id and record.state in {"lost", "retired"}:
                self._records.pop(backend_id, None)

    def _track_by_stable_id(self, stable_id: int) -> _TrackRecord | None:
        return next(
            (record for record in self._records.values() if record.stable_id == stable_id),
            None,
        )

    def _reject_ambiguous_world_associations(
        self,
        candidates: tuple[MaskCandidate, ...],
        world_points: Mapping[int, Point3],
    ) -> tuple[MaskCandidate, ...]:
        anchors = [
            record.world_point
            for record in self._records.values()
            if record.state != "retired" and record.world_point is not None
        ]
        rejected_ids: set[int] = set()
        if len(anchors) >= 2:
            for candidate in candidates:
                point = world_points.get(candidate.detection_id)
                if point is None:
                    continue
                distances = sorted(_distance(point, anchor) for anchor in anchors)
                if distances[1] - distances[0] <= self._ambiguity_margin_m:
                    rejected_ids.add(candidate.detection_id)
        if self._reserved_world_anchor is not None:
            ranked = sorted(
                (
                    _distance(point, self._reserved_world_anchor), detection_id
                )
                for detection_id, point in world_points.items()
            )
            if ranked and (
                ranked[0][0] > self._adapter.max_point_distance_m
                or (
                    len(ranked) > 1
                    and ranked[1][0] - ranked[0][0] <= self._ambiguity_margin_m
                )
            ):
                rejected_ids.update(detection_id for _, detection_id in ranked[:2])
        return tuple(
            candidate for candidate in candidates
            if candidate.detection_id not in rejected_ids
        )

    def _snapshots(self) -> tuple[TrackedBottle, ...]:
        snapshots = [
            TrackedBottle(
                stable_id=record.stable_id,
                backend_track_id=record.backend_track_id,
                state=record.state,  # type: ignore[arg-type]
                candidate=record.candidate,
                centroid_xy=record.centroid_xy,
                depth_supported=record.depth_supported,
                blockers=record.blockers,
            )
            for record in self._records.values()
        ]
        snapshots.sort(
            key=lambda item: (
                item.stable_id is None,
                item.stable_id if item.stable_id is not None else item.backend_track_id,
            )
        )
        return tuple(snapshots)


__all__ = ["StableTrackManager"]


def _distance(left: Point3, right: Point3) -> float:
    return sum((a - b) ** 2 for a, b in zip(left, right, strict=True)) ** 0.5
