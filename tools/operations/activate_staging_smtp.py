"""Fixed C2c rollout, using a user-filled root-only password file. Never log secrets."""
from datetime import datetime, timezone
import base64
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import shutil
import socket
import ssl
import subprocess
import time
import uuid

B = Path('/var/backups/thirdhand/access-C2c-smtp-20261030T150149Z')
BASE = Path('/opt/thirdhand-stage')
OLD = BASE / 'releases/73365433069aa612'
ENV = Path('/etc/thirdhand-stage/cloud.env')
NODE = str(BASE / 'node-v24.22.1/bin/node')
HOST = 'staging.uiea-thirdhand.com'
STEP = 'preflight'


def run(args, **kwargs):
    return subprocess.run(args, check=True, capture_output=True, **kwargs)


def protected(path):
    assert path.is_file() and not path.is_symlink() and path.stat().st_uid == 0
    assert path.stat().st_mode & 0o777 == 0o600
    return path.read_bytes()


def private_write(path, value):
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as stream:
        stream.write(value)


def atomic_env(value):
    temporary = ENV.with_name('.cloud.env.smtp-' + uuid.uuid4().hex)
    assert not temporary.exists()
    private_write(temporary, value)
    os.replace(temporary, ENV)


def select_release(path):
    temporary = BASE / ('current.smtp-' + uuid.uuid4().hex)
    assert not temporary.exists()
    temporary.symlink_to(path)
    os.replace(temporary, BASE / 'current')


def process_environment():
    pid = int(run(['systemctl', 'show', 'thirdhand-stage.service', '-p', 'MainPID', '--value']).stdout)
    assert pid > 1
    return dict(part.decode().split('=', 1) for part in Path(f'/proc/{pid}/environ').read_bytes().split(b'\0') if b'=' in part)


def request(path, body=None, host=HOST):
    stream = ssl.create_default_context().wrap_socket(socket.create_connection(('127.0.0.1', 443), timeout=10), server_hostname=host)
    connection = http.client.HTTPConnection(host, timeout=10)
    connection.sock = stream
    headers = {'Host': host}
    if body is not None:
        headers.update({'Content-Type': 'application/json', 'Origin': 'https://' + host})
        body = json.dumps(body).encode()
    connection.request('POST' if body is not None else 'GET', path, body=body, headers=headers)
    response = connection.getresponse()
    result = response.status, response.read()
    connection.close()
    return result


def health():
    deadline = time.monotonic() + 15
    while True:
        try:
            connection = http.client.HTTPConnection('127.0.0.1', 3202, timeout=1)
            connection.request('GET', '/healthz')
            response = connection.getresponse()
            assert response.status == 200 and json.loads(response.read())['deviceControl'] == 'unavailable'
            connection.close()
            return
        except (OSError, http.client.HTTPException):
            assert time.monotonic() < deadline
            time.sleep(.2)


