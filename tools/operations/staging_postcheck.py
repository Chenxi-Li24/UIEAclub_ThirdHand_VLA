"""C2 operator acceptance: reversible route shutdown, UTC, private backup, evidence."""
import gzip
from datetime import datetime, timezone
import hashlib
import http.client
import json
import os
from pathlib import Path
import socket
import shutil
import ssl
import subprocess
import time

B = Path('/var/backups/thirdhand/access-C2-20261030T125221Z')
R = Path('/opt/thirdhand-stage/current')
HOST = 'staging.uiea-thirdhand.com'
STEP = 'preflight'


def run(args, **kwargs):
    kwargs.setdefault('check', True)
    return subprocess.run(args, capture_output=True, **kwargs)


def request(path, *, host=HOST, body=None, cookie=None, csrf=None, compressed=False):
    context = ssl.create_default_context()
    stream = context.wrap_socket(socket.create_connection(('127.0.0.1', 443), timeout=20), server_hostname=host)
    connection = http.client.HTTPConnection(host, timeout=20)
    connection.sock = stream
    headers = {'Host': host}
    if body is not None:
        body = json.dumps(body).encode()
        headers.update({'Content-Type': 'application/json', 'Origin': 'https://' + host})
    if cookie:
        headers['Cookie'] = cookie
    if csrf:
        headers['X-CSRF-Token'] = csrf
    if compressed:
        headers['Accept-Encoding'] = 'gzip'
    connection.request('POST' if body is not None else 'GET', path, body=body, headers=headers)
    response = connection.getresponse()
    content = response.read(12 * 1024 * 1024)
    result = response.status, dict(response.getheaders()), content
    connection.close()
    return result


