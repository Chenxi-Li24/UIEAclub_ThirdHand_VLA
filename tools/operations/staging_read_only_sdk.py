"""Reviewed, forward-only C3a staging activation. No SDK or movement code here.

Run --review first. Activation additionally requires operator approval in chat.
Private keys stay on the server; exported enrollment JSON contains PUBLIC data.
"""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import shutil
import subprocess
import tarfile
import time
import urllib.request

DEVICE = 'ee625a57-049a-4c5d-92e1-9578ab9d21c3'
CREDENTIAL = '5d782909-cdce-4939-83b2-9ec76667e9dd'
CN = 'thirdhand-stage-sdk-readonly-20261031'
OLD = Path('/opt/thirdhand-stage/releases/fecd12218feca574')
CURRENT = Path('/opt/thirdhand-stage/current')
NODE = '/opt/thirdhand-stage/node-v24.22.1/bin/node'
PG = ['/usr/sbin/runuser', '-u', 'postgres', '--', '/usr/lib/postgresql/17/bin/psql',
      '-X', '-q', '-At', '-v', 'ON_ERROR_STOP=1', '-h', '/run/thirdhand-stage-db',
      '-p', '55440', '-d', 'thirdhand_stage']
CONFIG = [Path('/etc/thirdhand-stage/cloud.env'),
          Path('/etc/nginx/sites-available/staging.uiea-thirdhand.com'),
          Path('/etc/nginx/sites-available/edge.uiea-thirdhand.com'),
          Path('/etc/nginx/conf.d/thirdhand-stage-media-routing.conf')]


def run(arguments, data=None, env=None):
    return subprocess.run(arguments, input=data, text=True, check=True,
                          capture_output=True, env=env).stdout


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sql(value):
    return "'" + str(value).replace("'", "''") + "'"


def add_https_location(text, addition, hostname):
    # The edge HTTP and HTTPS servers both end with a default404. A global
    # replacement would also expose a plaintext route in the HTTP server.
    parts = re.split(r'(?m)(?=^server\s*\{)', text)
    targets = [i for i, part in enumerate(parts)
               if re.search(r'(?m)^\s*listen\s+443\s+ssl\s*;', part)
               and re.search(r'(?m)^\s*server_name\s+' + re.escape(hostname) + r'\s*;', part)]
    assert len(targets) == 1
    index = targets[0]; needle = '    location / { return 404; }'
    assert parts[index].count(needle) == 1
    parts[index] = parts[index].replace(needle, addition + '\n' + needle)
    return ''.join(parts)


def review(root):
    assert os.geteuid() == 0 and CURRENT.resolve() == OLD and root.is_dir()
    lock = json.loads((root / 'release-review.json').read_text())
    archive = root / 'C3a-cloud-release.tar.gz'
    assert sha(archive) == lock['archiveSha256']
    assert sha(root / 'device.csr') == lock['csrSha256']
    assert all(sha(root / relative) == digest for relative, digest in lock['templates'].items())
    assert not (root / 'before').exists()
    with tarfile.open(archive, 'r:gz') as tar:
        files = {}
        for item in tar:
            parts = PurePosixPath(item.name)
            assert item.isfile() and not parts.is_absolute() and '..' not in parts.parts
            assert parts.parts[0] == 'thirdhand-stage' and len(parts.parts) > 1
            name = '/'.join(parts.parts[1:]); assert name not in files
            files[name] = hashlib.sha256(tar.extractfile(item).read()).hexdigest()
        assert files.pop('manifest.json') == lock['manifestSha256']
    manifest = json.loads((root / 'manifest.json').read_text())
    assert sha(root / 'manifest.json') == lock['manifestSha256'] and manifest['files'] == files
    previous = json.loads((OLD / 'manifest.json').read_text())['files']
    changed = sorted(name for name in set(files) | set(previous) if files.get(name) != previous.get(name))
    assert changed == lock['changedFiles'] and all(sha(OLD / name) == digest for name, digest in previous.items())
    stage, edge, mapping = [p.read_text() for p in CONFIG[1:]]
    assert '/stream/v1/control' not in stage and '/edge/v1/telemetry-batches' not in edge and CN not in mapping
    add_https_location(stage, '', 'staging.uiea-thirdhand.com')
    add_https_location(edge, '', 'edge.uiea-thirdhand.com')
    assert mapping.count('    default thirdhand_probe_backend;') == 1
    run(['openssl', 'req', '-in', str(root / 'device.csr'), '-verify', '-noout'])
    assert run(['openssl', 'req', '-in', str(root / 'device.csr'), '-noout', '-subject', '-nameopt', 'RFC2253']).strip() == 'subject=CN=' + CN
    assert run(PG + ['-c', f"SELECT count(*) FROM ops.devices WHERE id={sql(DEVICE)}"]).strip() == '0'
    return lock, manifest, {str(p): sha(p) for p in CONFIG}


