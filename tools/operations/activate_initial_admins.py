"""Pinned initial-admin phase only. Review by default; --apply requires explicit approval."""
import argparse
import base64
from contextlib import contextmanager
import fcntl
import hashlib
import http.client
import json
import os
from pathlib import Path
import pwd
import selectors
import shlex
import shutil
import subprocess
import time
import uuid

ROOT = Path('/var/backups/thirdhand/initial-admins-20261101')
BASE = Path('/opt/thirdhand-stage')
OLD = BASE / 'releases/6edc4258818b6b65'
OLD_MANIFEST = '6edc4258818b6b65cc305a15af6b075a217f7b836e7d51e90ec836c5a1add0bd'
PACKAGE_SHA = 'ff7ea312a93fef1582051d4a4ed3b6c421291e8653781f386922516c098b5c68'
LIST_SHA = 'ceed233a5d9115f045ecae46e99b9d9465975e0e439996ada9c7d3dc08206749'
ENV = Path('/etc/thirdhand-stage/cloud.env')
NODE = BASE / 'node-v24.22.1/bin/node'
PG = ['runuser', '-u', 'postgres', '--', '/usr/lib/postgresql/17/bin/psql', '-X', '-q', '-At', '-P', 'pager=off', '-v', 'ON_ERROR_STOP=1', '-h', '/run/thirdhand-stage-db', '-p', '55440', '-d', 'thirdhand_stage']
MIGRATION_URL = 'postgresql://postgres@localhost/thirdhand_stage?host=%2Frun%2Fthirdhand-stage-db&port=55440'
FILES = {'platform/identity/src/accounts.js','platform/identity/src/initial-admins.js','platform/storage/src/admin-access.js','platform/storage/migrations/010-admin-applications.sql'}
SHARED_LOCK = Path('/var/backups/thirdhand/access-C3d-compact-camera-20261031/installer.lock')


def sha(value):
    return hashlib.sha256(value).hexdigest()


def run(args, **kwargs):
    return subprocess.run([str(arg) for arg in args], check=True, capture_output=True, **kwargs)


def sql(value):
    return run(PG, input=value.encode()).stdout.decode().strip()


def idle():
    assert sql("SELECT count(*) FROM ops.control_leases WHERE state IN ('requested','active','revoking');") == '0'


@contextmanager
def quiescent_lease_admission():
    # Drain existing lease writes and block new ones until the API is fully stopped.
    process = subprocess.Popen(PG, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
    try:
        process.stdin.write("BEGIN; SET LOCAL lock_timeout='5s'; LOCK TABLE ops.control_leases IN SHARE MODE; SELECT 'LEASE_GUARD_READY:'||count(*) FROM ops.control_leases WHERE state IN ('requested','active','revoking');\n")
        process.stdin.flush()
        with selectors.DefaultSelector() as ready:
            ready.register(process.stdout, selectors.EVENT_READ)
            assert ready.select(10), 'LEASE_GUARD_TIMEOUT'
        assert process.stdout.readline().strip() == 'LEASE_GUARD_READY:0', 'LEASE_GUARD_OCCUPIED'
        yield
    finally:
        if process.poll() is None:
            try:
                process.communicate('ROLLBACK;\n\\q\n', timeout=10)
            except (OSError, subprocess.TimeoutExpired):
                process.terminate()
                process.communicate(timeout=10)


def durable_import_state():
    try:
        if not sql("SELECT to_regclass('auth.initial_admin_batch');"):
            return False
        # Wait for a possibly still-finishing importer before a fresh snapshot read.
        state = sql("BEGIN ISOLATION LEVEL READ COMMITTED; SET LOCAL lock_timeout='10s'; SELECT pg_advisory_xact_lock(240103,2); SELECT count(*) FROM auth.initial_admin_batch; COMMIT;")
        return state != '0'
    except Exception:
        # An uncertain commit must never trigger rollback to an unaware old handler.
        return None


def private(path, value):
    with os.fdopen(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), 'wb') as output:
        output.write(value)


def config(value):
    return {key: shlex.split(raw)[0] if shlex.split(raw) else ''
            for line in value.decode().splitlines() if line and not line.startswith('#')
            for key, raw in [line.split('=', 1)]}


def select_release(path):
    temporary = BASE / ('current.initial-admins-' + uuid.uuid4().hex)
    temporary.symlink_to(path)
    os.replace(temporary, BASE / 'current')


