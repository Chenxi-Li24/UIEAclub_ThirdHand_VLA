"""Apply the approved C2g camera-only deployment, one explicit phase at a time.

Run from its root-only backup directory after uploading the frozen artifacts.
All stdout is metadata; credentials remain in owner-only server files.
"""
import argparse
import base64
from datetime import datetime, timezone
import grp
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import pwd
import secrets
import shutil
import subprocess
import tarfile
import urllib.request

ARCHIVE_SHA = 'bbb537fe91f3ce2aa24ca9741598ba5d4a4038b4a89326debe628a6ef05acb82'
MANIFEST_SHA = 'dedd2ce315287733e2846ac8c9ebe7da168de887c67e6bd9a8b6848d96eed171'
SFU_ARCHIVE_SHA = '1e9ee90ca301e1842b2887fc77cb122759756a9c8aeb4334ee91de3325ec43fb'
SFU_BINARY_SHA = '85a58024d9b36542712514e0e926c0adb74f6182bcb19a664b9d9eb98ad01b52'
DEVICE = '006e0cac-cf10-427e-a84c-42c260b3ac4e'
CREDENTIAL = '550b647b-1529-4776-8bd1-28f6c2795c26'
CN = 'thirdhand-stage-camera-20261031'
RELEASE = Path('/opt/thirdhand-stage/releases/bbb537fe91f3ce2a')
NODE = '/opt/thirdhand-stage/node-v24.22.1/bin/node'


def run(args, *, data=None, timeout=60, cwd=None):
    return subprocess.run(args, input=data, capture_output=True, text=True, check=True, timeout=timeout, cwd=cwd).stdout


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, data, mode=0o600, uid=0, gid=0):
    path = Path(path)
    temporary = path.with_name(path.name + '.C2g-new')
    assert not temporary.exists()
    temporary.write_bytes(data.encode() if isinstance(data, str) else data)
    temporary.chmod(mode)
    os.chown(temporary, uid, gid)
    temporary.replace(path)


def sql(value):
    return "'" + str(value).replace("'", "''") + "'"


def install(root, state):
    archive = root / 'C2-staging-release.tar.gz'
    assert sha(archive) == ARCHIVE_SHA
    if not RELEASE.exists():
        RELEASE.mkdir(mode=0o755)
        with tarfile.open(archive, 'r:gz') as tar:
            for item in tar:
                path = PurePosixPath(item.name)
                assert item.isfile() and path.parts[0] == 'thirdhand-stage' and len(path.parts) > 1
                assert not path.is_absolute() and '..' not in path.parts
                destination = RELEASE.joinpath(*path.parts[1:])
                destination.parent.mkdir(parents=True, exist_ok=True)
                with tar.extractfile(item) as source, destination.open('xb') as target:
                    shutil.copyfileobj(source, target)
                destination.chmod(0o644)
        for directory, _, _ in os.walk(RELEASE):
            Path(directory).chmod(0o755)
    assert sha(RELEASE / 'manifest.json') == MANIFEST_SHA
    manifest = json.loads((RELEASE / 'manifest.json').read_text())
    assert len(manifest['files']) == 4613
    actual = {str(p.relative_to(RELEASE)) for p in RELEASE.rglob('*') if p.is_file()}
    assert actual == set(manifest['files']) | {'manifest.json'}
    assert all(sha(RELEASE / name) == digest for name, digest in manifest['files'].items())
    run([NODE, '-e', "require('./services/cloud-api/src/media/runtime');console.log('camera-runtime-load-ok')"], cwd=RELEASE)
    sfu_archive = root / 'livekit_1.13.11_linux_amd64.tar.gz'
    if not sfu_archive.exists():
        with urllib.request.urlopen('https://github.com/livekit/livekit/releases/download/v1.13.11/livekit_1.13.11_linux_amd64.tar.gz', timeout=40) as source, sfu_archive.open('xb') as target:
            shutil.copyfileobj(source, target)
    assert sha(sfu_archive) == SFU_ARCHIVE_SHA
    target = Path('/opt/thirdhand-stage-media/bin/livekit-server')
    target.parent.mkdir(parents=True, exist_ok=True)
    for path in [target.parent.parent, target.parent]:
        path.chmod(0o755)
    if not target.exists():
        with tarfile.open(sfu_archive, 'r:gz') as tar:
            entries = [item for item in tar.getmembers() if item.isfile() and PurePosixPath(item.name).name == 'livekit-server']
            assert len(entries) == 1 and entries[0].size < 200000000
            with tar.extractfile(entries[0]) as source, target.open('xb') as output:
                shutil.copyfileobj(source, output)
        target.chmod(0o755)
    assert sha(target) == SFU_BINARY_SHA
    state['releaseInstalled'] = True
    state['sfuVersion'] = run([str(target), '--version']).strip()


