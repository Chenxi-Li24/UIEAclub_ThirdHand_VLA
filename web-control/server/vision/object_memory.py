"""Bounded robot-base object memory with explicit freshness and stability."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

import numpy as np

from .types import InvalidDataError, TrackState


@dataclass(frozen=True)
class ObjectMemoryConfig:
    max_age_ns: int
    max_position_std_m: float
    min_hits: int
    max_objects: int = 128

    def __post_init__(self) -> None:
        if self.max_age_ns < 0:
            raise InvalidDataError("max_age_ns must be non-negative")
        if not np.isfinite(self.max_position_std_m) or self.max_position_std_m <= 0.0:
            raise InvalidDataError("max_position_std_m must be finite and positive")
        if self.min_hits < 1:
            raise InvalidDataError("min_hits must be at least one")
        if self.max_objects < 1:
            raise InvalidDataError("max_objects must be at least one")


class ObjectMemory:
    def __init__(self, config: ObjectMemoryConfig):
        self.config = config
        self._tracks: dict[int, TrackState] = {}
        self._calibration_id: Optional[str] = None
        self._last_now_ns: Optional[int] = None

    def _validate_now(self, now_ns: int) -> None:
        if not isinstance(now_ns, int) or now_ns < 0:
            raise InvalidDataError("now_ns must be a non-negative integer")
        if self._last_now_ns is not None and now_ns < self._last_now_ns:
            raise InvalidDataError("object-memory time cannot move backwards")

    def _drop_expired(self, now_ns: int) -> None:
        expired = [
            track_id
            for track_id, track in self._tracks.items()
            if now_ns - track.last_seen_ns > self.config.max_age_ns
        ]
        for track_id in expired:
            del self._tracks[track_id]

    def set_calibration(self, calibration_id: str) -> None:
        if not calibration_id.startswith("sha256:"):
            raise InvalidDataError("calibration_id must start with sha256:")
        if self._calibration_id is not None and calibration_id != self._calibration_id:
            self._tracks.clear()
        self._calibration_id = calibration_id

    def ingest(self, tracks: Iterable[TrackState], now_ns: int) -> None:
        track_list = list(tracks)
        self._validate_now(now_ns)
        calibration_ids = set()
        for track in track_list:
            if track.pose.frame != "robot_base":
                raise InvalidDataError("object memory accepts robot_base tracks only")
            if track.last_seen_ns > now_ns:
                raise InvalidDataError("track timestamp cannot be in the future")
            calibration_ids.add(track.pose.calibration_id)
        if len(calibration_ids) > 1:
            raise InvalidDataError("one ingest cannot mix calibration IDs")
        if calibration_ids:
            incoming = next(iter(calibration_ids))
            if self._calibration_id is None:
                self._calibration_id = incoming
            elif incoming != self._calibration_id:
                raise InvalidDataError("call set_calibration before ingesting a new calibration")
        self._drop_expired(now_ns)
        for track in track_list:
            self._tracks[track.track_id] = track
        overflow = len(self._tracks) - self.config.max_objects
        if overflow > 0:
            oldest = sorted(
                self._tracks.values(),
                key=lambda item: (item.last_seen_ns, item.track_id),
            )[:overflow]
            for track in oldest:
                del self._tracks[track.track_id]
        self._last_now_ns = now_ns

    def get(self, track_id: int, now_ns: int) -> Optional[TrackState]:
        self._validate_now(now_ns)
        self._drop_expired(now_ns)
        self._last_now_ns = now_ns
        return self._tracks.get(track_id)

    def select_stable(self, label: str, now_ns: int) -> tuple[TrackState, ...]:
        self._validate_now(now_ns)
        self._drop_expired(now_ns)
        self._last_now_ns = now_ns
        candidates = []
        for track in self._tracks.values():
            covariance_eigenvalues = np.linalg.eigvalsh(track.pose.covariance_m2)
            position_std_m = float(np.sqrt(max(0.0, np.max(covariance_eigenvalues))))
            if (
                track.label == label
                and track.confirmed
                and track.hits >= self.config.min_hits
                and position_std_m <= self.config.max_position_std_m
            ):
                candidates.append(track)
        return tuple(
            sorted(
                candidates,
                key=lambda item: (float(np.trace(item.pose.covariance_m2)), item.track_id),
            )
        )

