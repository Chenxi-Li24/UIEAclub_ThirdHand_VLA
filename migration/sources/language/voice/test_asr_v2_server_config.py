#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import unittest

from funasr_backends import FunASRNanoBackend, ParaformerStreamingBackend
from whisper_backend import WhisperSmallBackend
from voice_bridge import build_model_manager, parse_args


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODEL_ROOT = PROJECT_ROOT / "models"


class AsrV2ServerConfigTests(unittest.TestCase):
    def test_server_defaults_are_loopback_3004_and_project_local_models(self) -> None:
        args = parse_args([])

        self.assertEqual(args.host, "127.0.0.1")
        self.assertEqual(args.port, 3004)
        self.assertEqual(args.model_root, str(MODEL_ROOT))
        self.assertEqual(args.paraformer_device, "cpu")

    def test_manager_factories_bind_the_three_approved_local_backends(self) -> None:
        args = parse_args([
            "--model-root", str(MODEL_ROOT),
        ])
        manager = build_model_manager(args)

        whisper = manager._factories["whisper-small"]()
        nano = manager._factories["fun-asr-nano"]()
        paraformer = manager._factories["paraformer-streaming"]()
        self.assertIsInstance(whisper, WhisperSmallBackend)
        self.assertIsInstance(nano, FunASRNanoBackend)
        self.assertIsInstance(paraformer, ParaformerStreamingBackend)
        self.assertEqual(
            whisper.model_path,
            str(MODEL_ROOT / "whisper-small"),
        )
        self.assertEqual(
            nano.model_path,
            str(MODEL_ROOT / "fun-asr-nano"),
        )
        self.assertEqual(
            paraformer.model_path,
            str(MODEL_ROOT / "paraformer-streaming"),
        )
        self.assertEqual(paraformer.device, "cpu")


if __name__ == "__main__":
    unittest.main()