def install_release(root, lock, manifest):
    destination = Path('/opt/thirdhand-stage/releases') / lock['archiveSha256'][:16]
    assert not destination.exists(); destination.mkdir(mode=0o755)
    with tarfile.open(root / 'C3a-cloud-release.tar.gz', 'r:gz') as tar:
        for item in tar:
            target = destination.joinpath(*PurePosixPath(item.name).parts[1:])
            target.parent.mkdir(parents=True, exist_ok=True)
            with tar.extractfile(item) as source, target.open('xb') as output:
                shutil.copyfileobj(source, output)
            target.chmod(0o644)
    for directory, _, _ in os.walk(destination):
        Path(directory).chmod(0o755)
    assert sha(destination / 'manifest.json') == lock['manifestSha256']
    assert all(sha(destination / name) == digest for name, digest in manifest['files'].items())
    return destination


def enroll(root, ca_key):
    assert ca_key.is_file() and not ca_key.is_symlink() and not ca_key.stat().st_mode & 0o077
    certificate = root / 'sdk-device.pem'
    extension = root / 'client.ext'
    extension.write_text('basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature\nextendedKeyUsage=clientAuth\n'
                         'subjectAltName=URI:urn:thirdhand:readonly:' + DEVICE + '\nsubjectKeyIdentifier=hash\nauthorityKeyIdentifier=keyid,issuer\n')
    run(['openssl', 'x509', '-req', '-in', str(root / 'device.csr'), '-CA', '/etc/thirdhand-probe/probe-ca.pem',
         '-CAkey', str(ca_key), '-set_serial', '0x' + secrets.token_hex(16), '-days', '7',
         '-extfile', str(extension), '-out', str(certificate)])
    run(['openssl', 'verify', '-purpose', 'sslclient', '-CAfile', '/etc/thirdhand-probe/probe-ca.pem', str(certificate)])
    public = run(['openssl', 'x509', '-in', str(certificate), '-pubkey', '-noout'])
    fingerprint = run(['openssl', 'x509', '-in', str(certificate), '-noout', '-fingerprint', '-sha256']).strip().split('=', 1)[1].replace(':', '').lower()
    serial = run(['openssl', 'x509', '-in', str(certificate), '-noout', '-serial']).strip().split('=', 1)[1]
    dates = dict(line.split('=', 1) for line in run(['openssl', 'x509', '-in', str(certificate), '-noout', '-dates']).strip().splitlines())
    parse = lambda value: datetime.strptime(value, '%b %d %H:%M:%S %Y %Z').replace(tzinfo=timezone.utc)
    starts, expires = parse(dates['notBefore']), parse(dates['notAfter'])
    ca_expires = run(['openssl', 'x509', '-in', '/etc/thirdhand-probe/probe-ca.pem', '-noout', '-enddate']).strip().split('=', 1)[1]
    assert expires <= parse(ca_expires)
    statements = 'BEGIN;\nINSERT INTO ops.devices(id,name,hardware_serial,enabled,capabilities,config_version) VALUES(' + ','.join([
        sql(DEVICE), sql('Lab Ubuntu · SDK read-only'), sql('lab-ubuntu:can0:readonly:' + DEVICE), 'true',
        sql(json.dumps({'camera': False, 'remoteControlEnabled': True})) + '::jsonb', sql('C3a-read-only-v1')]) + ');\n'
    statements += 'INSERT INTO ops.device_credentials(id,device_id,certificate_serial,fingerprint_sha256,public_key,not_before,expires_at,control_enabled,control_mode) VALUES(' + ','.join([
        sql(CREDENTIAL), sql(DEVICE), sql(serial), sql(fingerprint), sql(public), sql(starts.isoformat()), sql(expires.isoformat()), 'true', sql('read-only')]) + ');\nCOMMIT;'
    run(PG, statements)
    key = root / 'sdk-control-signing.key'; run(['openssl', 'genpkey', '-algorithm', 'ED25519', '-out', str(key)]); key.chmod(0o600)
    private = subprocess.run(['openssl', 'pkey', '-in', str(key), '-outform', 'DER'], check=True, capture_output=True).stdout
    signing_public = run(['openssl', 'pkey', '-in', str(key), '-pubout'])
    public_data = {'deviceId': DEVICE, 'credentialId': CREDENTIAL, 'readOnly': True,
        'certificatePem': certificate.read_text(), 'caPem': Path('/etc/thirdhand-probe/probe-ca.pem').read_text(),
        'signingKeys': {'sdk-stage-readonly-v1': signing_public}, 'expiresAt': expires.isoformat()}
    (root / 'enrollment-public.json').write_text(json.dumps(public_data, indent=2))
    return base64.b64encode(private).decode()


def switch_release(destination):
    temporary = Path('/opt/thirdhand-stage/current.C3a'); assert not temporary.exists()
    temporary.symlink_to(destination); temporary.replace(CURRENT)


