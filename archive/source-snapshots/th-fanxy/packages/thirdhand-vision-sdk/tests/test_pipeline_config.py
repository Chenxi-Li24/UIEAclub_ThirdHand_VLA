from __future__ import annotations

import pytest

from thirdhand_vision.core.errors import InputValidationError
from thirdhand_vision.pipeline.config import VisionConfig


def valid_mapping() -> dict:
    return {
        "depth": {"min_m": 0.1, "max_m": 2.0},
        "pose": {
            "min_points": 8,
            "erosion_px": 1,
            "mad_scale": 3.5,
            "noise_floor_m": 0.002,
        },
        "identity": {
            "max_cosine_distance": 0.4,
            "ambiguity_margin": 0.03,
            "appearance_weight": 0.8,
            "position_weight": 0.2,
            "max_position_distance_m": 0.2,
            "position_gate_max_age_ns": 500_000_000,
            "occluded_after_ns": 300_000_000,
            "inactive_after_ns": 1_500_000_000,
            "min_confirmed_hits": 2,
            "min_memory_confidence": 0.8,
            "min_memory_visibility": 0.5,
            "work_bank_size": 8,
            "stable_bank_size": 12,
            "max_identities": 64,
            "reacquire_confirmed_hits": 2,
            "max_actionable_position_std_m": 0.025,
            "max_actionable_pose_age_ns": 200_000_000,
            "min_actionable_pose_hits": 2,
        },
        "extensions": {"mode": "isolate"},
    }


def test_config_builds_typed_nested_settings() -> None:
    config = VisionConfig.from_mapping(valid_mapping())
    assert config.min_depth_m == pytest.approx(0.1)
    assert config.pose.min_points == 8
    assert config.identity.appearance_weight == pytest.approx(0.8)
    assert config.extension_mode == "isolate"


def test_config_rejects_unknown_keys() -> None:
    raw = valid_mapping()
    raw["surprise"] = True
    with pytest.raises(InputValidationError, match="unknown configuration keys"):
        VisionConfig.from_mapping(raw)

