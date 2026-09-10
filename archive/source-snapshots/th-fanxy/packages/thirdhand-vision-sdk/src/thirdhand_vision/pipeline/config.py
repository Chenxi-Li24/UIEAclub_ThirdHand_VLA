"""Strict machine-independent configuration for the offline pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import yaml

from thirdhand_vision.core.errors import InputValidationError
from thirdhand_vision.geometry.pose import InstancePoseConfig
from thirdhand_vision.identity.memory import IdentityConfig


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise InputValidationError(f"{name} must be a mapping")
    return dict(value)


def _exact_keys(value: Mapping[str, Any], expected: set[str], name: str) -> None:
    unknown = set(value) - expected
    missing = expected - set(value)
    if unknown:
        raise InputValidationError(f"unknown configuration keys in {name}: {sorted(unknown)}")
    if missing:
        raise InputValidationError(f"missing configuration keys in {name}: {sorted(missing)}")


@dataclass(frozen=True)
class VisionConfig:
    min_depth_m: float
    max_depth_m: float
    pose: InstancePoseConfig
    identity: IdentityConfig
    extension_mode: str = "strict"

    def __post_init__(self) -> None:
        lower, upper = float(self.min_depth_m), float(self.max_depth_m)
        if not np.isfinite([lower, upper]).all() or lower <= 0.0 or upper <= lower:
            raise InputValidationError("depth range must satisfy 0 < min < max")
        if not isinstance(self.pose, InstancePoseConfig):
            raise InputValidationError("pose config is invalid")
        if not isinstance(self.identity, IdentityConfig):
            raise InputValidationError("identity config is invalid")
        if self.extension_mode not in {"strict", "isolate"}:
            raise InputValidationError("extension mode must be strict or isolate")
        object.__setattr__(self, "min_depth_m", lower)
        object.__setattr__(self, "max_depth_m", upper)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "VisionConfig":
        root = _mapping(value, "configuration")
        _exact_keys(root, {"depth", "pose", "identity", "extensions"}, "configuration")
        depth = _mapping(root["depth"], "depth")
        pose = _mapping(root["pose"], "pose")
        identity = _mapping(root["identity"], "identity")
        extensions = _mapping(root["extensions"], "extensions")
        _exact_keys(depth, {"min_m", "max_m"}, "depth")
        _exact_keys(
            pose,
            {"min_points", "erosion_px", "mad_scale", "noise_floor_m"},
            "pose",
        )
        identity_keys = {
            "max_cosine_distance",
            "ambiguity_margin",
            "appearance_weight",
            "position_weight",
            "max_position_distance_m",
            "position_gate_max_age_ns",
            "occluded_after_ns",
            "inactive_after_ns",
            "min_confirmed_hits",
            "min_memory_confidence",
            "min_memory_visibility",
            "work_bank_size",
            "stable_bank_size",
            "max_identities",
            "reacquire_confirmed_hits",
            "max_actionable_position_std_m",
            "max_actionable_pose_age_ns",
            "min_actionable_pose_hits",
        }
        _exact_keys(identity, identity_keys, "identity")
        _exact_keys(extensions, {"mode"}, "extensions")
        try:
            return cls(
                min_depth_m=depth["min_m"],
                max_depth_m=depth["max_m"],
                pose=InstancePoseConfig(**pose),
                identity=IdentityConfig(**identity),
                extension_mode=extensions["mode"],
            )
        except TypeError as error:
            raise InputValidationError("configuration values have invalid types") from error


def load_vision_config(path: Path | str) -> VisionConfig:
    source = Path(path)
    try:
        raw = yaml.safe_load(source.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise InputValidationError("cannot read vision configuration") from error
    return VisionConfig.from_mapping(_mapping(raw, "configuration"))