def rollback(root):
    failures = []
    def attempt(step, action):
        try:
            action(); return True
        except Exception as error:
            failures.append({'step': step, 'errorType': type(error).__name__}); return False
    # Database availability must never govern filesystem/program restoration.
    attempt('revoke_device', lambda: run(PG, f"BEGIN; UPDATE ops.device_credentials SET revoked_at=coalesce(revoked_at,now()) WHERE id={sql(CREDENTIAL)}; UPDATE ops.devices SET enabled=false WHERE id={sql(DEVICE)}; COMMIT;"))
    for p in CONFIG:
        attempt('restore_' + p.name, lambda p=p: shutil.copyfile(root / 'before' / p.name, p))
    attempt('restore_release', lambda: switch_release(OLD))
    nginx_valid = attempt('nginx_config_test', lambda: run(['/usr/sbin/nginx', '-t']))
    attempt('restart_previous_api', lambda: run(['systemctl', 'restart', 'thirdhand-stage.service']))
    if nginx_valid:
        attempt('reload_nginx', lambda: run(['systemctl', 'reload', 'nginx']))
    (root / 'rollback-result.json').write_text(json.dumps({'rollbackAttempted': True, 'failures': failures}, indent=2))
    return failures


def apply(root, ca_key):
    os.umask(0o077)
    lock, manifest, hashes = review(root)
    before = root / 'before'; before.mkdir(mode=0o700)
    for p in CONFIG:
        shutil.copyfile(p, before / p.name)
    (before / 'source-hashes.json').write_text(json.dumps(hashes, indent=2))
    with (before / 'database.dump').open('xb') as output:
        subprocess.run(['/usr/sbin/runuser', '-u', 'postgres', '--', '/usr/lib/postgresql/17/bin/pg_dump',
          '-h', '/run/thirdhand-stage-db', '-p', '55440', '-d', 'thirdhand_stage', '-Fc'], stdout=output, check=True)
    destination = install_release(root, lock, manifest)
    try:
        run(['/usr/sbin/runuser', '-u', 'postgres', '--', 'env',
             'MIGRATION_DATABASE_URL=postgresql://postgres@localhost/thirdhand_stage?host=%2Frun%2Fthirdhand-stage-db&port=55440',
             NODE, str(destination / 'platform/storage/src/migrate-cli.js')])
        run(PG, (root / 'device/runtime-grants.sql').read_text())
        key = enroll(root, ca_key)
        for p in CONFIG:
            assert sha(p) == hashes[str(p)]
        environment = CONFIG[0].read_text(); assert 'DEVICE_CONTROL_' not in environment and 'DEVICE_TELEMETRY_' not in environment
        CONFIG[0].write_text(environment.rstrip() + '\nDEVICE_TELEMETRY_ENABLED=1\nDEVICE_CONTROL_ENABLED=1\nDEVICE_CONTROL_KEY_ID=sdk-stage-readonly-v1\nDEVICE_CONTROL_KEY_BASE64=' + key + '\n')
        CONFIG[0].chmod(0o640)
        for p, template, hostname in [(CONFIG[1], 'control-location.conf', 'staging.uiea-thirdhand.com'),
                                       (CONFIG[2], 'telemetry-location.conf', 'edge.uiea-thirdhand.com')]:
            p.write_text(add_https_location(p.read_text(), (root / 'device' / template).read_text(), hostname))
        CONFIG[3].write_text(CONFIG[3].read_text().replace('    default thirdhand_probe_backend;',
            '    default thirdhand_probe_backend;\n    "CN=' + CN + '" thirdhand_stage_camera_backend;'))
        run(['/usr/sbin/nginx', '-t'])
        switch_release(destination); run(['systemctl', 'restart', 'thirdhand-stage.service'])
        for attempt in range(30):
            try:
                with urllib.request.urlopen('http://127.0.0.1:3202/healthz', timeout=2) as response:
                    assert json.load(response)['deviceControl'] == 'explicit-read-only'
                break
            except Exception:
                if attempt == 29: raise
                time.sleep(0.25)
        run(['systemctl', 'reload', 'nginx'])
        result = {'cloudApplied': True, 'release': str(destination), 'deviceId': DEVICE,
                  'readOnly': True, 'newPublicPorts': [], 'motionTested': False,
                  'sdkConnectedByInstaller': False, 'databaseMigration': '009-scoped-device-control.sql'}
        (root / 'cloud-applied.json').write_text(json.dumps(result, indent=2)); return result
    except Exception:
        # Forward migration and captured data remain. Refuse the new identity,
        # restore the camera-only program/config; never replay any commands.
        rollback(root)
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--ca-key', type=Path); parser.add_argument('--apply', action='store_true'); args = parser.parse_args()
    root = args.root.resolve()
    assert root.parent == Path('/var/backups/thirdhand') and root.name == 'access-C3a-sdk-readonly-20261031'
    if args.apply:
        assert args.ca_key is not None
        print(json.dumps(apply(root, args.ca_key.resolve())))
    else:
        lock, manifest, hashes = review(root)
        print(json.dumps({'reviewOnly': True, 'files': len(manifest['files']), 'changedFiles': lock['changedFiles'],
                          'readOnly': True, 'deviceId': DEVICE, 'newPublicPorts': [], 'configBeforeHashes': hashes}))
