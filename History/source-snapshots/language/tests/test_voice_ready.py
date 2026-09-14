from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "voice_ready.py"


class VoiceReadyTests(unittest.TestCase):
    def _load(self):
        self.assertTrue(MODULE_PATH.exists(), "voice readiness checker is missing")
        spec = importlib.util.spec_from_file_location("voice_ready", MODULE_PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_ready_requires_default_whisper_small_on_cuda(self):
        module = self._load()
        payload = {
            "type": "model.list",
            "payload": {"status": {
                "state": "READY",
                "activeModelId": "whisper-small",
                "device": "cuda",
            }},
        }
        self.assertEqual(module.validate_ready_payload(payload), [])

    def test_ready_nano_is_rejected_as_the_wrong_startup_model(self):
        module = self._load()
        payload = {
            "type": "model.list",
            "payload": {"status": {
                "state": "READY",
                "activeModelId": "fun-asr-nano",
                "device": "cuda",
            }},
        }
        self.assertEqual(module.validate_ready_payload(payload), [
            "ASR_MODEL:fun-asr-nano",
        ])

    def test_error_or_wrong_model_never_counts_as_started(self):
        module = self._load()
        payload = {
            "type": "model.list",
            "payload": {"status": {
                "state": "ERROR",
                "activeModelId": None,
                "device": None,
            }},
        }
        self.assertEqual(module.validate_ready_payload(payload), [
            "ASR_STATE:ERROR",
            "ASR_MODEL:None",
            "ASR_DEVICE:None",
        ])


if __name__ == "__main__":
    unittest.main()
