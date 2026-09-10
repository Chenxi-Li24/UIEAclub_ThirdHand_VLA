#!/usr/bin/env python3
"""Explicitly copy verified assets into the project's ignored local tree."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from tools.assets.verify_assets import sha256_path


def _inside(root: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(root)
        return True
    except ValueError:
        return False


def import_asset(
    source: Path,
    destination: Path,
    *,
    project_root: Path,
    expected_sha256: str,
) -> dict[str, Any]:
    """Copy one asset after validation; never overwrite differing content."""
    root = project_root.resolve()
    local_root = (root / "local").resolve()
    source = source.resolve()
    destination = destination.resolve()
    expected = expected_sha256.lower()

    if not _inside(local_root, destination):
        raise ValueError(f"destination must be inside {local_root}")
    if not source.exists():
        return {"status": "source_missing", "source": str(source)}

    source_hash = sha256_path(source)
    if source_hash != expected:
        return {"status": "source_hash_mismatch", "actualSha256": source_hash}

    if destination.exists():
        destination_hash = sha256_path(destination)
        status = "already_present" if destination_hash == expected else "destination_conflict"
        return {"status": status, "actualSha256": destination_hash}

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{destination.name}.import-", dir=destination.parent)
    )
    payload = temporary / destination.name
    try:
        if source.is_dir():
            shutil.copytree(source, payload)
        else:
            shutil.copy2(source, payload)
        copied_hash = sha256_path(payload)
        if copied_hash != expected:
            return {"status": "copy_hash_mismatch", "actualSha256": copied_hash}
        os.replace(payload, destination)
        return {"status": "imported", "sha256": copied_hash, "destination": str(destination)}
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = import_asset(
        args.source,
        args.destination,
        project_root=args.project_root,
        expected_sha256=args.sha256,
    )
    print(json.dumps(result, ensure_ascii=True) if args.json else result["status"])
    return 0 if result["status"] in {"imported", "already_present"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