def enroll(root, state, ca_key):
    assert state.get('releaseInstalled')
    csr = root / 'device.csr'
    assert sha(csr) == '59957b3709fad5ff78a68610c8c9e2723a06efbe3ab5e0f73c7f904b2478e396'
    assert ca_key.is_file() and not ca_key.is_symlink() and not ca_key.stat().st_mode & 0o077
    run(['openssl', 'req', '-in', str(csr), '-verify', '-noout'])
    certificate = root / 'camera-device.pem'
    extension = root / 'camera-client.ext'
    extension.write_text('basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature\nextendedKeyUsage=clientAuth\nsubjectAltName=URI:urn:thirdhand:camera:' + DEVICE + '\nsubjectKeyIdentifier=hash\nauthorityKeyIdentifier=keyid,issuer\n')
    if not certificate.exists():
        run(['openssl', 'x509', '-req', '-in', str(csr), '-CA', '/etc/thirdhand-probe/probe-ca.pem', '-CAkey', str(ca_key),
             '-set_serial', '0x' + secrets.token_hex(16), '-days', '14', '-extfile', str(extension), '-out', str(certificate)])
    run(['openssl', 'verify', '-purpose', 'sslclient', '-CAfile', '/etc/thirdhand-probe/probe-ca.pem', str(certificate)])
    assert run(['openssl', 'x509', '-in', str(certificate), '-noout', '-subject', '-nameopt', 'RFC2253']).strip().replace('subject=', '').strip() == 'CN=' + CN
    public = run(['openssl', 'x509', '-in', str(certificate), '-pubkey', '-noout'])
    fingerprint = run(['openssl', 'x509', '-in', str(certificate), '-noout', '-fingerprint', '-sha256']).strip().split('=', 1)[1].replace(':', '').lower()
    serial = run(['openssl', 'x509', '-in', str(certificate), '-noout', '-serial']).strip().split('=', 1)[1]
    dates = dict(line.split('=', 1) for line in run(['openssl', 'x509', '-in', str(certificate), '-noout', '-dates']).strip().splitlines())
    parse_date = lambda value: datetime.strptime(value, '%b %d %H:%M:%S %Y %Z').replace(tzinfo=timezone.utc)
    starts, expires = parse_date(dates['notBefore']), parse_date(dates['notAfter'])
    ca_expiry = run(['openssl', 'x509', '-in', '/etc/thirdhand-probe/probe-ca.pem', '-noout', '-enddate']).strip().split('=', 1)[1]
    assert expires <= parse_date(ca_expiry)
    secret_file = root / 'media-secrets.private.json'
    if not secret_file.exists():
        key = root / 'camera-lease-signing.key'
        run(['openssl', 'genpkey', '-algorithm', 'ED25519', '-out', str(key)])
        key.chmod(0o600)
        private = subprocess.run(['openssl', 'pkey', '-in', str(key), '-outform', 'DER'], check=True, capture_output=True).stdout
        signing_public = run(['openssl', 'pkey', '-in', str(key), '-pubout'])
        write(secret_file, json.dumps({'apiKey': secrets.token_urlsafe(24), 'apiSecret': secrets.token_urlsafe(36),
                                     'signingKey': base64.b64encode(private).decode(), 'signingPublic': signing_public}))
    values = json.loads(secret_file.read_text())
    script = 'BEGIN;\nINSERT INTO ops.devices(id,name,hardware_serial,enabled,capabilities,config_version) VALUES(' + ','.join([
        sql(DEVICE), sql('Lab Ubuntu · XVisio camera'), sql('stage-camera:lab-ubuntu:' + DEVICE), 'true',
        sql(json.dumps({'camera': True, 'remoteControlEnabled': False})) + '::jsonb', sql('C2g-camera-only-v1')]) + ');\n'
    script += 'INSERT INTO ops.device_credentials(id,device_id,certificate_serial,fingerprint_sha256,public_key,not_before,expires_at) VALUES(' + ','.join([
        sql(CREDENTIAL), sql(DEVICE), sql(serial), sql(fingerprint), sql(public), sql(starts.isoformat()), sql(expires.isoformat())]) + ');\nCOMMIT;'
    run(['runuser', '-u', 'postgres', '--', '/usr/lib/postgresql/17/bin/psql', '-X', '-h', '/run/thirdhand-stage-db', '-p', '55440', '-d', 'thirdhand_stage', '-v', 'ON_ERROR_STOP=1', '-At'], data=script)
    write(root / 'camera-public.json', json.dumps({'deviceId': DEVICE, 'credentialId': CREDENTIAL,
          'certificatePem': certificate.read_text(), 'signingKeys': {'camera-stage-v1': values['signingPublic']},
          'fingerprintSha256': fingerprint, 'expiresAt': expires.isoformat()}, indent=2))
    state['cameraEnrolled'] = True
    state['certificateExpiresAt'] = expires.isoformat()


