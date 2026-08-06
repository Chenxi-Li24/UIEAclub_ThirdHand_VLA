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
    "ActiveViewConfig",
    "ActiveViewDryRunAdapter",
    "ActiveViewTargetReport",
    "DinoMaskEncoder",
    "InstanceDetection",
    "ModelContractError",
    "OnlinePerceptionEngine",
    "OnlinePerceptionResult",
    "OnlineVisionConfig",
    "RTMDetInstanceSegmenter",
    "detections_from_mmdet",
    "mask_to_patch_coverage",
    "load_online_vision_config",
    "load_active_view_config",
    "pool_patch_descriptor",
    "prepare_model_input",
    "render_overlay",
]


def __getattr__(name):
    """Keep online orchestration lazy so core vision imports cannot form a cycle."""

    if name in {
        "ActiveViewConfig",
        "ActiveViewDryRunAdapter",
        "ActiveViewTargetReport",
        "load_active_view_config",
    }:
        from . import active_view_online

        return getattr(active_view_online, name)
    if name in {
        "OnlinePerceptionEngine",
        "OnlinePerceptionResult",
        "OnlineVisionConfig",
        "load_online_vision_config",
        "render_overlay",
    }:
        from . import online

        return getattr(online, name)
    raise AttributeError(name)
