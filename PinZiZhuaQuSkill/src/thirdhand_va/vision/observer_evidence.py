"""One-shot evidence capture for a stationary near-field projection failure."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import json
from pathlib import Path
import time
from typing import Any

import cv2
import numpy as np

from thirdhand_va.common.contracts import MaskCandidate, RgbdFrame


def should_capture_projection_failure(
    payload: Mapping[str, Any], candidate: MaskCandidate | None
) -> bool:
    """Select a real, stationary RGB projection failure with a current mask."""

    return (
        candidate is not None
        and payload.get("event") == "bottle_projection_guard"
        and payload.get("rgb_observation_valid") is True
        and payload.get("projection_guard_valid") is False
        and payload.get("robot_pose_blockers") == []
        and "anchor_expired" not in payload.get("guard_blockers", [])
    )


def save_projection_failure_evidence(
    output_overlay: Path,
    *,
    frame: RgbdFrame,
    candidate: MaskCandidate,
    payload: Mapping[str, Any],
    write_started_at_ms: int | None = None,
    write_completed_at_ms: Callable[[], int] | None = None,
) -> dict[str, Any]:
    """Save one RGB, overlay, registered frame/mask, and timestamped metadata set."""

    overlay_path = Path(output_overlay)
    if overlay_path.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
        raise ValueError("output overlay must use .jpg, .jpeg, or .png")
    if candidate.mask.shape != frame.rgb.shape[:2]:
        raise ValueError("candidate mask must share the RGB frame grid")
    overlay_path.parent.mkdir(parents=True, exist_ok=True)
    stem = overlay_path.stem
    rgb_path = overlay_path.with_name(f"{stem}.rgb.png")
    frame_mask_path = overlay_path.with_name(f"{stem}.frame-mask.npz")
    metadata_path = overlay_path.with_name(f"{stem}.metadata.json")
    started_ms = (
        int(time.time() * 1000)
        if write_started_at_ms is None
        else int(write_started_at_ms)
    )

    rgb_bgr = cv2.cvtColor(frame.rgb, cv2.COLOR_RGB2BGR)
    overlay = rgb_bgr.copy()
    tint = overlay.copy()
    tint[candidate.mask] = (0, 180, 255)
    overlay = cv2.addWeighted(overlay, 0.72, tint, 0.28, 0.0)
    contours, _ = cv2.findContours(
        candidate.mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    cv2.drawContours(overlay, contours, -1, (0, 255, 255), 2)
    x0, y0, x1, y1 = (int(round(value)) for value in candidate.bbox_xyxy)
    cv2.rectangle(overlay, (x0, y0), (x1, y1), (0, 255, 255), 2)
    expected_uv = payload.get("pixel_uv")
    if (
        isinstance(expected_uv, (list, tuple))
        and len(expected_uv) == 2
        and np.isfinite(expected_uv).all()
    ):
        point = tuple(int(round(float(value))) for value in expected_uv)
        cv2.drawMarker(overlay, point, (255, 0, 255), cv2.MARKER_CROSS, 16, 2)
    label = ",".join(str(value) for value in payload.get("guard_blockers", []))
    cv2.putText(
        overlay,
        label[:90],
        (8, 24),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.52,
        (0, 0, 255),
        1,
        cv2.LINE_AA,
    )

    if not cv2.imwrite(str(overlay_path), overlay):
        raise OSError(f"failed to write overlay: {overlay_path}")
    if not cv2.imwrite(str(rgb_path), rgb_bgr):
        raise OSError(f"failed to write RGB frame: {rgb_path}")
    np.savez_compressed(
        frame_mask_path,
        rgb=frame.rgb,
        depth_m=frame.depth_m,
        xyz_camera_m=frame.xyz_camera_m,
        mask=candidate.mask,
    )
    completed_ms = (
        int(time.time() * 1000)
        if write_completed_at_ms is None
        else int(write_completed_at_ms())
    )
    metadata = {
        "schema": "thirdhand-stationary-projection-failure-evidence-v1",
        "frame_id": int(frame.sequence),
        "captured_monotonic_ns": int(frame.monotonic_ns),
        "camera_serial": frame.camera_serial,
        "target_detection_id": int(candidate.detection_id),
        "candidate_bbox_xyxy": list(candidate.bbox_xyxy),
        "candidate_score": float(candidate.score),
        "candidate_mask_area_px": int(candidate.mask.sum()),
        "candidate_reasons": list(candidate.reasons),
        "payload_observed_at_ms": payload.get("observed_at_ms"),
        "payload_emitted_at_ms": payload.get("emitted_at_ms"),
        "write_started_at_ms": started_ms,
        "write_completed_at_ms": completed_ms,
        "write_after_payload_emitted": (
            isinstance(payload.get("emitted_at_ms"), int)
            and started_ms >= int(payload["emitted_at_ms"])
        ),
        "projection_payload": dict(payload),
        "overlay_path": str(overlay_path.resolve()),
        "rgb_path": str(rgb_path.resolve()),
        "frame_mask_path": str(frame_mask_path.resolve()),
    }
    metadata_path.write_text(
        json.dumps(metadata, indent=2, sort_keys=True, default=_json_default) + "\n",
        encoding="utf-8",
    )
    return {
        "event": "projection_failure_evidence_saved",
        "frame_id": int(frame.sequence),
        "write_started_at_ms": started_ms,
        "write_completed_at_ms": completed_ms,
        "overlay_path": str(overlay_path.resolve()),
        "rgb_path": str(rgb_path.resolve()),
        "frame_mask_path": str(frame_mask_path.resolve()),
        "metadata_path": str(metadata_path.resolve()),
        "robot_control_enabled": False,
        "execution_enabled": False,
    }


def _json_default(value: Any) -> Any:
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    raise TypeError(f"not JSON serializable: {type(value).__name__}")


__all__ = ["save_projection_failure_evidence", "should_capture_projection_failure"]
