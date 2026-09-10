"""Timestamp-aware constant-velocity 3D tracker with global assignment."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional

import numpy as np
from scipy.optimize import linear_sum_assignment

from thirdhand_vision.core.errors import InputValidationError
from thirdhand_vision.core.types import PoseEstimate


@dataclass(frozen=True)
class TrackerConfig:
    max_distance_m: float
    max_age_ns: int
    min_confirmed_hits: int

    def __post_init__(self) -> None:
        if not np.isfinite(self.max_distance_m) or self.max_distance_m <= 0.0:
            raise InputValidationError("tracker distance must be positive")
        if isinstance(self.max_age_ns, bool) or not isinstance(self.max_age_ns, int) or self.max_age_ns < 0:
            raise InputValidationError("tracker age must be a non-negative integer")
        if isinstance(self.min_confirmed_hits, bool) or not isinstance(self.min_confirmed_hits, int) or self.min_confirmed_hits < 1:
            raise InputValidationError("tracker confirmation hits must be positive")


@dataclass(frozen=True)
class TrackObservation:
    label: str
    pose: PoseEstimate

    def __post_init__(self) -> None:
        if not isinstance(self.label, str) or not self.label:
            raise InputValidationError("track label must be a non-empty string")
        if not isinstance(self.pose, PoseEstimate) or self.pose.frame != "robot_base":
            raise InputValidationError("track pose must be a robot_base PoseEstimate")


@dataclass(frozen=True)
class TrackState:
    track_id: int
    label: str
    pose: PoseEstimate
    velocity_mps: np.ndarray = field(compare=False, repr=False)
    hits: int
    misses: int
    confirmed: bool
    last_seen_ns: int

    def __post_init__(self) -> None:
        velocity = np.asarray(self.velocity_mps, dtype=float)
        if velocity.shape != (3,) or not np.isfinite(velocity).all():
            raise InputValidationError("track velocity must be a finite three-vector")
        result = np.array(velocity, copy=True)
        result.setflags(write=False)
        object.__setattr__(self, "velocity_mps", result)


@dataclass
class _TrackRecord:
    track_id: int
    label: str
    pose: PoseEstimate
    velocity_mps: np.ndarray
    hits: int
    misses: int
    confirmed: bool


class MultiObjectTracker:
    def __init__(self, config: TrackerConfig) -> None:
        self.config = config
        self._records: dict[int, _TrackRecord] = {}
        self._next_track_id = 1
        self._last_update_ns: Optional[int] = None
        self._calibration_id: Optional[str] = None

    def reset(self) -> None:
        self._records.clear()
        self._last_update_ns = None
        self._calibration_id = None

    @staticmethod
    def _predicted_xyz(record: _TrackRecord, timestamp_ns: int) -> np.ndarray:
        elapsed_ns = max(0, timestamp_ns - record.pose.stamp.monotonic_ns)
        return record.pose.xyz_m + record.velocity_mps * (elapsed_ns / 1e9)

    def _costs(
        self,
        records: list[_TrackRecord],
        observations: list[TrackObservation],
    ) -> np.ndarray:
        costs = np.full((len(records), len(observations)), np.inf)
        for row, record in enumerate(records):
            for column, observation in enumerate(observations):
                if record.label != observation.label:
                    continue
                predicted = self._predicted_xyz(record, observation.pose.stamp.monotonic_ns)
                delta = observation.pose.xyz_m - predicted
                distance = float(np.linalg.norm(delta))
                if distance > self.config.max_distance_m:
                    continue
                covariance = record.pose.covariance_m2 + observation.pose.covariance_m2
                mahalanobis_squared = float(delta @ np.linalg.pinv(covariance) @ delta)
                costs[row, column] = np.sqrt(max(0.0, mahalanobis_squared)) + distance * 1e-6
        return costs

    def update(
        self,
        observations: Iterable[TrackObservation],
        now_ns: int,
    ) -> tuple[TrackState, ...]:
        items = list(observations)
        if isinstance(now_ns, bool) or not isinstance(now_ns, int) or now_ns < 0:
            raise InputValidationError("tracker time must be a non-negative integer")
        if self._last_update_ns is not None and now_ns < self._last_update_ns:
            raise InputValidationError("tracker time cannot move backwards")
        if any(not isinstance(item, TrackObservation) for item in items):
            raise InputValidationError("tracker observations are invalid")
        calibration_ids = {item.pose.calibration_id for item in items}
        if len(calibration_ids) > 1:
            raise InputValidationError("tracker update cannot mix calibration IDs")
        if calibration_ids:
            incoming = next(iter(calibration_ids))
            if self._calibration_id is not None and incoming != self._calibration_id:
                raise InputValidationError("tracker calibration changed; reset is required")
            self._calibration_id = incoming
        expired = [
            track_id
            for track_id, record in self._records.items()
            if now_ns - record.pose.stamp.monotonic_ns > self.config.max_age_ns
        ]
        for track_id in expired:
            del self._records[track_id]
        records = [self._records[key] for key in sorted(self._records)]
        costs = self._costs(records, items)
        matches: list[tuple[int, int]] = []
        if records and items:
            rows, columns = linear_sum_assignment(np.where(np.isfinite(costs), costs, 1e12))
            matches = [
                (int(row), int(column))
                for row, column in zip(rows, columns)
                if np.isfinite(costs[row, column])
            ]
        matched_rows = {row for row, _ in matches}
        matched_columns = {column for _, column in matches}
        for row, column in matches:
            record = records[row]
            item = items[column]
            elapsed_ns = item.pose.stamp.monotonic_ns - record.pose.stamp.monotonic_ns
            if elapsed_ns > 0:
                record.velocity_mps = (
                    item.pose.xyz_m - record.pose.xyz_m
                ) / (elapsed_ns / 1e9)
            record.pose = item.pose
            record.hits += 1
            record.misses = 0
            record.confirmed = record.confirmed or record.hits >= self.config.min_confirmed_hits
        for row, record in enumerate(records):
            if row not in matched_rows:
                record.misses += 1
        for column, item in enumerate(items):
            if column in matched_columns:
                continue
            track_id = self._next_track_id
            self._next_track_id += 1
            self._records[track_id] = _TrackRecord(
                track_id=track_id,
                label=item.label,
                pose=item.pose,
                velocity_mps=np.zeros(3),
                hits=1,
                misses=0,
                confirmed=self.config.min_confirmed_hits == 1,
            )
        self._last_update_ns = now_ns
        return tuple(
            TrackState(
                track_id=record.track_id,
                label=record.label,
                pose=record.pose,
                velocity_mps=record.velocity_mps,
                hits=record.hits,
                misses=record.misses,
                confirmed=record.confirmed,
                last_seen_ns=record.pose.stamp.monotonic_ns,
            )
            for record in (self._records[key] for key in sorted(self._records))
        )
