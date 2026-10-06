import hashlib
import json
from pathlib import Path

import pytest

from tools.assets.restore_runtime_assets import restore


def entry(name, data):
    return {'path': name, 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


def fixture(root, files, assembled):
    (root / 'configs/assets').mkdir(parents=True)
    for name, data in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    (root / 'configs/assets/runtime-assets.json').write_text(json.dumps({
        'files': [entry(n, d) for n, d in files.items()], 'assembledFiles': assembled,
    }))


def test_restores_large_weight_in_a_new_directory_and_is_idempotent(tmp_path):
    parts = {'local/models/test.pt.parts/000': b'first',
             'local/models/test.pt.parts/001': b'second'}
    assembled = {**entry('local/models/test.pt', b'firstsecond'), 'parts': list(parts)}
    fixture(tmp_path, parts, [assembled])
    assert restore(tmp_path)['assembledFiles'] == 1
    assert (tmp_path / 'local/models/test.pt').read_bytes() == b'firstsecond'
    restore(tmp_path)


def test_rejects_corrupt_parts_before_creating_weight(tmp_path):
    fixture(tmp_path, {'part': b'original'}, [])
    (tmp_path / 'part').write_bytes(b'corrupt!')
    with pytest.raises(ValueError, match='SHA-256'):
        restore(tmp_path)


def test_rejects_paths_outside_clone(tmp_path):
    fixture(tmp_path, {}, [])
    manifest = tmp_path / 'configs/assets/runtime-assets.json'
    manifest.write_text(json.dumps({'files': [entry('../outside', b'bad')],
                                    'assembledFiles': []}))
    with pytest.raises(ValueError):
        restore(tmp_path)
