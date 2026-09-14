#!/usr/bin/env python3
from __future__ import annotations

from types import SimpleNamespace
import unittest
from typing import Any

from whisper_backend import WhisperSmallBackend


class FakeWhisperModel:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def transcribe(self, audio: Any, **kwargs: Any):
        self.calls.append({"audio": audio, **kwargs})
        segments = iter([
            SimpleNamespace(text=" 向左 ", start=0.0, end=0.5),
            SimpleNamespace(text=" 移动 ", start=0.5, end=1.0),
        ])
        info = SimpleNamespace(
            language="zh",
            duration=1.0,
            language_probability=0.99,
        )
        return segments, info


class WhisperSmallBackendTests(unittest.IsolatedAsyncioTestCase):
    async def test_loads_explicit_local_path_and_normalizes_final(self) -> None:
        model = FakeWhisperModel()
        loader_calls: list[dict[str, Any]] = []
        clock_values = iter([10.0, 10.25])

        def loader(**kwargs: Any) -> FakeWhisperModel:
            loader_calls.append(kwargs)
            return model

        async def release_cuda() -> None:
            return None

        backend = WhisperSmallBackend(
            "/project/models/whisper-small",
            loader=loader,
            clock=lambda: next(clock_values),
            release_cuda=release_cuda,
        )

        await backend.load()
        result = await backend.transcribe_final([0.1, -0.1])

        self.assertEqual(loader_calls, [{
            "model_size_or_path": "/project/models/whisper-small",
            "device": "cuda",
            "compute_type": "float16",
            "local_files_only": True,
        }])
        self.assertEqual(model.calls, [{
            "audio": [0.1, -0.1],
            "language": None,
            "beam_size": 5,
            "vad_filter": False,
        }])
        self.assertEqual(result, {
            "text": "向左 移动",
            "language": "zh",
            "language_probability": 0.99,
            "segments": [
                {"start": 0.0, "end": 0.5, "text": "向左"},
                {"start": 0.5, "end": 1.0, "text": "移动"},
            ],
            "duration": 1.0,
            "processing_time": 0.25,
            "device": "cuda",
            "model_id": "whisper-small",
            "is_final": True,
        })
        self.assertTrue(backend.loaded)

    async def test_unload_is_idempotent_and_releases_cuda_once(self) -> None:
        releases: list[str] = []

        async def release_cuda() -> None:
            releases.append("release")

        backend = WhisperSmallBackend(
            "/project/models/whisper-small",
            loader=lambda **_kwargs: FakeWhisperModel(),
            release_cuda=release_cuda,
        )
        await backend.load()

        await backend.unload()
        await backend.unload()

        self.assertFalse(backend.loaded)
        self.assertEqual(releases, ["release"])

    async def test_transcribe_requires_loaded_model(self) -> None:
        backend = WhisperSmallBackend(
            "/project/models/whisper-small",
            loader=lambda **_kwargs: FakeWhisperModel(),
        )

        with self.assertRaisesRegex(RuntimeError, "not loaded"):
            await backend.transcribe_final([0.0])


if __name__ == "__main__":
    unittest.main()