def configure(root, state):
    assert state.get('cameraEnrolled')
    before = json.loads((root / 'backup.json').read_text())
    for name in ['/etc/thirdhand-stage/cloud.env', '/etc/nginx/sites-available/staging.uiea-thirdhand.com', '/etc/nginx/sites-available/edge.uiea-thirdhand.com']:
        assert sha(Path(name)) == before['sourceHashes'][name]
    stage = Path('/etc/nginx/sites-available/staging.uiea-thirdhand.com')
    stage_text = stage.read_text()
    needle = '    location = / { return 302 /login; }'
    assert stage_text.count(needle) == 1
    edge = Path('/etc/nginx/sites-available/edge.uiea-thirdhand.com')
    edge_text = edge.read_text()
    begin = edge_text.index('    location ~ ^/edge/v1/(?:connect|healthz)$ {')
    end = edge_text.index('    location / { return 404; }', begin)
    for name in ['/etc/thirdhand-stage-media', '/etc/systemd/system/thirdhand-stage.service.d/camera.conf',
                 '/etc/systemd/system/thirdhand-stage-media.service', '/etc/nginx/conf.d/thirdhand-stage-media-routing.conf',
                 '/etc/thirdhand-stage/media-locations.inc']:
        assert not Path(name).exists(), 'New C2g path already exists; inspect before modifying'
    try:
        pwd.getpwnam('thirdhand-media')
    except KeyError:
        run(['useradd', '--system', '--no-create-home', '--shell', '/usr/sbin/nologin', 'thirdhand-media'])
    try:
        grp.getgrnam('thirdhand-stage-edge')
    except KeyError:
        run(['groupadd', '--system', 'thirdhand-stage-edge'])
    run(['usermod', '-aG', 'thirdhand-stage-edge', 'www-data'])
    who = pwd.getpwnam('thirdhand-media')
    config_dir = Path('/etc/thirdhand-stage-media')
    config_dir.mkdir(mode=0o700)
    os.chown(config_dir, who.pw_uid, who.pw_gid)
    values = json.loads((root / 'media-secrets.private.json').read_text())
    yaml = (root / 'media/livekit.yaml.template').read_text().replace('__MEDIA_API_KEY__', values['apiKey']).replace('__MEDIA_API_SECRET__', values['apiSecret'])
    write(config_dir / 'livekit.yaml', yaml, uid=who.pw_uid, gid=who.pw_gid)
    environment = Path('/etc/thirdhand-stage/cloud.env')
    current = environment.read_text()
    assert 'MEDIA_ENABLED=' not in current
    suffix = '\nMEDIA_ENABLED=1\nMEDIA_EDGE_SOCKET_PATH=/run/thirdhand-stage-edge/edge.sock\nMEDIA_API_HOST=http://127.0.0.1:7880\nMEDIA_API_KEY=' + values['apiKey'] + '\nMEDIA_API_SECRET=' + values['apiSecret'] + '\nMEDIA_SIGNING_KEY_ID=camera-stage-v1\nMEDIA_SIGNING_KEY_BASE64=' + values['signingKey'] + '\nMEDIA_MAX_VIEWERS=2\n'
    write(environment, current.rstrip() + suffix)
    dropin = Path('/etc/systemd/system/thirdhand-stage.service.d')
    dropin.mkdir(exist_ok=True)
    write(dropin / 'camera.conf', (root / 'media/camera-api.conf').read_bytes(), 0o644)
    write('/etc/systemd/system/thirdhand-stage-media.service', (root / 'media/thirdhand-stage-media.service').read_bytes(), 0o644)
    write('/etc/nginx/conf.d/thirdhand-stage-media-routing.conf', (root / 'media/routing.conf').read_bytes(), 0o644)
    write('/etc/thirdhand-stage/media-locations.inc', (root / 'media/media-locations.inc').read_bytes(), 0o644)
    write(stage, stage_text.replace(needle, '    include /etc/thirdhand-stage/media-locations.inc;\n' + needle), 0o644)
    write(edge, edge_text[:begin] + (root / 'media/edge-location.inc').read_text() + '\n' + edge_text[end:], 0o644)
    run(['/usr/sbin/nginx', '-t'])
    run(['systemctl', 'daemon-reload'])
    state['configurationPrepared'] = True


