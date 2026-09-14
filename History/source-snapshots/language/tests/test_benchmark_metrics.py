#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "asr_benchmark", ROOT / "benchmarks" / "run_benchmark.py"
)
benchmark = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(benchmark)


class BenchmarkMetricTests(unittest.TestCase):
    def test_chinese_cer_uses_character_edits(self) -> None:
        self.assertEqual(benchmark.cer("向左转动", "向右转动"), 0.25)

    def test_english_wer_uses_word_edits(self) -> None:
        self.assertEqual(
            benchmark.wer("move the arm left", "move arm right"),
            0.5,
        )

    def test_latency_summary_reports_nearest_rank_p95(self) -> None:
        summary = benchmark.latency_summary([10, 20, 30, 40, 50])
        self.assertEqual(summary, {"p50Ms": 30.0, "p95Ms": 50.0})

    def test_intent_accuracy_is_separate_from_transcript_metrics(self) -> None:
        rows = [
            {"expectedIntent": "turn.left", "actualIntent": "turn.left"},
            {"expectedIntent": "lift.up", "actualIntent": "turn.left"},
        ]
        self.assertEqual(benchmark.intent_accuracy(rows), 0.5)

    def test_failed_gpu_case_is_recorded_without_policy_change(self) -> None:
        case = benchmark.failed_case(
            "paraformer-gpu",
            "GPU_RESOURCE_BUSY",
            "insufficient free VRAM",
        )
        self.assertEqual(case["status"], "failed")
        self.assertEqual(case["errorCode"], "GPU_RESOURCE_BUSY")
        self.assertFalse(case["deploymentPolicyChanged"])


if __name__ == "__main__":
    unittest.main()
