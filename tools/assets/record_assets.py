#!/usr/bin/env python3
"""Measure present local assets and atomically record their size and hash."""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from tools.assets.verify_assets import sha256_path, size_path


def _inside(root: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(root)
        return True
    except ValueError:
        return False


def record_manifest(
    project_root: Path,
    template_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    """Measure existing assets and atomically write a new manifest."""
    root = project_root.resolve()
    document = deepcopy(json.loads(template_path.read_text(encoding="utf-8")))
    document["generatedAt"] = datetime.now(timezone.utc).isoformat()
    document["hashAlgorithm"] = "thirdhand-directory-sha256-v1"

    for asset in document.get("assets", []):
        relative = Path(asset["relativePath"])
        candidate = (root / relative).resolve()
        if relative.is_absolute() or not _inside(root, candidate):
            raise ValueError(f"asset path resolves outside project root: {relative}")
        if candidate.exists():
            asset["sizeBytes"] = size_path(candidate)
            asset["sha256"] = sha256_path(candidate)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{output_path.name}.", dir=output_path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(document, stream, ensure_ascii=True, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, output_path)
    finally:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
    return document


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    document = record_manifest(args.project_root, args.template, args.output)
    print(f"recorded {len(document.get('assets', []))} assets in {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
