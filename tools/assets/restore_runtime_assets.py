#!/usr/bin/env python3
"""Verify tracked payloads and reconstruct split weights; never touches hardware."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import os
import tempfile


def safe_path(root: Path, name: str) -> Path:
    path = (root / name).resolve()
    path.relative_to(root.resolve())
    return path


def verify(path: Path, entry: dict) -> None:
    if not path.is_file():
        raise FileNotFoundError(f'{path}: missing asset; run git lfs pull')
    if path.stat().st_size != entry['size']:
        raise ValueError(f'{path}: size mismatch; run git lfs pull if this is a pointer')
    with path.open('rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != entry['sha256']:
            raise ValueError(f'{path}: SHA-256 mismatch')


def restore(root: Path, *, assemble: bool = True) -> dict:
    manifest = json.loads((root / 'configs/assets/runtime-assets.json').read_text())
    for entry in manifest['files']:
        verify(safe_path(root, entry['path']), entry)
    for entry in manifest['assembledFiles']:
        target = safe_path(root, entry['path'])
        if target.exists():
            verify(target, entry)
        elif assemble:
            target.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(dir=target.parent, prefix='.assemble-')
            try:
                with os.fdopen(fd, 'wb') as output:
                    for name in entry['parts']:
                        with safe_path(root, name).open('rb') as incoming:
                            while block := incoming.read(8 * 1024 * 1024):
                                output.write(block)
                verify(Path(temporary), entry)
                os.replace(temporary, target)
            finally:
                Path(temporary).unlink(missing_ok=True)
    return {'verifiedFiles': len(manifest['files']),
            'assembledFiles': len(manifest['assembledFiles']) if assemble else 0}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--verify-only', action='store_true')
    args = parser.parse_args()
    print(json.dumps(restore(args.root, assemble=not args.verify_only)))
