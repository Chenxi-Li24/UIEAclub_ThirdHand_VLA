"""Held-out pixel validation for a non-executable legacy dual-camera seed."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np
from vision.camera_models import PinholeCamera, SeucmCamera
from vision.geometry import make_transform, validate_transform

from vision_models.calibration_targets import TargetCorners


class LegacyCandidateValidationError(ValueError):
    """Raised when candidate evidence cannot be scored safely."""


@dataclass(frozen=True)
class LegacyCandidatePairResult:
    common_points: int
    d435_reprojection_rmse_px: float
    lumos_reprojection_median_px: float
    lumos_reprojection_p95_px: float
    passes_pixel_gate: bool
    lumos_errors_px: np.ndarray = field(compare=False, repr=False)
    t_d435_from_board: np.ndarray = field(compare=False, repr=False)

    def __post_init__(self) -> None:
        errors = np.asarray(self.lumos_errors_px, dtype=float)
        try:
            board_pose = validate_transform(self.t_d435_from_board)
        except (TypeError, ValueError) as exc:
            raise LegacyCandidateValidationError(
                "legacy candidate board pose is invalid"
            ) from exc
        metrics = np.asarray(
            [
                self.d435_reprojection_rmse_px,
                self.lumos_reprojection_median_px,
                self.lumos_reprojection_p95_px,
            ],
            dtype=float,
        )
        if (
            isinstance(self.common_points, bool)
            or not isinstance(self.common_points, int)
            or self.common_points < 4
            or errors.ndim != 1
            or len(errors) < 4
            or not np.isfinite(errors).all()
            or not np.isfinite(metrics).all()
            or np.any(metrics < 0.0)
            or not isinstance(self.passes_pixel_gate, (bool, np.bool_))
        ):
            raise LegacyCandidateValidationError(
                "legacy candidate validation result is invalid"
            )
        errors.setflags(write=False)
        board_pose.setflags(write=False)
        object.__setattr__(self, "lumos_errors_px", errors)
        object.__setattr__(self, "t_d435_from_board", board_pose)
        object.__setattr__(self, "passes_pixel_gate", bool(self.passes_pixel_gate))


def _camera_matrix(camera: PinholeCamera) -> np.ndarray:
    return np.array(
        [[camera.fx, 0.0, camera.cx], [0.0, camera.fy, camera.cy], [0.0, 0.0, 1.0]],
        dtype=np.float64,
    )


def _matched_corners(
    first: TargetCorners,
    second: TargetCorners,
) -> tuple[np.ndarray, np.ndarray, tuple[int, ...]]:
    first_index = {key: index for index, key in enumerate(first.point_ids)}
    second_index = {key: index for index, key in enumerate(second.point_ids)}
    common = tuple(sorted(set(first_index).intersection(second_index)))
    if len(common) < 4:
        raise LegacyCandidateValidationError(
            "both cameras must share at least four target points"
        )
    first_objects = np.asarray(
        [first.object_points[first_index[key]] for key in common], dtype=np.float64
    )
    second_objects = np.asarray(
        [second.object_points[second_index[key]] for key in common], dtype=np.float64
    )
    if not np.allclose(first_objects, second_objects, atol=1e-12, rtol=0.0):
        raise LegacyCandidateValidationError(
            "target object coordinates disagree between cameras"
        )
    second_pixels = np.asarray(
        [second.image_points[second_index[key]] for key in common], dtype=np.float64
    )
    return first_objects, second_pixels, common


def evaluate_legacy_candidate_pair(
    *,
    d435: PinholeCamera,
    lumos: SeucmCamera,
    t_lumos_from_d435: Any,
    d435_detection: TargetCorners,
    lumos_detection: TargetCorners,
) -> LegacyCandidatePairResult:
    """Solve the board only in D435, then score native SEUCM pixels in Lumos."""

    if not isinstance(d435, PinholeCamera) or not isinstance(lumos, SeucmCamera):
        raise LegacyCandidateValidationError(
            "typed D435 and Lumos camera models are required"
        )
    if not isinstance(d435_detection, TargetCorners) or not isinstance(
        lumos_detection, TargetCorners
    ):
        raise LegacyCandidateValidationError("typed target detections are required")
    relative = validate_transform(t_lumos_from_d435)
    intrinsics = _camera_matrix(d435)
    distortion = np.zeros(4, dtype=np.float64)
    solved, rotation_vector, translation = cv2.solvePnP(
        d435_detection.object_points,
        d435_detection.image_points,
        intrinsics,
        distortion,
        flags=cv2.SOLVEPNP_IPPE,
    )
    if not solved:
        raise LegacyCandidateValidationError("D435 target PnP failed")
    rotation_vector, translation = cv2.solvePnPRefineLM(
        d435_detection.object_points,
        d435_detection.image_points,
        intrinsics,
        distortion,
        rotation_vector,
        translation,
    )
    rotation, _jacobian = cv2.Rodrigues(rotation_vector)
    t_d435_from_board = make_transform(rotation, np.asarray(translation).reshape(3))
    d435_projected, _jacobian = cv2.projectPoints(
        d435_detection.object_points,
        rotation_vector,
        translation,
        intrinsics,
        distortion,
    )
    d435_residuals = (
        np.asarray(d435_projected).reshape(-1, 2) - d435_detection.image_points
    )
    d435_rmse = float(np.sqrt(np.mean(np.sum(d435_residuals * d435_residuals, axis=1))))
    common_objects, lumos_actual, common_point_ids = _matched_corners(
        d435_detection,
        lumos_detection,
    )
    points_d435 = (
        common_objects @ t_d435_from_board[:3, :3].T + t_d435_from_board[:3, 3]
    )
    points_lumos = points_d435 @ relative[:3, :3].T + relative[:3, 3]
    lumos_projected, valid = lumos.project(points_lumos)
    if not valid.all():
        raise LegacyCandidateValidationError(
            "legacy candidate projects common target points outside Lumos"
        )
    errors = np.linalg.norm(lumos_projected - lumos_actual, axis=1)
    median = float(np.median(errors))
    p95 = float(np.percentile(errors, 95))
    common_points = len(common_point_ids)
    passes = common_points >= 24 and d435_rmse <= 1.5 and p95 <= 4.0
    return LegacyCandidatePairResult(
        common_points=common_points,
        d435_reprojection_rmse_px=d435_rmse,
        lumos_reprojection_median_px=median,
        lumos_reprojection_p95_px=p95,
        passes_pixel_gate=passes,
        lumos_errors_px=errors,
        t_d435_from_board=t_d435_from_board,
    )


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")


def _rotation_delta_rad(first: np.ndarray, second: np.ndarray) -> float:
    relative = first[:3, :3].T @ second[:3, :3]
    return math.acos(float(np.clip((np.trace(relative) - 1.0) / 2.0, -1.0, 1.0)))


def pose_is_distinct(
    candidate: LegacyCandidatePairResult,
    previous: Iterable[LegacyCandidatePairResult],
    *,
    translation_m: float = 0.015,
    rotation_deg: float = 3.0,
) -> bool:
    """Return whether a board pose is separated from every selected pose."""

    if not isinstance(candidate, LegacyCandidatePairResult):
        raise LegacyCandidateValidationError("candidate pose result is invalid")
    items = tuple(previous)
    if any(not isinstance(item, LegacyCandidatePairResult) for item in items):
        raise LegacyCandidateValidationError("previous pose results are invalid")
    thresholds = np.asarray([translation_m, rotation_deg], dtype=float)
    if not np.isfinite(thresholds).all() or np.any(thresholds <= 0.0):
        raise LegacyCandidateValidationError("pose separation thresholds are invalid")
    rotation_rad = math.radians(rotation_deg)
    return all(
        np.linalg.norm(
            candidate.t_d435_from_board[:3, 3] - item.t_d435_from_board[:3, 3]
        )
        >= translation_m - 1e-12
        or _rotation_delta_rad(
            candidate.t_d435_from_board,
            item.t_d435_from_board,
        )
        >= rotation_rad - 1e-12
        for item in items
    )


def _distinct_pose_count(items: tuple[LegacyCandidatePairResult, ...]) -> int:
    ordered = sorted(
        items,
        key=lambda item: tuple(
            np.round(item.t_d435_from_board.reshape(-1), decimals=12)
        ),
    )
    selected: list[LegacyCandidatePairResult] = []
    for item in ordered:
        if pose_is_distinct(item, selected):
            selected.append(item)
    return len(selected)


def summarize_legacy_candidate(
    observations: Iterable[LegacyCandidatePairResult],
    *,
    candidate_id: str,
) -> dict[str, Any]:
    items = tuple(observations)
    if any(not isinstance(item, LegacyCandidatePairResult) for item in items):
        raise LegacyCandidateValidationError(
            "legacy validation observations are invalid"
        )
    if (
        not isinstance(candidate_id, str)
        or len(candidate_id) != 71
        or not candidate_id.startswith("sha256:")
    ):
        raise LegacyCandidateValidationError("legacy candidate ID is invalid")
    if not items:
        raise LegacyCandidateValidationError("legacy validation requires observations")
    all_errors = np.concatenate([item.lumos_errors_px for item in items])
    d435_rmse = float(
        math.sqrt(np.mean([item.d435_reprojection_rmse_px**2 for item in items]))
    )
    lumos_median = float(np.median(all_errors))
    lumos_p95 = float(np.percentile(all_errors, 95))
    required_samples = 10
    distinct_poses = _distinct_pose_count(items)
    passing_pairs = sum(item.passes_pixel_gate for item in items)
    relative_validated = (
        len(items) >= required_samples
        and distinct_poses >= required_samples
        and passing_pairs == len(items)
        and all(item.common_points >= 24 for item in items)
        and d435_rmse <= 1.5
        and lumos_p95 <= 4.0
    )
    blockers = ["handeye_validation_missing", "table_validation_missing"]
    if not relative_validated:
        blockers.insert(0, "relative_extrinsic_validation_failed")
    if distinct_poses < required_samples:
        blockers.insert(0, "pose_diversity_insufficient")
    payload: dict[str, Any] = {
        "schema_version": 1,
        "candidate_id": candidate_id,
        "samples": len(items),
        "required_samples": required_samples,
        "passing_pairs": passing_pairs,
        "distinct_poses": distinct_poses,
        "pose_separation_translation_m": 0.015,
        "pose_separation_rotation_deg": 3.0,
        "common_points_min": min(item.common_points for item in items),
        "d435_reprojection_rmse_px": d435_rmse,
        "lumos_reprojection_median_px": lumos_median,
        "lumos_reprojection_p95_px": lumos_p95,
        "relative_extrinsic_validated": relative_validated,
        "executable": False,
        "remaining_blockers": blockers,
    }
    payload["content_id"] = f"sha256:{hashlib.sha256(_canonical(payload)).hexdigest()}"
    return payload


__all__ = [
    "LegacyCandidatePairResult",
    "LegacyCandidateValidationError",
    "evaluate_legacy_candidate_pair",
    "pose_is_distinct",
    "summarize_legacy_candidate",
]
