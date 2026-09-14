import asyncio
import unittest
from unittest.mock import patch

from benchmarks.model_benchmark import (
    iter_pcm_chunks,
    load_pcm16_mono,
    run_paraformer_case,
)


class FakeParaformer:
    device = "cpu"
    model_id = "paraformer-streaming"

    def __init__(self):
        self.pushes = []

    def start_stream(self, session_id):
        self.session_id = session_id

    async def push_audio(self, session_id, pcm):
        self.pushes.append(pcm)
        return "hello" if len(self.pushes) == 1 else None

    async def finish_stream(self, session_id, _audio):
        return {
            "text": "hello world",
            "duration": 1.2,
            "processing_time": 0.12,
        }


class ModelBenchmarkTests(unittest.TestCase):
    def test_load_pcm16_mono_requires_16khz_mono_s16(self):
        class FakeWave:
            def __enter__(self): return self
            def __exit__(self, *_args): return False
            def getnchannels(self): return 1
            def getsampwidth(self): return 2
            def getframerate(self): return 16000
            def getcomptype(self): return "NONE"
            def getnframes(self): return 4
            def readframes(self, _count): return b"\x01\x00\xff\xff\x02\x00\xfe\xff"

        with patch("benchmarks.model_benchmark.wave.open", return_value=FakeWave()):
            pcm, duration = load_pcm16_mono("sample.wav")
        self.assertEqual(pcm, b"\x01\x00\xff\xff\x02\x00\xfe\xff")
        self.assertAlmostEqual(duration, 4 / 16000)

    def test_chunks_preserve_all_audio(self):
        pcm = bytes(range(100))
        self.assertEqual(b"".join(iter_pcm_chunks(pcm, 24)), pcm)

    def test_paraformer_case_reports_partial_final_and_rtf(self):
        backend = FakeParaformer()
        row = asyncio.run(run_paraformer_case(
            backend,
            case={"id": "en-1", "reference": "hello world", "category": "en"},
            pcm=b"\0\0" * 19200,
            duration=1.2,
            chunk_bytes=19200,
        ))
        self.assertEqual(row["transcript"], "hello world")
        self.assertIsNotNone(row["firstPartialMs"])
        self.assertGreaterEqual(row["finalLatencyMs"], row["firstPartialMs"])
        self.assertAlmostEqual(row["rtf"], 0.1)
        self.assertEqual(len(backend.pushes), 2)


if __name__ == "__main__":
    unittest.main()
