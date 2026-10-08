"""Runtime confidence must never weaken the reviewed vision configuration."""

from pathlib import Path
import unittest

import numpy as np

from services.vision.python.camera_bridge import CameraRuntime
from thirdhand_va.common.config import VisionConfig
from thirdhand_va.common.contracts import RgbdFrame
from thirdhand_va.vision.pipeline import VisionPipeline
from thirdhand_va.vision.perception.interfaces import RawCandidate


CONFIG = VisionConfig.from_yaml(Path(__file__).resolve().parents[3] / "configs/vision.yaml")


class FakeModel:
    def __init__(self):
        self.value = CONFIG.min_bottle_score

    def set_min_bottle_score(self, value):
        self.value = value


class FakeBackend:
    def infer(self, _rgb):
        return ()


class RuntimeConfidenceTest(unittest.TestCase):
    def test_threshold_hides_previous_low_score_track_immediately(self):
        class LowScoreBackend:
            def infer(self, _rgb):
                return (RawCandidate(
                    detection_id=1, prompt_label="bottle", score=0.49,
                    bbox_xyxy=(35, 20, 65, 80), mask=mask, descriptor=None,
                ),)

        mask = np.zeros((100, 100), dtype=bool)
        mask[20:80, 35:65] = True
        pipeline = VisionPipeline(CONFIG, LowScoreBackend())
        def frame(sequence):
            return RgbdFrame(
                sequence=sequence, monotonic_ns=sequence * 100_000_000,
                camera_serial=CONFIG.camera_serial,
                rgb=np.zeros((100, 100, 3), dtype=np.uint8),
                depth_m=np.zeros((100, 100), dtype=np.float32),
                xyz_camera_m=np.zeros((100, 100, 3), dtype=np.float32),
            )
        before = None
        for sequence in range(1, 5):
            before = pipeline.process(frame(sequence))
        self.assertTrue(before.tracks)
        pipeline.set_min_bottle_score(0.65)
        after = pipeline.process(frame(5))
        self.assertFalse(after.tracks)

    def test_threshold_removes_low_score_targets_from_tracking_and_display(self):
        pipeline = VisionPipeline(CONFIG, FakeBackend())
        pipeline.set_min_bottle_score(0.65)
        rgb = np.zeros((100, 100, 3), dtype=np.uint8)
        mask = np.zeros((100, 100), dtype=bool)
        mask[20:80, 35:65] = True
        candidates = tuple(RawCandidate(
            detection_id=index, prompt_label="bottle", score=score,
            bbox_xyxy=(35, 20, 65, 80), mask=mask, descriptor=None,
        ) for index, score in enumerate((0.49, 0.65, 0.82), start=1))
        filtered = pipeline.filter.filter(rgb, candidates)
        self.assertEqual([item.detection_id for item in filtered], [2, 3])

    def test_runtime_refuses_confidence_below_reviewed_floor(self):
        pipeline = VisionPipeline(CONFIG, FakeBackend())
        with self.assertRaisesRegex(ValueError, "safety floor"):
            pipeline.set_min_bottle_score(CONFIG.min_bottle_score - 0.01)
        pipeline.set_min_bottle_score(0.65)
        self.assertEqual(pipeline.filter.min_bottle_score, 0.65)
        self.assertEqual(pipeline.config.content_id, CONFIG.content_id)

    def test_bridge_updates_actual_model_and_clears_selection(self):
        runtime = CameraRuntime((), model_factory=FakeModel,
                                min_bottle_score_floor=CONFIG.min_bottle_score)
        model = FakeModel()
        runtime._model = model
        runtime._selected_id = 3
        runtime._selection_request_id = "selected-3"
        self.assertFalse(runtime.set_min_bottle_score(CONFIG.min_bottle_score - 0.01))
        self.assertTrue(runtime.set_min_bottle_score(0.7))
        self.assertEqual(model.value, 0.7)
        self.assertIsNone(runtime.status()["selection"]["stableId"])
        self.assertEqual(runtime.status()["confidence"]["minimumScore"], 0.7)
