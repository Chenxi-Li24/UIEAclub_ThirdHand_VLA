"""Freeze exact binary bytes for the C4 showcase-entry/CSV-only deployment."""
import base64
import gzip
import hashlib
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PLAN = REPO / '.superpowers/sdd/2026-10-30-public-access-rollout'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def encoded(data):
    return base64.b64encode(data).decode('ascii')


def main():
    previous = json.loads(gzip.decompress((PLAN / 'C3a-visible-controls.delta.json.gz').read_bytes()))
    manifest_bytes = (PLAN / 'C2-release/manifest.json').read_bytes()
    files = json.loads(manifest_bytes)['files']
    before = previous['manifest']['files']
    changed = {name for name in files if before.get(name) != files[name]}
    assert len(changed) == 6
    archive_sha = sha((PLAN / 'C2-staging-release.tar.gz').read_bytes())
    site = REPO / 'showcase/dist'
    javascript = list((site / 'assets').glob('*.js'))
    assert len(javascript) == 1
    index, js = (site / 'index.html').read_bytes(), javascript[0].read_bytes()
    baseline = PLAN / 'showcase-baseline'
    package = {'archiveSha256': archive_sha, 'manifestSha256': sha(manifest_bytes),
               'manifestBase64': encoded(manifest_bytes), 'oldManifestSha256': previous['manifestSha256'],
               'changes': {name: encoded((PLAN / 'C2-release' / name).read_bytes()) for name in sorted(changed)},
               'showcase': {'oldIndexSha256': sha((baseline / 'online-index.html').read_bytes()),
                            'oldJsPath': 'assets/index-CL3W_Xbj.js', 'oldJsSha256': sha((baseline / 'online-index.js').read_bytes()),
                            'cssPath': 'assets/index-DwGmTHpk.css', 'cssSha256': sha((baseline / 'online-index.css').read_bytes()),
                            'indexBase64': encoded(index), 'indexSha256': sha(index),
                            'jsPath': javascript[0].relative_to(site).as_posix(), 'jsBase64': encoded(js), 'jsSha256': sha(js)}}
    assert all(sha(base64.b64decode(value)) == files[name] for name, value in package['changes'].items())
    output = PLAN / 'C4-showcase-tables.delta.json.gz'
    output.write_bytes(gzip.compress(json.dumps(package, separators=(',', ':')).encode(), mtime=0))
    report = {'package': str(output), 'bytes': output.stat().st_size, 'sha256': sha(output.read_bytes()),
              'release': archive_sha[:16], 'manifestSha256': package['manifestSha256'],
              'changes': sorted(changed), 'showcaseJs': package['showcase']['jsPath'],
              'newIndexSha256': package['showcase']['indexSha256']}
    (PLAN / 'C4-frozen-artifacts.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report))


if __name__ == '__main__':
    main()
