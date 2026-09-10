"""Robust fixed-intrinsics relative-extrinsic solver for Lumos and D435."""

from __future__ import annotations

import json
import math
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from scipy.optimize import least_squares
from scipy.spatial.transform import Rotation
from vision.geometry import validate_transform

from vision_models.calibration_capture import CalibrationCaptureError
from vision_models.dual_camera_candidate import (
    DualCameraCandidate,
    build_refit_candidate_payload,
)
from vision_models.dual_camera_refit_capture import (
    FIT_REQUIRED_SAMPLES,
    DualCameraFitObservation,
    observations_from_manifest,
)


@dataclass(frozen=True)
class DualCameraRefitResult:
    """Accepted fit geometry and bounded diagnostics."""

    transform: np.ndarray = field(compare=False, repr=False)
    samples: int
    corners: int
    median_px: float
    p95_px: float
    baseline_m: float
    rotation_deg: float
    nfev: int

    def __post_init__(self) -> None:
        try:
            transform = validate_transform(self.transform)
        except (TypeError, ValueError) as exc:
            raise CalibrationCaptureError("refit result transform is invalid") from exc
        numeric = np.asarray(
            [
                self.samples,
                self.corners,
                self.median_px,
                self.p95_px,
                self.baseline_m,
                self.rotation_deg,
                self.nfev,
            ],
            dtype=float,
        )
        if (
            isinstance(self.samples, bool)
            or not isinstance(self.samples, int)
            or isinstance(self.corners, bool)
            or not isinstance(self.corners, int)
            or isinstance(self.nfev, bool)
            or not isinstance(self.nfev, int)
            or not np.isfinite(numeric).all()
            or np.any(numeric < 0.0)
        ):
            raise CalibrationCaptureError("refit result metrics are invalid")
        transform.setflags(write=False)
        object.__setattr__(self, "transform", transform)


def _parameters_from_matrix(transform: Any) -> np.ndarray:
    matrix = validate_transform(transform)
    return np.concatenate(
        (Rotation.from_matrix(matrix[:3, :3]).as_rotvec(), matrix[:3, 3])
    )


def _matrix_from_parameters(parameters: Any) -> np.ndarray:
    values = np.asarray(parameters, dtype=float)
    if values.shape != (6,) or not np.isfinite(values).all():
        raise CalibrationCaptureError("refit parameters are invalid")
    transform = np.eye(4, dtype=float)
    transform[:3, :3] = Rotation.from_rotvec(values[:3]).as_matrix()
    transform[:3, 3] = values[3:]
    return validate_transform(transform)


