"""Pure RGB projection guard for a frozen, depth-backed bottle reference.

Freshness, robot-pose coverage, and calibration approval remain caller gates.  This
module never derives a new robot target from a near-field RGB frame.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import os
from pathlib import Path
import sys
from typing import Any

import cv2
import numpy as np

try:
    from thirdhand_vision.core.camera import SeucmCamera
except ModuleNotFoundError:
    # The checked-in SDK is a sibling source tree rather than a package declared
    # by this project's pyproject.  Keep the runtime usable from the documented
    # PinZi interpreter while still using the single SDK camera implementation.
    _sdk_source = Path(
        os.environ.get(
            "THIRDHAND_VISION_SDK_SRC",
            str(Path.home() / "TH-Fanxy/packages/thirdhand-vision-sdk/src"),
        )
    )
    if not _sdk_source.is_dir():
        raise
    sys.path.insert(0, str(_sdk_source))
    from thirdhand_vision.core.camera import SeucmCamera

from thirdhand_va.common.contracts import MaskCandidate, RgbdFrame


_CAMERA = SeucmCamera(
    fx=392.5984802,
    fy=392.4404297,
    cx=637.3952637,
    cy=641.7739868,
    alpha=0.6799842119,
    beta=0.7471178174,
    width=1280,
    height=1280,
)
_STREAM_WIDTH = 640
_STREAM_HEIGHT = 480
_MAX_REFERENCE_POINTS = 256
_MIN_REFERENCE_POINTS = 20
_MIN_SCORE = 0.50
_MAX_APPEARANCE_DISTANCE = 0.35
_MIN_PROJECTED_SUPPORT = 0.65
_MAX_CENTER_ERROR_PX = 12.0
_MIN_WIDTH_RATIO = 0.85
_MAX_WIDTH_RATIO = 1.15
_TRACKING_ASPECT_ONLY_REASONS = frozenset({
    "bottle_aspect_out_of_range",
    "container_type_not_bottle",
})


def create_reference(
    frame: RgbdFrame,
    candidate: MaskCandidate,
    t_base_camera: np.ndarray,
    center_base_xyz_m: Sequence[float],
    calibration_id: str,
) -> dict[str, Any]:
    """Freeze one stationary RGB-D target as a JSON-serializable RGB guard reference."""

    transform = _transform(t_base_camera)
    center = _triplet(center_base_xyz_m, "center_base_xyz_m")
    if not calibration_id:
        raise ValueError("calibration_id must not be empty")
    _validate_candidate_grid(frame, candidate)
    if not candidate.authorized or not candidate.mask.any():
        raise ValueError("reference candidate must be authorized with a non-empty mask")
    descriptor = _descriptor(candidate)

    points_camera = np.asarray(frame.xyz_camera_m[candidate.mask], dtype=np.float64)
    finite = np.isfinite(points_camera).all(axis=1) & (points_camera[:, 2] > 0.0)
    points_camera = points_camera[finite]
    if len(points_camera) < _MIN_REFERENCE_POINTS:
        raise ValueError("reference requires depth-backed mask points")

    near_low, near_high = np.quantile(points_camera[:, 2], (0.05, 0.45))
    points_camera = points_camera[
        (points_camera[:, 2] >= near_low) & (points_camera[:, 2] <= near_high)
    ]
    points_base = points_camera @ transform[:3, :3].T + transform[:3, 3]
    body = points_base[(points_base[:, 2] >= 0.10) & (points_base[:, 2] <= 0.14)]
    if len(body) < _MIN_REFERENCE_POINTS:
        raise ValueError("reference has insufficient bottle-body points in base z [0.10, 0.14] m")
    if len(body) > _MAX_REFERENCE_POINTS:
        indices = np.linspace(0, len(body) - 1, _MAX_REFERENCE_POINTS, dtype=int)
        body = body[indices]

    reference_camera = (body - transform[:3, 3]) @ transform[:3, :3]
    reference_uv, visible = _project_stream(reference_camera)
    reference_uv = reference_uv[visible]
    if len(reference_uv) < _MIN_REFERENCE_POINTS:
        raise ValueError("reference bottle-body projection is outside the RGB stream")
    projected_centroid = np.median(reference_uv, axis=0)
    projected_width = float(
        np.quantile(reference_uv[:, 0], 0.99) - np.quantile(reference_uv[:, 0], 0.01)
    )
    if projected_width <= 1e-9:
        raise ValueError("reference bottle-body projection has zero width")
    center_camera = (center - transform[:3, 3]) @ transform[:3, :3]
    center_uv, center_visible = _project_stream(center_camera[None, :])
    if not bool(center_visible[0]):
        raise ValueError("reference center projects outside the RGB stream")
    mask_centroid, mask_width = _mask_slice_geometry(candidate.mask, reference_uv)
    if mask_centroid is None or mask_width is None:
        raise ValueError("reference mask has no local body cross-section support")
    return {
        "schema": "thirdhand-nearfield-rgb-reference-v1",
        "camera_model": "lumos_seucm_native_1280_center_crop_640x480",
        "camera_serial": frame.camera_serial,
        "calibration_id": str(calibration_id),
        "reference_frame_id": int(frame.sequence),
        "reference_captured_monotonic_ns": int(frame.monotonic_ns),
        "target_detection_id": int(candidate.detection_id),
        "reference_score": float(candidate.score),
        "reference_descriptor": descriptor.tolist(),
        "center_base_xyz_m": center.tolist(),
        "body_points_base_m": body.tolist(),
        "body_point_count": int(len(body)),
        "reference_mask_centroid_uv": mask_centroid.tolist(),
        "reference_mask_width_px": float(mask_width),
        "reference_projected_body_centroid_uv": projected_centroid.tolist(),
        "reference_projected_body_width_px": projected_width,
        "reference_center_residual_uv": (mask_centroid - projected_centroid).tolist(),
        "reference_mask_to_body_width_ratio": float(mask_width / projected_width),
        "reference_near_surface_depth_range_m": [float(near_low), float(near_high)],
    }


def evaluate_reference(
    frame: RgbdFrame,
    candidate: MaskCandidate | None,
    t_base_camera: np.ndarray | None,
    reference: Mapping[str, Any],
    expected_translation_m: Sequence[float] = (0.0, 0.0, 0.0),
) -> dict[str, Any]:
    """Compare a current RGB mask with the projection of a frozen Base-frame reference."""

    blockers: list[str] = []
    diagnostics: dict[str, Any] = {
        "expected_center_camera_xyz_m": None,
        "expected_center_uv": None,
        "projected_centroid_uv": None,
        "observed_centroid_uv": None,
        "projected_support_fraction": None,
        "center_error_px": None,
        "projected_width_px": None,
        "observed_width_px": None,
        "width_ratio": None,
        "width_ratio_diagnostic_only": True,
        "width_ratio_reference_range": [_MIN_WIDTH_RATIO, _MAX_WIDTH_RATIO],
        "width_ratio_outside_reference_tolerance": None,
        "appearance_distance": None,
        "projected_visible_fraction": None,
        "calibration_id": reference.get("calibration_id"),
        "candidate_reasons": None,
        "candidate_bbox_xyxy": None,
        "candidate_score": None,
        "candidate_mask_area_px": None,
        "reference_tracking_aspect_only_exception": False,
    }
    if reference.get("schema") != "thirdhand-nearfield-rgb-reference-v1":
        raise ValueError("unsupported near-field reference schema")
    delta = _triplet(expected_translation_m, "expected_translation_m")

    if frame.camera_serial != reference.get("camera_serial"):
        blockers.append("camera_serial_mismatch")
    if candidate is None:
        blockers.append("target_lost")
    else:
        _validate_candidate_grid(frame, candidate)
        diagnostics.update({
            "candidate_reasons": list(candidate.reasons),
            "candidate_bbox_xyxy": list(candidate.bbox_xyxy),
            "candidate_score": float(candidate.score),
            "candidate_mask_area_px": int(candidate.mask.sum()),
        })
        aspect_only_exception = (
            not candidate.authorized
            and frozenset(candidate.reasons) == _TRACKING_ASPECT_ONLY_REASONS
        )
        diagnostics["reference_tracking_aspect_only_exception"] = aspect_only_exception
        if candidate.detection_id != int(reference["target_detection_id"]):
            blockers.append("target_id_mismatch")
        if not candidate.authorized and not aspect_only_exception:
            blockers.append("candidate_not_authorized")
        if not candidate.mask.any():
            blockers.append("mask_empty")
        score_floor = max(_MIN_SCORE, float(reference["reference_score"]) - 0.25)
        if candidate.score < score_floor:
            blockers.append("score_too_low")
        current_descriptor = candidate.descriptor
        reference_descriptor = np.asarray(reference["reference_descriptor"], dtype=np.float64)
        if (
            current_descriptor is None
            or current_descriptor.shape != reference_descriptor.shape
            or not np.isfinite(current_descriptor).all()
            or not np.isfinite(reference_descriptor).all()
        ):
            blockers.append("appearance_unavailable")
        else:
            appearance_distance = _cosine_distance(current_descriptor, reference_descriptor)
            diagnostics["appearance_distance"] = appearance_distance
            if appearance_distance > _MAX_APPEARANCE_DISTANCE:
                blockers.append("appearance_mismatch")

    rgb_blockers = {
        "camera_serial_mismatch",
        "target_lost",
        "target_id_mismatch",
        "candidate_not_authorized",
        "mask_empty",
        "score_too_low",
        "appearance_unavailable",
        "appearance_mismatch",
    }
    rgb_valid = not any(item in rgb_blockers for item in blockers)
    if t_base_camera is None:
        blockers.append("pose_unavailable")
        return _result(rgb_valid, False, blockers, diagnostics)

    transform = _transform(t_base_camera)
    points_base = np.asarray(reference["body_points_base_m"], dtype=np.float64)
    if points_base.ndim != 2 or points_base.shape[1:] != (3,) or len(points_base) < _MIN_REFERENCE_POINTS:
        raise ValueError("reference body points must be finite Nx3 data")
    if not np.isfinite(points_base).all():
        raise ValueError("reference body points must be finite Nx3 data")
    points_base = points_base + delta
    points_camera = (points_base - transform[:3, 3]) @ transform[:3, :3]
    uv, visible = _project_stream(points_camera)
    visible_count = int(np.count_nonzero(visible))
    diagnostics["projected_visible_fraction"] = visible_count / len(points_base)
    if visible_count < _MIN_REFERENCE_POINTS:
        blockers.append("projected_target_out_of_view")
        return _result(rgb_valid, False, blockers, diagnostics)
    if diagnostics["projected_visible_fraction"] < _MIN_PROJECTED_SUPPORT:
        blockers.append("projected_target_clipped")

    projected = uv[visible]
    projected_centroid = np.median(projected, axis=0)
    diagnostics["projected_centroid_uv"] = projected_centroid.tolist()
    projected_width = float(np.quantile(projected[:, 0], 0.99) - np.quantile(projected[:, 0], 0.01))
    diagnostics["projected_width_px"] = projected_width

    center_base = np.asarray(reference["center_base_xyz_m"], dtype=np.float64) + delta
    center_camera = (center_base - transform[:3, 3]) @ transform[:3, :3]
    center_uv, center_visible = _project_stream(center_camera[None, :])
    diagnostics["expected_center_camera_xyz_m"] = center_camera.tolist()
    if bool(center_visible[0]):
        diagnostics["expected_center_uv"] = center_uv[0].tolist()
    else:
        blockers.append("expected_center_out_of_view")

    if candidate is not None and candidate.mask.any():
        observed_centroid, observed_width = _mask_slice_geometry(candidate.mask, projected)
        if observed_centroid is None or observed_width is None:
            blockers.append("projected_cross_section_unobserved")
            return _result(rgb_valid, False, blockers, diagnostics)
        diagnostics["observed_centroid_uv"] = observed_centroid.tolist()
        diagnostics["observed_width_px"] = observed_width
        residual = np.asarray(reference["reference_center_residual_uv"], dtype=np.float64)
        comparison_center = projected_centroid + residual
        center_error = float(np.linalg.norm(observed_centroid - comparison_center))
        diagnostics["center_error_px"] = center_error
        if center_error > _MAX_CENTER_ERROR_PX:
            blockers.append("projected_position_mismatch")

        expected_width = projected_width * float(reference["reference_mask_to_body_width_ratio"])
        width_ratio = observed_width / expected_width if expected_width > 1e-9 else float("inf")
        diagnostics["width_ratio"] = width_ratio
        diagnostics["width_ratio_outside_reference_tolerance"] = not (
            _MIN_WIDTH_RATIO <= width_ratio <= _MAX_WIDTH_RATIO
        )

        expanded_mask = cv2.dilate(
            candidate.mask.astype(np.uint8), np.ones((7, 7), dtype=np.uint8)
        ).astype(bool)
        rounded = np.rint(projected).astype(int)
        rounded[:, 0] = np.clip(rounded[:, 0], 0, _STREAM_WIDTH - 1)
        rounded[:, 1] = np.clip(rounded[:, 1], 0, _STREAM_HEIGHT - 1)
        support = expanded_mask[rounded[:, 1], rounded[:, 0]]
        support_fraction = float(np.mean(support))
        diagnostics["projected_support_fraction"] = support_fraction
        if support_fraction < _MIN_PROJECTED_SUPPORT:
            blockers.append("projected_support_mismatch")

    projection_blockers = set(blockers)
    return _result(rgb_valid, rgb_valid and not projection_blockers, blockers, diagnostics)


def _project_stream(points_camera: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    native_uv, valid = _CAMERA.project(points_camera)
    stream_uv = np.column_stack(
        (native_uv[:, 0] * 0.5, (native_uv[:, 1] - 160.0) * 0.5)
    )
    valid &= np.isfinite(stream_uv).all(axis=1)
    valid &= np.asarray(points_camera)[:, 2] > 0.0
    valid &= (stream_uv[:, 0] >= 0.0) & (stream_uv[:, 0] < _STREAM_WIDTH)
    valid &= (stream_uv[:, 1] >= 0.0) & (stream_uv[:, 1] < _STREAM_HEIGHT)
    return stream_uv, valid


def _result(
    rgb_valid: bool,
    projection_valid: bool,
    blockers: Sequence[str],
    diagnostics: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "rgb_observation_valid": bool(rgb_valid),
        "projection_guard_valid": bool(projection_valid),
        "guard_blockers": list(dict.fromkeys(blockers)),
        "diagnostics": dict(diagnostics),
    }


def _validate_candidate_grid(frame: RgbdFrame, candidate: MaskCandidate) -> None:
    if frame.rgb.shape[:2] != (_STREAM_HEIGHT, _STREAM_WIDTH):
        raise ValueError("near-field guard requires the registered 640x480 RGB stream")
    if candidate.mask.shape != frame.rgb.shape[:2]:
        raise ValueError("candidate mask must share the RGB frame grid")


def _descriptor(candidate: MaskCandidate) -> np.ndarray:
    if candidate.descriptor is None:
        raise ValueError("reference candidate requires an RGB appearance descriptor")
    descriptor = np.asarray(candidate.descriptor, dtype=np.float64)
    if not np.isfinite(descriptor).all() or np.linalg.norm(descriptor) <= 1e-12:
        raise ValueError("reference descriptor must be finite and non-zero")
    return descriptor


def _transform(value: Any) -> np.ndarray:
    transform = np.asarray(value, dtype=np.float64)
    if transform.shape != (4, 4) or not np.isfinite(transform).all():
        raise ValueError("t_base_camera must be a finite 4x4 transform")
    if not np.allclose(transform[3], [0.0, 0.0, 0.0, 1.0], atol=1e-9):
        raise ValueError("t_base_camera must be homogeneous")
    return transform


def _triplet(value: Sequence[float], name: str) -> np.ndarray:
    result = np.asarray(value, dtype=np.float64)
    if result.shape != (3,) or not np.isfinite(result).all():
        raise ValueError(f"{name} must contain three finite values")
    return result


def _mask_centroid(mask: np.ndarray) -> np.ndarray:
    ys, xs = np.nonzero(mask)
    if not len(xs):
        return np.asarray([np.nan, np.nan], dtype=np.float64)
    return np.asarray([np.median(xs), np.median(ys)], dtype=np.float64)


def _mask_slice_geometry(
    mask: np.ndarray, projected_uv: np.ndarray
) -> tuple[np.ndarray | None, float | None]:
    """Measure the current mask over the same image rows as projected body samples."""

    lower, upper = np.quantile(projected_uv[:, 1], (0.05, 0.95))
    ys, xs = np.nonzero(mask)
    keep = (ys >= int(np.floor(lower))) & (ys <= int(np.ceil(upper)))
    ys = ys[keep]
    xs = xs[keep]
    if not len(xs):
        return None, None
    row_widths = []
    for row in np.unique(ys):
        row_x = xs[ys == row]
        row_widths.append(float(row_x.max() - row_x.min() + 1))
    width = float(np.median(row_widths))
    return np.asarray([np.median(xs), np.median(ys)], dtype=np.float64), width


def _cosine_distance(left: Any, right: Any) -> float:
    first = np.asarray(left, dtype=np.float64)
    second = np.asarray(right, dtype=np.float64)
    denominator = float(np.linalg.norm(first) * np.linalg.norm(second))
    if denominator <= 1e-12:
        return 1.0
    return float(1.0 - np.clip(first @ second / denominator, -1.0, 1.0))


__all__ = ["create_reference", "evaluate_reference"]
