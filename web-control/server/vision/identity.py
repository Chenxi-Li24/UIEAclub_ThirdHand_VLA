"""Persistent appearance identity with conservative RGB-D association."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Optional

import numpy as np
from scipy.optimize import linear_sum_assignment

from .types import CalibrationRef, FrameStamp, InvalidDataError, PoseEstimate


class IdentityStatus(str, Enum):
    TENTATIVE = "tentative"
    CONFIRMED = "confirmed"
    OCCLUDED = "occluded"
    INACTIVE = "inactive"
    AMBIGUOUS = "ambiguous"


def _finite_assignment(costs: np.ndarray) -> list[tuple[int, int]]:
    """Return a maximum-cardinality, minimum-cost finite assignment."""

    row_count, column_count = costs.shape
    if row_count == 0 or column_count == 0:
        return []
    unmatched_cost = 1e6
    forbidden_cost = 1e12
    size = row_count + column_count
    augmented = np.full((size, size), forbidden_cost, dtype=float)
    augmented[:row_count, :column_count] = np.where(
        np.isfinite(costs), costs, forbidden_cost
    )
    for row in range(row_count):
        augmented[row, column_count + row] = unmatched_cost
    for column in range(column_count):
        augmented[row_count + column, column] = unmatched_cost
    augmented[row_count:, column_count:] = 0.0
    rows, columns = linear_sum_assignment(augmented)
    return sorted(
        (int(row), int(column))
        for row, column in zip(rows, columns)
        if row < row_count
        and column < column_count
        and np.isfinite(costs[int(row), int(column)])
    )


def _global_ambiguity_reasons(
    costs: np.ndarray,
    ambiguity_margin: float,
) -> dict[int, str]:
    """Reject observations whose full assignment has a near-equal alternative."""

    best = _finite_assignment(costs)
    if not best:
        return {}
    best_cost = sum(float(costs[row, column]) for row, column in best)
    best_by_column = {column: row for row, column in best}
    reasons: dict[int, str] = {}
    for forbidden_row, forbidden_column in best:
        alternative_costs = np.array(costs, copy=True)
        alternative_costs[forbidden_row, forbidden_column] = np.inf
        alternative = _finite_assignment(alternative_costs)
        if len(alternative) != len(best):
            continue
        alternative_cost = sum(
            float(costs[row, column]) for row, column in alternative
        )
        if alternative_cost - best_cost > ambiguity_margin + 1e-12:
            continue
        alternative_by_column = {column: row for row, column in alternative}
        changed_columns = {
            column
            for column in range(costs.shape[1])
            if best_by_column.get(column) != alternative_by_column.get(column)
        }
        competition = any(
            column not in best_by_column or column not in alternative_by_column
            for column in changed_columns
        )
        reason = (
            "observations_compete_for_identity"
            if competition
            else "appearance_candidates_within_margin"
        )
        for column in changed_columns:
            reasons.setdefault(column, reason)
    return reasons


def _normalized_descriptor(value: object) -> np.ndarray:
    array = np.asarray(value, dtype=float)
    if array.ndim != 1 or array.size == 0:
        raise InvalidDataError("descriptor must be a non-empty 1D vector")
    if not np.isfinite(array).all():
        raise InvalidDataError("descriptor must contain only finite values")
    norm = float(np.linalg.norm(array))
    if norm <= 0.0:
        raise InvalidDataError("descriptor norm must be positive")
    result = np.array(array / norm, copy=True)
    result.setflags(write=False)
    return result


@dataclass(frozen=True)
class IdentityObservation:
    observation_id: int
    label: str
    confidence: float
    visibility: float
    descriptor: np.ndarray
    stamp: FrameStamp
    pose: Optional[PoseEstimate] = None

    def __post_init__(self) -> None:
        confidence = float(self.confidence)
        visibility = float(self.visibility)
        if self.observation_id < 0 or not self.label:
            raise InvalidDataError("observation identity and label must be valid")
        if not np.isfinite([confidence, visibility]).all():
            raise InvalidDataError("confidence and visibility must be finite")
        if not 0.0 <= confidence <= 1.0 or not 0.0 <= visibility <= 1.0:
            raise InvalidDataError("confidence and visibility must be within [0, 1]")
        if self.pose is not None:
            if self.pose.frame != "robot_base":
                raise InvalidDataError("identity pose must be in robot_base")
            if self.pose.stamp.monotonic_ns != self.stamp.monotonic_ns:
                raise InvalidDataError("identity pose and appearance stamps must match")
        object.__setattr__(self, "confidence", confidence)
        object.__setattr__(self, "visibility", visibility)
        object.__setattr__(self, "descriptor", _normalized_descriptor(self.descriptor))


@dataclass(frozen=True)
class PersistentIdentityConfig:
    max_cosine_distance: float
    ambiguity_margin: float
    appearance_weight: float
    position_weight: float
    max_position_distance_m: float
    position_gate_max_age_ns: int
    occluded_after_ns: int
    inactive_after_ns: int
    min_confirmed_hits: int
    min_memory_confidence: float
    min_memory_visibility: float
    work_bank_size: int
    stable_bank_size: int
    max_identities: int
    reacquire_confirmed_hits: int = 2
    max_actionable_position_std_m: float = 0.025
    max_actionable_pose_age_ns: int = 200_000_000

    def __post_init__(self) -> None:
        finite = (
            self.max_cosine_distance,
            self.ambiguity_margin,
            self.appearance_weight,
            self.position_weight,
            self.max_position_distance_m,
            self.min_memory_confidence,
            self.min_memory_visibility,
            self.max_actionable_position_std_m,
        )
        if not np.isfinite(finite).all():
            raise InvalidDataError("identity configuration must be finite")
        if not 0.0 < self.max_cosine_distance <= 2.0:
            raise InvalidDataError("max_cosine_distance must be within (0, 2]")
        if self.ambiguity_margin < 0.0:
            raise InvalidDataError("ambiguity_margin must be non-negative")
        if self.appearance_weight < 0.0 or self.position_weight < 0.0:
            raise InvalidDataError("association weights must be non-negative")
        if self.appearance_weight + self.position_weight <= 0.0:
            raise InvalidDataError("at least one association weight must be positive")
        if self.max_position_distance_m <= 0.0:
            raise InvalidDataError("max_position_distance_m must be positive")
        if self.position_gate_max_age_ns < 0:
            raise InvalidDataError("position_gate_max_age_ns must be non-negative")
        if self.occluded_after_ns < 0 or self.inactive_after_ns < self.occluded_after_ns:
            raise InvalidDataError("identity state ages are invalid")
        if self.min_confirmed_hits < 1:
            raise InvalidDataError("min_confirmed_hits must be at least one")
        if not 0.0 <= self.min_memory_confidence <= 1.0:
            raise InvalidDataError("min_memory_confidence must be within [0, 1]")
        if not 0.0 <= self.min_memory_visibility <= 1.0:
            raise InvalidDataError("min_memory_visibility must be within [0, 1]")
        if self.work_bank_size < 1 or self.stable_bank_size < 1:
            raise InvalidDataError("prototype bank sizes must be positive")
        if self.max_identities < 1:
            raise InvalidDataError("max_identities must be positive")
        if self.reacquire_confirmed_hits < 1:
            raise InvalidDataError("reacquire_confirmed_hits must be at least one")
        if self.max_actionable_position_std_m <= 0.0:
            raise InvalidDataError("max_actionable_position_std_m must be positive")
        if self.max_actionable_pose_age_ns < 0:
            raise InvalidDataError("max_actionable_pose_age_ns must be non-negative")


@dataclass(frozen=True)
class IdentityAssignment:
    observation_id: int
    identity_id: Optional[int]
    status: IdentityStatus
    cost: Optional[float]
    reason: Optional[str] = None


@dataclass(frozen=True)
class IdentitySnapshot:
    identity_id: int
    label: str
    status: IdentityStatus
    hits: int
    last_seen_ns: int
    work_prototype_count: int
    stable_prototype_count: int
    pose: Optional[PoseEstimate]
    actionable: bool


@dataclass(frozen=True)
class IdentityUpdate:
    assignments: tuple[IdentityAssignment, ...]
    snapshots: tuple[IdentitySnapshot, ...]


@dataclass
class _IdentityRecord:
    identity_id: int
    label: str
    work_bank: list[np.ndarray]
    stable_bank: list[np.ndarray]
    hits: int
    last_seen_ns: int
    current_pose: Optional[PoseEstimate]
    association_pose: Optional[PoseEstimate]
    association_pose_ns: Optional[int]
    confirmed: bool
    reacquiring: bool
    reacquire_hits: int


class PersistentIdentityMemory:
    """Bounded physical-instance memory with explicit ambiguity rejection."""

    def __init__(self, config: PersistentIdentityConfig):
        self.config = config
        self._records: dict[int, _IdentityRecord] = {}
        self._next_identity_id = 1
        self._descriptor_dimension: Optional[int] = None
        self._last_now_ns: Optional[int] = None
        self._calibration: Optional[CalibrationRef] = None

    def _validate_now(self, now_ns: int) -> None:
        if not isinstance(now_ns, int) or now_ns < 0:
            raise InvalidDataError("now_ns must be a non-negative integer")
        if self._last_now_ns is not None and now_ns < self._last_now_ns:
            raise InvalidDataError("identity-memory time cannot move backwards")

    def _validate_observations(
        self,
        observations: list[IdentityObservation],
        now_ns: int,
    ) -> None:
        observation_ids = [item.observation_id for item in observations]
        if len(set(observation_ids)) != len(observation_ids):
            raise InvalidDataError("observation IDs must be unique within an update")
        timestamps = {item.stamp.monotonic_ns for item in observations}
        if len(timestamps) > 1:
            raise InvalidDataError("one identity update cannot mix frame timestamps")
        calibration_ids = set()
        for item in observations:
            if item.stamp.monotonic_ns > now_ns:
                raise InvalidDataError("identity observation cannot be from the future")
            if (
                self._descriptor_dimension is not None
                and len(item.descriptor) != self._descriptor_dimension
            ):
                raise InvalidDataError("descriptor dimension changed; reset the identity process")
            if item.pose is not None:
                calibration_ids.add(item.pose.calibration_id)
        if len(calibration_ids) > 1:
            raise InvalidDataError("one identity update cannot mix calibration IDs")
        if calibration_ids:
            incoming = next(iter(calibration_ids))
            if self._calibration is None:
                self._calibration = CalibrationRef(incoming, False, None)
            elif incoming != self._calibration.calibration_id:
                raise InvalidDataError("call set_calibration before using a new calibration")

    def _status(self, record: _IdentityRecord, now_ns: int) -> IdentityStatus:
        age = now_ns - record.last_seen_ns
        if age >= self.config.inactive_after_ns:
            return IdentityStatus.INACTIVE
        if age >= self.config.occluded_after_ns:
            return IdentityStatus.OCCLUDED
        if record.reacquiring:
            return IdentityStatus.TENTATIVE
        return IdentityStatus.CONFIRMED if record.confirmed else IdentityStatus.TENTATIVE

    @staticmethod
    def _appearance_cost(record: _IdentityRecord, descriptor: np.ndarray) -> float:
        prototypes = record.stable_bank + record.work_bank
        return min(max(0.0, 1.0 - float(prototype @ descriptor)) for prototype in prototypes)

    def _association_cost(
        self,
        records: list[_IdentityRecord],
        observations: list[IdentityObservation],
    ) -> np.ndarray:
        costs = np.full((len(records), len(observations)), np.inf)
        for row, record in enumerate(records):
            for column, observation in enumerate(observations):
                if record.label != observation.label:
                    continue
                appearance = self._appearance_cost(record, observation.descriptor)
                if appearance > self.config.max_cosine_distance:
                    continue
                weighted_cost = self.config.appearance_weight * appearance
                total_weight = self.config.appearance_weight
                if (
                    record.association_pose is not None
                    and observation.pose is not None
                    and record.association_pose_ns is not None
                    and observation.stamp.monotonic_ns - record.association_pose_ns
                    <= self.config.position_gate_max_age_ns
                ):
                    distance = float(
                        np.linalg.norm(
                            observation.pose.xyz_m - record.association_pose.xyz_m
                        )
                    )
                    if distance > self.config.max_position_distance_m:
                        continue
                    weighted_cost += self.config.position_weight * (
                        distance / self.config.max_position_distance_m
                    )
                    total_weight += self.config.position_weight
                if total_weight <= 0.0:
                    continue
                costs[row, column] = weighted_cost / total_weight
        return costs

    def _quality_allows_memory_update(self, observation: IdentityObservation) -> bool:
        return (
            observation.confidence >= self.config.min_memory_confidence
            and observation.visibility >= self.config.min_memory_visibility
        )

    @staticmethod
    def _append_bounded(bank: list[np.ndarray], descriptor: np.ndarray, capacity: int) -> None:
        bank.append(np.array(descriptor, copy=True))
        while len(bank) > capacity:
            bank.pop(0)

    def _evict_inactive_for_capacity(self, now_ns: int) -> bool:
        if len(self._records) < self.config.max_identities:
            return True
        inactive = [
            record
            for record in self._records.values()
            if self._status(record, now_ns) is IdentityStatus.INACTIVE
        ]
        if not inactive:
            return False
        victim = min(inactive, key=lambda item: (item.last_seen_ns, item.identity_id))
        del self._records[victim.identity_id]
        return True

    def _new_record(
        self,
        observation: IdentityObservation,
        now_ns: int,
    ) -> Optional[_IdentityRecord]:
        if not self._evict_inactive_for_capacity(now_ns):
            return None
        identity_id = self._next_identity_id
        self._next_identity_id += 1
        descriptor = np.array(observation.descriptor, copy=True)
        confirmed = self.config.min_confirmed_hits == 1
        stable = [np.array(descriptor, copy=True)] if confirmed else []
        record = _IdentityRecord(
            identity_id=identity_id,
            label=observation.label,
            work_bank=[descriptor],
            stable_bank=stable,
            hits=1,
            last_seen_ns=observation.stamp.monotonic_ns,
            current_pose=observation.pose,
            association_pose=observation.pose,
            association_pose_ns=None
            if observation.pose is None
            else observation.stamp.monotonic_ns,
            confirmed=confirmed,
            reacquiring=False,
            reacquire_hits=0,
        )
        self._records[identity_id] = record
        return record

    def _snapshot(self, record: _IdentityRecord, now_ns: int) -> IdentitySnapshot:
        status = self._status(record, now_ns)
        pose = record.current_pose if record.last_seen_ns == now_ns else None
        calibration_valid = (
            self._calibration is not None
            and self._calibration.validated
            and pose is not None
            and pose.calibration_id == self._calibration.calibration_id
        )
        position_std_m = (
            float(np.sqrt(max(0.0, np.max(np.linalg.eigvalsh(pose.covariance_m2)))))
            if pose is not None
            else np.inf
        )
        actionable = (
            status is IdentityStatus.CONFIRMED
            and pose is not None
            and calibration_valid
            and now_ns - pose.stamp.monotonic_ns
            <= self.config.max_actionable_pose_age_ns
            and position_std_m <= self.config.max_actionable_position_std_m
        )
        return IdentitySnapshot(
            identity_id=record.identity_id,
            label=record.label,
            status=status,
            hits=record.hits,
            last_seen_ns=record.last_seen_ns,
            work_prototype_count=len(record.work_bank),
            stable_prototype_count=len(record.stable_bank),
            pose=pose,
            actionable=actionable,
        )

    def update(
        self,
        observations: Iterable[IdentityObservation],
        now_ns: int,
    ) -> IdentityUpdate:
        observation_list = list(observations)
        self._validate_now(now_ns)
        self._validate_observations(observation_list, now_ns)
        trusted_dimensions = {
            len(item.descriptor)
            for item in observation_list
            if self._quality_allows_memory_update(item)
        }
        if self._descriptor_dimension is None:
            if len(trusted_dimensions) > 1:
                raise InvalidDataError(
                    "trusted observations cannot mix descriptor dimensions"
                )
            if trusted_dimensions:
                self._descriptor_dimension = next(iter(trusted_dimensions))

        records = [self._records[key] for key in sorted(self._records)]
        costs = self._association_cost(records, observation_list)
        ambiguous_reasons = _global_ambiguity_reasons(
            costs,
            self.config.ambiguity_margin,
        )
        ambiguous_columns = set(ambiguous_reasons)

        matches: list[tuple[int, int]] = []
        eligible_columns = [
            column for column in range(len(observation_list)) if column not in ambiguous_columns
        ]
        if records and eligible_columns:
            eligible_costs = costs[:, eligible_columns]
            for row, local_column in _finite_assignment(eligible_costs):
                column = eligible_columns[int(local_column)]
                matches.append((int(row), column))

        assignments: dict[int, IdentityAssignment] = {}
        matched_columns = {column for _, column in matches}
        for row, column in matches:
            record = records[row]
            observation = observation_list[column]
            if not self._quality_allows_memory_update(observation):
                assignments[column] = IdentityAssignment(
                    observation_id=observation.observation_id,
                    identity_id=record.identity_id,
                    status=IdentityStatus.TENTATIVE,
                    cost=float(costs[row, column]),
                    reason="low_quality_association",
                )
                continue
            was_inactive = self._status(record, observation.stamp.monotonic_ns) is (
                IdentityStatus.INACTIVE
            )
            record.hits += 1
            record.last_seen_ns = observation.stamp.monotonic_ns
            record.current_pose = observation.pose
            if observation.pose is not None:
                record.association_pose = observation.pose
                record.association_pose_ns = observation.stamp.monotonic_ns
            record.confirmed = record.confirmed or record.hits >= self.config.min_confirmed_hits
            if was_inactive:
                record.reacquire_hits = 1 if observation.pose is not None else 0
                record.reacquiring = (
                    record.reacquire_hits < self.config.reacquire_confirmed_hits
                )
            elif record.reacquiring:
                if observation.pose is None:
                    record.reacquire_hits = 0
                else:
                    record.reacquire_hits += 1
                if record.reacquire_hits >= self.config.reacquire_confirmed_hits:
                    record.reacquiring = False
            self._append_bounded(
                record.work_bank,
                observation.descriptor,
                self.config.work_bank_size,
            )
            if record.confirmed:
                self._append_bounded(
                    record.stable_bank,
                    observation.descriptor,
                    self.config.stable_bank_size,
                )
            assignments[column] = IdentityAssignment(
                observation_id=observation.observation_id,
                identity_id=record.identity_id,
                status=IdentityStatus.CONFIRMED
                if record.confirmed and not record.reacquiring
                else IdentityStatus.TENTATIVE,
                cost=float(costs[row, column]),
            )

        for column, observation in enumerate(observation_list):
            if column in ambiguous_columns:
                assignments[column] = IdentityAssignment(
                    observation_id=observation.observation_id,
                    identity_id=None,
                    status=IdentityStatus.AMBIGUOUS,
                    cost=None,
                    reason=ambiguous_reasons[column],
                )
            elif column not in matched_columns:
                if not self._quality_allows_memory_update(observation):
                    assignments[column] = IdentityAssignment(
                        observation_id=observation.observation_id,
                        identity_id=None,
                        status=IdentityStatus.AMBIGUOUS,
                        cost=None,
                        reason="observation_below_memory_quality",
                    )
                    continue
                record = self._new_record(observation, now_ns)
                if record is None:
                    assignments[column] = IdentityAssignment(
                        observation_id=observation.observation_id,
                        identity_id=None,
                        status=IdentityStatus.AMBIGUOUS,
                        cost=None,
                        reason="identity_capacity_reached",
                    )
                else:
                    assignments[column] = IdentityAssignment(
                        observation_id=observation.observation_id,
                        identity_id=record.identity_id,
                        status=IdentityStatus.CONFIRMED
                        if record.confirmed
                        else IdentityStatus.TENTATIVE,
                        cost=None,
                        reason="new_identity",
                    )

        self._last_now_ns = now_ns
        return IdentityUpdate(
            assignments=tuple(assignments[index] for index in range(len(observation_list))),
            snapshots=tuple(
                self._snapshot(self._records[key], now_ns) for key in sorted(self._records)
            ),
        )

    def snapshots(self, now_ns: int) -> tuple[IdentitySnapshot, ...]:
        self._validate_now(now_ns)
        self._last_now_ns = now_ns
        return tuple(self._snapshot(self._records[key], now_ns) for key in sorted(self._records))

    def set_calibration(self, calibration: CalibrationRef | str) -> None:
        if isinstance(calibration, str):
            calibration = CalibrationRef(calibration, False, None)
        if not isinstance(calibration, CalibrationRef):
            raise InvalidDataError("calibration must be a CalibrationRef or calibration ID")
        if (
            self._calibration is not None
            and calibration.calibration_id != self._calibration.calibration_id
        ):
            for record in self._records.values():
                record.current_pose = None
                record.association_pose = None
                record.association_pose_ns = None
                record.reacquiring = record.confirmed
                record.reacquire_hits = 0
        self._calibration = calibration
