"""Depth rendering and deterministic Vision overlays."""

from .depth_heatmap import (
    DEFAULT_DEPTH_ALPHA,
    add_depth_legend,
    blend_registered_depth,
    render_depth_heatmap,
)
from .overlay import OverlayResult, RenderMetrics, encode_jpeg, render_overlay
from .monitor import (
    DEFAULT_MONITOR_DEPTH_ALPHA,
    MonitorFrame,
    compose_monitor_frame,
    render_monitor_notice,
)
from .preview_status import render_offline_frame, render_preview_banner

__all__ = [
    "OverlayResult",
    "RenderMetrics",
    "DEFAULT_DEPTH_ALPHA",
    "DEFAULT_MONITOR_DEPTH_ALPHA",
    "MonitorFrame",
    "add_depth_legend",
    "blend_registered_depth",
    "compose_monitor_frame",
    "encode_jpeg",
    "render_depth_heatmap",
    "render_monitor_notice",
    "render_offline_frame",
    "render_overlay",
    "render_preview_banner",
]
