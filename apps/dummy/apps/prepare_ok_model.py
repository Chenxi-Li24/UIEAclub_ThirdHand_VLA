"""Prepare pinned palm gesture/pose checkpoints; no cameras or SDK are run."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from dummy.config import APP_ROOT, resolve_project_path


def prepare_model(manifest_name):
    manifest = json.loads((APP_ROOT / 'configs' / manifest_name).read_text())
    destination = resolve_project_path(manifest['path'])
    def valid(path):
        if not path.is_file() or path.stat().st_size != manifest['bytes']:
            return False
        with path.open('rb') as handle:
            return hashlib.file_digest(handle, 'sha256').hexdigest() == manifest['sha256']
    if valid(destination):
        print('Gesture model verified:', destination)
        return
    if destination.exists():
        raise RuntimeError('Existing model failed validation; it was not overwritten')
    destination.parent.mkdir(parents=True, exist_ok=True)
    output = tempfile.NamedTemporaryFile(mode='wb', prefix=destination.name+'.',
                                         suffix='.download', dir=destination.parent, delete=False)
    temporary = Path(output.name)
    try:
        with output, urllib.request.urlopen(manifest['url'], timeout=60) as response:
            total = 0
            while chunk := response.read(1024*1024):
                total += len(chunk)
                if total > manifest['bytes']:
                    raise RuntimeError('Checkpoint exceeds manifest size')
                output.write(chunk)
        if not valid(temporary):
            raise RuntimeError('Downloaded checkpoint hash/size mismatch')
        # No overwrite even if another preparer creates the final path meanwhile.
        import os
        os.link(temporary, destination)
        print('Gesture model prepared:', destination)
    finally:
        temporary.unlink(missing_ok=True)


def prepare():
    for manifest_name in ('ok-gesture-model.json', 'ok-pose-model.json'):
        prepare_model(manifest_name)


if __name__ == '__main__':
    prepare()