def main():
    global STEP
    assert os.geteuid() == 0 and os.uname().sysname == 'Linux'
    assert json.loads(protected(B / 'smtp-auth-check.json'))['success']
    assert not (B / 'smtp-activation.json').exists() and not (B / 'smtp-delivery.accepted.json').exists()
    config = json.loads(protected(Path('/etc/thirdhand-stage/smtp.pending.json')))
    assert config['host'] == 'smtpdm.aliyun.com' and config['port'] == 465
    assert config['username'] == config['from'] == 'thirdhand@mail.uiea-thirdhand.com'
    assert len(config['allowedRecipients']) == 1
    password = protected(Path('/etc/thirdhand-stage/smtp-password.pending')).decode().removesuffix('\n').removesuffix('\r')
    assert 8 <= len(password) <= 1024 and not any(ord(ch) < 32 or ord(ch) == 127 for ch in password)
    original = protected(ENV)
    assert not re.search(rb'(?m)^SMTP_HOST=', original)
    assert (BASE / 'current').resolve() == OLD
    runtime = process_environment()
    assert runtime['PUBLIC_ORIGIN'] == 'https://' + HOST and runtime['CLOUD_BIND_HOST'] == '127.0.0.1'
    assert request('/', host='uiea-thirdhand.com')[0] == 200
    main_hash = hashlib.sha256(Path('/www/wwwroot/uiea-thirdhand-static/index.html').read_bytes()).hexdigest()
    assert main_hash == '639bb62379c763ebbd4610125cafc3ebff3aa14debb0c3ca2f50ee75d1a478bd'
    private_write(B / 'cloud.env.before', original)
    private_write(B / 'previous-release.txt', (str(OLD) + '\n').encode())
    STEP = 'verified-release-delta'
    delta = json.loads((B / 'release-delta.json').read_text())
    old_manifest_bytes = (OLD / 'manifest.json').read_bytes()
    assert hashlib.sha256(old_manifest_bytes).hexdigest() == delta['baseManifestSha256']
    manifest = json.loads(old_manifest_bytes)
    assert all(not path.is_symlink() for path in OLD.rglob('*'))
    assert {path.relative_to(OLD).as_posix() for path in OLD.rglob('*') if path.is_file()} == set(manifest['files']) | {'manifest.json'}
    assert all(hashlib.sha256((OLD / name).read_bytes()).hexdigest() == digest for name, digest in manifest['files'].items())
    assert set(delta['files']) == {'platform/identity/src/smtp.js', 'services/cloud-api/src/config.js', 'tools/operations/isolate_staging_restore.js'}
    assert re.fullmatch('[a-f0-9]{64}', delta['nextArchiveSha256'])
    release = BASE / 'releases' / delta['nextArchiveSha256'][:16]
    assert not release.exists()
    shutil.copytree(OLD, release)
    for name, encoded in delta['files'].items():
        data = base64.b64decode(encoded, validate=True)
        assert hashlib.sha256(data).hexdigest() == delta['fileHashes'][name]
        (release / name).write_bytes(data)
        manifest['files'][name] = delta['fileHashes'][name]
    assert delta['manifestNewline'] in ('\n', '\r\n')
    manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True) + '\n').replace('\n', delta['manifestNewline']).encode()
    assert hashlib.sha256(manifest_bytes).hexdigest() == delta['nextManifestSha256']
    (release / 'manifest.json').write_bytes(manifest_bytes)
    assert all(hashlib.sha256((release / name).read_bytes()).hexdigest() == digest for name, digest in manifest['files'].items())
    assert all(not path.is_symlink() for path in release.rglob('*'))
    assert {path.relative_to(release).as_posix() for path in release.rglob('*') if path.is_file()} == set(manifest['files']) | {'manifest.json'}
    STEP = 'configuration-and-authentication'
    additions = {'SMTP_HOST': config['host'], 'SMTP_PORT': str(config['port']), 'SMTP_USER': config['username'],
                 'SMTP_FROM': config['from'], 'SMTP_PASSWORD': password,
                 'SMTP_ALLOWED_RECIPIENTS_JSON': json.dumps(config['allowedRecipients'], separators=(',', ':'))}
    runtime.update(additions)
    module = f"const config=require('{release}/services/cloud-api/src/config').loadCloudConfig();const {{createSmtpMailer}}=require('{release}/platform/identity/src/smtp');let transport;const mail=createSmtpMailer(config.smtp,options=>(transport=require('{release}/node_modules/nodemailer').createTransport(options)));"
    auth_code = module + "(async()=>{try{await transport.verify();console.log('SMTP_NODE_AUTH_PASSED')}finally{mail.close()}})().catch(()=>{console.error('SMTP_NODE_AUTH_FAILED');process.exitCode=1});"
    assert run([NODE, '-'], input=auth_code.encode(), env=runtime, cwd=release, timeout=30).stdout.strip() == b'SMTP_NODE_AUTH_PASSED'
    quote = lambda value: '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'
    new_env = original + ('\n' + '\n'.join(key + '=' + quote(value) for key, value in additions.items()) + '\n').encode()
    switched = False
    try:
        STEP = 'activate-private-smtp'
        run(['systemctl', 'stop', 'thirdhand-stage.service', 'thirdhand-stage-export.service'])
        switched = True
        atomic_env(new_env)
        select_release(release)
        run(['systemctl', 'start', 'thirdhand-stage.service', 'thirdhand-stage-export.service'])
        health()
        applied = process_environment()
        assert all(applied[key] == value for key, value in additions.items())
        assert request('/login')[0] == 200
        status, body = request('/api/v1/auth/register', {'username': 'unapproved_mail_fixture', 'email': 'unapproved@example.invalid', 'displayName': 'C2c negative mail fixture', 'password': 'SyntheticOnly-9!Negative'})
        assert status == 503 and json.loads(body)['error'] == 'MAIL_UNAVAILABLE'
        assert request('/ws')[0] == request('/voice')[0] == request('/vision')[0] == 404
        assert request('/', host='uiea-thirdhand.com')[0] == 200
        assert hashlib.sha256(Path('/www/wwwroot/uiea-thirdhand-static/index.html').read_bytes()).hexdigest() == main_hash
        STEP = 'one-authorized-test-message'
        send_code = module + "(async()=>{try{const to=config.smtp.allowedRecipients[0];mail.ensureAvailable({to});const result=await transport.sendMail({from:config.smtp.from,to,subject:'ThirdHand SMTP delivery test',text:'ThirdHand staging mail delivery test.\\n\\nThe SMTP connection and website configuration have been verified. Registration email verification is completed separately on the website.\\n\\nhttps://staging.uiea-thirdhand.com/register'});if(result.accepted.length!==1||result.rejected.length)throw Error();console.log(JSON.stringify({acceptedBySmtp:true,acceptedCount:result.accepted.length,messageId:result.messageId,inboxConfirmed:false}));}finally{mail.close()}})().catch(()=>{console.error('SMTP_TEST_DELIVERY_FAILED');process.exitCode=1});"
        delivery = json.loads(run([NODE, '-'], input=send_code.encode(), env=applied, cwd=release, timeout=45).stdout)
        private_write(B / 'smtp-delivery.accepted.json', json.dumps(delivery, indent=2).encode())
        result = {'success': True, 'checkedAt': datetime.now(timezone.utc).isoformat(), 'stagingOnly': True,
                  'release': str(release), 'canonicalArchiveSha256': delta['nextArchiveSha256'],
                  'manifestSha256': delta['nextManifestSha256'], 'manifestFilesVerified': len(manifest['files']),
                  'assembledFromVerifiedBaseAndThreeSourceFiles': True, 'smtpAuthenticationPassed': True,
                  'smtpHost': config['host'], 'smtpPort': config['port'], 'sender': config['from'],
                  'recipientRestrictionCount': 1, 'unapprovedRegistrationRejected': True,
                  'systemdSecretValueMatched': True, 'controlAvailable': False, 'originalShowcaseUnchanged': True,
                  'delivery': delivery, 'realAdministratorRegistered': False}
        private_write(B / 'smtp-activation.json', json.dumps(result, indent=2).encode())
        print(json.dumps(result, indent=2), flush=True)
    except Exception:
        if switched:
            run(['systemctl', 'stop', 'thirdhand-stage.service', 'thirdhand-stage-export.service'])
            atomic_env(original)
            select_release(OLD)
            run(['systemctl', 'start', 'thirdhand-stage.service', 'thirdhand-stage-export.service'])
            health()
            print('SMTP_ROLLED_BACK_TO_PREVIOUS_STAGING', flush=True)
        raise


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('STAGING_SMTP_FAILED at ' + STEP + ' type ' + type(error).__name__, flush=True)
        raise SystemExit(1) from None
