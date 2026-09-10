from __future__ import annotations

from dataclasses import replace

import pytest

from thirdhand_vision.core.errors import ExtensionError
from thirdhand_vision.extensions.base import TargetSelection
from test_offline_pipeline import build_pipeline, pipeline_config, rgb_frame
from thirdhand_vision.identity.memory import PersistentIdentityMemory
from thirdhand_vision.pipeline.offline import VisionPipeline


class ColorEnricher:
    name = "color"

    def enrich(self, frame, result, context):
        detection_id = result.instances[0].detection.detection_id
        return {detection_id: {"color": context["color"]}}


class BottleSelector:
    name = "bottle-selector"

    def select(self, result, context):
        item = next(instance for instance in result.instances if instance.detection.label == context["query"])
        return TargetSelection(item.identity_id, 0.9, "label match")


class BrokenEnricher:
    name = "broken"

    def enrich(self, frame, result, context):
        raise RuntimeError("private details")


def test_extensions_enrich_and_select_existing_identity() -> None:
    pipeline = build_pipeline(enrichers=(ColorEnricher(),), selector=BottleSelector())
    result = pipeline.process(rgb_frame(), {"color": "blue", "query": "bottle"})
    assert result.instances[0].annotations == {"color": "blue"}
    assert result.selected_identity_id == result.instances[0].identity_id


def test_strict_extension_failure_is_wrapped() -> None:
    pipeline = build_pipeline(enrichers=(BrokenEnricher(),))
    with pytest.raises(ExtensionError, match="broken"):
        pipeline.process(rgb_frame(), {})


def test_isolated_extension_failure_keeps_core_result() -> None:
    strict = pipeline_config()
    config = replace(strict, extension_mode="isolate")
    pipeline = VisionPipeline(
        build_pipeline().segmenter,
        build_pipeline().encoder,
        PersistentIdentityMemory(config.identity),
        config,
        enrichers=(BrokenEnricher(),),
    )
    result = pipeline.process(rgb_frame(), {})
    assert len(result.instances) == 1
    assert result.extension_errors == ("broken:RuntimeError",)
