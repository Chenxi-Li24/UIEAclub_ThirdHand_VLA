from pathlib import Path
from dataclasses import asdict

import pytest

from thirdhand_va.common.config import VisionConfig


def test_loads_checked_yaml_configuration(tmp_path: Path) -> None:
    path = tmp_path / "vision.yaml"
    path.write_text(
        """
camera_serial: "250801DR48FP25002738"
min_depth_m: 0.15
max_depth_m: 1.20
min_mask_pixels: 800
min_depth_points: 300
min_depth_ratio: 0.55
stability_window: 5
required_stable_hits: 4
max_pose_spread_m: 0.012
min_grasp_width_m: 0.012
max_grasp_width_m: 0.072
camera_registration_id: "xvisio-sdk:250801DR48FP25002738"
camera_mount_id: "lumos-ego-std:end-effector:installation-1"
max_visible_tracks: 5
track_confirmation_hits: 3
track_lost_timeout_ms: 2000
redetect_interval_frames: 15
mask_erosion_px: 2
upright_axis_max_angle_deg: 15.0
table_plane_distance_m: 0.008
min_grasp_clearance_m: 0.010
min_neighbor_clearance_m: 0.012
approach_corridor_radius_m: 0.035
approach_corridor_length_m: 0.10
grasp_band_fractions: [0.35, 0.50, 0.65]
grounding_model: "IDEA-Research/grounding-dino-tiny"
sam_model: "facebook/sam2-hiera-small"
grounding_revision: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
grounding_weights_sha256: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
sam_revision: "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
sam_weights_sha256: "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
hf_home: "/models/huggingface"
grounding_box_threshold: 0.30
grounding_text_threshold: 0.25
min_bottle_score: 0.38
min_coke_score: 0.38
min_competitor_margin: 0.08
competitor_iou: 0.45
min_reference_similarity: 0.85
min_bottle_aspect_ratio: 2.20
max_bottle_aspect_ratio: 5.50
max_neck_body_ratio: 0.72
reference_descriptor_bins: 8
min_track_mask_iou: 0.50
min_horizontal_gap_px: 12.0
max_track_center_distance_px: 120.0
track_ambiguity_margin: 0.05
max_track_point_distance_m: 0.08
max_frame_age_ms: 300
""".strip(),
        encoding="utf-8",
    )

    config = VisionConfig.from_yaml(path)

    assert config.camera_serial == "250801DR48FP25002738"
    assert config.stability_window == 5
    assert config.required_stable_hits == 4
    assert config.hf_home == Path("/models/huggingface")
    assert config.max_grasp_width_m == 0.072
    assert config.grasp_band_fractions == (0.35, 0.5, 0.65)


def test_rejects_configured_grasp_width_above_safe_72mm() -> None:
    raw = asdict(VisionConfig.from_yaml(Path("configs/vision.yaml")))
    raw.pop("content_id")
    raw["max_grasp_width_m"] = 0.073

    with pytest.raises(ValueError, match="72 mm"):
        VisionConfig.from_mapping(raw)


def test_deployed_lumos_depth_gate_admits_sparse_dark_opaque_bottle_depth() -> None:
    """Keep the live-camera threshold tied to the 2026-08-23 30-frame check.

    The dark opaque bottle supplied 441--500 robust in-mask depth points while
    the valid-pixel ratio fell as low as 5.8%.  Absolute support and the 4-of-5
    pose-stability gate remain independent fail-closed checks.
    """
    config = VisionConfig.from_yaml(Path("configs/vision.yaml"))

    assert config.min_depth_points >= 250
    assert config.min_depth_ratio <= 0.055
    assert config.required_stable_hits >= 4
    assert config.max_pose_spread_m <= 0.012


def test_rejects_unknown_configuration_key(tmp_path: Path) -> None:
    path = tmp_path / "vision.yaml"
    path.write_text(
        """
camera_serial: camera
min_depth_m: 0.15
max_depth_m: 1.20
min_mask_pixels: 800
min_depth_points: 300
min_depth_ratio: 0.55
stability_window: 5
required_stable_hits: 4
max_pose_spread_m: 0.012
grounding_model: grounding
sam_model: sam
hf_home: null
grounding_box_threshold: 0.30
grounding_text_threshold: 0.25
min_coke_score: 0.38
min_competitor_margin: 0.08
competitor_iou: 0.45
min_reference_similarity: 0.85
min_bottle_aspect_ratio: 2.20
max_bottle_aspect_ratio: 5.50
max_neck_body_ratio: 0.72
reference_descriptor_bins: 8
min_track_mask_iou: 0.50
max_frame_age_ms: 300
surprise: forbidden
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Unknown configuration keys.*surprise"):
        VisionConfig.from_yaml(path)
