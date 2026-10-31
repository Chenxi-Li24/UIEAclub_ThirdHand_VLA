"""Apply the fixed, immutable maintenance tool only to the offline C2 clone."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import pwd
import subprocess
import time

B = Path('/var/backups/thirdhand/access-C2-20261030T125221Z')
ROOT = Path('/var/lib/thirdhand-stage-backups/C2-20261030')
DB = 'thirdhand_stage_restore_c2_20261030'
NODE = '/opt/thirdhand-stage/node-v24.22.1/bin/node'
UNIT = 'thirdhand-stage-restore.service'


def run(args, **kwargs):
    return subprocess.run(args, check=True, capture_output=True, **kwargs)


def query(text, *, live=False):
    return run(['runuser', '-u', 'postgres', '--', '/usr/lib/postgresql/17/bin/psql', '-h', '/run/thirdhand-stage-db' if live else '/run/thirdhand-stage-restore-db', '-p', '55440' if live else '55441', '-U', 'postgres', '-d', 'thirdhand_stage' if live else DB, '-v', 'ON_ERROR_STOP=1', '-Atc', text]).stdout.decode().strip()


def main():
    assert os.geteuid() == 0 and not (B / 'C2-restore-mfa.json').exists()
    tool = Path('/opt/thirdhand-stage/maintenance/restore-current').resolve(strict=True)
    manifest = json.loads((tool / 'manifest.json').read_text())
    assert all(hashlib.sha256((tool / name).read_bytes()).hexdigest() == digest for name, digest in manifest['files'].items())
    live_mfa_count = query('SELECT count(*) FROM auth.mfa_credentials WHERE revoked_at IS NULL', live=True)
    p = ROOT / 'epoch-floors.json'
    p.write_bytes((B / 'restore-epoch-floors.json').read_bytes())
    user = pwd.getpwnam('postgres')
    p.chmod(0o600)
    os.chown(p, user.pw_uid, user.pw_gid)
    run(['systemctl', 'start', UNIT])
    try:
        deadline = time.monotonic() + 15
        while True:
            try:
                assert query('SELECT pg_is_in_recovery()') == 'f'
                break
            except subprocess.CalledProcessError:
                assert time.monotonic() < deadline
                time.sleep(.2)
        active = int(query('SELECT count(*) FROM auth.mfa_credentials WHERE revoked_at IS NULL'))
        assert active > 0
        digest_before = query("SELECT encode(sha256(payload_bytes),'hex') FROM telemetry.ingest_batch_payloads ORDER BY batch_id")
        url = 'postgresql://postgres@localhost:55441/' + DB + '?host=/run/thirdhand-stage-restore-db'
        result = run(['runuser', '-u', 'postgres', '--', 'env', 'MIGRATION_DATABASE_URL=' + url, NODE,
                      str(tool / 'tools/operations/isolate_staging_restore.js'), str(p), 'ISOLATE_STAGING_RESTORE'], cwd=tool)
        assert json.loads(result.stdout)['controlAuthorized'] is False
        assert query('SELECT count(*) FROM auth.mfa_credentials WHERE revoked_at IS NULL') == '0'
        assert digest_before == query("SELECT encode(sha256(payload_bytes),'hex') FROM telemetry.ingest_batch_payloads ORDER BY batch_id")
        assert query('SELECT count(*) FROM auth.mfa_credentials WHERE revoked_at IS NULL', live=True) == live_mfa_count
        value = dict(success=True, checkedAt=datetime.now(timezone.utc).isoformat(), cloneOnly=True,
                     previouslyActiveMfaCredentials=active, remainingActiveMfaCredentials=0, rawBytesUnchanged=True,
                     tool=str(tool), toolFilesVerified=manifest['files'], liveStagingMfaUnchanged=True)
        (B / 'C2-restore-mfa.json').write_text(json.dumps(value, indent=2))
        (B / 'C2-restore-mfa.json').chmod(0o600)
        print(json.dumps(value, indent=2), flush=True)
    finally:
        run(['systemctl', 'stop', UNIT])


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('C2_RESTORE_MFA_FAILED ' + type(error).__name__, flush=True)
        raise SystemExit(1) from None
