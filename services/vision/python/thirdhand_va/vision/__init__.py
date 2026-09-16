"""Reusable camera perception, selection, geometry, and tracking modules."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .pipeline import VisionPipeline

__all__ = ["VisionPipeline"]


def __getattr__(name: str):
    """Load the optional full pipeline only when callers explicitly request it."""
    if name == "VisionPipeline":
        from .pipeline import VisionPipeline

        return VisionPipeline
    raise AttributeError(name)
