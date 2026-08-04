#!/usr/bin/env python3
"""Run a fail-closed RTMDet plus DINO model smoke test without robot access."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[2]
SERVER = ROOT / "web-control/server"
if str(SERVER) not in sys.path:
    sys.path.insert(0, str(SERVER))

from vision_models.offline_replay import load_remind3d_config  # noqa: E402


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def check_config(path: Path) -> dict[str, Any]:
    config = load_remind3d_config(path)
    return {
        "canonical_image": config.canonical_image,
        "config_valid": True,
        "detector_backend": config.detector_backend,
        "fallback_descriptor": config.fallback_descriptor,
        "robot_execution_enabled": config.robot_execution_enabled,
    }


def evaluate_smoke_limits(
    latencies_ms: Sequence[float],
    allocated_memory_gib: float,
    reserved_memory_gib: float,
    latency_p95_limit_ms: float,
    gpu_memory_limit_gib: float,
) -> dict[str, float]:
    import numpy as np

    values = np.asarray(latencies_ms, dtype=float)
    memory_values = np.asarray(
        [allocated_memory_gib, reserved_memory_gib],
        dtype=float,
    )
    limits = np.asarray([latency_p95_limit_ms, gpu_memory_limit_gib], dtype=float)
    if (
        values.ndim != 1
        or len(values) == 0
        or not np.isfinite(values).all()
        or np.any(values < 0.0)
    ):
        raise RuntimeError("smoke latencies must be finite non-negative values")
    if not np.isfinite(memory_values).all() or np.any(memory_values < 0.0):
        raise RuntimeError("GPU smoke memory values must be finite and non-negative")
    if not np.isfinite(limits).all() or np.any(limits <= 0.0):
        raise RuntimeError("smoke limits must be finite and positive")
    latency_p50, latency_p95 = np.percentile(values, [50, 95])
    peak_memory_gib = float(np.max(memory_values))
    if latency_p95 > latency_p95_limit_ms:
        raise RuntimeError(
            f"latency p95 {latency_p95:.3f} ms exceeds "
            f"{latency_p95_limit_ms:.3f} ms"
        )
    if peak_memory_gib > gpu_memory_limit_gib:
        raise RuntimeError(
            f"GPU reserved/allocated peak {peak_memory_gib:.3f} GiB exceeds "
            f"{gpu_memory_limit_gib:.3f} GiB"
        )
    return {
        "gpu_peak_allocated_gib": float(allocated_memory_gib),
        "gpu_peak_reserved_gib": float(reserved_memory_gib),
        "gpu_peak_gib": peak_memory_gib,
        "latency_p50_ms": float(latency_p50),
        "latency_p95_ms": float(latency_p95),
    }


def _cuda_device_index(value: str) -> int:
    match = re.fullmatch(r"cuda(?::(0|[1-9][0-9]*))?", str(value).strip())
    if match is None:
        raise RuntimeError("model smoke requires a CUDA device such as cuda:0")
    return 0 if match.group(1) is None else int(match.group(1))


def run_model_smoke(arguments: argparse.Namespace) -> dict[str, Any]:
    import cv2
    import numpy as np
    import torch

    from vision_models.dino import DinoMaskEncoder
    from vision_models.rtmdet import RTMDetInstanceSegmenter

    config = load_remind3d_config(arguments.config)
    device_index = _cuda_device_index(arguments.device)
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is unavailable in the REMIND-3D model environment")
    if device_index >= torch.cuda.device_count():
        raise RuntimeError(
            f"CUDA device index {device_index} is unavailable; "
            f"device_count={torch.cuda.device_count()}"
        )
    torch.cuda.set_device(device_index)
    model_device = f"cuda:{device_index}"
    capability = torch.cuda.get_device_capability(device_index)
    architecture = f"sm_{capability[0]}{capability[1]}"
    supported_architectures = tuple(torch.cuda.get_arch_list())
    if architecture not in supported_architectures:
        raise RuntimeError(
            f"PyTorch build does not support GPU architecture {architecture}: "
            f"{supported_architectures}"
        )
    image_bgr = cv2.imread(str(arguments.image), cv2.IMREAD_COLOR)
    if image_bgr is None:
        raise RuntimeError(f"cannot read smoke image: {arguments.image}")
    image_rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
    labels = tuple(label.strip() for label in arguments.labels.split(",") if label.strip())
    if not labels:
        raise RuntimeError("--labels must contain at least one class name")

    segmenter = RTMDetInstanceSegmenter(
        config_path=arguments.detector_config,
        checkpoint_path=arguments.detector_checkpoint,
        labels=labels,
        device=model_device,
        min_score=arguments.min_score,
    )
    encoder = DinoMaskEncoder(
        model_id=arguments.descriptor_model or config.fallback_descriptor,
        device=model_device,
        min_patch_coverage=arguments.min_patch_coverage,
        max_long_side=config.dino_max_long_side,
    )

    torch.cuda.reset_peak_memory_stats(device_index)
    latencies_ms = []
    detection_count = 0
    descriptors = ()
    for iteration in range(arguments.iterations + 1):
        torch.cuda.synchronize(device_index)
        started = time.perf_counter()
        detections = segmenter.predict(image_rgb)
        if not detections:
            raise RuntimeError("RTMDet smoke inference returned no instance masks")
        descriptors = encoder.encode(image_rgb, [item.mask for item in detections])
        torch.cuda.synchronize(device_index)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        detection_count = len(detections)
        if iteration > 0:
            latencies_ms.append(elapsed_ms)
    if len(descriptors) != detection_count:
        raise RuntimeError("DINO descriptor count does not match RTMDet mask count")
    descriptor_norms = [float(np.linalg.norm(item)) for item in descriptors]
    if not descriptor_norms or not np.isfinite(descriptor_norms).all():
        raise RuntimeError("DINO returned missing or non-finite descriptors")
    if not np.allclose(descriptor_norms, 1.0, atol=1e-5):
        raise RuntimeError(f"DINO descriptors are not unit normalized: {descriptor_norms}")
    limit_metrics = evaluate_smoke_limits(
        latencies_ms,
        allocated_memory_gib=torch.cuda.max_memory_allocated(device_index) / 1024**3,
        reserved_memory_gib=torch.cuda.max_memory_reserved(device_index) / 1024**3,
        latency_p95_limit_ms=config.latency_p95_limit_ms,
        gpu_memory_limit_gib=config.gpu_memory_limit_gib,
    )
    return {
        "capability": list(capability),
        "descriptor_count": len(descriptors),
        "descriptor_dimension": int(descriptors[0].shape[0]),
        "descriptor_model": arguments.descriptor_model or config.fallback_descriptor,
        "descriptor_norm_min": min(descriptor_norms),
        "descriptor_norm_max": max(descriptor_norms),
        "detection_count": detection_count,
        "device": model_device,
        "gpu": torch.cuda.get_device_name(device_index),
        "robot_execution_enabled": False,
        "smoke_passed": True,
        "supported_architectures": list(supported_architectures),
        "torch": torch.__version__,
        **limit_metrics,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-config", type=Path)
    parser.add_argument("--config", type=Path, default=ROOT / "configs/vision/remind3d.yaml")
    parser.add_argument("--image", type=Path)
    parser.add_argument("--detector-config", type=Path)
    parser.add_argument("--detector-checkpoint", type=Path)
    parser.add_argument("--labels", default="")
    parser.add_argument("--descriptor-model")
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--min-score", type=float, default=0.35)
    parser.add_argument("--min-patch-coverage", type=float, default=0.10)
    parser.add_argument("--iterations", type=int, default=3)
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    if arguments.check_config is not None:
        print(json.dumps(check_config(arguments.check_config), sort_keys=True))
        return 0
    required = {
        "--image": arguments.image,
        "--detector-config": arguments.detector_config,
        "--detector-checkpoint": arguments.detector_checkpoint,
        "--output": arguments.output,
    }
    missing = [name for name, value in required.items() if value is None]
    if missing:
        raise SystemExit(f"model smoke requires: {', '.join(missing)}")
    if arguments.iterations < 1:
        raise SystemExit("--iterations must be at least one")
    report = run_model_smoke(arguments)
    write_json_atomic(arguments.output, report)
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
