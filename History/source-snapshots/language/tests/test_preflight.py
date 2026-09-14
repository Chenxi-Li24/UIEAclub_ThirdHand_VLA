#!/usr/bin/env python3
from __future__ import annotations

import importlib.machinery
import importlib.util
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


def load_preflight():
    path = ROOT / "scripts" / "preflight.py"
    loader = importlib.machinery.SourceFileLoader("asr_v2_preflight", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class PreflightTests(unittest.TestCase):
    def test_model_path_escape_is_rejected_with_literal_code(self) -> None:
        preflight = load_preflight()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            errors = preflight.collect_static_errors(
                root,
                {
                    "fun-asr-nano": root.parent / "outside",
                    "paraformer-streaming": root / "models" / "paraformer-streaming",
                },
            )
        self.assertIn("MODEL_PATH_ESCAPE:fun-asr-nano", errors)

    def test_missing_snapshots_have_stable_error_codes(self) -> None:
        preflight = load_preflight()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            errors = preflight.collect_static_errors(
                root,
                {
                    "fun-asr-nano": root / "models" / "fun-asr-nano",
                    "paraformer-streaming": root / "models" / "paraformer-streaming",
                },
            )
        self.assertIn("MODEL_MISSING:fun-asr-nano", errors)
        self.assertIn("MODEL_MISSING:paraformer-streaming", errors)

    def test_complete_local_snapshots_pass_static_checks(self) -> None:
        preflight = load_preflight()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            nano = root / "models" / "fun-asr-nano"
            paraformer = root / "models" / "paraformer-streaming"
            nano.mkdir(parents=True)
            paraformer.mkdir(parents=True)
            (nano / "model.pt").write_bytes(b"fixture")
            (paraformer / "model.pt").write_bytes(b"fixture")
            errors = preflight.collect_static_errors(
                root,
                {"fun-asr-nano": nano, "paraformer-streaming": paraformer},
            )
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
