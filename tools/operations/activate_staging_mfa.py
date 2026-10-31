"""C2e offline QR and password-first UI; no owner enrollment or hardware access."""
from datetime import datetime, timezone
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
from activate_staging_smtp import run, protected, private_write, select_release, health, request, BASE
from activate_staging_auth_ui import verify_files

OLD = BASE / 'releases/5c595ee21f7b21a6'
BACKUP = Path('/var/backups/thirdhand/access-C2e-mfa-20261031')
CHANGES = {'apps/web/public/js/account-security.js', 'apps/web/public/js/i18n-cloud-catalog.js',
           'apps/web/public/css/cloud-workspace.css', 'platform/identity/src/accounts.js',
           'services/cloud-api/src/routes/session.js', 'services/cloud-api/src/workspace-pages.js',
           'apps/web/public/js/lib/qrcode-generator-2.0.4.js', 'apps/web/public/js/lib/qrcode-generator-2.0.4.LICENSE.txt'}


def main():
    assert os.geteuid() == 0 and os.uname().sysname == 'Linux'
    assert not (BACKUP / 'activation.json').exists()
    assert (BASE / 'current').resolve() == OLD
    env = protected(Path('/etc/thirdhand-stage/cloud.env'))
    index = Path('/www/wwwroot/uiea-thirdhand-static/index.html')
    main_hash = hashlib.sha256(index.read_bytes()).hexdigest()
    delta = json.loads(protected(BACKUP / 'release-delta.json'))
    original_manifest = (OLD / 'manifest.json').read_bytes()
    assert hashlib.sha256(original_manifest).hexdigest() == delta['baseManifestSha256']
    manifest = json.loads(original_manifest)
    verify_files(OLD, manifest)
    assert set(delta['files']) == CHANGES and re.fullmatch('[a-f0-9]{64}', delta['nextArchiveSha256'])
    release = BASE / 'releases' / delta['nextArchiveSha256'][:16]
    assert not release.exists()
    private_write(BACKUP / 'cloud.env.before', env)
    private_write(BACKUP / 'previous-release.txt', (str(OLD) + '\n').encode())
    shutil.copytree(OLD, release)
    for name, encoded in delta['files'].items():
        data = base64.b64decode(encoded, validate=True)
        assert hashlib.sha256(data).hexdigest() == delta['fileHashes'][name]
        (release / name).write_bytes(data)
        manifest['files'][name] = delta['fileHashes'][name]
    assert delta['manifestNewline'] == '\r\n'
    serialized = (json.dumps(manifest, indent=2, sort_keys=True) + '\n').replace('\n', '\r\n').encode()
    assert hashlib.sha256(serialized).hexdigest() == delta['nextManifestSha256']
    (release / 'manifest.json').write_bytes(serialized)
    verify_files(release, manifest)
    switched = False
    try:
        select_release(release)
        switched = True
        run(['systemctl', 'restart', 'thirdhand-stage.service', 'thirdhand-stage-export.service'])
        health()
        assert request('/login')[0] == 200
        assert request('/api/v1/mfa/prepare', {'password': 'Synthetic negative only'})[0] == 401
        assert request('/control-assets/js/lib/qrcode-generator-2.0.4.js')[0] == 401
        assert request('/ws')[0] == request('/voice')[0] == request('/vision')[0] == 404
        assert protected(Path('/etc/thirdhand-stage/cloud.env')) == env
        assert request('/', host='uiea-thirdhand.com')[0] == 200
        assert hashlib.sha256(index.read_bytes()).hexdigest() == main_hash
        result = {'success': True, 'checkedAt': datetime.now(timezone.utc).isoformat(),
                  'release': str(release), 'canonicalArchiveSha256': delta['nextArchiveSha256'],
                  'manifestSha256': delta['nextManifestSha256'], 'manifestFilesVerified': len(manifest['files']),
                  'assembledFromVerifiedBaseAndEightFiles': True, 'stagingOnly': True,
                  'privateConfigurationUnchanged': True, 'ownerMfaUntouched': True,
                  'showcaseUnchangedAtMfaDeployment': True, 'controlAvailable': False}
        private_write(BACKUP / 'activation.json', json.dumps(result, indent=2).encode())
        print(json.dumps(result, indent=2), flush=True)
    except Exception:
        if switched:
            select_release(OLD)
            run(['systemctl', 'restart', 'thirdhand-stage.service', 'thirdhand-stage-export.service'])
            health()
            print('MFA_UI_ROLLED_BACK', flush=True)
        raise


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('MFA_UI_ACTIVATION_FAILED ' + type(error).__name__, flush=True)
        raise SystemExit(1) from None
