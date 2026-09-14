"""Feature-encoder protocols and optional DINOv2 adapter."""

from .base import FeatureEncoder, normalized_descriptor
from .dino import (
    DinoV2Encoder,
    mask_to_patch_coverage,
    pool_patch_descriptor,
    prepare_model_input,
)

__all__ = [
    "DinoV2Encoder",
    "FeatureEncoder",
    "mask_to_patch_coverage",
    "normalized_descriptor",
    "pool_patch_descriptor",
    "prepare_model_input",
]

