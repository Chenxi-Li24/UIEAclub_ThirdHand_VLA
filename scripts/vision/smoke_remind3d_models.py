#!/usr/bin/env python3
"""Run a fail-closed RTMDet plus DINO model smoke test without robot access."""

from __future__ import annotations

import argparse
import json
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


def run_model_smoke(arguments: argparse.Namespace) -> dict[str, Any]:
    import cv2
    import numpy as np
    import torch

    from vision_models.dino import DinoMaskEncoder
    from vision_models.rtmdet import RTMDetInstanceSegmenter

    config = load_remind3d_config(arguments.config)
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is unavailable in the REMIND-3D model environment")
    capability = torch.cuda.get_device_capability()
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
        device=arguments.device,
        min_score=arguments.min_score,
    )
    encoder = DinoMaskEncoder(
        model_id=arguments.descriptor_model or config.fallback_descriptor,
        device=arguments.device,
        min_patch_coverage=arguments.min_patch_coverage,
        max_long_side=config.dino_max_long_side,
    )

    torch.cuda.reset_peak_memory_stats()
    latencies_ms = []
    detection_count = 0
    descriptors = ()
    for iteration in range(arguments.iterations + 1):
        torch.cuda.synchronize()
        started = time.perf_counter()
        detections = segmenter.predict(image_rgb)
        if not detections:
            raise RuntimeError("RTMDet smoke inference returned no instance masks")
        descriptors = encoder.encode(image_rgb, [item.mask for item in detections])
        torch.cuda.synchronize()
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
    peak_memory_gib = torch.cuda.max_memory_allocated() / 1024**3
    if peak_memory_gib > config.gpu_memory_limit_gib:
        raise RuntimeError(
            f"GPU peak {peak_memory_gib:.3f} GiB exceeds {config.gpu_memory_limit_gib:.3f} GiB"
        )
    latency_p50, latency_p95 = np.percentile(np.asarray(latencies_ms), [50, 95])
    return {
        "capability": list(capability),
        "descriptor_count": len(descriptors),
        "descriptor_dimension": int(descriptors[0].shape[0]),
        "descriptor_model": arguments.descriptor_model or config.fallback_descriptor,
        "descriptor_norm_min": min(descriptor_norms),
        "descriptor_norm_max": max(descriptor_norms),
        "detection_count": detection_count,
        "device": arguments.device,
        "gpu": torch.cuda.get_device_name(),
        "gpu_peak_gib": peak_memory_gib,
        "latency_p50_ms": float(latency_p50),
        "latency_p95_ms": float(latency_p95),
        "robot_execution_enabled": False,
        "smoke_passed": True,
        "supported_architectures": list(supported_architectures),
        "torch": torch.__version__,
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