def _project_observation(
    observation: DualCameraFitObservation,
    candidate: DualCameraCandidate,
    transform: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    points_d435 = (
        observation.object_points_m @ observation.t_d435_from_board[:3, :3].T
        + observation.t_d435_from_board[:3, 3]
    )
    points_lumos = points_d435 @ transform[:3, :3].T + transform[:3, 3]
    return candidate.lumos.project(points_lumos)


def _residual_vector(
    parameters: np.ndarray,
    observations: tuple[DualCameraFitObservation, ...],
    candidate: DualCameraCandidate,
) -> np.ndarray:
    transform = _matrix_from_parameters(parameters)
    chunks: list[np.ndarray] = []
    for observation in observations:
        projected, valid = _project_observation(observation, candidate, transform)
        residual = projected - observation.lumos_image_points_px
        if not valid.all():
            residual = np.asarray(residual, dtype=float)
            residual[~valid] = 1000.0
        chunks.append(residual.reshape(-1))
    return np.concatenate(chunks)


def _solve(
    observations: tuple[DualCameraFitObservation, ...],
    candidate: DualCameraCandidate,
    initial: np.ndarray,
):
    return least_squares(
        _residual_vector,
        initial,
        args=(observations, candidate),
        method="trf",
        loss="soft_l1",
        f_scale=2.0,
        x_scale="jac",
        max_nfev=1000,
    )


def _aggregate_pose_initialization(
    observations: tuple[DualCameraFitObservation, ...],
    candidate: DualCameraCandidate,
) -> np.ndarray:
    seed = _parameters_from_matrix(candidate.t_lumos_from_d435)
    solutions = []
    for observation in observations:
        solved = _solve((observation,), candidate, seed)
        if not solved.success or not np.isfinite(solved.x).all():
            raise CalibrationCaptureError("per-pose refit initialization failed")
        solutions.append(_matrix_from_parameters(solved.x))
    rotations = Rotation.from_matrix(
        np.stack([transform[:3, :3] for transform in solutions])
    )
    translation = np.median(
        np.stack([transform[:3, 3] for transform in solutions]), axis=0
    )
    aggregate = np.concatenate((rotations.mean().as_rotvec(), translation))
    return aggregate


def solve_dual_camera_refit(
    manifest: dict[str, Any],
    seed: DualCameraCandidate,
) -> DualCameraRefitResult:
    """Fit one Lumos-from-D435 transform from exactly 12 verified fit poses."""

    if not isinstance(manifest, dict) or manifest.get("purpose") != "fit":
        raise CalibrationCaptureError("refit solver requires purpose=fit")
    if not isinstance(seed, DualCameraCandidate):
        raise CalibrationCaptureError("typed dual-camera seed is required")
    if manifest.get("seed_candidate_id") != seed.candidate_id:
        raise CalibrationCaptureError("fit seed candidate changed")
    observations = observations_from_manifest(manifest)
    if len(observations) != FIT_REQUIRED_SAMPLES:
        raise CalibrationCaptureError("refit solver requires exactly 12 samples")
    if any(
        item.common_points < 24 or item.d435_reprojection_rmse_px > 1.5
        for item in observations
    ):
        raise CalibrationCaptureError("fit observations do not satisfy capture gates")
    initial = _aggregate_pose_initialization(observations, seed)
    solved = _solve(observations, seed, initial)
    if not solved.success or not np.isfinite(solved.x).all():
        raise CalibrationCaptureError("joint refit optimization did not converge")
    transform = _matrix_from_parameters(solved.x)
    errors: list[np.ndarray] = []
    for observation in observations:
        projected, valid = _project_observation(observation, seed, transform)
        if not valid.all():
            raise CalibrationCaptureError("refit projects outside the Lumos EUCM domain")
        errors.append(np.linalg.norm(projected - observation.lumos_image_points_px, axis=1))
    combined = np.concatenate(errors)
    median = float(np.median(combined))
    p95 = float(np.percentile(combined, 95))
    baseline = float(np.linalg.norm(transform[:3, 3]))
    rotation_deg = float(
        math.degrees(Rotation.from_matrix(transform[:3, :3]).magnitude())
    )
    if not 0.02 <= baseline <= 0.30:
        raise CalibrationCaptureError("refit baseline is outside [0.02, 0.30] m")
    if rotation_deg > 45.0:
        raise CalibrationCaptureError("refit rotation exceeds 45 degrees")
    if p95 > 3.0:
        raise CalibrationCaptureError("refit pixel P95 exceeds 3 px")
    return DualCameraRefitResult(
        transform=transform,
        samples=len(observations),
        corners=len(combined),
        median_px=median,
        p95_px=p95,
        baseline_m=baseline,
        rotation_deg=rotation_deg,
        nfev=int(solved.nfev),
    )


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(
                json.dumps(
                    payload, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False
                ).encode("ascii")
                + b"\n"
            )
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def write_refit_candidate(
    path: Path | str,
    *,
    result: DualCameraRefitResult,
    seed_payload: dict[str, Any],
    fit_dataset_id: str,
) -> Path:
    """Atomically persist one already-gated, non-executable refit candidate."""

    if not isinstance(result, DualCameraRefitResult):
        raise CalibrationCaptureError("typed refit result is required")
    destination = Path(path)
    if destination.exists():
        raise CalibrationCaptureError("refit candidate output already exists")
    payload = build_refit_candidate_payload(
        seed_payload=seed_payload,
        transform=result.transform,
        fit_dataset_id=fit_dataset_id,
        metrics={
            "samples": result.samples,
            "corners": result.corners,
            "median_px": result.median_px,
            "p95_px": result.p95_px,
            "baseline_m": result.baseline_m,
            "rotation_deg": result.rotation_deg,
            "nfev": result.nfev,
        },
    )
    _atomic_json(destination, payload)
    return destination


__all__ = [
    "DualCameraRefitResult",
    "solve_dual_camera_refit",
    "write_refit_candidate",
]
