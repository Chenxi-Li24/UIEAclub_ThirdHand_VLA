"""Detection-event serialization and latest-frame publishing for Vision."""

from __future__ import annotations

import hashlib
import json
from typing import Any, BinaryIO

from thirdhand_va.common.contracts import VisionDecision

from .mjpeg_publisher import FrameProvenance, build_mjpeg_part


def build_detection_event(
    decision: VisionDecision,
    provenance: FrameProvenance,
    overlay_jpeg: bytes,
    grasp_preview: dict[str, Any] | None = None,
    model_provenance: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build a fail-closed v3 event paired with one rendered Lumos frame."""

    if decision.frame_id != provenance.frame_id:
        raise ValueError("decision and overlay frame ids must match")
    if (
        decision.captured_monotonic_ns
        and decision.captured_monotonic_ns != provenance.monotonic_ns
    ):
        raise ValueError("decision and overlay monotonic times must match")
    targets = []
    for track in decision.tracks:
        candidate = track.candidate
        selected = (
            decision.selected_stable_id is not None
            and track.stable_id == decision.selected_stable_id
        )
        item = {
            "stable_id": track.stable_id,
            "backend_track_id": track.backend_track_id,
            "track_state": track.state,
            "detection_id": candidate.detection_id,
            "label": candidate.label,
            "score": candidate.score,
            "bbox_xyxy": list(candidate.bbox_xyxy),
            "centroid_xy": list(track.centroid_xy),
            "selected": selected,
            "depth_valid": track.depth_supported,
            "blockers": list(track.blockers),
        }
        if selected and grasp_preview is not None:
            item.update(
                {
                    "actionable": grasp_preview.get("allowed") is True,
                    "calibration_validated": grasp_preview.get("allowed") is True,
                    "arm_stationary": "arm_not_stationary"
                    not in grasp_preview.get("blockers", []),
                    "safety_approved": grasp_preview.get("allowed") is True,
                    "observed_at_ms": provenance.observed_at_ms,
                    "grasp_preview": grasp_preview,
                }
            )
        targets.append(item)
    pose = None
    if decision.pose is not None:
        pose = {
            "frame": decision.pose.frame,
            "point_m": list(decision.pose.point_m),
            "axis": list(decision.pose.axis),
            "approach": list(decision.pose.approach),
            "width_m": decision.pose.width_m,
            "position_std_m": list(decision.pose.position_std_m),
            "depth_valid_ratio": decision.pose.depth_valid_ratio,
        }
    return {
        "type": "detection_result",
        "schema": "thirdhand-va-detection-v3",
        "ts": provenance.observed_at_ms,
        "frame_id": provenance.frame_id,
        "monotonic_ns": provenance.monotonic_ns,
        "overlay_sha256": "sha256:" + hashlib.sha256(overlay_jpeg).hexdigest(),
        "robot_control_enabled": False,
        "hardware_validation": "pending",
        "request_id": decision.request_id,
        "selected_stable_id": decision.selected_stable_id,
        "camera_serial": decision.camera_serial,
        "registration_id": decision.registration_id,
        "motion_epoch": decision.motion_epoch,
        "evidence_id": decision.evidence_id,
        "model_provenance": dict(model_provenance or {}),
        "status": decision.status,
        "reasons": list(decision.reasons),
        "stable_hits": decision.stable_hits,
        "window_size": decision.window_size,
        "targets": targets,
        "pose": pose,
    }


class LatestFramePublisher:
    """Single-slot publisher: offering a frame replaces any unsent older frame."""

    def __init__(self) -> None:
        self._pending: tuple[
            bytes,
            VisionDecision,
            FrameProvenance,
            dict[str, Any] | None,
            dict[str, str] | None,
        ] | None = None

    def offer(
        self,
        jpeg: bytes,
        decision: VisionDecision,
        provenance: FrameProvenance,
        grasp_preview: dict[str, Any] | None = None,
        model_provenance: dict[str, str] | None = None,
    ) -> None:
        if decision.frame_id != provenance.frame_id:
            raise ValueError("decision and provenance frame ids must match")
        self._pending = (
            bytes(jpeg),
            decision,
            provenance,
            grasp_preview,
            None if model_provenance is None else dict(model_provenance),
        )

    def drain(
        self,
        primary_mjpeg: BinaryIO,
        event_stream: BinaryIO,
        overlay_mjpeg: BinaryIO,
    ) -> bool:
        pending, self._pending = self._pending, None
        if pending is None:
            return False
        jpeg, decision, provenance, grasp_preview, model_provenance = pending
        part = build_mjpeg_part(jpeg, provenance)
        event = build_detection_event(
            decision,
            provenance,
            jpeg,
            grasp_preview=grasp_preview,
            model_provenance=model_provenance,
        )
        encoded_event = json.dumps(
            event, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8") + b"\n"
        try:
            primary_mjpeg.write(part)
            event_stream.write(encoded_event)
            overlay_mjpeg.write(part)
            for stream in (primary_mjpeg, event_stream, overlay_mjpeg):
                flush = getattr(stream, "flush", None)
                if flush is not None:
                    flush()
        except (BrokenPipeError, OSError):
            return False
        return True
