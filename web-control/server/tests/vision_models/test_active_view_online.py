from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from vision.types import InvalidDataError
from vision_models.active_view_online import (
    load_active_view_config,
    load_active_view_config_dict,
)


PROJECT_ROOT = Path(__file__).parents[4]
EVIDENCE_ID = "sha256:" + "b" * 64


def test_checked_in_active_view_config_is_execution_locked_and_empty() -> None:
    config = load_active_view_config(PROJECT_ROOT / "configs/vision/active_view.yaml")

    assert config.dry_run_enabled is True
    assert config.execution_enabled is False
    assert config.table_plane.validated is False
    assert config.observation_poses == ()
    assert config.inner_roi_fraction == pytest.approx(0.60)
    assert config.min_depth_points == 80
    assert config.stable_sample_count == 5
    assert config.max_refinement_steps == 3
    assert config.proposal_ttl_ns == 200_000_000


def test_config_dict_rejects_any_execution_permission() -> None:
    with pytest.raises(InvalidDataError, match="execution"):
        load_active_view_config_dict(
            {
                "schema_version": 1,
                "dry_run_enabled": True,
                "active_view_execution_enabled": True,
            }
        )


def test_config_loader_builds_an_immutable_observation_catalog() -> None:
    raw = _valid_config_dict()
    raw["observation_poses"] = [
        {
            "pose_id": "table_center",
            "joints_deg": [0, 1, 2, 3, 4, 5],
            "t_base_from_flange": np.eye(4).tolist(),
            "coverage_polygon_xy_m": [
                [-0.2, -0.1],
                [0.2, -0.1],
                [0.2, 0.1],
                [-0.2, 0.1],
            ],
            "allowed_start_pose_ids": ["home"],
            "path_validation_id": EVIDENCE_ID,
            "calibration_id": EVIDENCE_ID,
            "joint_tolerance_deg": 0.5,
        }
    ]

    config = load_active_view_config_dict(raw)

    assert len(config.observation_poses) == 1
    assert config.observation_poses[0].pose_id == "table_center"
    assert config.observation_poses[0].joints_deg.flags.writeable is False
    assert config.observation_poses[0].joint_tolerance_deg == 0.5


def test_config_loader_rejects_duplicate_pose_ids_and_long_ttl() -> None:
    raw = _valid_config_dict()
    pose = {
        "pose_id": "duplicate",
        "joints_deg": [0, 1, 2, 3, 4, 5],
        "t_base_from_flange": np.eye(4).tolist(),
        "coverage_polygon_xy_m": [[0, 0], [1, 0], [0, 1]],
        "allowed_start_pose_ids": ["home"],
        "path_validation_id": EVIDENCE_ID,
        "calibration_id": EVIDENCE_ID,
    }
    raw["observation_poses"] = [pose, dict(pose)]
    with pytest.raises(InvalidDataError, match="duplicate"):
        load_active_view_config_dict(raw)

    raw = _valid_config_dict()
    raw["motion_proposals"]["proposal_ttl_ms"] = 1_001
    with pytest.raises(InvalidDataError, match="TTL"):
        load_active_view_config_dict(raw)


def test_config_contract_cannot_be_replaced_with_unsafe_motion_limits() -> None:
    config = load_active_view_config_dict(_valid_config_dict())

    with pytest.raises(InvalidDataError, match="translation"):
        replace(config, max_translation_m=0.021)
    with pytest.raises(InvalidDataError, match="rotation"):
        replace(config, max_rotation_rad=np.deg2rad(5.1))
    with pytest.raises(InvalidDataError, match="refinement"):
        replace(config, max_refinement_steps=4)
    with pytest.raises(InvalidDataError, match="TTL"):
        replace(config, proposal_ttl_ns=1_000_000_001)


def _valid_config_dict() -> dict:
    return {
        "schema_version": 1,
        "dry_run_enabled": True,
        "active_view_execution_enabled": False,
        "table_plane": {
            "normal_base": [0.0, 0.0, 1.0],
            "offset_m": 0.0,
            "position_rmse_m": 0.010,
            "calibration_id": EVIDENCE_ID,
            "validated": False,
        },
        "quality": {
            "inner_roi_fraction": 0.60,
            "coverage_margin_m": 0.010,
            "min_depth_points": 80,
            "min_central_fraction": 0.60,
            "stable_sample_count": 5,
            "max_center_deviation_m": 0.010,
            "max_axis_mad_m": 0.005,
        },
        "motion_proposals": {
            "max_translation_m": 0.020,
            "max_rotation_deg": 5.0,
            "max_refinement_steps": 3,
            "proposal_ttl_ms": 200,
        },
        "observation_poses": [],
    }
