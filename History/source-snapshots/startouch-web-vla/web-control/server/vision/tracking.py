"""Timestamp-aware 3D multi-object tracking with global assignment."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional, Sequence

import numpy as np
from scipy.optimize import linear_sum_assignment

from .types import InvalidDataError, TrackObservation, TrackState


@dataclass(frozen=True)
class TrackerConfig:
    max_distance_m: float
    max_age_ns: int
    min_confirmed_hits: int

    def __post_init__(self) -> None:
        if not np.isfinite(self.max_distance_m) or self.max_distance_m <= 0.0:
            raise InvalidDataError("max_distance_m must be finite and positive")
        if self.max_age_ns < 0:
            raise InvalidDataError("max_age_ns must be non-negative")
        if self.min_confirmed_hits < 1:
            raise InvalidDataError("min_confirmed_hits must be at least one")


@dataclass
class _TrackRecord:
    track_id: int
    label: str
    pose: object
    velocity_mps: np.ndarray
    hits: int
    misses: int
    confirmed: bool


class MultiObjectTracker:
    """Track robot-base positions without performing camera or robot I/O."""

    def __init__(self, config: TrackerConfig):
        self.config = config
        self._records: dict[int, _TrackRecord] = {}
        self._next_track_id = 1
        self._last_update_ns: Optional[int] = None
        self._calibration_id: Optional[str] = None

    def reset(self) -> None:
        """Clear state while intentionally never reusing process-local IDs."""

        self._records.clear()
        self._last_update_ns = None
        self._calibration_id = None

    def _validate_update(
        self,
        observations: Sequence[TrackObservation],
        now_ns: int,
    ) -> None:
        if not isinstance(now_ns, int) or now_ns < 0:
            raise InvalidDataError("now_ns must be a non-negative integer")
        if self._last_update_ns is not None and now_ns < self._last_update_ns:
            raise InvalidDataError("tracker time cannot move backwards")
        calibration_ids = set()
        for observation in observations:
            if observation.pose.frame != "robot_base":
                raise InvalidDataError("tracker observations must be in robot_base")
            if observation.pose.stamp.monotonic_ns > now_ns:
                raise InvalidDataError("observation timestamp cannot be in the future")
            calibration_ids.add(observation.pose.calibration_id)
        if len(calibration_ids) > 1:
            raise InvalidDataError("one tracker update cannot mix calibration IDs")
        if calibration_ids:
            incoming = next(iter(calibration_ids))
            if self._calibration_id is not None and incoming != self._calibration_id:
                raise InvalidDataError("calibration changed; reset tracker before continuing")

    @staticmethod
    def _predicted_xyz(record: _TrackRecord, timestamp_ns: int) -> np.ndarray:
        elapsed_ns = max(0, timestamp_ns - record.pose.stamp.monotonic_ns)
        return record.pose.xyz_m + record.velocity_mps * (elapsed_ns / 1e9)

    def _association_cost(
        self,
        records: Sequence[_TrackRecord],
        observations: Sequence[TrackObservation],
    ) -> np.ndarray:
        cost = np.full((len(records), len(observations)), np.inf)
        for row, record in enumerate(records):
            for column, observation in enumerate(observations):
                if record.label != observation.label:
                    continue
                predicted = self._predicted_xyz(record, observation.pose.stamp.monotonic_ns)
                delta = observation.pose.xyz_m - predicted
                distance = float(np.linalg.norm(delta))
                if distance > self.config.max_distance_m:
                    continue
                combined_covariance = record.pose.covariance_m2 + observation.pose.covariance_m2
                mahalanobis_squared = float(delta @ np.linalg.pinv(combined_covariance) @ delta)
                cost[row, column] = np.sqrt(max(0.0, mahalanobis_squared)) + distance * 1e-6
        return cost

    def _match(
        self,
        records: Sequence[_TrackRecord],
        observations: Sequence[TrackObservation],
    ) -> list[tuple[int, int]]:
        if not records or not observations:
            return []
        cost = self._association_cost(records, observations)
        rows, columns = linear_sum_assignment(np.where(np.isfinite(cost), cost, 1e12))
        return [
            (int(row), int(column))
            for row, column in zip(rows, columns)
            if np.isfinite(cost[row, column])
        ]

    def update(
        self,
        observations: Iterable[TrackObservation],
        now_ns: int,
    ) -> tuple[TrackState, ...]:
        observation_list = list(observations)
        self._validate_update(observation_list, now_ns)
        if observation_list and self._calibration_id is None:
            self._calibration_id = observation_list[0].pose.calibration_id

        expired = [
            track_id
            for track_id, record in self._records.items()
            if now_ns - record.pose.stamp.monotonic_ns > self.config.max_age_ns
        ]
        for track_id in expired:
            del self._records[track_id]

        records = [self._records[track_id] for track_id in sorted(self._records)]
        matches = self._match(records, observation_list)
        matched_record_rows = {row for row, _ in matches}
        matched_observations = {column for _, column in matches}

        for row, column in matches:
            record = records[row]
            observation = observation_list[column]
            elapsed_ns = observation.pose.stamp.monotonic_ns - record.pose.stamp.monotonic_ns
            if elapsed_ns > 0:
                velocity = (observation.pose.xyz_m - record.pose.xyz_m) / (elapsed_ns / 1e9)
            else:
                velocity = record.velocity_mps.copy()
            record.pose = observation.pose
            record.velocity_mps = velocity
            record.hits += 1
            record.misses = 0
            record.confirmed = record.confirmed or record.hits >= self.config.min_confirmed_hits

        for row, record in enumerate(records):
            if row not in matched_record_rows:
                record.misses += 1

        for column, observation in enumerate(observation_list):
            if column in matched_observations:
                continue
            track_id = self._next_track_id
            self._next_track_id += 1
            self._records[track_id] = _TrackRecord(
                track_id=track_id,
                label=observation.label,
                pose=observation.pose,
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
            for record in (self._records[track_id] for track_id in sorted(self._records))
        )
