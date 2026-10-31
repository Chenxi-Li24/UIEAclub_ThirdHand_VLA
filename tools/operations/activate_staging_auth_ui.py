"""Apply the reviewed three-file auth UI update to the existing staging runtime."""
from datetime import datetime, timezone
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
from activate_staging_smtp import run, protected, private_write, select_release, health, request, BASE

OLD = BASE / 'releases/5728c3201df4b33d'
BACKUP = Path('/var/backups/thirdhand/access-C2d-auth-ui-20261030')
ENV = Path('/etc/thirdhand-stage/cloud.env')
CHANGES = {'apps/web/public/js/auth-page.js', 'apps/web/public/css/auth.css', 'apps/web/public/js/i18n-auth-catalog.js'}


def verify_files(path, manifest):
    assert all(not item.is_symlink() for item in path.rglob('*'))
    assert {item.relative_to(path).as_posix() for item in path.rglob('*') if item.is_file()} == set(manifest['files']) | {'manifest.json'}
    assert all(hashlib.sha256((path / name).read_bytes()).hexdigest() == digest for name, digest in manifest['files'].items())


def main():
    assert os.geteuid() == 0 and os.uname().sysname == 'Linux'
    assert not (BACKUP / 'activation.json').exists()
    assert (BASE / 'current').resolve() == OLD
    original_env = protected(ENV)
    main_index = Path('/www/wwwroot/uiea-thirdhand-static/index.html')
    main_hash = hashlib.sha256(main_index.read_bytes()).hexdigest()
    assert main_hash == '639bb62379c763ebbd4610125cafc3ebff3aa14debb0c3ca2f50ee75d1a478bd'
    delta = json.loads(protected(BACKUP / 'release-delta.json'))
    old_bytes = (OLD / 'manifest.json').read_bytes()
    assert hashlib.sha256(old_bytes).hexdigest() == delta['baseManifestSha256']
    manifest = json.loads(old_bytes)
    verify_files(OLD, manifest)
    assert set(delta['files']) == CHANGES
    assert re.fullmatch('[a-f0-9]{64}', delta['nextArchiveSha256'])
    release = BASE / 'releases' / delta['nextArchiveSha256'][:16]
    if (BACKUP / 'cloud.env.before').exists():
        assert protected(BACKUP / 'cloud.env.before') == original_env
        assert protected(BACKUP / 'previous-release.txt') == (str(OLD) + '\n').encode()
    else:
        private_write(BACKUP / 'cloud.env.before', original_env)
        private_write(BACKUP / 'previous-release.txt', (str(OLD) + '\n').encode())
    if not release.exists():
        shutil.copytree(OLD, release)
        for name, encoded in delta['files'].items():
            data = base64.b64decode(encoded, validate=True)
            assert hashlib.sha256(data).hexdigest() == delta['fileHashes'][name]
            (release / name).write_bytes(data)
    for name in CHANGES:
        manifest['files'][name] = delta['fileHashes'][name]
    assert delta['manifestNewline'] in ('\n', '\r\n')
    new_bytes = (json.dumps(manifest, indent=2, sort_keys=True) + '\n').replace('\n', delta['manifestNewline']).encode()
    assert hashlib.sha256(new_bytes).hexdigest() == delta['nextManifestSha256']
    if (release / 'manifest.json').read_bytes() != new_bytes:
        assert (release / 'manifest.json').read_bytes() == old_bytes
        (release / 'manifest.json').write_bytes(new_bytes)
    verify_files(release, manifest)
    switched = False
    try:
        select_release(release)
        switched = True
        run(['systemctl', 'restart', 'thirdhand-stage.service', 'thirdhand-stage-export.service'])
        health()
        for path in ['/login', '/register', '/verify-email']:
            assert request(path)[0] == 200
        for name in CHANGES:
            status, body = request('/control-assets/' + name.removeprefix('apps/web/public/'))
            assert status == 200 and hashlib.sha256(body).hexdigest() == delta['fileHashes'][name]
        assert request('/ws')[0] == request('/voice')[0] == request('/vision')[0] == 404
        assert request('/', host='uiea-thirdhand.com')[0] == 200
        assert hashlib.sha256(main_index.read_bytes()).hexdigest() == main_hash
        assert protected(ENV) == original_env
        report = {'success': True, 'checkedAt': datetime.now(timezone.utc).isoformat(), 'stagingOnly': True,
                  'release': str(release), 'canonicalArchiveSha256': delta['nextArchiveSha256'],
                  'manifestSha256': delta['nextManifestSha256'], 'manifestFilesVerified': len(manifest['files']),
                  'assembledFromVerifiedBaseAndThreeSourceFiles': True, 'publicAssetsHashMatched': True,
                  'smtpConfigurationUnchanged': True, 'controlAvailable': False, 'originalShowcaseUnchanged': True}
        private_write(BACKUP / 'activation.json', json.dumps(report, indent=2).encode())
        print(json.dumps(report, indent=2), flush=True)
    except Exception:
        if switched:
            select_release(OLD)
            run(['systemctl', 'restart', 'thirdhand-stage.service', 'thirdhand-stage-export.service'])
            health()
            print('AUTH_UI_ROLLED_BACK', flush=True)
        raise


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('AUTH_UI_ACTIVATION_FAILED ' + type(error).__name__, flush=True)
        raise SystemExit(1) from None
