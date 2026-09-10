#!/usr/bin/env python3
from __future__ import annotations

import struct
import unittest
from typing import Any

from funasr_backends import FunASRNanoBackend, ParaformerStreamingBackend


class FakeModel:
    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def generate(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        self.calls.append({"args": args, **kwargs})
        return [self.responses.pop(0)]


class BackendAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_nano_loads_only_local_path_on_cuda_and_normalizes_final(self) -> None:
        model = FakeModel([{
            "text": "turn left",
            "language": "en",
            "timestamp": [[0, 420]],
        }])
        loader_calls: list[dict[str, Any]] = []

        def loader(**kwargs: Any) -> FakeModel:
            loader_calls.append(kwargs)
            return model

        backend = FunASRNanoBackend(
            "/project/models/fun-asr-nano",
            loader=loader,
            clock=lambda: 10.0,
        )
        await backend.load()
        result = await backend.transcribe_final([0.1, -0.1])

        self.assertEqual(loader_calls, [{
            "model": "/project/models/fun-asr-nano",
            "tensor_parallel_size": 1,
            "gpu_memory_utilization": 0.35,
            "vllm_kwargs": {
                "attention_config": {"backend": "TRITON_ATTN"},
                "max_num_seqs": 4,
            },
        }])
        self.assertEqual(model.calls[0]["args"], ([[0.1, -0.1]],))
        self.assertEqual(model.calls[0]["language"], "auto")
        self.assertEqual(model.calls[0]["temperature"], 0.0)
        self.assertEqual(model.calls[0]["repetition_penalty"], 1.0)
        self.assertEqual(result, {
            "text": "turn left",
            "language": "en",
            "segments": [[0, 420]],
            "duration": None,
            "processing_time": 0.0,
            "device": "cuda",
            "model_id": "fun-asr-nano",
            "is_final": True,
        })
        self.assertTrue(backend.loaded)
        await backend.unload()
        self.assertFalse(backend.loaded)

    async def test_paraformer_emits_partial_per_600ms_and_flushes_final(self) -> None:
        model = FakeModel([
            {"text": "向左"},
            {"text": "一点"},
        ])

        backend = ParaformerStreamingBackend(
            "/project/models/paraformer-streaming",
            device="cpu",
            loader=lambda **_kwargs: model,
            clock=lambda: 20.0,
        )
        await backend.load()
        backend.start_stream("s1")

        pcm_600ms = struct.pack("<h", 1000) * 9_600
        partial = await backend.push_audio("s1", pcm_600ms)
        final = await backend.finish_stream("s1", [])

        self.assertEqual(partial, "向左")
        self.assertEqual(final, {
            "text": "向左一点",
            "language": None,
            "segments": [],
            "duration": 0.6,
            "processing_time": 0.0,
            "device": "cpu",
            "model_id": "paraformer-streaming",
            "is_final": True,
        })
        self.assertFalse(model.calls[0]["is_final"])
        self.assertTrue(model.calls[1]["is_final"])
        self.assertEqual(model.calls[0]["chunk_size"], [0, 10, 5])
        self.assertIs(model.calls[0]["cache"], model.calls[1]["cache"])

    async def test_paraformer_cancel_discards_buffer_without_inference(self) -> None:
        model = FakeModel([])
        backend = ParaformerStreamingBackend(
            "/project/models/paraformer-streaming",
            device="cpu",
            loader=lambda **_kwargs: model,
        )
        await backend.load()
        backend.start_stream("s2")
        await backend.push_audio("s2", struct.pack("<h", 1000) * 1_600)

        backend.cancel_stream("s2")

        self.assertEqual(model.calls, [])
        self.assertNotIn("s2", backend.active_stream_ids)


if __name__ == "__main__":
    unittest.main()
