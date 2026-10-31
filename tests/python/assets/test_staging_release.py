import importlib.util
from pathlib import Path


def test_private_key_filter_rejects_complete_keys_but_allows_parser_literals():
    root = Path(__file__).resolve().parents[3]
    spec = importlib.util.spec_from_file_location('staging_release', root / 'tools/deploy/build_staging_release.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert not module.contains_private_key(b'if (!pem.startsWith("-----BEGIN PRIVATE KEY-----")) throw new Error();')
    synthetic = b'-----BEGIN PRIVATE KEY-----\n' + b'A' * 64 + b'\n-----END PRIVATE KEY-----'
    assert module.contains_private_key(synthetic)
    assert module.contains_private_key(synthetic.replace(b'\n', b'\\n'))
