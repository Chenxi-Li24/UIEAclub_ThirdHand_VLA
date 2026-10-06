"""Pure algebraic one-step pivot calibration and validation."""

from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

import numpy as np


DEFAULT_THRESHOLDS = {
    "fitRmsGreenM": 0.002,
    "fitMaximumGreenM": 0.004,
    "fitRmsMaximumM": 0.003,
    "fitMaximumM": 0.005,
    "validationMaximumM": 0.005,
}


def _rigid(value: Any, name: str) -> np.ndarray:
    matrix = np.asarray(value, dtype=np.float64)
    if matrix.shape != (4, 4) or not np.isfinite(matrix).all():
        raise ValueError(f"{name}_must_be_finite_rigid_transform")
    if not np.allclose(matrix[3], [0, 0, 0, 1], atol=1e-9):
        raise ValueError(f"{name}_must_be_finite_rigid_transform")
    rotation = matrix[:3, :3]
    if not np.allclose(rotation.T @ rotation, np.eye(3), atol=1e-7) or not math.isclose(
        float(np.linalg.det(rotation)), 1.0, abs_tol=1e-7
    ):
        raise ValueError(f"{name}_must_be_finite_rigid_transform")
    return matrix.copy()


def _thresholds(value: Mapping[str, Any]) -> dict[str, float]:
    if set(value) != set(DEFAULT_THRESHOLDS):
        raise ValueError("thresholds_invalid")
    parsed = {key: float(value[key]) for key in DEFAULT_THRESHOLDS}
    if not all(math.isfinite(item) and item > 0 for item in parsed.values()):
        raise ValueError("thresholds_invalid")
    if (
        parsed["fitRmsGreenM"] > parsed["fitRmsMaximumM"]
        or parsed["fitMaximumGreenM"] > parsed["fitMaximumM"]
    ):
        raise ValueError("thresholds_invalid")
    return parsed


def _samples(values: Sequence[Mapping[str, Any]], minimum: int) -> list[tuple[str, np.ndarray]]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)) or len(values) < minimum:
        raise ValueError("at_least_eight_samples_required" if minimum == 8 else "at_least_three_validation_samples_required")
    result = []
    identifiers: set[str] = set()
    for item in values:
        identifier = item.get("id") if isinstance(item, Mapping) else None
        if not isinstance(identifier, str) or not identifier or identifier in identifiers:
            raise ValueError("sample_id_invalid_or_duplicate")
        identifiers.add(identifier)
        result.append((identifier, _rigid(item.get("T_base_flange"), "T_base_flange")))
    return result


def _rotation_angle(first: np.ndarray, second: np.ndarray) -> float:
    cosine = (float(np.trace(first.T @ second)) - 1.0) / 2.0
    return math.acos(max(-1.0, min(1.0, cosine)))


def solve_pivot(
    fit_samples: Sequence[Mapping[str, Any]], thresholds: Mapping[str, Any]
) -> dict[str, Any]:
    """Solve probe and fixed points from canonical base-to-flange transforms."""
    parsed_thresholds = _thresholds(thresholds)
    samples = _samples(fit_samples, 8)
    rotations = [matrix[:3, :3] for _, matrix in samples]
    minimum_pair_angle = min(
        _rotation_angle(rotations[left], rotations[right])
        for left in range(len(rotations))
        for right in range(left + 1, len(rotations))
    )
    if minimum_pair_angle < math.radians(5.0):
        raise ValueError("duplicate_orientation")

    design = np.vstack([np.hstack((matrix[:3, :3], -np.eye(3))) for _, matrix in samples])
    target = np.concatenate([-matrix[:3, 3] for _, matrix in samples])
    solution, _, rank, singular_values = np.linalg.lstsq(design, target, rcond=None)
    if int(rank) < 6 or float(singular_values[-1]) < 1e-6:
        raise ValueError("rank_or_orientation_coverage_insufficient")
    probe = solution[:3]
    fixed = solution[3:]
    residuals = [
        float(np.linalg.norm(matrix[:3, :3] @ probe + matrix[:3, 3] - fixed))
        for _, matrix in samples
    ]
    rms = float(np.sqrt(np.mean(np.square(residuals))))
    maximum = max(residuals)
    worst = int(np.argmax(residuals))
    if rms > parsed_thresholds["fitRmsMaximumM"] or maximum > parsed_thresholds["fitMaximumM"]:
        classification = "red"
    elif rms > parsed_thresholds["fitRmsGreenM"] or maximum > parsed_thresholds["fitMaximumGreenM"]:
        classification = "yellow"
    else:
        classification = "green"
    return {
        "schema": "thirdhand-tcp-pivot-solve-v1",
        "accepted": classification != "red",
        "classification": classification,
        "probe_tip_flange_m": probe.tolist(),
        "fixed_point_base_m": fixed.tolist(),
        "rank": int(rank),
        "singular_values": singular_values.tolist(),
        "minimum_pair_rotation_deg": math.degrees(minimum_pair_angle),
        "sample_ids": [identifier for identifier, _ in samples],
        "sample_residuals_m": residuals,
        "rms_residual_m": rms,
        "maximum_residual_m": maximum,
        "worst_sample_id": samples[worst][0],
        "thresholds": dict(parsed_thresholds),
    }