def main():
    global STEP
    assert os.geteuid() == 0 and (B / 'C2-restore-drill.json').is_file()
    include = Path('/etc/thirdhand-stage/business-upstream.inc')
    original = include.read_bytes()
    assert b'127.0.0.1:3202' in original and b'9983' not in original
    (B / 'business-before-rollback.inc').write_bytes(original)
    STEP = 'maintenance-route-rollback'
    try:
        include.write_text('return 503;\n')
        run(['/usr/sbin/nginx', '-t'])
        run(['systemctl', 'reload', 'nginx'])
        deadline = time.monotonic() + 5
        while request('/login')[0] != 503:
            assert time.monotonic() < deadline
            time.sleep(.1)
        run(['systemctl', 'stop', 'thirdhand-stage.service', 'thirdhand-stage-export.service'])
        assert request('/api/v1/session')[0] == 503
        assert request('/', host='uiea-thirdhand.com')[0] == 200
        STEP = 'utc-display-config'
        psql = ['/usr/lib/postgresql/17/bin/psql', '-h', '/run/thirdhand-stage-db', '-p', '55440', '-U', 'postgres', '-d', 'thirdhand_stage', '-v', 'ON_ERROR_STOP=1', '-Atc']
        run(['runuser', '-u', 'postgres', '--', *psql, "ALTER DATABASE thirdhand_stage SET TimeZone='UTC'"])
        assert run(['runuser', '-u', 'postgres', '--', *psql, 'SHOW TimeZone']).stdout.strip() == b'UTC'
        run(['systemctl', 'start', 'thirdhand-stage.service', 'thirdhand-stage-export.service'])
        deadline = time.monotonic() + 15
        while True:
            try:
                c = http.client.HTTPConnection('127.0.0.1', 3202, timeout=1)
                c.request('GET', '/healthz')
                response = c.getresponse()
                assert response.status == 200 and json.loads(response.read())['deviceControl'] == 'unavailable'
                c.close()
                break
            except (OSError, http.client.HTTPException):
                assert time.monotonic() < deadline
                time.sleep(.2)
    finally:
        run(['systemctl', 'start', 'thirdhand-stage.service', 'thirdhand-stage-export.service'])
        include.write_bytes(original)
        run(['/usr/sbin/nginx', '-t'])
        run(['systemctl', 'reload', 'nginx'])
    deadline = time.monotonic() + 5
    while request('/login')[0] != 200:
        assert time.monotonic() < deadline
        time.sleep(.1)
    STEP = 'gzip-and-observer-postcheck'
    account = next(x for x in json.loads((B / 'review-accounts.private.json').read_text())['accounts'] if x['username'] == 'c2_observer2')
    status, headers, body = request('/api/v1/auth/login', body={'login': account['username'], 'password': account['password'], 'requestedMode': 'observe'})
    assert status == 200
    cookie = headers['Set-Cookie'].split(';')[0]
    identity = json.loads(body)
    status, headers, body = request('/control-assets/models/startouch-v3/meshes/gripper_base.STL', cookie=cookie, compressed=True)
    assert status == 200 and headers['Content-Encoding'] == 'gzip'
    expected = (R / 'assets/robot/startouch-v3/meshes/gripper_base.STL').read_bytes()
    assert hashlib.sha256(gzip.decompress(body)).digest() == hashlib.sha256(expected).digest()
    compression = dict(originalBytes=len(expected), gzipBytes=len(body))
    status, headers, body = request('/api/v1/history?kind=samples&from=2026-10-30T00:00:00Z&to=2026-10-31T00:00:00Z', cookie=cookie)
    assert status == 200
    rows = json.loads(body)['rows']
    assert len(rows) == 3 and all(r['captured_at'].endswith('+00:00') for r in rows)
    assert request('/api/v1/admin/users', cookie=cookie)[0] == 403
    assert request('/api/v1/sdk/connect', body={}, cookie=cookie, csrf=identity['csrfToken'])[0] == 403
    STEP = 'manifest-original-site-and-private-backup'
    manifest = json.loads((R / 'manifest.json').read_text())
    assert all(hashlib.sha256((R / name).read_bytes()).hexdigest() == digest for name, digest in manifest['files'].items())
    showcase = Path('/www/wwwroot/uiea-thirdhand-static/index.html')
    showcase_hash = hashlib.sha256(showcase.read_bytes()).hexdigest()
    assert showcase_hash == '639bb62379c763ebbd4610125cafc3ebff3aa14debb0c3ca2f50ee75d1a478bd'
    main_config = Path('/etc/nginx/sites-available/uiea-thirdhand.com')
    assert main_config.read_bytes() == (B / 'etc-nginx/sites-available/uiea-thirdhand.com').read_bytes()
    edge_config = Path('/etc/nginx/sites-available/edge.uiea-thirdhand.com')
    assert edge_config.read_bytes() == (B / 'etc-nginx/sites-available/edge.uiea-thirdhand.com').read_bytes()
    assert request('/', host='uiea-thirdhand.com')[0] == 200
    assert request('/device/v1/healthz', host='edge.uiea-thirdhand.com')[0] == 400
    assert request('/ws')[0] == request('/voice')[0] == request('/vision')[0] == 404
    tcp = run(['ss', '-H', '-ltn']).stdout.decode()
    assert ':55440' not in tcp and ':55441' not in tcp and ':5432' not in tcp
    assert '127.0.0.1:3202' in tcp
    services = {}
    for service in ('thirdhand-stage.service', 'thirdhand-stage-export.service', 'postgresql@17-stage.service', 'thirdhand-probe-relay.service', 'postgresql@17-main.service', 'nginx.service'):
        values = dict(line.split('=', 1) for line in run(['systemctl', 'show', service, '-p', 'ActiveState', '-p', 'NRestarts', '-p', 'MemoryCurrent', '-p', 'ControlGroup']).stdout.decode().splitlines())
        assert values['ActiveState'] == 'active'
        events = Path('/sys/fs/cgroup' + values['ControlGroup']) / 'memory.events'
        if events.exists():
            counters = dict(line.split() for line in events.read_text().splitlines())
            assert counters.get('oom') == counters.get('oom_kill') == '0'
            values['memoryEvents'] = counters
        services[service] = values
    dump = run(['runuser', '-u', 'postgres', '--', '/usr/lib/postgresql/17/bin/pg_dump', '-h', '/run/thirdhand-stage-db', '-p', '55440', '-U', 'postgres', '-d', 'thirdhand_stage', '-Fc', '--no-owner']).stdout
    private_dump = B / 'post-C2-business.dump'
    fd = os.open(private_dump, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as out:
        out.write(dump)
    private_config = B / 'private-stage-config'
    private_config.mkdir(mode=0o700)
    for name in ('cloud.env', 'export.env'):
        shutil.copy2(Path('/etc/thirdhand-stage') / name, private_config / name)
        (private_config / name).chmod(0o600)
    cert = Path('/www/server/panel/vhost/cert/staging.uiea-thirdhand.com')
    os.utime(cert, None)
    result = dict(success=True, checkedAt=datetime.now(timezone.utc).isoformat(), maintenance503Verified=True, servicesRestarted=True, originalSiteHash=showcase_hash,
                  mainAndEdgeConfigsUnchanged=True, edgeUnauthenticatedDenied=True, modelGzip=compression,
                  historyUtc=True, manifestFilesVerified=len(manifest['files']), databaseUnixOnly=True,
                  privateDumpBytes=len(dump), restoreCloneStopped=run(['systemctl', 'is-active', 'thirdhand-stage-restore.service'], check=False).returncode != 0,
                  services=services)
    (B / 'C2-postcheck.json').write_text(json.dumps(result, indent=2))
    (B / 'C2-postcheck.json').chmod(0o600)
    print(json.dumps(result, indent=2), flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('C2_POSTCHECK_FAILED at ' + STEP + ' type ' + type(error).__name__, flush=True)
        raise SystemExit(1) from None
