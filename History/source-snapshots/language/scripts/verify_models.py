#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REQUIRED_FILES = {
    "whisper-small": ("model.bin", "config.json", "tokenizer.json"),
    "paraformer-streaming": ("model.pt",),
    "fun-asr-nano": ("model.pt",),
}


def main() -> int:
    models: dict[str, dict[str, object]] = {}
    ok = True
    for model_name, filenames in REQUIRED_FILES.items():
        model_root = PROJECT_ROOT / "models" / model_name
        missing = [name for name in filenames if not (model_root / name).is_file()]
        models[model_name] = {
            "path": str(model_root),
            "present": model_root.is_dir() and not missing,
            "missing": missing,
        }
        ok = ok and bool(models[model_name]["present"])
    print(json.dumps({"ok": ok, "models": models}, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
