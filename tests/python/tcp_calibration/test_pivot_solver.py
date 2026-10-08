import copy
import json
from pathlib import Path

import numpy as np
import pytest

from tools.tcp_calibration.pivot_solver import (
    DEFAULT_THRESHOLDS,
    derive_grasp_tcp,
    solve_pivot,
    validate_pivot,
)


FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "tcp-calibration"
    / "reference-pivot.json"
)


def fixture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def noisy_samples(case_name):
    data = fixture()
    samples = copy.deepcopy(data["fit_samples"])
    noise = data["noise_cases"][case_name]["translation_noise_m"]
    for sample, vector in zip(samples, noise, strict=True):
        for index in range(3):
            sample["T_base_flange"][index][3] += vector[index]
    return samples


def test_exact_fit_recovers_probe_pivot_and_diagnostics():
    data = fixture()
    result = solve_pivot(data["fit_samples"], DEFAULT_THRESHOLDS)

    assert result["schema"] == "thirdhand-tcp-pivot-solve-v1"
    assert result["accepted"] is True
    assert result["rank"] == 6
    assert result["classification"] == "green"
    assert np.allclose(result["probe_tip_flange_m"], data["known_probe_tip_flange_m"], atol=1e-9)
    assert np.allclose(result["fixed_point_base_m"], data["known_fixed_point_base_m"], atol=1e-9)
    assert result["rms_residual_m"] < 1e-9
    assert result["maximum_residual_m"] < 1e-9
    assert result["worst_sample_id"] in {sample["id"] for sample in data["fit_samples"]}
    assert len(result["sample_residuals_m"]) == 8
    assert len(result["singular_values"]) == 6
    assert result["thresholds"] == DEFAULT_THRESHOLDS


@pytest.mark.parametrize(
    ("case_name", "maximum_probe_error_m"),
    [
        ("noise-0.5mm", 0.003),
        ("noise-1mm", 0.006),
        ("noise-2mm", 0.012),
        ("noise-5mm", 0.030),
    ],
)
def test_seeded_noise_results_are_finite(case_name, maximum_probe_error_m):
    data = fixture()
    result = solve_pivot(noisy_samples(case_name), DEFAULT_THRESHOLDS)

    error = np.linalg.norm(
        np.asarray(result["probe_tip_flange_m"]) - data["known_probe_tip_flange_m"]
    )
    assert np.isfinite(result["singular_values"]).all()
    assert error < maximum_probe_error_m


def test_rejects_fewer_than_eight_samples():
    with pytest.raises(ValueError, match="at_least_eight_samples_required"):
        solve_pivot(fixture()["fit_samples"][:7], DEFAULT_THRESHOLDS)


def test_rejects_duplicate_orientations():
    samples = copy.deepcopy(fixture()["fit_samples"])
    samples[7]["T_base_flange"] = copy.deepcopy(samples[0]["T_base_flange"])
    with pytest.raises(ValueError, match="duplicate_orientation"):
        solve_pivot(samples, DEFAULT_THRESHOLDS)


def test_rejects_single_axis_rank_deficiency():
    probe = np.asarray(fixture()["known_probe_tip_flange_m"])
    pivot = np.asarray(fixture()["known_fixed_point_base_m"])
    samples = []
    for index, angle in enumerate(np.linspace(0.0, 1.4, 8)):
        c, s = np.cos(angle), np.sin(angle)
        rotation = np.asarray([[1, 0, 0], [0, c, -s], [0, s, c]])
        transform = np.eye(4)
        transform[:3, :3] = rotation
        transform[:3, 3] = pivot - rotation @ probe
        samples.append({"id": f"single-axis-{index}", "T_base_flange": transform.tolist()})

    with pytest.raises(ValueError, match="rank_or_orientation_coverage_insufficient"):
        solve_pivot(samples, DEFAULT_THRESHOLDS)


def test_validation_is_disjoint_and_does_not_refit_candidate():
    data = fixture()
    candidate = solve_pivot(data["fit_samples"], DEFAULT_THRESHOLDS)
    original_probe = list(candidate["probe_tip_flange_m"])
    validation = validate_pivot(candidate, data["validation_samples"], DEFAULT_THRESHOLDS)

    assert validation["schema"] == "thirdhand-tcp-pivot-validation-v1"
    assert validation["accepted"] is True
    assert validation["maximum_error_m"] < 1e-9
    assert candidate["probe_tip_flange_m"] == original_probe
    assert set(validation["sample_ids"]).isdisjoint(candidate["sample_ids"])


def test_validation_rejects_fit_sample_reuse_and_large_error():
    data = fixture()
    candidate = solve_pivot(data["fit_samples"], DEFAULT_THRESHOLDS)
    with pytest.raises(ValueError, match="validation_sample_reused"):
        validate_pivot(candidate, data["fit_samples"][:3], DEFAULT_THRESHOLDS)

    validation = copy.deepcopy(data["validation_samples"])
    validation[0]["T_base_flange"][0][3] += 0.006
    report = validate_pivot(candidate, validation, DEFAULT_THRESHOLDS)
    assert report["accepted"] is False
    assert report["maximum_error_m"] > 0.005


def test_grasp_tcp_applies_measured_distance_once():
    transform = np.eye(4)
    transform[:3, 3] = [0.183, 0.012, -0.006]
    result = derive_grasp_tcp(transform.tolist(), 0.020, [1.0, 0.0, 0.0], 0.001)

    assert result["probe_tip_to_grasp_plane_m"] == 0.020
    assert result["measurement_uncertainty_m"] == 0.001
    assert result["tool_axis_flange"] == [1.0, 0.0, 0.0]
    assert np.allclose(result["T_flange_grasp_tcp"][0][3], 0.163)


@pytest.mark.parametrize(
    ("distance,axis,uncertainty"),
    [(-0.001, [1, 0, 0], 0.001), (0.02, [2, 0, 0], 0.001), (0.02, [1, 0, 0], 0.0)],
)
def test_grasp_tcp_rejects_invalid_measurement(distance, axis, uncertainty):
    with pytest.raises(ValueError):
        derive_grasp_tcp(np.eye(4).tolist(), distance, axis, uncertainty)