def set_env(value):
    original = ENV.stat()
    temporary = ENV.with_name('.cloud.env.initial-admins-' + uuid.uuid4().hex)
    private(temporary, value)
    os.chown(temporary, original.st_uid, original.st_gid)
    os.chmod(temporary, original.st_mode & 0o777)
    os.replace(temporary, ENV)


def health():
    for _ in range(40):
        try:
            connection = http.client.HTTPConnection('127.0.0.1', 3202, timeout=2)
            connection.request('GET', '/healthz')
            response = connection.getresponse()
            ok = response.status == 200 and json.loads(response.read()).get('deviceControl') == 'explicit-read-only'
            connection.close()
            if ok:
                return
        except (OSError, ValueError, http.client.HTTPException):
            pass
        time.sleep(.25)
    raise RuntimeError('API_HEALTH_FAILED')


def review():
    assert os.geteuid() == 0
    assert (BASE / 'current').resolve() == OLD
    raw_manifest = (OLD / 'manifest.json').read_bytes()
    assert sha(raw_manifest) == OLD_MANIFEST
    manifest = json.loads(raw_manifest)
    actual = {p.relative_to(OLD).as_posix() for p in OLD.rglob('*') if p.is_file()}
    assert actual == set(manifest['files']) | {'manifest.json'}
    assert all(not p.is_symlink() for p in OLD.rglob('*'))
    assert all(sha((OLD / name).read_bytes()) == digest for name, digest in manifest['files'].items())
    assert sha((ROOT / 'package.json').read_bytes()) == PACKAGE_SHA
    package = json.loads((ROOT / 'package.json').read_bytes())
    assert package['format'] == 1 and package['oldManifestSha256'] == OLD_MANIFEST
    assert set(package['files']) == FILES
    for name, item in package['files'].items():
        assert item['before'] == manifest['files'].get(name)
        assert sha(base64.b64decode(item['contents'], validate=True)) == item['after']
    idle()
    assert not sql("SELECT to_regclass('auth.initial_admin_allowlist');")
    assert sql("SELECT count(*) FROM public.thirdhand_schema_migrations;") == '9'
    assert sha((ROOT / 'initial-admins.private.json').read_bytes()) == LIST_SHA
    addresses = json.loads((ROOT / 'initial-admins.private.json').read_bytes())
    assert len(addresses) == 8 and len(set(addresses)) == 8
    assert all(address == address.strip().lower() and '@' in address for address in addresses)
    original = ENV.read_bytes()
    values = config(original)
    recipients = sorted(set(addresses) | {value.strip().lower() for value in json.loads(values['SMTP_ALLOWED_RECIPIENTS_JSON'])})
    assert values.get('REGISTRATION_MODE', 'restricted') == 'restricted' and len(recipients) <= 10
    assert run(['systemctl','is-active','thirdhand-stage.service']).stdout.strip() == b'active'
    print(json.dumps({'reviewed':True,'currentRelease':str(OLD),'initialEmails':8,'temporaryMailRecipients':len(recipients),'changedSourceFiles':len(FILES),'controlLeases':0,'initialBatchNotImported':True}))
    return package, manifest, original, recipients


