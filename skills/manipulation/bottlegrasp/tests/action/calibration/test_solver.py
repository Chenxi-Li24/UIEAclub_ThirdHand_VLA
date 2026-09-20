import cv2
import json
import numpy as np
import pytest
import subprocess
import sys

from thirdhand_va.action.calibration import HandEyeSolveError, solve_handeye


def transform(rotation_vector, translation) -> np.ndarray:
    result = np.eye(4, dtype=np.float64)
    result[:3, :3] = cv2.Rodrigues(
        np.asarray(rotation_vector, dtype=np.float64)
    )[0]
    result[:3, 3] = np.asarray(translation, dtype=np.float64)
    return result


def synthetic_manifest(*, one_axis: bool = False, validation_count: int = 4):
    truth = transform([0.08, -0.12, 0.05], [0.035, -0.018, 0.072])
    base_target = transform([0.04, 0.03, -0.02], [0.55, 0.02, 0.12])
    samples = []
    for index in range(16):
        if one_axis:
            rotation_vector = [0.0, 0.0, -0.55 + index * 0.075]
        else:
            axis = np.asarray(
                [
                    np.sin(index * 0.73) + 0.2,
                    np.cos(index * 0.51) - 0.1,
                    np.sin(index * 0.37 + 0.4),
                ]
            )
            axis /= np.linalg.norm(axis)
            rotation_vector = axis * (0.18 + 0.035 * index)
        base_tool = transform(
            rotation_vector,
            [
                0.28 + 0.012 * index,
                -0.16 + 0.025 * (index % 5),
                0.24 + 0.014 * (index % 4),
            ],
        )
        camera_target = np.linalg.inv(truth) @ np.linalg.inv(base_tool) @ base_target
        samples.append(
            {
                "sample_id": f"sample-{index:02d}",
                "T_base_tool": base_tool.tolist(),
                "T_camera_target": camera_target.tolist(),
            }
        )
    split = len(samples) - validation_count
    return {
        "schema": "thirdhand-handeye-samples-v1",
        "camera": {
            "camera_serial": "250801DR48FP25002738",
            "registration_id": "xvisio-sdk:250801DR48FP25002738",
            "camera_mount_id": "lumos-ego-std:end-effector:installation-1",
        },
        "tcp_semantics": "configured_tool_tcp",
        "fit_samples": samples[:split],
        "validation_samples": samples[split:],
    }, truth


def test_solver_recovers_known_tool_camera_transform() -> None:
    manifest, truth = synthetic_manifest()

    report = solve_handeye(manifest)

    np.testing.assert_allclose(report.t_tool_camera[:3, 3], truth[:3, 3], atol=0.002)
    np.testing.assert_allclose(report.t_tool_camera[:3, :3], truth[:3, :3], atol=0.01)
    assert report.fit_sample_count == 12
    assert report.validation_sample_count == 4
    assert report.validation_translation_rmse_m < 0.003
    assert report.validation_rotation_rmse_deg < 0.5
    assert report.numerically_validated is True


def test_solver_requires_rotation_axis_diversity() -> None:
    manifest, _ = synthetic_manifest(one_axis=True)

    with pytest.raises(HandEyeSolveError, match="rotation_axis_diversity"):
        solve_handeye(manifest)


def test_solver_requires_independent_held_out_validation() -> None:
    manifest, _ = synthetic_manifest(validation_count=2)

    with pytest.raises(HandEyeSolveError, match="validation_samples"):
        solve_handeye(manifest)


def test_calibration_payload_never_self_activates_hardware() -> None:
    manifest, _ = synthetic_manifest()

    payload = solve_handeye(manifest).to_calibration_payload()

    assert payload["T_tool_camera"]["matrix_4x4"]
    assert payload["tcp_semantics"] == "configured_tool_tcp"
    assert payload["camera"]["camera_mount_id"].startswith("lumos-ego-std:")
    assert payload["activated_camera_mount_id"] is None
    assert payload["camera_mount_id_activation"] is False
    assert payload["physical_validation"]["status"] == "pending"
    assert payload["approved_for_bottle_grasp"] is False
    assert payload["sample_manifest_id"].startswith("sha256:")


def test_cli_writes_a_debuggable_locked_calibration(tmp_path) -> None:
    manifest, _ = synthetic_manifest()
    source = tmp_path / "samples.json"
    output = tmp_path / "calibration.json"
    source.write_text(json.dumps(manifest), encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/action/calibrate_handeye.py",
            str(source),
            "--output",
            str(output),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    summary = json.loads(completed.stdout)
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert summary["type"] == "handeye_solve_report"
    assert summary["robot_control_enabled"] is False
    assert payload["approved_for_bottle_grasp"] is False
