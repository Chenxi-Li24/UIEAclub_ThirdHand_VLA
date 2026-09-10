#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import subprocess
import threading
import time
import uuid
import wave
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]


def load_pcm16_mono(path: Path) -> tuple[bytes, float]:
    with wave.open(str(path), "rb") as source:
        if (
            source.getnchannels() != 1
            or source.getsampwidth() != 2
            or source.getframerate() != 16_000
            or source.getcomptype() != "NONE"
        ):
            raise ValueError(f"Expected 16 kHz mono PCM S16LE WAV: {path}")
        frames = source.readframes(source.getnframes())
        duration = source.getnframes() / source.getframerate()
    return frames, duration


def iter_pcm_chunks(pcm: bytes, chunk_bytes: int) -> Iterable[bytes]:
    if chunk_bytes <= 0 or chunk_bytes % 2:
        raise ValueError("chunk_bytes must be a positive even number")
    for offset in range(0, len(pcm), chunk_bytes):
        yield pcm[offset: offset + chunk_bytes]


def _gpu_snapshot() -> tuple[float | None, float | None]:
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=utilization.gpu,memory.used",
                "--format=csv,noheader,nounits",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=3,
        )
        first = result.stdout.strip().splitlines()[0]
        utilization, memory = (float(item.strip()) for item in first.split(","))
        return utilization, memory
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        return None, None


class ResourceSampler:
    def __init__(self, interval: float = 0.25) -> None:
        self.interval = interval
        self.samples: list[dict[str, float | None]] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> dict[str, float | None]:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        return self.summary()

    def _run(self) -> None:
        import psutil

        process = psutil.Process()
        while not self._stop.is_set():
            rss = process.memory_info().rss
            for child in process.children(recursive=True):
                try:
                    rss += child.memory_info().rss
                except psutil.Error:
                    pass
            gpu_util, gpu_memory = _gpu_snapshot()
            self.samples.append({
                "systemCpuPct": psutil.cpu_percent(interval=None),
                "systemRamPct": psutil.virtual_memory().percent,
                "processRssMiB": rss / 1024 / 1024,
                "gpuUtilPct": gpu_util,
                "gpuMemoryMiB": gpu_memory,
            })
            self._stop.wait(self.interval)

    def summary(self) -> dict[str, float | None]:
        def maximum(name: str) -> float | None:
            values = [
                float(sample[name])
                for sample in self.samples
                if sample.get(name) is not None
            ]
            return round(max(values), 1) if values else None

        return {
            "peakSystemCpuPct": maximum("systemCpuPct"),
            "peakSystemRamPct": maximum("systemRamPct"),
            "peakProcessRssMiB": maximum("processRssMiB"),
            "peakGpuUtilPct": maximum("gpuUtilPct"),
            "peakGpuMemoryMiB": maximum("gpuMemoryMiB"),
        }


async def run_paraformer_case(
    backend: Any,
    *,
    case: dict[str, Any],
    pcm: bytes,
    duration: float,
    chunk_bytes: int = 19_200,
) -> dict[str, Any]:
    session_id = f"benchmark-{uuid.uuid4()}"
    backend.start_stream(session_id)
    started = time.perf_counter()
    first_partial_ms: float | None = None
    for chunk in iter_pcm_chunks(pcm, chunk_bytes):
        partial = await backend.push_audio(session_id, chunk)
        if partial and first_partial_ms is None:
            first_partial_ms = (time.perf_counter() - started) * 1000
    result = await backend.finish_stream(session_id, None)
    final_latency_ms = (time.perf_counter() - started) * 1000
    processing_time = float(result.get("processing_time") or 0.0)
    return {
        **case,
        "transcript": str(result.get("text") or ""),
        "device": backend.device,
        "modelId": backend.model_id,
        "durationSec": duration,
        "firstPartialMs": round(first_partial_ms, 1) if first_partial_ms is not None else None,
        "finalLatencyMs": round(final_latency_ms, 1),
        "latencyMs": round(processing_time * 1000, 1),
        "rtf": round(processing_time / duration, 4) if duration else None,
    }


async def run_nano_case(
    backend: Any,
    *,
    case: dict[str, Any],
    wav_path: Path,
    duration: float,
) -> dict[str, Any]:
    started = time.perf_counter()
    result = await backend.transcribe_final(str(wav_path))
    final_latency_ms = (time.perf_counter() - started) * 1000
    processing_time = float(result.get("processing_time") or 0.0)
    return {
        **case,
        "transcript": str(result.get("text") or ""),
        "device": backend.device,
        "modelId": backend.model_id,
        "durationSec": duration,
        "firstPartialMs": None,
        "finalLatencyMs": round(final_latency_ms, 1),
        "latencyMs": round(processing_time * 1000, 1),
        "rtf": round(processing_time / duration, 4) if duration else None,
    }


async def run_scenario(name: str, manifest_path: Path) -> dict[str, Any]:
    import sys

    sys.path.insert(0, str(ROOT / "voice"))
    from funasr_backends import FunASRNanoBackend, ParaformerStreamingBackend

    if name == "fun-asr-nano-gpu":
        backend = FunASRNanoBackend(str(ROOT / "models" / "fun-asr-nano"))
    elif name in {"paraformer-cpu", "paraformer-gpu"}:
        backend = ParaformerStreamingBackend(
            str(ROOT / "models" / "paraformer-streaming"),
            device="cpu" if name.endswith("cpu") else "cuda",
        )
    else:
        raise ValueError(f"Unknown scenario: {name}")

    manifest = json.loads(manifest_path.read_text("utf-8"))
    sampler = ResourceSampler()
    sampler.start()
    load_started = time.perf_counter()
    try:
        await backend.load()
        load_ms = (time.perf_counter() - load_started) * 1000
        rows = []
        for item in manifest:
            wav_path = (manifest_path.parent / item["file"]).resolve()
            pcm, duration = load_pcm16_mono(wav_path)
            case = {key: value for key, value in item.items() if key != "file"}
            if name == "fun-asr-nano-gpu":
                row = await run_nano_case(
                    backend,
                    case=case,
                    wav_path=wav_path,
                    duration=duration,
                )
            else:
                row = await run_paraformer_case(
                    backend,
                    case=case,
                    pcm=pcm,
                    duration=duration,
                )
            rows.append(row)
        return {
            "scenario": name,
            "status": "passed",
            "deploymentPolicyChanged": False,
            "loadMs": round(load_ms, 1),
            "rows": rows,
            "resources": sampler.stop(),
        }
    except Exception as error:
        return {
            "scenario": name,
            "status": "failed",
            "deploymentPolicyChanged": False,
            "errorType": type(error).__name__,
            "message": str(error),
            "resources": sampler.stop(),
        }
    finally:
        await backend.unload()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one isolated ASR benchmark scenario.")
    parser.add_argument(
        "scenario",
        choices=("fun-asr-nano-gpu", "paraformer-cpu", "paraformer-gpu"),
    )
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = asyncio.run(run_scenario(args.scenario, args.manifest.resolve()))
    output = args.output or ROOT / "benchmarks" / f"{args.scenario}.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
