"""Stable-ID bottle perception, geometry, evidence, and motion epochs."""

from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import time

import numpy as np

from thirdhand_va.common.config import VisionConfig
from thirdhand_va.common.contracts import (
    GraspPoseCamera,
    RgbdFrame,
    TrackedBottle,
    VisionDecision,
)
from thirdhand_va.vision.geometry import GeometryRejected, estimate_grasp_candidates
from thirdhand_va.vision.perception.bottle_filter import BottleCandidateFilter
from thirdhand_va.vision.perception.interfaces import PerceptionBackend
from thirdhand_va.vision.selection import (
    StableBottleSelector,
    StableSelectionRequest,
)
from thirdhand_va.vision.tracking import StableTrackManager
from thirdhand_va.vision.tracking.stability import StabilityWindow


class VisionPipeline:
    def __init__(
        self,
        config: VisionConfig,
        backend: PerceptionBackend,
        *,
        tracker: StableTrackManager | None = None,
    ) -> None:
        self.config = config
        self.backend = backend
        self.filter = BottleCandidateFilter(config)
        self.tracker = tracker or StableTrackManager.from_config(config)
        self.selector = StableBottleSelector()
        self.selection: StableSelectionRequest | None = None
        self.motion_epoch = 0
        self.camera_moving = False
        self.world_anchor_required = False
        self.stability = StabilityWindow(config)

    def select(
        self,
        stable_id: int,
        request_id: str,
        *,
        force: bool = False,
    ) -> bool:
        request = StableSelectionRequest(stable_id, request_id)
        if self.selection == request and not force:
            return False
        if self.selection is not None and self.selection.request_id != request_id:
            return False
        if not self.tracker.reserve(stable_id, request_id):
            return False
        self.selection = request
        self.stability = StabilityWindow(self.config)
        return True

    def release(self, request_id: str) -> None:
        self.tracker.release(request_id)
        if self.selection is not None and self.selection.request_id == request_id:
            self.selection = None
            self.stability = StabilityWindow(self.config)

    def begin_motion_epoch(self, epoch: int) -> None:
        if not isinstance(epoch, int) or epoch <= self.motion_epoch:
            raise ValueError("motion epoch must strictly increase")
        self.motion_epoch = epoch
        self.camera_moving = True
        self.world_anchor_required = True
        self.stability = StabilityWindow(self.config)

    def set_camera_moving(self, moving: bool) -> None:
        self.camera_moving = bool(moving)
        if self.camera_moving:
            self.stability = StabilityWindow(self.config)

    def reset_pose_reference(self) -> None:
        self.stability = StabilityWindow(self.config)

    def process(
        self,
        frame: RgbdFrame,
        *,
        now_ns: int | None = None,
        t_base_camera: np.ndarray | None = None,
    ) -> VisionDecision:
        current_ns = time.monotonic_ns() if now_ns is None else now_ns
        candidates = self.filter.filter(frame.rgb, self.backend.infer(frame.rgb))
        scene_exclusion_mask = np.zeros(frame.depth_m.shape, dtype=bool)
        for candidate in candidates:
            if candidate.mask.shape == scene_exclusion_mask.shape:
                scene_exclusion_mask |= candidate.mask
        poses: dict[int, GraspPoseCamera] = {}
        camera_points: dict[int, tuple[float, float, float]] = {}
        world_points: dict[int, tuple[float, float, float]] = {}
        base_transform = None
        if t_base_camera is not None:
            candidate_transform = np.asarray(t_base_camera, dtype=np.float64)
            if (
                candidate_transform.shape == (4, 4)
                and np.isfinite(candidate_transform).all()
                and np.allclose(candidate_transform[3], [0, 0, 0, 1], atol=1e-9)
            ):
                base_transform = candidate_transform
        blockers: dict[int, tuple[str, ...]] = {}
        approach_direction_camera = None if base_transform is None else (
            base_transform[:3, :3].T @ np.asarray([1.0, 0.0, 0.0])
        )
        upright_direction_camera = None if base_transform is None else (
            base_transform[:3, :3].T @ np.asarray([0.0, 0.0, 1.0])
        )
        for candidate in candidates:
            if candidate.mask.shape == frame.xyz_camera_m.shape[:2]:
                tracking_points = frame.xyz_camera_m[candidate.mask]
                tracking_points = tracking_points[
                    np.isfinite(tracking_points).all(axis=1)
                ]
                if len(tracking_points) >= self.config.min_depth_points:
                    tracking_point = np.median(tracking_points, axis=0)
                    camera_points[candidate.detection_id] = tuple(
                        float(value) for value in tracking_point
                    )
                    if base_transform is not None:
                        transformed = base_transform @ np.asarray(
                            [*camera_points[candidate.detection_id], 1.0]
                        )
                        if np.isfinite(transformed[:3]).all():
                            world_points[candidate.detection_id] = tuple(
                                float(value) for value in transformed[:3]
                            )
            if not candidate.authorized:
                blockers[candidate.detection_id] = candidate.reasons
                continue
            try:
                ranked = estimate_grasp_candidates(
                    frame,
                    candidate,
                    self.config,
                    scene_exclusion_mask=scene_exclusion_mask,
                    approach_direction_camera=approach_direction_camera,
                    upright_direction_camera=upright_direction_camera,
                )
            except GeometryRejected as error:
                blockers[candidate.detection_id] = (str(error),)
                continue
            pose = ranked[0].pose
            poses[candidate.detection_id] = pose
            blockers[candidate.detection_id] = ()

        if self.world_anchor_required and (
            base_transform is None
            or not self.tracker.reserved_world_anchor_available
        ):
            tracks = self.tracker.update(
                (),
                now_ns=current_ns,
                camera_moving=self.camera_moving,
                camera_points={},
                world_points={},
                candidate_blockers={},
            )
            return self._decision(
                frame,
                status="uncertain",
                reasons=("robot_base_anchor_unavailable",),
                tracks=tracks,
                candidates=candidates,
            )

        tracks = self.tracker.update(
            candidates,
            now_ns=current_ns,
            camera_moving=self.camera_moving,
            camera_points=camera_points,
            world_points=world_points,
            candidate_blockers=blockers,
        )
        if base_transform is not None:
            self.world_anchor_required = False
        if self.selection is None:
            return self._decision(
                frame,
                status="searching",
                reasons=("selection_not_requested",),
                tracks=tracks,
                candidates=candidates,
            )

        selection = self.selector.select(tracks, self.selection)
        if selection.selected is None:
            self.stability = StabilityWindow(self.config)
            return self._decision(
                frame,
                status="uncertain",
                reasons=selection.reasons,
                tracks=tracks,
                candidates=candidates,
            )
        selected = selection.selected
        pose = poses.get(selected.candidate.detection_id)
        if self.camera_moving:
            self.stability = StabilityWindow(self.config)
            return self._decision(
                frame,
                status="uncertain",
                target_track=selected,
                pose=pose,
                reasons=("camera_motion_active",),
                tracks=tracks,
                candidates=candidates,
            )
        if pose is None or not selected.depth_supported:
            self.stability.update(frame, (), now_ns=current_ns)
            reasons = selected.blockers or ("target_depth_temporarily_unavailable",)
            return self._decision(
                frame,
                status="uncertain",
                target_track=selected,
                reasons=reasons,
                tracks=tracks,
                candidates=candidates,
            )
        stable = self.stability.update(
            frame,
            ((selected.candidate, pose),),
            now_ns=current_ns,
        )
        return self._enrich(stable, frame, tracks, candidates)

    def _decision(
        self,
        frame: RgbdFrame,
        *,
        status: str,
        reasons: tuple[str, ...],
        tracks: tuple[TrackedBottle, ...],
        candidates,
        target_track: TrackedBottle | None = None,
        pose: GraspPoseCamera | None = None,
    ) -> VisionDecision:
        decision = VisionDecision(
            status=status,  # type: ignore[arg-type]
            frame_id=frame.sequence,
            target=None if target_track is None else target_track.candidate,
            pose=pose,
            reasons=reasons,
            stable_hits=0,
            window_size=self.config.stability_window,
        )
        return self._enrich(decision, frame, tracks, candidates)

    def _enrich(
        self,
        decision: VisionDecision,
        frame: RgbdFrame,
        tracks: tuple[TrackedBottle, ...],
        candidates,
    ) -> VisionDecision:
        enriched = replace(
            decision,
            request_id=None if self.selection is None else self.selection.request_id,
            selected_stable_id=(
                None if self.selection is None else self.selection.stable_id
            ),
            tracks=tracks,
            candidates=tuple(candidates),
            captured_monotonic_ns=frame.monotonic_ns,
            camera_serial=frame.camera_serial,
            registration_id=self.config.camera_registration_id,
            motion_epoch=self.motion_epoch,
            evidence_id=None,
            selection_side=None,
            requested_ordinal=None,
            spatial_ranks=(),
        )
        return replace(enriched, evidence_id=_evidence_id(enriched))


def _evidence_id(decision: VisionDecision) -> str:
    pose = decision.pose
    payload = {
        "frame_id": decision.frame_id,
        "captured_monotonic_ns": decision.captured_monotonic_ns,
        "camera_serial": decision.camera_serial,
        "registration_id": decision.registration_id,
        "motion_epoch": decision.motion_epoch,
        "request_id": decision.request_id,
        "selected_stable_id": decision.selected_stable_id,
        "status": decision.status,
        "reasons": list(decision.reasons),
        "pose": None if pose is None else {
            "point_m": list(pose.point_m),
            "axis": list(pose.axis),
            "approach": list(pose.approach),
            "width_m": pose.width_m,
            "position_std_m": list(pose.position_std_m),
        },
        "tracks": [
            {
                "stable_id": track.stable_id,
                "backend_track_id": track.backend_track_id,
                "state": track.state,
                "detection_id": track.candidate.detection_id,
                "depth_supported": track.depth_supported,
                "blockers": list(track.blockers),
            }
            for track in decision.tracks
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


__all__ = ["VisionPipeline"]
