import hashlib
import json

import numpy as np
import pytest

from thirdhand_va.action.calibration.import_handeye import (
    HandEyeImportError,
    import_handeye_artifact,
)


def _source_payload() -> dict:
    return {
        "schema_version": 1,
        "artifact_type": "eye_in_hand_calibration_candidate",
        "calibration_type": "eye_in_hand",
        "T_flange_camera": {"matrix_4x4": np.eye(4).tolist()},
        "camera": {
            "camera_serial": "250801DR48FP25002738",
        },
        "camera_mount_id": "source-mount-id",
        "selected_method": "HORAUD",
        "numerically_validated": True,
        "validation": {
            "held_out": {
                "translation_rmse_m": 0.0049,
                "rotation_rmse_deg": 0.9,
                "T_base_board_per_sample": {"large_debug_payload": []},
            },
        },
        "physical_validation": {
            "status": "pending",
            "measured_error_m": None,
            "required_3d_point_or_grasp_error_m_max": 0.01,
        },
    }


def test_importer_creates_explicit_fail_closed_v3_artifact(tmp_path) -> None:
    source = tmp_path / "source.json"
    source.write_text(json.dumps(_source_payload(), sort_keys=True))
    expected_sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
    output = tmp_path / "imported.json"

    artifact = import_handeye_artifact(
        source,
        output,
        expected_sha256=expected_sha256,
    )

    assert artifact["schema"] == "thirdhand-handeye-calibration-v3"
    assert artifact["robot_state_semantics"] == "T_base_flange"
    assert artifact["extrinsic_semantics"] == "T_flange_camera"
    assert artifact["T_flange_camera"]["matrix_4x4"] == np.eye(4).tolist()
    assert artifact["source"]["sha256"] == f"sha256:{expected_sha256}"
    assert artifact["source"]["filename"] == "source.json"
    assert "path" not in artifact["source"]
    assert artifact["numerical_validation"] == {
        "held_out": {"translation_rmse_m": 0.0049, "rotation_rmse_deg": 0.9}
    }
    assert artifact["camera"]["registration_id"] == "xvisio-sdk:250801DR48FP25002738"
    assert artifact["camera_mount_id_activation"] is False
    assert artifact["activated_camera_mount_id"] is None
    assert artifact["approved_for_bottle_grasp"] is False
    assert json.loads(output.read_text()) == artifact


def test_importer_rejects_unexpected_source_bytes(tmp_path) -> None:
    source = tmp_path / "source.json"
    source.write_text(json.dumps(_source_payload()))

    with pytest.raises(HandEyeImportError, match="SHA-256"):
        import_handeye_artifact(
            source,
            tmp_path / "imported.json",
            expected_sha256="0" * 64,
        )