def activate(root, state):
    assert state.get('configurationPrepared')
    run(['systemctl', 'enable', '--now', 'thirdhand-stage-media.service'])
    assert run(['systemctl', 'is-active', 'thirdhand-stage-media.service']).strip() == 'active'
    temporary = Path('/opt/thirdhand-stage/current.C2g-new')
    assert not temporary.exists()
    temporary.symlink_to(RELEASE)
    temporary.replace('/opt/thirdhand-stage/current')
    run(['systemctl', 'restart', 'thirdhand-stage.service'])
    assert run(['systemctl', 'is-active', 'thirdhand-stage.service']).strip() == 'active'
    run(['/usr/sbin/nginx', '-t'])
    run(['systemctl', 'reload', 'nginx.service'])
    run(['ufw', 'allow', '7881/tcp', 'comment', 'ThirdHand C2g ICE TCP'])
    run(['ufw', 'allow', '7882/udp', 'comment', 'ThirdHand C2g ICE UDP'])
    state['activated'] = True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=['install', 'enroll', 'configure', 'activate'])
    parser.add_argument('--ca-key', type=Path)
    args = parser.parse_args()
    assert os.geteuid() == 0
    os.umask(0o077)
    root = Path('/var/backups/thirdhand/C2g-backup-path').read_text().strip()
    root = Path(root)
    assert root.is_dir() and root.parent == Path('/var/backups/thirdhand') and root.name.startswith('access-C2g-camera-')
    state_file = root / 'deployment-state.json'
    state = json.loads(state_file.read_text()) if state_file.exists() else {}
    marker = {'install': 'releaseInstalled', 'enroll': 'cameraEnrolled', 'configure': 'configurationPrepared', 'activate': 'activated'}[args.phase]
    assert not state.get(marker), 'Phase already completed; inspect state rather than rerun'
    if args.phase == 'enroll':
        assert args.ca_key
        enroll(root, state, args.ca_key)
    else:
        globals()[args.phase](root, state)
    write(state_file, json.dumps(state, indent=2))
    print(json.dumps({'phase': args.phase, 'success': True, 'state': state}))


if __name__ == '__main__':
    main()
