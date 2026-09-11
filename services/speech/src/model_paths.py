from __future__ import annotations

from pathlib import Path


MODEL_PATHS = {
    "whisper-small": Path("local/models/asr/medium"),
    "paraformer-streaming": Path("local/models/asr/realtime"),
    "fun-asr-nano": Path("local/models/asr/high"),
}


def build_model_paths(repo_root: Path) -> dict[str, Path]:
    root = repo_root.expanduser().resolve()
    return {
        model_id: (root / relative_path).resolve()
        for model_id, relative_path in MODEL_PATHS.items()
    }
