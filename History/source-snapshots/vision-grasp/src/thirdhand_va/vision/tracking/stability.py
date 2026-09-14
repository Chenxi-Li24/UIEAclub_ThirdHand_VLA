"""Bounded 4-of-5 fail-closed stability window."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import numpy as np

from thirdhand_va.common.config import VisionConfig
from thirdhand_va.common.contracts import (
    GraspPoseCamera,
    MaskCandidate,
    RgbdFrame,
    VisionDecision,
)

PoseCandidate = tuple[MaskCandidate, GraspPoseCamera]


@dataclass(frozen=True, slots=True)
class _Observation:
    frame_id: int
    candidate: MaskCandidate
    pose: GraspPoseCamera


class StabilityWindow:
    def __init__(self, config: VisionConfig) -> None:
        self.config = config
        self._observations: deque[_Observation | None] = deque(
            maxlen=config.stability_window
        )
        self._last_sequence = -1
        self._last_timestamp = -1

    def update(
        self,
        frame: RgbdFrame,
        candidates_with_pose: tuple[PoseCandidate, ...],
        *,
        now_ns: int,
    ) -> VisionDecision:
        if (
            frame.sequence <= self._last_sequence
            or frame.monotonic_ns <= self._last_timestamp
        ):
            return self._decision(
                "rejected",
                frame.sequence,
                reasons=("frame_not_monotonic",),
            )
        self._last_sequence = frame.sequence
        self._last_timestamp = frame.monotonic_ns
        age_ns = now_ns - frame.monotonic_ns
        if age_ns < 0:
            self._observations.append(None)
            return self._decision(
                "rejected",
                frame.sequence,
                reasons=("frame_timestamp_in_future",),
            )
        if age_ns > self.config.max_frame_age_ms * 1_000_000:
            self._observations.append(None)
            return self._decision(
                "rejected",
                frame.sequence,
                reasons=("frame_stale",),
            )

        authorized = tuple(
            item for item in candidates_with_pose if item[0].authorized
        )
        if len(authorized) > 1:
            self._observations.append(None)
            return self._decision(
                "uncertain",
                frame.sequence,
                reasons=("multiple_authorized_targets",),
            )
        if not authorized:
            self._observations.append(None)
            return self._decision(
                "searching",
                frame.sequence,
                reasons=("no_authorized_target",),
            )
        candidate, pose = authorized[0]
        previous = next(
            (item for item in reversed(self._observations) if item is not None),
            None,
        )
        if (
            previous is not None
            and _mask_iou(previous.candidate.mask, candidate.mask)
            < self.config.min_track_mask_iou
        ):
            self._observations.clear()
            self._observations.append(
                _Observation(frame.sequence, candidate, pose)
            )
            return self._decision(
                "uncertain",
                frame.sequence,
                target=candidate,
                pose=pose,
                reasons=("target_track_jump", "stability_hits_insufficient"),
            )

        self._observations.append(_Observation(frame.sequence, candidate, pose))
        valid = tuple(item for item in self._observations if item is not None)
        hits = len(valid)
        if hits < self.config.required_stable_hits:
            return self._decision(
                "uncertain",
                frame.sequence,
                target=candidate,
                pose=pose,
                reasons=("stability_hits_insufficient",),
            )
        positions = np.asarray([item.pose.point_m for item in valid])
        center = np.median(positions, axis=0)
        spread = float(np.linalg.norm(positions - center, axis=1).max())
        if spread > self.config.max_pose_spread_m:
            return self._decision(
                "uncertain",
                frame.sequence,
                target=candidate,
                pose=pose,
                reasons=("pose_spread_too_large",),
            )
        return self._decision(
            "ready",
            frame.sequence,
            target=candidate,
            pose=pose,
            reasons=(),
        )

    def _decision(
        self,
        status: str,
        frame_id: int,
        *,
        target: MaskCandidate | None = None,
        pose: GraspPoseCamera | None = None,
        reasons: tuple[str, ...],
    ) -> VisionDecision:
        hits = sum(item is not None for item in self._observations)
        return VisionDecision(
            status=status,
            frame_id=frame_id,
            target=target,
            pose=pose,
            reasons=reasons,
            stable_hits=hits,
            window_size=self.config.stability_window,
        )


def _mask_iou(left: np.ndarray, right: np.ndarray) -> float:
    if left.shape != right.shape:
        return 0.0
    intersection = int(np.logical_and(left, right).sum())
    union = int(np.logical_or(left, right).sum())
    return intersection / union if union else 0.0
