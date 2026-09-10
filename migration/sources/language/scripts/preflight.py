#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.metadata
import json
from pathlib import Path
import socket
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODEL_REQUIRED_FILES = {
    "whisper-small": ("model.bin", "config.json", "tokenizer.json"),
    "paraformer-streaming": ("model.pt",),
    "fun-asr-nano": ("model.pt",),
}


def collect_static_errors(
    root: Path,
    model_paths: dict[str, Path],
) -> list[str]:
    root = root.resolve()
    errors: list[str] = []
    for model_name, path_value in model_paths.items():
        required_files = MODEL_REQUIRED_FILES[model_name]
        path = path_value.resolve()
        try:
            path.relative_to(root)
        except ValueError:
            errors.append(f"MODEL_PATH_ESCAPE:{model_name}")
            continue
        if not path.is_dir() or any(
            not (path / filename).is_file() for filename in required_files
        ):
            errors.append(f"MODEL_MISSING:{model_name}")
    return errors


def port_available(host: str, port: int) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind((host, port))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def runtime_errors(
    root: Path,
    *,
    check_ports: bool = True,
    voice_host: str = "127.0.0.1",
    voice_port: int = 3004,
    web_host: str = "127.0.0.1",
    web_port: int = 9983,
) -> list[str]:
    errors = collect_static_errors(
        root,
        {
            model_name: root / "models" / model_name
            for model_name in MODEL_REQUIRED_FILES
        },
    )
    if Path(sys.prefix).resolve() != (root / "runtime" / "python").resolve():
        errors.append("BUNDLED_PYTHON_MISMATCH")
    if not (root / "runtime" / "node" / "bin" / "node").is_file():
        errors.append("BUNDLED_NODE_MISSING")
    try:
        if importlib.metadata.version("vllm") != "0.19.1":
            errors.append("VLLM_VERSION_MISMATCH")
    except importlib.metadata.PackageNotFoundError:
        errors.append("VLLM_MISSING")
    try:
        import torch
        if not torch.cuda.is_available():
            errors.append("CUDA_UNAVAILABLE")
    except Exception:
        errors.append("CUDA_UNAVAILABLE")
    if check_ports:
        if not port_available(voice_host, voice_port):
            errors.append(f"PORT_BUSY:{voice_port}")
        if not port_available(web_host, web_port):
            errors.append(f"PORT_BUSY:{web_port}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the isolated ASR V2 runtime.")
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--skip-port-check", action="store_true")
    parser.add_argument("--voice-host", default="127.0.0.1")
    parser.add_argument("--voice-port", type=int, default=3004)
    parser.add_argument("--web-host", default="127.0.0.1")
    parser.add_argument("--web-port", type=int, default=9983)
    args = parser.parse_args()
    root = args.project_root.resolve()
    errors = runtime_errors(
        root,
        check_ports=not args.skip_port_check,
        voice_host=args.voice_host,
        voice_port=args.voice_port,
        web_host=args.web_host,
        web_port=args.web_port,
    )
    payload = {"ok": not errors, "projectRoot": str(root), "errors": errors}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
