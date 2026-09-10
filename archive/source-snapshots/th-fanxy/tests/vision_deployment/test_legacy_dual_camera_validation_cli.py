from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from vision_models.calibration_targets import CharucoSpec
from vision_models.legacy_dual_camera_validation import LegacyCandidatePairResult


def _load_script_namespace() -> dict[str, object]:
    script_path = Path(__file__).parents[2] / "scripts/vision/validate_legacy_dual_camera.py"
    namespace: dict[str, object] = {
        "__name__": "validate_legacy_du_camera_test",
        "__file__": str(script_path),
    }
    exec(compile(script_path.read_text(encoding="utf-8"), script_path, "exec"), namespace)
    return namespace


def _result(*, x_m: float, passes: bool = True) -> LegacyCandidatePairResult:
    board_pose = np.eye(4)
    board_pose[:3, 3] = [x_m, 0.0, 0.65]
    p95 = 1.2 if passes else 12.0
    return LegacyCandidatePairResult(
        common_points=32,
        d435_reprojection_rmse_px=0.4,
        lumos_reprojection_median_px=0.8,
        lumos_reprojection_p95_px=p95,
        passes_pixel_gate=passes,
        lumos_errors_px=np.linspace(0.2, p95, 32),
        t_d435_from_board=board_pose,
    )


def test_validation_cli_appends_content_addressed_non_executable_evidence(
    tmp_path: Path,
) -> None:
    script_path = Path(__file__).parents[2] / "scripts/vision/validate_legacy_dual_camera.py"
    namespace = _load_script_namespace()
    target = CharucoSpec(9, 12, 0.015, 0.01125, "DICT_5X5_100")

    for index in range(10):
        board_pose = np.eye(4)
        board_pose[:3, 3] = [-0.09 + index * 0.02, 0.0, 0.65]
        result = LegacyCandidatePairResult(
            common_points=32,
            d435_reprojection_rmse_px=0.4,
            lumos_reprojection_median_px=0.8,
            lumos_reprojection_p95_px=1.2,
            passes_pixel_gate=True,
            lumos_errors_px=np.linspace(0.2, 1.2, 32),
            t_d435_from_board=board_pose,
        )
        output = namespace["append_observation"](
            tmp_path,
            sample_id=f"pose-{index + 1:02d}",
            candidate_id="sha256:" + "a" * 64,
            lumos_jpeg=b"lumos" + bytes([index]),
            d435_jpeg=b"d435" + bytes([index]),
            result=result,
            target=target,
        )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["content_id"].startswith("sha256:")
    assert len(payload["observations"]) == 10
    assert payload["summary"]["distinct_poses"] == 10
    assert payload["summary"]["relative_extrinsic_validated"] is True
    assert payload["summary"]["executable"] is False
    assert payload["motion_or_robot_access"] is False
    assert payload["target"] == {
        "family": "charuco",
        "rows": 9,
        "columns": 12,
        "square_size_m": 0.015,
        "marker_size_m": 0.01125,
        "dictionary": "DICT_5X5_100",
    }
    source = script_path.read_text(encoding="utf-8").lower()
    for forbidden in ("startouch", "pyrealsense2", "move_joint", "move_l"):
        assert forbidden not in source


def test_repository_candidate_config_is_seed_only_and_matches_audited_id() -> None:
    root = Path(__file__).parents[2]
    config = json.loads(
        (root / "configs/vision/calibration/legacy_dual_camera_candidate.json").read_text(
            encoding="utf-8"
        )
    )

    assert config["candidate_id"] == (
        "sha256:f94d890aab743141c52ca639cd7e8267aaa798da84b109ce09ac2a48e731b3f5"
    )
    assert config["status"] == "candidate_only"
    assert config["executable"] is False
    assert config["seed_hypothesis"] == "d435_extra_inversion_corrected"
    assert config["d435"]["serial"] == "349622074226"
    assert config["lumos"]["model"] == "eucm"


def test_required_quality_and_pose_gates_reject_before_writing(tmp_path: Path) -> None:
    namespace = _load_script_namespace()
    append_observation = namespace["append_observation"]
    target = CharucoSpec(9, 12, 0.015, 0.01125, "DICT_5X5_100")
    common = {
        "output": tmp_path,
        "candidate_id": "sha256:" + "a" * 64,
        "lumos_jpeg": b"lumos",
        "d435_jpeg": b"d435",
        "target": target,
        "require_pass": True,
        "require_distinct": True,
    }

    manifest_path = append_observation(
        sample_id="pose-01",
        result=_result(x_m=0.0),
        **common,
    )
    original = manifest_path.read_bytes()

    with pytest.raises(Exception, match="pose is not distinct"):
        append_observation(
            sample_id="pose-02",
            result=_result(x_m=0.014),
            **common,
        )
    assert manifest_path.read_bytes() == original
    assert not (tmp_path / "images/lumos/pose-02.jpg").exists()

    with pytest.raises(Exception, match="pixel gate"):
        append_observation(
            sample_id="pose-02",
            result=_result(x_m=0.020, passes=False),
            **common,
        )
    assert manifest_path.read_bytes() == original
    assert not (tmp_path / "images/d435/pose-02.jpg").exists()


def test_status_json_is_bounded_non_executable_and_camera_free(tmp_path: Path) -> None:
    root = Path(__file__).parents[2]
    script_path = root / "scripts/vision/validate_legacy_dual_camera.py"
    completed = subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--output",
            str(tmp_path),
            "--status",
            "--json",
        ],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr
    report = json.loads(completed.stdout)
    assert report == {
        "schema_version": 1,
        "ok": True,
        "action": "status",
        "sample": None,
        "summary": {
            "samples": 0,
            "required_samples": 10,
            "passing_pairs": 0,
            "distinct_poses": 0,
            "relative_extrinsic_validated": False,
            "remaining_blockers": [
                "pose_diversity_insufficient",
                "relative_extrinsic_validation_failed",
                "handeye_validation_missing",
                "table_validation_missing",
            ],
        },
        "safety": {
            "motion_or_robot_access": False,
            "executable": False,
        },
    }
    assert str(tmp_path) not in completed.stdout


@pytest.mark.parametrize(
    ("message", "code"),
    [
        ("board pose is not distinct from existing evidence", "pose_not_distinct"),
        ("ChArUco requires at least six chessboard corners", "target_not_visible"),
        ("sample failed the pixel gate", "pixel_gate_failed"),
        ("both cameras must share at least four target points", "insufficient_common_points"),
        ("D435 camera request failed", "camera_unavailable"),
    ],
)
def test_capture_errors_have_stable_public_codes(message: str, code: str) -> None:
    namespace = _load_script_namespace()

    assert namespace["classify_capture_error"](ValueError(message)) == code
