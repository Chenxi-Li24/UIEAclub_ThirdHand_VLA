#!/usr/bin/env python3
"""Import the verified Startouch web geometry into the project-local asset mount."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import tempfile

from tools.assets.verify_assets import sha256_path, size_path


ASSET_ID = "robot.startouch-v3.geometry"
DESTINATION = Path("assets/robot/startouch-v3")


def prepare(project_root: Path, source: Path, manifest_path: Path) -> dict[str, object]:
    root = project_root.resolve()
    source = source.resolve()
    manifest = json.loads(manifest_path.resolve().read_text(encoding="utf-8"))
    expected = next(
        (item for item in manifest.get("assets", []) if item.get("id") == ASSET_ID),
        None,
    )
    if expected is None:
        raise ValueError(f"asset {ASSET_ID} is absent from {manifest_path}")
    if not source.is_dir():
        return {"status": "source_missing", "source": str(source)}

    actual_hash = sha256_path(source)
    actual_size = size_path(source)
    if actual_hash != expected.get("sha256") or actual_size != expected.get("sizeBytes"):
        return {
            "status": "source_mismatch",
            "actualSha256": actual_hash,
            "actualSizeBytes": actual_size,
        }

    destination = (root / DESTINATION).resolve()
    assets_root = (root / "assets" / "robot").resolve()
    destination.relative_to(assets_root)
    if destination.exists():
        destination_hash = sha256_path(destination)
        destination_size = size_path(destination)
        status = (
            "already_present"
            if destination_hash == actual_hash and destination_size == actual_size
            else "destination_conflict"
        )
        return {
            "status": status,
            "destination": str(destination),
            "actualSha256": destination_hash,
            "actualSizeBytes": destination_size,
        }

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".startouch-v3.", dir=destination.parent))
    payload = temporary / destination.name
    try:
        shutil.copytree(source, payload)
        if sha256_path(payload) != actual_hash or size_path(payload) != actual_size:
            return {"status": "copy_mismatch"}
        os.replace(payload, destination)
    finally:
        shutil.rmtree(temporary, ignore_errors=True)
    return {
        "status": "imported",
        "destination": str(destination),
        "sha256": actual_hash,
        "sizeBytes": actual_size,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = prepare(args.project_root, args.source, args.manifest)
    print(json.dumps(result, ensure_ascii=True) if args.json else result["status"])
    return 0 if result["status"] in {"imported", "already_present"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
