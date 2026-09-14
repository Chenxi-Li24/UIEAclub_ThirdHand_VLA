from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest
import wave


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "benchmarks" / "prepare_official_samples.py"


class OfficialSamplePreparationTests(unittest.TestCase):
    def test_conversion_produces_16khz_mono_pcm16_without_changing_duration(self):
        self.assertTrue(MODULE_PATH.exists(), "official sample preparer is missing")
        spec = importlib.util.spec_from_file_location("prepare_official_samples", MODULE_PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.wav"
            output = Path(directory) / "output.wav"
            sample_rate = 48_000
            frame_count = 4_800
            stereo_silence = b"\0\0\0\0" * frame_count
            with wave.open(str(source), "wb") as wav:
                wav.setnchannels(2)
                wav.setsampwidth(2)
                wav.setframerate(sample_rate)
                wav.writeframes(stereo_silence)

            metadata = module.convert_to_pcm16_mono_16khz(source, output)

            with wave.open(str(output), "rb") as wav:
                self.assertEqual(wav.getnchannels(), 1)
                self.assertEqual(wav.getsampwidth(), 2)
                self.assertEqual(wav.getframerate(), 16_000)
                self.assertEqual(wav.getcomptype(), "NONE")
                self.assertAlmostEqual(wav.getnframes() / 16_000, 0.1, places=3)
            self.assertEqual(metadata["sampleRate"], 16_000)
            self.assertAlmostEqual(metadata["durationSec"], 0.1, places=3)


if __name__ == "__main__":
    unittest.main()
