from pathlib import Path
import importlib.util
import sys
from unittest.mock import patch
import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[3]
MODULE = ROOT / "services/vision/python/thirdhand_va/vision/perception/meituan_battery.py"

def module():
    assert MODULE.exists(), "RGB-only shared-model battery adapter is missing"
    spec = importlib.util.spec_from_file_location("meituan_battery_test", MODULE)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value

@pytest.mark.parametrize("rgb,want", [
    ((255,0,0),"red"), ((255,230,0),"yellow"),
    ((0,140,255),"blue"), ((80,220,0),"green"),
])
def test_color_is_measured_inside_mask_not_neighbor_or_white_background(rgb, want):
    m = module()
    image = np.full((60,60,3), 255, np.uint8)
    image[10:50,10:50] = rgb
    image[:8] = (255,0,0)
    mask = np.zeros((60,60), bool)
    mask[10:50,10:50] = True
    result = m.classify_color(image, mask, m.load_defaults())
    assert result["color"] == want
    assert result["colorScore"] > .9

def test_unknown_for_no_colored_pixels_or_ambiguous_red_and_blue():
    m = module()
    mask = np.ones((40,40), bool)
    image = np.full((40,40,3), 255, np.uint8)
    assert m.classify_color(image, mask, m.load_defaults())["color"] == "unknown"
    image[:20] = (255,0,0)
    image[20:] = (0,0,255)
    assert m.classify_color(image, mask, m.load_defaults())["color"] == "unknown"

@pytest.mark.parametrize("bad", [
    {"prompt":""}, {"prompt":"x"*513}, {"boxThreshold":float("nan")},
    {"textThreshold":1.1}, {"boxThreshold":"0.3"}, {"codePath":"/tmp/evil.py"},
])
def test_request_parameters_reject_invalid_values_and_code_paths(bad):
    m = module()
    with pytest.raises(ValueError):
        m.parameters(bad)

def test_single_frame_returns_colored_contour_and_metadata_without_depth():
    m = module()
    rgb = np.full((80,80,3), 255, np.uint8)
    rgb[20:60,20:60] = (255,0,0)
    mask = np.zeros((80,80), bool)
    mask[20:60,20:60] = True
    candidates = [{"box":[20.,20.,60.,60.], "score":.88, "mask":mask}]
    existing = object()
    with patch.object(m, "detect_masks", return_value=candidates) as infer:
        result = m.recognize(existing, rgb, 17, m.parameters({}))
    assert infer.call_args.args[0] is existing
    assert result["frameId"] == 17
    assert result["detections"][0]["color"] == "red"
    assert result["detections"][0]["score"] == .88
    assert result["detections"][0]["contour"]
    assert result["jpeg"].startswith(b"\xff\xd8")
    assert not ({"depth", "xyz", "slot"} & result.keys())

def test_shared_inference_uses_battery_prompt_and_correct_sam_box_shape():
    from types import SimpleNamespace
    from contextlib import nullcontext
    import torch
    m = module()
    sessions = []
    class Inputs(dict):
        def __getattr__(self, key):
            return self[key]
        def to(self, device):
            return self
    class Dino:
        def __call__(self, **kwargs):
            assert kwargs["text"] == ["battery ."]
            return Inputs(input_ids=torch.zeros((1,1), dtype=torch.int64))
        def post_process_grounded_object_detection(self, *args, **kwargs):
            return [{"boxes":torch.tensor([[2.,2.,18.,18.]]), "scores":torch.tensor([.9])}]
    class Sam:
        def init_video_session(self, **kwargs):
            value = SimpleNamespace(reset=False)
            value.reset_inference_session = lambda: setattr(value, "reset", True)
            sessions.append(value)
            return value
        def __call__(self, **kwargs):
            value = Inputs()
            value.original_sizes = torch.tensor([[20,20]])
            value.pixel_values = torch.zeros((1,3,20,20))
            return value
        def add_inputs_to_inference_session(self, **kwargs):
            assert kwargs["input_boxes"] == [[[2.,2.,18.,18.]]]
        def post_process_masks(self, *args, **kwargs):
            return [torch.ones((1,1,20,20), dtype=torch.bool)]
    models = SimpleNamespace(
        torch=SimpleNamespace(inference_mode=nullcontext, autocast=lambda **kwargs:nullcontext(),
                              float16=torch.float16,bfloat16=torch.bfloat16),
        device="cpu", dino_processor=Dino(), dino_model=lambda **kwargs:None,
        sam_processor=Sam(), sam_model=lambda **kwargs:SimpleNamespace(pred_masks=None))
    rows = m.detect_masks(models, np.zeros((20,20,3), np.uint8), m.parameters({}))
    assert rows[0]["mask"].shape == (20,20)
    assert sessions[0].reset

def test_caption_prompt_is_accepted_by_real_dino_processor_without_weights():
    from contextlib import nullcontext
    from types import SimpleNamespace
    import torch
    from tokenizers import Tokenizer
    from tokenizers.models import WordLevel
    from tokenizers.pre_tokenizers import Whitespace
    from transformers import PreTrainedTokenizerFast, GroundingDinoImageProcessor, GroundingDinoProcessor
    vocabulary = Tokenizer(WordLevel({"[UNK]": 0, "battery": 1, ".": 2}, unk_token="[UNK]"))
    vocabulary.pre_tokenizer = Whitespace()
    tokenizer = PreTrainedTokenizerFast(tokenizer_object=vocabulary, unk_token="[UNK]")
    processor = GroundingDinoProcessor(
        image_processor=GroundingDinoImageProcessor(do_resize=False), tokenizer=tokenizer)
    models = SimpleNamespace(
        torch=SimpleNamespace(inference_mode=nullcontext, autocast=lambda **kwargs:nullcontext(), float16=torch.float16),
        device="cpu", dino_processor=processor,
        dino_model=lambda **kwargs:SimpleNamespace(logits=torch.full((1,1,kwargs["input_ids"].shape[1]),-100.),
                                                   pred_boxes=torch.zeros((1,1,4))))
    assert module().detect_masks(models,np.zeros((20,20,3),np.uint8),module().parameters({})) == []
