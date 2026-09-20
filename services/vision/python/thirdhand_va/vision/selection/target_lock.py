"""Persist and validate the identity of a selected bottle across frames."""

from __future__ import annotations

import numpy as np

from thirdhand_va.common.contracts import GraspPoseCamera, MaskCandidate

from .ordinal_selector import SelectionResult, mask_centroid


class TargetLock:
    """Match a chosen bottle without applying spatial ordinal sorting again."""

    def __init__(
        self,
        min_mask_iou: float,
        max_center_distance_px: float,
        ambiguity_margin: float,
        max_point_distance_m: float,
    ) -> None:
        self.min_mask_iou = float(min_mask_iou)
        self.max_center_distance_px = float(max_center_distance_px)
        self.ambiguity_margin = float(ambiguity_margin)
        self.max_point_distance_m = float(max_point_distance_m)
        self._mask: np.ndarray | None = None
        self._center: tuple[float, float] | None = None
        self._point: tuple[float, float, float] | None = None
        self._detection_id: int | None = None

    @property
    def acquired(self) -> bool:
        return self._mask is not None

    def acquire(
        self,
        candidate: MaskCandidate,
        pose: GraspPoseCamera | None = None,
    ) -> None:
        self._mask = np.array(candidate.mask, dtype=bool, copy=True)
        self._center = mask_centroid(candidate.mask)
        self._point = None if pose is None else pose.point_m
        self._detection_id = candidate.detection_id

    def reset(self) -> None:
        self._mask = None
        self._center = None
        self._point = None
        self._detection_id = None

    def match(self, candidates: tuple[MaskCandidate, ...]) -> SelectionResult:
        if self._mask is None or self._center is None:
            return SelectionResult(None, (), ("target_lock_not_acquired",))
        same_id = tuple(
            item
            for item in candidates
            if item.authorized and item.detection_id == self._detection_id
        )
        if len(same_id) == 1:
            selected = same_id[0]
            self._mask = np.array(selected.mask, dtype=bool, copy=True)
            self._center = mask_centroid(selected.mask)
            return SelectionResult(selected, (), ())
        if len(same_id) > 1:
            return SelectionResult(None, (), ("target_id_ambiguous",))
        scored: list[tuple[float, MaskCandidate, tuple[float, float]]] = []
        for item in candidates:
            if not item.authorized:
                continue
            center = mask_centroid(item.mask)
            iou = _mask_iou(self._mask, item.mask)
            distance = float(np.linalg.norm(np.subtract(center, self._center)))
            if iou < self.min_mask_iou and distance > self.max_center_distance_px:
                continue
            normalized_distance = distance / max(self.max_center_distance_px, 1.0)
            scored.append((iou - normalized_distance, item, center))
        if not scored:
            return SelectionResult(None, (), ("target_track_lost",))
        scored.sort(key=lambda item: item[0], reverse=True)
        if len(scored) > 1 and scored[0][0] - scored[1][0] <= self.ambiguity_margin:
            return SelectionResult(None, (), ("target_lock_ambiguous",))
        _, selected, center = scored[0]
        self._mask = np.array(selected.mask, dtype=bool, copy=True)
        self._center = center
        self._detection_id = selected.detection_id
        return SelectionResult(selected, (), ())

    def confirm_pose(self, pose: GraspPoseCamera) -> tuple[bool, tuple[str, ...]]:
        if self._point is not None:
            distance = float(np.linalg.norm(np.subtract(pose.point_m, self._point)))
            if distance > self.max_point_distance_m:
                return False, ("target_3d_jump",)
        self._point = pose.point_m
        return True, ()

    def reset_pose_reference(self) -> None:
        """Keep the tracked mask but reset the moving camera-frame point gate."""
        self._point = None


def _mask_iou(left: np.ndarray, right: np.ndarray) -> float:
    if left.shape != right.shape:
        return 0.0
    union = int(np.logical_or(left, right).sum())
    if not union:
        return 0.0
    return int(np.logical_and(left, right).sum()) / union


__all__ = ["TargetLock"]
