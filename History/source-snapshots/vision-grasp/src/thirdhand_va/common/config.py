"""Strict configuration loading shared by the visual module entry points."""

from __future__ import annotations

from dataclasses import dataclass, field, fields
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import yaml


@dataclass(frozen=True, slots=True)
class VisionConfig:
    content_id: str = field(init=False, repr=False, default="")
    camera_serial: str
    camera_registration_id: str
    camera_mount_id: str
    min_depth_m: float
    max_depth_m: float
    min_mask_pixels: int
    min_depth_points: int
    min_depth_ratio: float
    stability_window: int
    required_stable_hits: int
    max_pose_spread_m: float
    min_grasp_width_m: float
    max_grasp_width_m: float
    max_visible_tracks: int
    track_confirmation_hits: int
    track_lost_timeout_ms: int
    redetect_interval_frames: int
    mask_erosion_px: int
    upright_axis_max_angle_deg: float
    table_plane_distance_m: float
    min_grasp_clearance_m: float
    min_neighbor_clearance_m: float
    approach_corridor_radius_m: float
    approach_corridor_length_m: float
    grasp_band_fractions: tuple[float, ...]
    grounding_model: str
    sam_model: str
    grounding_revision: str
    grounding_weights_sha256: str
    sam_revision: str
    sam_weights_sha256: str
    hf_home: Path | None
    grounding_box_threshold: float
    grounding_text_threshold: float
    min_bottle_score: float
    min_coke_score: float
    min_competitor_margin: float
    competitor_iou: float
    min_reference_similarity: float
    min_bottle_aspect_ratio: float
    max_bottle_aspect_ratio: float
    max_neck_body_ratio: float
    reference_descriptor_bins: int
    min_track_mask_iou: float
    min_horizontal_gap_px: float
    max_track_center_distance_px: float
    track_ambiguity_margin: float
    max_track_point_distance_m: float
    max_frame_age_ms: int

    @classmethod
    def from_yaml(cls, path: str | Path) -> "VisionConfig":
        config_path = Path(path)
        raw_bytes = config_path.read_bytes()
        raw = yaml.safe_load(raw_bytes.decode("utf-8"))
        if not isinstance(raw, Mapping):
            raise ValueError("vision configuration must be a YAML mapping")
        config = cls.from_mapping(raw)
        object.__setattr__(
            config, "content_id", "sha256:" + hashlib.sha256(raw_bytes).hexdigest()
        )
        return config

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "VisionConfig":
        expected = {item.name for item in fields(cls) if item.init}
        unknown = sorted(set(raw) - expected)
        missing = sorted(expected - set(raw))
        if unknown:
            raise ValueError(f"Unknown configuration keys: {', '.join(unknown)}")
        if missing:
            raise ValueError(f"Missing configuration keys: {', '.join(missing)}")
        values = dict(raw)
        values["hf_home"] = (
            None if values["hf_home"] is None else Path(values["hf_home"])
        )
        try:
            values["grasp_band_fractions"] = tuple(
                float(value) for value in values["grasp_band_fractions"]
            )
        except (TypeError, ValueError) as error:
            raise ValueError("grasp_band_fractions must be a numeric sequence") from error
        config = cls(**values)
        canonical = json.dumps(
            raw, sort_keys=True, separators=(",", ":"), default=str
        ).encode()
        object.__setattr__(
            config, "content_id", "sha256:" + hashlib.sha256(canonical).hexdigest()
        )
        config._validate()
        return config

    def _validate(self) -> None:
        if not self.camera_serial:
            raise ValueError("camera_serial must not be empty")
        if not self.camera_registration_id:
            raise ValueError("camera_registration_id must not be empty")
        if not self.camera_mount_id:
            raise ValueError("camera_mount_id must not be empty")
        if not 0 < self.min_depth_m < self.max_depth_m:
            raise ValueError("depth limits must satisfy 0 < min < max")
        if self.min_mask_pixels <= 0 or self.min_depth_points <= 0:
            raise ValueError("pixel and point thresholds must be positive")
        if not 0.0 < self.min_depth_ratio <= 1.0:
            raise ValueError("min_depth_ratio must be in (0, 1]")
        if not 0 < self.required_stable_hits <= self.stability_window:
            raise ValueError("stable hits must be within the stability window")
        if self.max_pose_spread_m <= 0:
            raise ValueError("max_pose_spread_m must be positive")
        if not 0 < self.min_grasp_width_m < self.max_grasp_width_m:
            raise ValueError("grasp width limits must satisfy 0 < min < max")
        if self.max_grasp_width_m > 0.072:
            raise ValueError("max_grasp_width_m must not exceed the 72 mm safety limit")
        if not 1 <= self.max_visible_tracks <= 5:
            raise ValueError("max_visible_tracks must be in [1, 5]")
        if not 1 <= self.track_confirmation_hits <= self.stability_window:
            raise ValueError("track_confirmation_hits must fit the stability window")
        if self.track_lost_timeout_ms <= 0 or self.redetect_interval_frames <= 0:
            raise ValueError("tracking timeouts and intervals must be positive")
        if self.mask_erosion_px < 0:
            raise ValueError("mask_erosion_px must be non-negative")
        if not 0 < self.upright_axis_max_angle_deg < 90:
            raise ValueError("upright_axis_max_angle_deg must be in (0, 90)")
        if self.table_plane_distance_m <= 0 or self.min_grasp_clearance_m < 0:
            raise ValueError("table distance must be positive and clearance non-negative")
        if (
            self.min_neighbor_clearance_m < 0
            or self.approach_corridor_radius_m <= 0
            or self.approach_corridor_length_m <= 0
        ):
            raise ValueError("neighbor and approach corridor limits must be positive")
        if (
            not self.grasp_band_fractions
            or tuple(sorted(set(self.grasp_band_fractions)))
            != self.grasp_band_fractions
            or any(not 0.0 < value < 1.0 for value in self.grasp_band_fractions)
        ):
            raise ValueError(
                "grasp_band_fractions must be unique, increasing, and within (0, 1)"
            )
        if not self.grounding_model or not self.sam_model:
            raise ValueError("model identifiers must not be empty")
        import re
        if not re.fullmatch(r"[0-9a-f]{40}", self.grounding_revision) or not re.fullmatch(
            r"[0-9a-f]{40}", self.sam_revision
        ):
            raise ValueError("model revisions must be exact 40-character Git commits")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", self.grounding_weights_sha256) or not re.fullmatch(
            r"sha256:[0-9a-f]{64}", self.sam_weights_sha256
        ):
            raise ValueError("model weight hashes must be SHA-256 IDs")
        probabilities = {
            "grounding_box_threshold": self.grounding_box_threshold,
            "grounding_text_threshold": self.grounding_text_threshold,
            "min_bottle_score": self.min_bottle_score,
            "min_coke_score": self.min_coke_score,
            "min_competitor_margin": self.min_competitor_margin,
            "competitor_iou": self.competitor_iou,
            "min_reference_similarity": self.min_reference_similarity,
            "max_neck_body_ratio": self.max_neck_body_ratio,
            "min_track_mask_iou": self.min_track_mask_iou,
            "track_ambiguity_margin": self.track_ambiguity_margin,
        }
        if any(not 0.0 <= value <= 1.0 for value in probabilities.values()):
            raise ValueError("perception probabilities and ratios must be in [0, 1]")
        if not 0 < self.min_bottle_aspect_ratio < self.max_bottle_aspect_ratio:
            raise ValueError("bottle aspect limits must satisfy 0 < min < max")
        if self.reference_descriptor_bins < 2:
            raise ValueError("reference_descriptor_bins must be at least 2")
        if self.max_frame_age_ms <= 0:
            raise ValueError("max_frame_age_ms must be positive")
        if self.min_horizontal_gap_px < 0:
            raise ValueError("min_horizontal_gap_px must be non-negative")
        if self.max_track_center_distance_px <= 0 or self.max_track_point_distance_m <= 0:
            raise ValueError("track distance limits must be positive")


__all__ = ["VisionConfig"]
