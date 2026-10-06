import json
from pathlib import Path

import numpy as np


FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "tcp-calibration"
    / "reference-pivot.json"
)


def load_fixture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def solve_one_step(samples):
    rows = []
    values = []
    for sample in samples:
        transform = np.asarray(sample["T_base_flange"], dtype=np.float64)
        rows.append(np.hstack((transform[:3, :3], -np.eye(3))))
        values.append(-transform[:3, 3])
    matrix = np.vstack(rows)
    vector = np.concatenate(values)
    solution, _, rank, singular_values = np.linalg.lstsq(matrix, vector, rcond=None)
    return solution[:3], solution[3:], rank, singular_values


def test_reference_fixture_recovers_known_probe_and_pivot():
    fixture = load_fixture()
    probe, pivot, rank, _ = solve_one_step(fixture["fit_samples"])

    assert rank == 6
    assert np.linalg.norm(probe - fixture["known_probe_tip_flange_m"]) < 1e-9
    assert np.linalg.norm(pivot - fixture["known_fixed_point_base_m"]) < 1e-9
    assert np.linalg.norm(probe - fixture["reference_result"]["probe_tip_flange_m"]) < 1e-12
    assert np.linalg.norm(pivot - fixture["reference_result"]["fixed_point_base_m"]) < 1e-12


def test_reference_fixture_has_independent_validation_set():
    fixture = load_fixture()
    fit_ids = {sample["id"] for sample in fixture["fit_samples"]}
    validation_ids = {sample["id"] for sample in fixture["validation_samples"]}

    assert len(fit_ids) == 8
    assert len(validation_ids) == 3
    assert fit_ids.isdisjoint(validation_ids)


def test_noise_cases_are_deterministic():
    fixture = load_fixture()
    expected = {
        "noise-0.5mm": (0.0005, [0.00015236, -0.00051999, 0.00037523], 0.0004136350782),
        "noise-1mm": (0.001, [0.00030472, -0.00103998, 0.00075045], 0.00082726897384),
        "noise-2mm": (0.002, [0.00060943, -0.00207997, 0.0015009], 0.0016545388558),
        "noise-5mm": (0.005, [0.00152359, -0.00519992, 0.00375226], 0.00413634824134),
    }

    assert set(fixture["noise_cases"]) == set(expected)
    for name, (scale, first_vector, expected_rms) in expected.items():
        case = fixture["noise_cases"][name]
        vectors = np.asarray(case["translation_noise_m"], dtype=np.float64)
        rms = float(np.sqrt(np.mean(np.square(vectors))))
        assert case["configured_sigma_m"] == scale
        assert vectors.shape == (8, 3)
        assert np.allclose(vectors[0], first_vector, atol=5e-9, rtol=0)
        assert abs(rms - expected_rms) < 1e-12
