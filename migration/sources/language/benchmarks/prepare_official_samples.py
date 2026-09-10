#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import struct
import wave


ROOT = Path(__file__).resolve().parents[1]
TARGET_RATE = 16_000


def _read_wav(path: Path) -> tuple[list[float], int]:
    with wave.open(str(path), "rb") as source:
        if source.getsampwidth() != 2 or source.getcomptype() != "NONE":
            raise ValueError(f"Expected uncompressed PCM16 WAV: {path}")
        channels = source.getnchannels()
        sample_rate = source.getframerate()
        frames = source.readframes(source.getnframes())
    values = struct.unpack(f"<{len(frames) // 2}h", frames)
    mono = [
        sum(values[offset: offset + channels]) / (channels * 32768.0)
        for offset in range(0, len(values), channels)
    ]
    return mono, sample_rate


def _read_any_audio(path: Path) -> tuple[list[float], int]:
    if path.suffix.lower() == ".wav":
        return _read_wav(path)
    import soundfile as sf

    data, sample_rate = sf.read(str(path), dtype="float32", always_2d=True)
    return data.mean(axis=1).tolist(), int(sample_rate)


def _resample(samples: list[float], source_rate: int) -> list[float]:
    if source_rate == TARGET_RATE:
        return samples
    try:
        import numpy as np
        from scipy.signal import resample_poly

        divisor = math.gcd(source_rate, TARGET_RATE)
        result = resample_poly(
            np.asarray(samples, dtype=np.float32),
            TARGET_RATE // divisor,
            source_rate // divisor,
        )
        return result.tolist()
    except ImportError:
        output_count = round(len(samples) * TARGET_RATE / source_rate)
        if output_count <= 0:
            return []
        return [
            samples[min(len(samples) - 1, round(index * source_rate / TARGET_RATE))]
            for index in range(output_count)
        ]


def convert_to_pcm16_mono_16khz(source: Path, output: Path) -> dict[str, float | int | str]:
    samples, source_rate = _read_any_audio(Path(source))
    samples = _resample(samples, source_rate)
    pcm = [round(max(-1.0, min(0.999969, sample)) * 32768.0) for sample in samples]
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output), "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(TARGET_RATE)
        target.writeframes(struct.pack(f"<{len(pcm)}h", *pcm))
    return {
        "source": str(source),
        "output": str(output),
        "sampleRate": TARGET_RATE,
        "durationSec": len(pcm) / TARGET_RATE,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare official Nano examples for both ASR backends.")
    parser.add_argument("--model-root", type=Path, default=ROOT / "models" / "fun-asr-nano")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "benchmarks" / "audio")
    parser.add_argument("--manifest", type=Path, default=ROOT / "benchmarks" / "official-samples-manifest.json")
    args = parser.parse_args()

    rows = []
    for language in ("zh", "en"):
        source = args.model_root / "example" / f"{language}.mp3"
        output = args.output_dir / f"official-nano-{language}.wav"
        metadata = convert_to_pcm16_mono_16khz(source, output)
        rows.append({
            "id": f"official-nano-{language}",
            "category": f"official-{language}",
            "file": str(output.relative_to(args.manifest.parent)),
            "referenceStatus": "not-provided-by-upstream",
            "source": str(source),
            "durationSec": round(float(metadata["durationSec"]), 4),
        })
    args.manifest.write_text(json.dumps(rows, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps(rows, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
