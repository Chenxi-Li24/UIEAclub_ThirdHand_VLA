#!/usr/bin/env python3
"""Verify recorded source hashes without writing to the source repository."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys


SDK_ROOT = Path(__file__).resolve().parents[1]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify(source_root: Path) -> tuple[str, ...]:
    payload = json.loads((SDK_ROOT / "SOURCE_MAP.json").read_text(encoding="utf-8"))
    failures = []
    for record in payload["records"]:
        relative = Path(record["source_path"])
        if relative.is_absolute() or ".." in relative.parts:
            failures.append(f"invalid source path: {relative}")
            continue
        source = source_root / relative
        if not source.is_file():
            failures.append(f"missing source: {relative}")
            continue
        actual = sha256_file(source)
        if actual != record["source_sha256"]:
            failures.append(f"source changed: {relative}")
    return tuple(failures)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    arguments = parser.parse_args()
    failures = verify(arguments.source_root.resolve())
    if failures:
        for failure in failures:
            print(failure, file=sys.stderr)
        return 1
    print("all selected source files match recorded SHA-256 values")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

