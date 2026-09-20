import numpy as np
import pytest
import torch

from thirdhand_va.common.config import VisionConfig
from thirdhand_va.vision.perception import grounded_sam
from thirdhand_va.vision.perception.grounded_sam import (
    PROMPTS,
    GroundedSamBackend,
    masked_rgb_descriptor,
    sam_input_boxes,
)
from thirdhand_va.vision.perception.interfaces import canonical_prompt_label
from thirdhand_va.vision.perception.interfaces import RawCandidate


def test_prompt_requests_generic_bottles_only() -> None:
    assert PROMPTS == ("bottle",)


def test_tokenizer_redundancy_maps_back_to_controlled_prompt() -> None:
    assert canonical_prompt_label(
        "coca - cola plastic bottle coca - cola"
    ) == "coca-cola plastic bottle"


def test_sam_boxes_use_three_list_levels() -> None:
    assert sam_input_boxes(((1.0, 2.0, 3.0, 4.0),)) == [
        [[1.0, 2.0, 3.0, 4.0]]
    ]


def test_masked_descriptor_ignores_background() -> None:
    mask = np.zeros((20, 20), dtype=bool)
    mask[4:16, 8:12] = True
    first = np.zeros((20, 20, 3), dtype=np.uint8)
    first[mask] = (220, 30, 20)
    second = first.copy()
    second[~mask] = (15, 240, 90)

    left = masked_rgb_descriptor(first, mask, bins=8)
    right = masked_rgb_descriptor(second, mask, bins=8)

    np.testing.assert_allclose(left, right)
    assert np.linalg.norm(left) == pytest.approx(1.0)


def test_backend_construction_does_not_load_gpu_models() -> None:
    config = VisionConfig.from_yaml("configs/vision.yaml")

    backend = GroundedSamBackend(config, local_files_only=True)

    assert backend.models_loaded is False


def test_backend_uses_huggingface_hub_subdirectory() -> None:
    config = VisionConfig.from_yaml("configs/vision.yaml")

    backend = GroundedSamBackend(config, local_files_only=True)

    assert backend.model_cache_dir == config.hf_home / "hub"


def test_backend_redetects_on_interval_and_discovers_new_objects() -> None:
    config = VisionConfig.from_yaml("configs/vision.yaml")

    class SchedulingBackend(GroundedSamBackend):
        def __init__(self):
            super().__init__(config)
            self.detect_calls = 0
            self.track_calls = 0

        def _load_models(self):
            return object()

        def _detect_and_seed(self, image, image_array, models):
            self.detect_calls += 1
            self._video_session = object()
            return tuple(
                RawCandidate(
                    detection_id=index,
                    prompt_label="bottle",
                    score=0.9,
                    bbox_xyxy=(1, 1, 3, 7),
                    mask=np.ones((8, 8), dtype=bool),
                    descriptor=np.ones(4, dtype=np.float32),
                )
                for index in range(self.detect_calls)
            )

        def _track_frame(self, image, image_array, models):
            self.track_calls += 1
            return ()

    backend = SchedulingBackend()
    rgb = np.zeros((8, 8, 3), dtype=np.uint8)

    outputs = [backend.infer(rgb) for _ in range(config.redetect_interval_frames + 1)]

    assert backend.detect_calls == 2
    assert backend.track_calls == config.redetect_interval_frames - 1
    assert {candidate.detection_id for candidate in outputs[-1]} == {0, 1}


def test_model_provenance_names_configured_models_and_versions() -> None:
    config = VisionConfig.from_yaml("configs/vision.yaml")

    provenance = GroundedSamBackend(config).model_provenance()

    assert provenance["grounding_model"] == config.grounding_model
    assert provenance["grounding_revision"] == config.grounding_revision
    assert provenance["grounding_weights_sha256"] == config.grounding_weights_sha256
    assert provenance["sam_model"] == config.sam_model
    assert provenance["sam_revision"] == config.sam_revision
    assert provenance["sam_weights_sha256"] == config.sam_weights_sha256
    assert provenance["transformers_version"] == "4.56.2"


class _FakeSession:
    def __init__(self) -> None:
        self.processed_frames = {index: object() for index in range(40)}
        self.output_dict_per_obj = {
            0: {
                "cond_frame_outputs": {0: {"prompt": object()}},
                "non_cond_frame_outputs": {
                    index: {"memory": object()} for index in range(1, 40)
                },
            }
        }
        self.frames_tracked_per_obj = {
            0: {index: {"tracked": True} for index in range(40)}
        }

    def get_obj_num(self) -> int:
        return 1


def test_stream_history_pruning_bounds_dictionary_frames_and_keeps_prompt() -> None:
    """Regression: HF 4.56 stores processed_frames as a dict, not a list."""
    backend = object.__new__(GroundedSamBackend)
    backend._video_session = _FakeSession()

    backend._prune_video_history(39, keep_frames=8)

    session = backend._video_session
    # Preserve dictionary length because HF chooses the next streaming frame
    # index from len(processed_frames); clear tensors without reusing indices.
    assert len(session.processed_frames) == 40
    assert session.processed_frames[0] is not None
    assert all(session.processed_frames[index] is None for index in range(1, 31))
    assert all(session.processed_frames[index] is not None for index in range(31, 40))
    assert sorted(session.output_dict_per_obj[0]["cond_frame_outputs"]) == [0]
    assert sorted(session.output_dict_per_obj[0]["non_cond_frame_outputs"]) == list(
        range(31, 40)
    )
    assert sorted(session.frames_tracked_per_obj[0]) == list(range(31, 40))


@pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA hardware required")
def test_cuda_inference_uses_fp16_autocast() -> None:
    """Removing autocast must put both vision models back on the slow FP32 path."""
    with grounded_sam.cuda_inference_context(torch):
        assert torch.is_autocast_enabled("cuda")
        assert torch.get_autocast_dtype("cuda") is torch.float16