def validate_pivot(
    candidate: Mapping[str, Any],
    validation_samples: Sequence[Mapping[str, Any]],
    thresholds: Mapping[str, Any],
) -> dict[str, Any]:
    parsed_thresholds = _thresholds(thresholds)
    if candidate.get("schema") != "thirdhand-tcp-pivot-solve-v1":
        raise ValueError("candidate_invalid")
    probe = np.asarray(candidate.get("probe_tip_flange_m"), dtype=np.float64)
    fixed = np.asarray(candidate.get("fixed_point_base_m"), dtype=np.float64)
    if probe.shape != (3,) or fixed.shape != (3,) or not np.isfinite(probe).all() or not np.isfinite(fixed).all():
        raise ValueError("candidate_invalid")
    samples = _samples(validation_samples, 3)
    fit_ids = set(candidate.get("sample_ids", []))
    if fit_ids.intersection(identifier for identifier, _ in samples):
        raise ValueError("validation_sample_reused")
    predictions = [(matrix[:3, :3] @ probe + matrix[:3, 3]) for _, matrix in samples]
    errors = [float(np.linalg.norm(prediction - fixed)) for prediction in predictions]
    maximum = max(errors)
    return {
        "schema": "thirdhand-tcp-pivot-validation-v1",
        "accepted": maximum <= parsed_thresholds["validationMaximumM"],
        "sample_ids": [identifier for identifier, _ in samples],
        "predicted_fixed_points_base_m": [value.tolist() for value in predictions],
        "sample_errors_m": errors,
        "rms_error_m": float(np.sqrt(np.mean(np.square(errors)))),
        "maximum_error_m": maximum,
        "thresholds": dict(parsed_thresholds),
    }


def derive_grasp_tcp(
    T_flange_probe_tip: Any,
    distance_m: float,
    tool_axis_flange: Sequence[float],
    measurement_uncertainty_m: float,
) -> dict[str, Any]:
    transform = _rigid(T_flange_probe_tip, "T_flange_probe_tip")
    distance = float(distance_m)
    uncertainty = float(measurement_uncertainty_m)
    axis = np.asarray(tool_axis_flange, dtype=np.float64)
    if (
        not math.isfinite(distance)
        or distance < 0
        or distance > 1.0
        or not math.isfinite(uncertainty)
        or uncertainty <= 0
        or uncertainty > 0.010
        or axis.shape != (3,)
        or not np.isfinite(axis).all()
        or not math.isclose(float(np.linalg.norm(axis)), 1.0, abs_tol=1e-9)
    ):
        raise ValueError("grasp_tcp_measurement_invalid")
    grasp = transform.copy()
    grasp[:3, 3] = transform[:3, 3] - distance * axis
    return {
        "schema": "thirdhand-grasp-tcp-derived-v1",
        "T_flange_probe_tip": transform.tolist(),
        "T_flange_grasp_tcp": grasp.tolist(),
        "probe_tip_to_grasp_plane_m": distance,
        "measurement_uncertainty_m": uncertainty,
        "tool_axis_flange": axis.tolist(),
    }

