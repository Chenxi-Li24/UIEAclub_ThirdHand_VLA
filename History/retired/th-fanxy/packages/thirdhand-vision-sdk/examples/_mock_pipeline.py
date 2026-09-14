"""Small deterministic adapters used by the hardware-free examples."""

from __future__ import annotations

import numpy as np

from thirdhand_vision import FrameBundle, FrameStamp, InstanceDetection
from thirdhand_vision.geometry import InstancePoseConfig
from thirdhand_vision.identity import IdentityConfig, PersistentIdentityMemory
from thirdhand_vision.pipeline import VisionConfig, VisionPipeline


class MockBottleSegmenter:
    def predict(self, image_rgb: np.ndarray):
        height, width = image_rgb.shape[:2]
        mask = np.zeros((height, width), dtype=bool)
        mask[height // 4 : 3 * height // 4, width // 4 : 3 * width // 4] = True
        return (
            InstanceDetection(
                detection_id=0,
                label="bottle",
                score=0.95,
                bbox_xyxy=np.array(
                    [width / 4, height / 4, 3 * width / 4, 3 * height / 4]
                ),
                mask=mask,
                image_shape=(height, width),
            ),
        )


class MockFeatureEncoder:
    model_id = "mock-feature-encoder"

    def encode(self, image_rgb: np.ndarray, masks):
        return tuple(np.array([0.8, 0.6]) for _ in masks)


def default_config(extension_mode: str = "strict") -> VisionConfig:
    identity = IdentityConfig(
        max_cosine_distance=0.4,
        ambiguity_margin=0.03,
        appearance_weight=0.8,
        position_weight=0.2,
        max_position_distance_m=0.2,
        position_gate_max_age_ns=500_000_000,
        occluded_after_ns=300_000_000,
        inactive_after_ns=1_500_000_000,
        min_confirmed_hits=1,
        min_memory_confidence=0.8,
        min_memory_visibility=0.5,
        work_bank_size=8,
        stable_bank_size=12,
        max_identities=64,
        reacquire_confirmed_hits=2,
        max_actionable_position_std_m=0.025,
        max_actionable_pose_age_ns=200_000_000,
        min_actionable_pose_hits=1,
    )
    return VisionConfig(
        min_depth_m=0.1,
        max_depth_m=2.0,
        pose=InstancePoseConfig(8, 1, 3.5, 0.002),
        identity=identity,
        extension_mode=extension_mode,
    )


def build_pipeline(*, enrichers=(), selector=None) -> VisionPipeline:
    config = default_config()
    return VisionPipeline(
        MockBottleSegmenter(),
        MockFeatureEncoder(),
        PersistentIdentityMemory(config.identity),
        config,
        enrichers=enrichers,
        selector=selector,
    )


def fixture_frame() -> FrameBundle:
    return FrameBundle(
        rgb=np.zeros((32, 32, 3), dtype=np.uint8),
        stamp=FrameStamp("offline_rgb", 1, 1_000_000),
    )

