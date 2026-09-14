"""REMIND-style engineering subset for persistent physical-object identity."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, Optional

import numpy as np
from scipy.optimize import linear_sum_assignment

from thirdhand_vision.core.errors import InputValidationError
from thirdhand_vision.core.types import CameraCalibrationRef, FrameStamp, PoseEstimate


class IdentityStatus(str, Enum):
    TENTATIVE = "tentative"
    CONFIRMED = "confirmed"
    OCCLUDED = "occluded"
    INACTIVE = "inactive"
    AMBIGUOUS = "ambiguous"


def _descriptor(value: object) -> np.ndarray:
    descriptor = np.asarray(value, dtype=float)
    if descriptor.ndim != 1 or not len(descriptor) or not np.isfinite(descriptor).all():
        raise InputValidationError("identity descriptor must be a finite non-empty vector")
    norm = float(np.linalg.norm(descriptor))
    if not np.isfinite(norm) or norm <= 0.0:
        raise InputValidationError("identity descriptor norm must be positive")
    result = np.array(descriptor / norm, copy=True)
    result.setflags(write=False)
    return result


@dataclass(frozen=True)
class IdentityObservation:
    observation_id: int
    label: str
    confidence: float
    visibility: float
    descriptor: np.ndarray = field(compare=False, repr=False)
    stamp: FrameStamp
    pose: Optional[PoseEstimate] = field(default=None, compare=False)

    def __post_init__(self) -> None:
        if isinstance(self.observation_id, bool) or not isinstance(self.observation_id, int) or self.observation_id < 0:
            raise InputValidationError("observation_id must be a non-negative integer")
        if not isinstance(self.label, str) or not self.label:
            raise InputValidationError("identity label must be a non-empty string")
        for name in ("confidence", "visibility"):
            value = float(getattr(self, name))
            if not np.isfinite(value) or not 0.0 <= value <= 1.0:
                raise InputValidationError(f"{name} must be within [0, 1]")
            object.__setattr__(self, name, value)
        if not isinstance(self.stamp, FrameStamp):
            raise InputValidationError("identity stamp must be a FrameStamp")
        if self.pose is not None:
            if not isinstance(self.pose, PoseEstimate):
                raise InputValidationError("identity pose must be a PoseEstimate")
            if self.pose.frame != "robot_base":
                raise InputValidationError("identity pose must use robot_base")
            if self.pose.stamp.monotonic_ns != self.stamp.monotonic_ns:
                raise InputValidationError("identity pose and observation timestamps must match")
        object.__setattr__(self, "descriptor", _descriptor(self.descriptor))


@dataclass(frozen=True)
class IdentityConfig:
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
    reacquire_confirmed_hits: int
    max_actionable_position_std_m: float
    max_actionable_pose_age_ns: int
    min_actionable_pose_hits: int

    def __post_init__(self) -> None:
        fractions = (
            "max_cosine_distance",
            "ambiguity_margin",
            "appearance_weight",
            "position_weight",
            "min_memory_confidence",
            "min_memory_visibility",
        )
        if any(not np.isfinite(float(getattr(self, name))) or float(getattr(self, name)) < 0.0 for name in fractions):
            raise InputValidationError("identity distance, weights and quality limits must be non-negative")
        if not 0.0 < self.max_cosine_distance <= 2.0:
            raise InputValidationError("max_cosine_distance must be within (0, 2]")
        if self.appearance_weight + self.position_weight <= 0.0:
            raise InputValidationError("identity association needs a positive weight")
        if not 0.0 <= self.min_memory_confidence <= 1.0 or not 0.0 <= self.min_memory_visibility <= 1.0:
            raise InputValidationError("memory quality thresholds must be within [0, 1]")
        if not np.isfinite(self.max_position_distance_m) or self.max_position_distance_m <= 0.0:
            raise InputValidationError("maximum position distance must be positive")
        if not np.isfinite(self.max_actionable_position_std_m) or self.max_actionable_position_std_m <= 0.0:
            raise InputValidationError("maximum actionable position deviation must be positive")
        integer_fields = (
            "position_gate_max_age_ns",
            "occluded_after_ns",
            "inactive_after_ns",
            "min_confirmed_hits",
            "work_bank_size",
            "stable_bank_size",
            "max_identities",
            "reacquire_confirmed_hits",
            "max_actionable_pose_age_ns",
            "min_actionable_pose_hits",
        )
        if any(isinstance(getattr(self, name), bool) or not isinstance(getattr(self, name), int) or getattr(self, name) < 1 for name in integer_fields):
            raise InputValidationError("identity counts and age limits must be positive integers")
        if self.occluded_after_ns >= self.inactive_after_ns:
            raise InputValidationError("occluded age must be less than inactive age")


@dataclass(frozen=True)
class IdentityAssignment:
    observation_id: int
    identity_id: Optional[int]
    status: IdentityStatus
    cost: Optional[float] = None
    reason: Optional[str] = None
    appearance_similarity: Optional[float] = None


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
    pose_hits: int


class PersistentIdentityMemory:
    """Global appearance association with bounded dual prototype banks."""

    def __init__(self, config: IdentityConfig) -> None:
        if not isinstance(config, IdentityConfig):
            raise InputValidationError("identity config is required")
        self.config = config
        self._records: dict[int, _IdentityRecord] = {}
        self._next_identity_id = 1
        self._last_now_ns: Optional[int] = None
        self._descriptor_dimension: Optional[int] = None
        self._calibration: Optional[CameraCalibrationRef] = None

    def reset(self) -> None:
        self._records.clear()
        self._last_now_ns = None
        self._descriptor_dimension = None
        self._calibration = None

    def set_calibration(self, calibration: CameraCalibrationRef) -> None:
        if not isinstance(calibration, CameraCalibrationRef):
            raise InputValidationError("calibration must be a CameraCalibrationRef")
        if self._calibration is not None and self._calibration.calibration_id != calibration.calibration_id:
            for record in self._records.values():
                record.current_pose = None
                record.association_pose = None
                record.association_pose_ns = None
                record.pose_hits = 0
        self._calibration = calibration

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
        return min(max(0.0, 1.0 - float(item @ descriptor)) for item in prototypes)

    def _costs(
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
                weighted = self.config.appearance_weight * appearance
                total_weight = self.config.appearance_weight
                if (
                    record.association_pose is not None
                    and record.association_pose_ns is not None
                    and observation.pose is not None
                    and observation.stamp.monotonic_ns - record.association_pose_ns
                    <= self.config.position_gate_max_age_ns
                ):
                    distance = float(
                        np.linalg.norm(observation.pose.xyz_m - record.association_pose.xyz_m)
                    )
                    if distance > self.config.max_position_distance_m:
                        continue
                    weighted += self.config.position_weight * (
                        distance / self.config.max_position_distance_m
                    )
                    total_weight += self.config.position_weight
                costs[row, column] = weighted / total_weight
        return costs

    def _ambiguous_columns(self, costs: np.ndarray) -> set[int]:
        ambiguous: set[int] = set()
        for column in range(costs.shape[1]):
            finite = np.sort(costs[np.isfinite(costs[:, column]), column])
            if len(finite) >= 2 and finite[1] - finite[0] < self.config.ambiguity_margin:
                ambiguous.add(column)
        return ambiguous

    @staticmethod
    def _assign(costs: np.ndarray, columns: list[int], rows: list[int]) -> list[tuple[int, int]]:
        if not rows or not columns:
            return []
        local = costs[np.ix_(rows, columns)]
        local_rows, local_columns = linear_sum_assignment(
            np.where(np.isfinite(local), local, 1e12)
        )
        return [
            (rows[int(row)], columns[int(column)])
            for row, column in zip(local_rows, local_columns)
            if np.isfinite(local[row, column])
        ]

    def _quality_allows_update(self, observation: IdentityObservation) -> bool:
        return (
            observation.confidence >= self.config.min_memory_confidence
            and observation.visibility >= self.config.min_memory_visibility
        )

    @staticmethod
    def _append(bank: list[np.ndarray], descriptor: np.ndarray, capacity: int) -> None:
        bank.append(np.array(descriptor, copy=True))
        while len(bank) > capacity:
            bank.pop(0)

    def _new_record(self, observation: IdentityObservation) -> Optional[_IdentityRecord]:
        if len(self._records) >= self.config.max_identities:
            inactive = [
                record
                for record in self._records.values()
                if self._status(record, observation.stamp.monotonic_ns) is IdentityStatus.INACTIVE
            ]
            if not inactive:
                return None
            victim = min(inactive, key=lambda item: (item.last_seen_ns, item.identity_id))
            del self._records[victim.identity_id]
        identity_id = self._next_identity_id
        self._next_identity_id += 1
        confirmed = self.config.min_confirmed_hits == 1
        descriptor = np.array(observation.descriptor, copy=True)
        record = _IdentityRecord(
            identity_id=identity_id,
            label=observation.label,
            work_bank=[descriptor],
            stable_bank=[np.array(descriptor, copy=True)] if confirmed else [],
            hits=1,
            last_seen_ns=observation.stamp.monotonic_ns,
            current_pose=observation.pose,
            association_pose=observation.pose,
            association_pose_ns=None if observation.pose is None else observation.stamp.monotonic_ns,
            confirmed=confirmed,
            reacquiring=False,
            reacquire_hits=0,
            pose_hits=1 if observation.pose is not None else 0,
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
            and calibration_valid
            and pose is not None
            and now_ns - pose.stamp.monotonic_ns <= self.config.max_actionable_pose_age_ns
            and position_std_m <= self.config.max_actionable_position_std_m
            and record.pose_hits >= self.config.min_actionable_pose_hits
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
        items = list(observations)
        if isinstance(now_ns, bool) or not isinstance(now_ns, int) or now_ns < 0:
            raise InputValidationError("identity time must be a non-negative integer")
        if self._last_now_ns is not None and now_ns < self._last_now_ns:
            raise InputValidationError("identity time cannot move backwards")
        if any(not isinstance(item, IdentityObservation) for item in items):
            raise InputValidationError("observations must contain IdentityObservation values")
        if any(item.stamp.monotonic_ns > now_ns for item in items):
            raise InputValidationError("identity observation cannot be in the future")
        trusted_dimensions = {
            len(item.descriptor) for item in items if self._quality_allows_update(item)
        }
        if len(trusted_dimensions) > 1:
            raise InputValidationError("trusted observations cannot mix descriptor dimensions")
        if self._descriptor_dimension is None and trusted_dimensions:
            self._descriptor_dimension = next(iter(trusted_dimensions))
        if self._descriptor_dimension is not None and any(
            len(item.descriptor) != self._descriptor_dimension for item in items
        ):
            raise InputValidationError("identity descriptor dimension changed")
        records = [self._records[key] for key in sorted(self._records)]
        costs = self._costs(records, items)
        ambiguous = self._ambiguous_columns(costs)
        trusted_columns = [
            index
            for index, item in enumerate(items)
            if self._quality_allows_update(item) and index not in ambiguous
        ]
        low_columns = [
            index
            for index, item in enumerate(items)
            if not self._quality_allows_update(item) and index not in ambiguous
        ]
        all_rows = list(range(len(records)))
        trusted_matches = self._assign(costs, trusted_columns, all_rows)
        used_rows = {row for row, _ in trusted_matches}
        low_matches = self._assign(
            costs,
            low_columns,
            [row for row in all_rows if row not in used_rows],
        )
        assignments: dict[int, IdentityAssignment] = {}
        for row, column in trusted_matches:
            record = records[row]
            item = items[column]
            prior_status = self._status(record, item.stamp.monotonic_ns)
            similarity = 1.0 - self._appearance_cost(record, item.descriptor)
            record.hits += 1
            record.last_seen_ns = item.stamp.monotonic_ns
            record.current_pose = item.pose
            if item.pose is None:
                # Canonical RGB may arrive between depth frames. Preserve the
                # recent pose-hit chain so an asynchronous camera rate does not
                # make an otherwise stable target permanently non-actionable.
                pass
            elif prior_status is IdentityStatus.INACTIVE:
                record.pose_hits = 1
            else:
                record.pose_hits += 1
            if item.pose is not None:
                record.association_pose = item.pose
                record.association_pose_ns = item.stamp.monotonic_ns
            record.confirmed = record.confirmed or record.hits >= self.config.min_confirmed_hits
            if prior_status is IdentityStatus.INACTIVE:
                record.reacquire_hits = 1 if item.pose is not None else 0
                record.reacquiring = record.reacquire_hits < self.config.reacquire_confirmed_hits
            elif record.reacquiring:
                record.reacquire_hits = record.reacquire_hits + 1 if item.pose is not None else 0
                if record.reacquire_hits >= self.config.reacquire_confirmed_hits:
                    record.reacquiring = False
            self._append(record.work_bank, item.descriptor, self.config.work_bank_size)
            if record.confirmed:
                self._append(record.stable_bank, item.descriptor, self.config.stable_bank_size)
            assignment_status = (
                IdentityStatus.CONFIRMED
                if record.confirmed and not record.reacquiring
                else IdentityStatus.TENTATIVE
            )
            assignments[column] = IdentityAssignment(
                observation_id=item.observation_id,
                identity_id=record.identity_id,
                status=assignment_status,
                cost=float(costs[row, column]),
                appearance_similarity=float(similarity),
            )
        for row, column in low_matches:
            record = records[row]
            item = items[column]
            assignments[column] = IdentityAssignment(
                observation_id=item.observation_id,
                identity_id=record.identity_id,
                status=IdentityStatus.TENTATIVE,
                cost=float(costs[row, column]),
                reason="low_quality_association",
                appearance_similarity=1.0 - self._appearance_cost(record, item.descriptor),
            )
        matched_columns = {column for _, column in trusted_matches + low_matches}
        for column, item in enumerate(items):
            if column in ambiguous:
                assignments[column] = IdentityAssignment(
                    observation_id=item.observation_id,
                    identity_id=None,
                    status=IdentityStatus.AMBIGUOUS,
                    reason="ambiguous_association",
                )
            elif column not in matched_columns and self._quality_allows_update(item):
                record = self._new_record(item)
                assignments[column] = IdentityAssignment(
                    observation_id=item.observation_id,
                    identity_id=None if record is None else record.identity_id,
                    status=(
                        IdentityStatus.TENTATIVE
                        if record is None or not record.confirmed
                        else IdentityStatus.CONFIRMED
                    ),
                    reason="identity_capacity_exhausted" if record is None else None,
                    appearance_similarity=1.0 if record is not None else None,
                )
            elif column not in matched_columns:
                assignments[column] = IdentityAssignment(
                    observation_id=item.observation_id,
                    identity_id=None,
                    status=IdentityStatus.TENTATIVE,
                    reason="low_quality_unmatched",
                )
        self._last_now_ns = now_ns
        ordered_assignments = tuple(assignments[index] for index in range(len(items)))
        snapshots = tuple(
            self._snapshot(self._records[key], now_ns) for key in sorted(self._records)
        )
        return IdentityUpdate(ordered_assignments, snapshots)
