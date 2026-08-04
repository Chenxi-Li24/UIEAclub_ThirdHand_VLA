"""Hardware-isolated adapters for REMIND-3D model inference."""

from .contracts import InstanceDetection, ModelContractError
from .dino import (
    DinoMaskEncoder,
    mask_to_patch_coverage,
    pool_patch_descriptor,
    prepare_model_input,
)
from .rtmdet import RTMDetInstanceSegmenter, detections_from_mmdet

__all__ = [
    "DinoMaskEncoder",
    "InstanceDetection",
    "ModelContractError",
    "RTMDetInstanceSegmenter",
    "detections_from_mmdet",
    "mask_to_patch_coverage",
    "pool_patch_descriptor",
    "prepare_model_input",
]
