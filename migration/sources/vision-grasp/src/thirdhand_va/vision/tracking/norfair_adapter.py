"""Thin Norfair association adapter isolated from user-facing bottle IDs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import numpy as np
from norfair import Detection, Tracker

from thirdhand_va.common.config import VisionConfig
from thirdhand_va.common.contracts import MaskCandidate


Point3 = tuple[float, float, float]


@dataclass(frozen=True, slots=True)
class Association:
    backend_track_id: int
    candidate: MaskCandidate


@dataclass(frozen=True, slots=True)
class _Observation:
    candidate: MaskCandidate
    centroid_xy: tuple[float, float]
    camera_point: Point3 | None
    world_point: Point3 | None
    camera_moving: bool


def tracking_centroid(mask: np.ndarray) -> tuple[float, float]:
    rows, columns = np.nonzero(mask)
    if rows.size == 0:
        raise ValueError("tracking mask must be non-empty")
    return float(columns.mean()), float(rows.mean())


class NorfairTrackerAdapter:
    """Convert immutable bottle candidates to and from Norfair objects."""

    def __init__(
        self,
        *,
        max_center_distance_px: float,
        max_point_distance_m: float,
        distance_threshold: float = 0.78,
    ) -> None:
        self.max_center_distance_px = float(max_center_distance_px)
        self.max_point_distance_m = float(max_point_distance_m)
        if self.max_center_distance_px <= 0 or self.max_point_distance_m <= 0:
            raise ValueError("tracking distance limits must be positive")
        self._tracker = Tracker(
            distance_function=self._distance,
            distance_threshold=float(distance_threshold),
            initialization_delay=0,
            hit_counter_max=30,
            past_detections_length=4,
        )

    @classmethod
    def from_config(cls, config: VisionConfig) -> "NorfairTrackerAdapter":
        return cls(
            max_center_distance_px=config.max_track_center_distance_px,
            max_point_distance_m=config.max_track_point_distance_m,
        )

    def update(
        self,
        candidates: tuple[MaskCandidate, ...],
        *,
        camera_moving: bool = False,
        camera_points: Mapping[int, Point3] | None = None,
        world_points: Mapping[int, Point3] | None = None,
    ) -> tuple[Association, ...]:
        camera_points = camera_points or {}
        world_points = world_points or {}
        detections: list[Detection] = []
        current_object_ids: set[int] = set()
        for candidate in candidates:
            centroid = tracking_centroid(candidate.mask)
            observation = _Observation(
                candidate=candidate,
                centroid_xy=centroid,
                camera_point=_point_or_none(camera_points.get(candidate.detection_id)),
                world_point=_point_or_none(world_points.get(candidate.detection_id)),
                camera_moving=camera_moving,
            )
            current_object_ids.add(id(candidate))
            detections.append(
                Detection(
                    points=np.asarray([centroid], dtype=np.float32),
                    scores=np.asarray([candidate.score], dtype=np.float32),
                    data=observation,
                    embedding=candidate.descriptor,
                    label="bottle",
                )
            )

        tracked_objects = self._tracker.update(detections=detections)
        associations: list[Association] = []
        for tracked in tracked_objects:
            observation = getattr(tracked.last_detection, "data", None)
            if not isinstance(observation, _Observation):
                continue
            if id(observation.candidate) not in current_object_ids:
                continue
            backend_id = tracked.id
            if backend_id is None:
                backend_id = -int(tracked.initializing_id or 0) - 1
            associations.append(
                Association(int(backend_id), observation.candidate)
            )
        return tuple(associations)

    def _distance(self, detection: Detection, tracked) -> float:
        current = detection.data
        previous = tracked.last_detection.data
        if not isinstance(current, _Observation) or not isinstance(previous, _Observation):
            return 1_000_000.0

        world_distance = _point_distance(current.world_point, previous.world_point)
        if world_distance is not None and world_distance > self.max_point_distance_m:
            return 1_000_000.0

        descriptor_distance = _cosine_distance(
            current.candidate.descriptor,
            previous.candidate.descriptor,
        )
        if current.camera_moving and descriptor_distance > 0.55:
            return 1_000_000.0

        mask_distance = 1.0 - _mask_iou(
            current.candidate.mask,
            previous.candidate.mask,
        )
        center_distance = min(
            1.0,
            float(np.linalg.norm(
                np.asarray(current.centroid_xy) - np.asarray(previous.centroid_xy)
            )) / self.max_center_distance_px,
        )
        point_term = (
            0.5
            if world_distance is None
            else min(1.0, world_distance / self.max_point_distance_m)
        )
        if current.camera_moving:
            return 0.10 * mask_distance + 0.10 * center_distance + (
                0.60 * descriptor_distance + 0.20 * point_term
            )
        return (
            0.40 * mask_distance
            + 0.25 * center_distance
            + 0.25 * descriptor_distance
            + 0.10 * point_term
        )


def _mask_iou(left: np.ndarray, right: np.ndarray) -> float:
    if left.shape != right.shape:
        return 0.0
    union = int(np.logical_or(left, right).sum())
    if union == 0:
        return 0.0
    return int(np.logical_and(left, right).sum()) / union


def _cosine_distance(left: np.ndarray | None, right: np.ndarray | None) -> float:
    if left is None or right is None or left.shape != right.shape:
        return 0.5
    denominator = float(np.linalg.norm(left) * np.linalg.norm(right))
    if denominator <= 1e-12:
        return 0.5
    similarity = float(np.dot(left, right) / denominator)
    return float(np.clip((1.0 - similarity) / 2.0, 0.0, 1.0))


def _point_distance(left: Point3 | None, right: Point3 | None) -> float | None:
    if left is None or right is None:
        return None
    return float(np.linalg.norm(np.asarray(left) - np.asarray(right)))


def _point_or_none(value: object) -> Point3 | None:
    if value is None:
        return None
    point = np.asarray(value, dtype=np.float64)
    if point.shape != (3,) or not np.isfinite(point).all():
        return None
    return tuple(float(item) for item in point)


__all__ = ["Association", "NorfairTrackerAdapter", "tracking_centroid"]
