#!/usr/bin/env python3
"""Export working runtime assets into a clone without environments or credentials."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil

CHUNK_SIZE = 1_000_000_000
SKIP = {'.git', '.gitignore', '.gitattributes', '.env', 'api_keys.yaml', '__pycache__', '.pytest_cache',
        '.cache', '.locks', '.DS_Store', 'build', 'dist', '*.egg-info'}


def digest(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def export(source: Path, destination: Path, funasr: Path | None = None) -> dict:
    source, destination = source.resolve(), destination.resolve()
    if source == destination:
        raise ValueError('source and destination must differ')
    entries, assembled = [], []

    def copy_file(src: Path, relative: Path) -> None:
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        size = src.stat().st_size
        if size > 2_000_000_000:
            parts = []
            with src.open('rb') as incoming:
                index = 0
                while data := incoming.read(CHUNK_SIZE):
                    part = relative.parent / (relative.name + '.parts') / f'{index:03d}'
                    out = destination / part
                    out.parent.mkdir(parents=True, exist_ok=True)
                    if out.exists() and digest(out) != hashlib.sha256(data).hexdigest():
                        raise FileExistsError(out)
                    if not out.exists():
                        out.write_bytes(data)
                    entries.append({'path': part.as_posix(), 'size': len(data),
                                    'sha256': digest(out)})
                    parts.append(part.as_posix())
                    index += 1
            assembled.append({'path': relative.as_posix(), 'size': size,
                              'sha256': digest(src), 'parts': parts})
            return
        if target.exists():
            if size != target.stat().st_size or digest(src) != digest(target):
                raise FileExistsError(f'asset conflict: {target}')
        else:
            shutil.copy2(src, target, follow_symlinks=True)
        entries.append({'path': relative.as_posix(), 'size': size, 'sha256': digest(target)})

    def tree(src: Path, relative: Path, snapshots_only: bool = False) -> None:
        if not src.is_dir():
            raise FileNotFoundError(src)
        for path in sorted(src.rglob('*')):
            sub = path.relative_to(src)
            if any(p in SKIP or p.endswith('.egg-info') or p.startswith('build-py')
                   for p in sub.parts):
                continue
            if not path.is_file() or path.suffix in {'.pyc', '.pyo'}:
                continue
            if snapshots_only:
                if 'snapshots' not in sub.parts and 'refs' not in sub.parts:
                    continue
                if path.name in {'pytorch_model.bin', 'sam2.1_hiera_tiny.pt'}:
                    continue  # Transformers uses the pinned safetensors weights.
            copy_file(path, relative / sub)

    for name in ('assets/robot/startouch-v3', 'local/sdk/startouch', 'local/sdk/xvisio',
                 'local/generated/startouch-python', 'local/models/asr'):
        tree(source / name, Path(name))
    tree(source / 'local/models/vision/huggingface',
         Path('local/models/vision/huggingface'), snapshots_only=True)
    copy_file(source / 'apps/dummy/models/blaze_face_short_range.tflite',
              Path('apps/dummy/models/blaze_face_short_range.tflite'))
    yolo = source / 'local/models/vision/yolov8n.pt'
    if yolo.exists():
        copy_file(yolo, Path('local/models/vision/yolov8n.pt'))
    yunet = source / 'local/models/vision/face_detection_yunet_2026may.onnx'
    if yunet.exists():
        copy_file(yunet, Path('local/models/vision/face_detection_yunet_2026may.onnx'))
    tree(funasr or source / 'local/vendor/funasr', Path('local/vendor/funasr'))
    report = {'schemaVersion': 1, 'platform': 'linux-x86_64',
              'pythonVersion': '3.11', 'files': entries, 'assembledFiles': assembled}
    manifest = destination / 'configs/assets/runtime-assets.json'
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--funasr-source', type=Path)
    args = parser.parse_args()
    report = export(args.source, args.destination, args.funasr_source)
    print(json.dumps({'files': len(report['files']),
                      'sizeBytes': sum(f['size'] for f in report['files']),
                      'assembledFiles': len(report['assembledFiles'])}))
