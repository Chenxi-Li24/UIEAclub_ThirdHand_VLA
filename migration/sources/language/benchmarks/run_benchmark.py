#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import re
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[1]


def edit_distance(reference: Sequence[Any], hypothesis: Sequence[Any]) -> int:
    previous = list(range(len(hypothesis) + 1))
    for ref_index, ref_item in enumerate(reference, start=1):
        current = [ref_index]
        for hyp_index, hyp_item in enumerate(hypothesis, start=1):
            current.append(min(
                current[-1] + 1,
                previous[hyp_index] + 1,
                previous[hyp_index - 1] + (ref_item != hyp_item),
            ))
        previous = current
    return previous[-1]


def normalize_characters(text: str) -> list[str]:
    return [
        char.lower()
        for char in text
        if char.isalnum() or "\u4e00" <= char <= "\u9fff"
    ]


def normalize_words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", text.lower())


def cer(reference: str, hypothesis: str) -> float:
    expected = normalize_characters(reference)
    if not expected:
        return 0.0 if not normalize_characters(hypothesis) else 1.0
    return edit_distance(expected, normalize_characters(hypothesis)) / len(expected)


def wer(reference: str, hypothesis: str) -> float:
    expected = normalize_words(reference)
    if not expected:
        return 0.0 if not normalize_words(hypothesis) else 1.0
    return edit_distance(expected, normalize_words(hypothesis)) / len(expected)


def latency_summary(values: Sequence[float]) -> dict[str, float | None]:
    if not values:
        return {"p50Ms": None, "p95Ms": None}
    ordered = sorted(float(value) for value in values)

    def nearest_rank(fraction: float) -> float:
        index = max(0, math.ceil(fraction * len(ordered)) - 1)
        return round(ordered[index], 1)

    return {"p50Ms": nearest_rank(0.50), "p95Ms": nearest_rank(0.95)}


def intent_accuracy(rows: Sequence[dict[str, Any]]) -> float | None:
    comparable = [row for row in rows if row.get("expectedIntent") is not None]
    if not comparable:
        return None
    correct = sum(
        row.get("expectedIntent") == row.get("actualIntent")
        for row in comparable
    )
    return correct / len(comparable)


def failed_case(name: str, error_code: str, message: str) -> dict[str, Any]:
    return {
        "scenario": name,
        "status": "failed",
        "errorCode": error_code,
        "message": message,
        "deploymentPolicyChanged": False,
    }


def summarize_rows(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    chinese = [row for row in rows if row.get("category") == "zh"]
    english = [row for row in rows if row.get("category") == "en"]
    return {
        "chineseCer": (
            sum(cer(row["reference"], row["transcript"]) for row in chinese)
            / len(chinese)
            if chinese else None
        ),
        "englishWer": (
            sum(wer(row["reference"], row["transcript"]) for row in english)
            / len(english)
            if english else None
        ),
        "intentAccuracy": intent_accuracy(rows),
        **latency_summary([row["latencyMs"] for row in rows]),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize ASR V2 benchmark rows.")
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "benchmarks/results.json")
    args = parser.parse_args()
    rows = json.loads(args.input.read_text("utf-8"))
    result = summarize_rows(rows)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