def main(apply=False):
    os.umask(0o077)
    with (ROOT / 'operation.lock').open('a') as lock, SHARED_LOCK.open('r+') as shared_lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(shared_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        package, manifest, original, recipients = review()
        if not apply:
            return
        assert not (ROOT / 'applied.json').exists()
        private(ROOT / 'cloud.env.before', original)
        with (ROOT / 'database.before.dump').open('xb') as output:
            subprocess.run(['runuser','-u','postgres','--','/usr/lib/postgresql/17/bin/pg_dump','-h','/run/thirdhand-stage-db','-p','55440','-d','thirdhand_stage','-Fc'],stdout=output,check=True)
        digest = sha((ROOT / 'package.json').read_bytes())
        destination = BASE / ('releases/initial-admins-' + digest[:16])
        assert not destination.exists()
        shutil.copytree(OLD, destination)
        for name, item in package['files'].items():
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(base64.b64decode(item['contents'], validate=True))
            target.chmod(0o644)
            manifest['files'][name] = item['after']
        (destination / 'manifest.json').write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n')
        assert all(sha((destination / name).read_bytes()) == value for name, value in manifest['files'].items())
        for name in FILES:
            if name.endswith('.js'):
                run([NODE, '--check', destination / name])
        # Restrict code and DB effects to the account service. Never change robot/media units.
        switched = False
        imported = False
        owned_env = original
        try:
            assert (BASE / 'current').resolve() == OLD and ENV.read_bytes() == original
            with quiescent_lease_admission():
                run(['systemctl','stop','thirdhand-stage.service'])
            idle()
            run(['runuser','-u','postgres','--','env','MIGRATION_DATABASE_URL=' + MIGRATION_URL,NODE,destination / 'platform/storage/src/migrate-cli.js'])
            sql('GRANT SELECT ON auth.initial_admin_batch,auth.initial_admin_allowlist TO "thirdhand-stage"; GRANT UPDATE(user_id,consumed_at) ON auth.initial_admin_allowlist TO "thirdhand-stage"; GRANT SELECT,INSERT,UPDATE ON auth.admin_applications TO "thirdhand-stage";')
            os_user = pwd.getpwnam('postgres')
            temporary = Path('/run/thirdhand-initial-admins-20261101')
            temporary.mkdir(mode=0o700)
            os.chown(temporary, os_user.pw_uid, os_user.pw_gid)
            private(temporary / 'initial-admins.json', (ROOT / 'initial-admins.private.json').read_bytes())
            os.chown(temporary / 'initial-admins.json', os_user.pw_uid, os_user.pw_gid)
            quote = lambda value: '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'
            lines = original.decode().splitlines()
            replacement = 'SMTP_ALLOWED_RECIPIENTS_JSON=' + quote(json.dumps(recipients, separators=(',', ':')))
            assert sum(line.startswith('SMTP_ALLOWED_RECIPIENTS_JSON=') for line in lines) == 1
            next_env = ('\n'.join(replacement if line.startswith('SMTP_ALLOWED_RECIPIENTS_JSON=') else line for line in lines) + '\n').encode()
            before_values, after_values = config(original), config(next_env)
            assert {k:v for k,v in before_values.items() if k!='SMTP_ALLOWED_RECIPIENTS_JSON'} == {k:v for k,v in after_values.items() if k!='SMTP_ALLOWED_RECIPIENTS_JSON'}
            set_env(next_env)
            owned_env = next_env
            select_release(destination)
            switched = True
            run(['systemctl','start','thirdhand-stage.service'])
            health()
            # Import only once the new email-verification handler is healthy.
            result = run(['runuser','-u','postgres','--','env','MIGRATION_DATABASE_URL=' + MIGRATION_URL,NODE,destination / 'platform/identity/src/initial-admins.js',temporary / 'initial-admins.json','--confirm-initial-admins'])
            imported = True
            private(ROOT / 'import-result.log', result.stdout)
            summary = json.loads(sql("SELECT json_build_object('listed',(SELECT count(*) FROM auth.initial_admin_allowlist),'claimed',(SELECT count(*) FROM auth.initial_admin_allowlist WHERE consumed_at IS NOT NULL),'sealed',(SELECT count(*) FROM auth.initial_admin_batch),'pending',(SELECT count(*) FROM auth.initial_admin_allowlist WHERE consumed_at IS NULL));"))
            assert summary['listed'] == 8 and summary['sealed'] == 1
            assert (BASE / 'current').resolve() == destination
            health()
            report = {'applied':True,'phase':'initial-admins-only','release':str(destination),'sourceFilesVerified':len(manifest['files']),'emailVerificationRequired':True,'mfaRequired':True,'observerRegistration':'temporarily restricted until phase 2',**summary}
            private(ROOT / 'applied.json', json.dumps(report, indent=2).encode())
            print(json.dumps(report))
        except Exception:
            durable = True if imported else durable_import_state()
            rollback_allowed = durable is False and ENV.read_bytes() == owned_env and (BASE / 'current').resolve() in (OLD, destination)
            if rollback_allowed:
                with quiescent_lease_admission():
                    run(['systemctl','stop','thirdhand-stage.service'])
                    if switched:
                        select_release(OLD)
                    set_env(original)
                    run(['systemctl','start','thirdhand-stage.service'])
                health()
            private(ROOT / 'failed.json', json.dumps({'failed':True,'importCommitted':durable,'schemaRetained':True,'manualReviewRequired':not rollback_allowed}).encode())
            raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    try:
        main(args.apply)
    except Exception as error:
        print(json.dumps({'failed':True,'type':type(error).__name__,'reviewPrivateLogs':True}))
        raise SystemExit(1)
