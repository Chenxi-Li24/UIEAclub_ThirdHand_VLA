"""One-shot operator C2 physical base/WAL drill. Fixed isolated targets, no SDK."""
import base64
import hashlib
import json
import os
from pathlib import Path
import pwd
import shutil
import subprocess
import time
import uuid

RELEASE = '/opt/thirdhand-stage/current'
NODE = '/opt/thirdhand-stage/node-v24.22.1/bin/node'
ISOLATE = '/opt/thirdhand-stage/maintenance/restore-current/tools/operations/isolate_staging_restore.js'
PG = '/usr/lib/postgresql/17/bin/'
REPORT = Path('/var/backups/thirdhand/access-C2-20261030T125221Z')
ROOT = Path('/var/lib/thirdhand-stage-backups/C2-20261030')
CLONE_DB = 'thirdhand_stage_restore_c2_20261030'
UNIT = 'thirdhand-stage-restore.service'
STEP = 'preflight'


def run(args, **kwargs):
    return subprocess.run(args, check=True, capture_output=True, **kwargs)


def db(script, *, clone=False, database=None):
    config = dict(host='/run/thirdhand-stage-restore-db' if clone else '/run/thirdhand-stage-db',
                  port=55441 if clone else 55440, database=database or ('postgres' if clone else 'thirdhand_stage'), user='postgres', max=1)
    code = (f"const {{Pool}}=require('{RELEASE}/node_modules/pg');const pool=new Pool({json.dumps(config)});"
            "(async()=>{try{" + script + "}finally{await pool.end()}})().catch(()=>{process.stderr.write('DRILL_DB_FAILED');process.exitCode=1});")
    output = run(['runuser', '-u', 'postgres', '--', NODE, '-'], input=code.encode(), cwd=RELEASE)
    return json.loads(output.stdout)


def sql(statement, params=None, **kwargs):
    return db('console.log(JSON.stringify((await pool.query(' + json.dumps(statement) + ',' + json.dumps(params or []) + ')).rows));', **kwargs)


def save(name, value):
    p = REPORT / name
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as out:
        json.dump(value, out, indent=2)


def main():
    global STEP
    assert os.geteuid() == 0 and os.uname().sysname == 'Linux'
    assert Path(ISOLATE).is_file()
    assert not ROOT.exists() and not (Path('/etc/systemd/system') / UNIT).exists()
    fixture = json.loads((REPORT / 'history-fixture.json').read_text())
    assert (REPORT / 'C2-history-export.json').exists()
    postgres = pwd.getpwnam('postgres')
    ROOT.mkdir(mode=0o700)
    os.chown(ROOT, postgres.pw_uid, postgres.pw_gid)
    ids = {k: str(uuid.uuid4()) for k in ('boot', 'executor', 'run', 'command', 'lease', 'takeover', 'credential', 'token')}
    user = sql("SELECT id FROM auth.users WHERE username='c2_observer'")[0]['id']
    # The session uses the application repository and its existing private key.
    env = dict(line.split('=', 1) for line in Path('/etc/thirdhand-stage/cloud.env').read_text().splitlines() if '=' in line and not line.startswith('#'))
    key = env['CSRF_KEY_BASE64'].strip('"\'')
    session = db(f"const {{createSessions}}=require('{RELEASE}/platform/identity/src/sessions');const sessions=createSessions({{pool,csrfKey:Buffer.from({json.dumps(key)},'base64')}});console.log(JSON.stringify(await sessions.issue({{userId:{json.dumps(user)},clientLabel:'C2 isolated restore fixture'}})));")
    save('restore-session.private.json', session)
    STEP = 'seed-pending-synthetic-records'
    x = {**ids, 'device': fixture['device'], 'user': user, 'session': session['sessionId']}
    db('const x=' + json.dumps(x) + ";await pool.query('BEGIN');" + r"""
      await pool.query("INSERT INTO ops.device_credentials(id,device_id,certificate_serial,fingerprint_sha256,public_key,not_before,expires_at) VALUES($1,$2,$3,repeat('a',64),'C2-SYNTHETIC-NOT-A-CERTIFICATE',now()-interval '1 minute',now()+interval '1 day')",[x.credential,x.device,'synthetic-'+x.credential]);
      await pool.query("INSERT INTO ops.device_boots(boot_id,device_id,agent_version) VALUES($1,$2,'synthetic-restore')",[x.boot,x.device]);
      await pool.query("INSERT INTO ops.execution_instances(executor_epoch,device_id,boot_id,worker_instance_id) VALUES($1,$2,$3,'synthetic-restore')",[x.executor,x.device,x.boot]);
      await pool.query("INSERT INTO ops.control_leases(id,device_id,user_id,session_id,client_instance_id,boot_id,executor_epoch,lease_epoch,state,expires_at) VALUES($1,$2,$3,$4,gen_random_uuid(),$5,$6,8,'active',now()+interval '1 day')",[x.lease,x.device,x.user,x.session,x.boot,x.executor]);
      await pool.query("INSERT INTO ops.control_takeovers(id,device_id,user_id,session_id,client_instance_id,target_lease_id,target_epoch,nonce_hash,state,expires_at) VALUES($1,$2,$3,$4,gen_random_uuid(),$5,8,repeat('b',64),'pending',now()+interval '1 day')",[x.takeover,x.device,x.user,x.session,x.lease]);
      await pool.query("INSERT INTO ops.runs(id,device_id,boot_id,actor_user_id,actor_kind,actor_display_name,source,status,versions) VALUES($1,$2,$3,$4,'user','C2 Synthetic Restore','dummy','running',jsonb_build_object('synthetic',true))",[x.run,x.device,x.boot,x.user]);
      await pool.query("INSERT INTO ops.commands(command_id,run_id,device_id,boot_id,executor_epoch,lease_epoch,sequence,opcode,schema_version,parameters,expires_at,state) VALUES($1,$2,$3,$4,$5,8,1,'synthetic_noop',1,jsonb_build_object('synthetic',true),now()+interval '1 day','accepted')",[x.command,x.run,x.device,x.boot,x.executor]);
      await pool.query("INSERT INTO auth.one_time_tokens(id,user_id,purpose,token_hash,expires_at) VALUES($1,$2,'reset_password',repeat('c',64),now()+interval '1 day')",[x.token,x.user]);
      await pool.query("INSERT INTO security.audit_events(event_code,outcome,context) VALUES('c2.restore.before_base','success',jsonb_build_object('synthetic',true))");
      await pool.query('COMMIT');console.log('{}');
    """)
    save('restore-fixture.json', x)
    floor = {fixture['device']: '9007199254741001'}
    save('restore-epoch-floors.json', floor)  # Independent of the database/physical backup.
    STEP = 'base-backup'
    started = time.monotonic()
    run(['runuser', '-u', 'postgres', '--', PG + 'pg_basebackup', '-h', '/run/thirdhand-stage-db', '-p', '55440', '-U', 'postgres', '-D', str(ROOT / 'base'), '-X', 'stream', '-c', 'fast', '--no-password'], timeout=180)
    run(['runuser', '-u', 'postgres', '--', PG + 'pg_verifybackup', str(ROOT / 'base')], timeout=120)
    base_seconds = time.monotonic() - started
    assert sql("SELECT count(*)::int n FROM security.audit_events WHERE event_code='c2.restore.after_base'")[0]['n'] == 0
    STEP = 'post-base-wal'
    sql("INSERT INTO security.audit_events(event_code,outcome,context) VALUES('c2.restore.after_base','success',jsonb_build_object('synthetic',true))")
    target = 'c2_after_base_20261030'
    lsn = sql('SELECT pg_create_restore_point($1)::text lsn', [target])[0]['lsn']
    segment = sql('SELECT pg_walfile_name($1::pg_lsn) segment', [lsn])[0]['segment']
    sql('SELECT pg_switch_wal()')
    deadline = time.monotonic() + 60
    while not (ROOT.parent / 'wal' / segment).is_file():
        assert time.monotonic() < deadline, 'WAL_ARCHIVE_TIMEOUT'
        time.sleep(.5)
    STEP = 'isolated-clone'
    data = ROOT / 'restore'
    run(['cp', '-a', str(ROOT / 'base') + '/.', str(data)])
    config = ROOT / 'restore.conf'
    config.write_text("\n".join([
        f"data_directory='{data}'", f"hba_file='{ROOT / 'pg_hba.conf'}'", f"ident_file='{ROOT / 'pg_ident.conf'}'",
        "listen_addresses=''", "port=55441", "unix_socket_directories='/run/thirdhand-stage-restore-db'", "unix_socket_permissions=0700",
        "shared_buffers='32MB'", "max_connections=20", "work_mem='1MB'", "archive_mode=off", "hot_standby=on",
        f"restore_command='cp {ROOT.parent / 'wal'}/%f %p'", f"recovery_target_name='{target}'", "recovery_target_action='promote'",
        "logging_collector=off", "log_statement='none'", "log_min_error_statement='panic'", '']))
    (ROOT / 'pg_hba.conf').write_text('local all postgres peer\nlocal all all reject\n')
    (ROOT / 'pg_ident.conf').write_text('')
    (data / 'recovery.signal').touch()
    for p in [config, ROOT / 'pg_hba.conf', ROOT / 'pg_ident.conf', data / 'recovery.signal']:
        p.chmod(0o600)
        os.chown(p, postgres.pw_uid, postgres.pw_gid)
    unit = Path('/etc/systemd/system') / UNIT
    unit.write_text(f"""[Unit]
Description=Offline C2 restore drill only
[Service]
User=postgres
Group=postgres
ExecStart={PG}postgres -D {data} -c config_file={config}
RuntimeDirectory=thirdhand-stage-restore-db
RuntimeDirectoryMode=0700
KillSignal=SIGINT
TimeoutStopSec=60
NoNewPrivileges=true
PrivateTmp=true
PrivateDevices=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths={ROOT} /run/thirdhand-stage-restore-db
RestrictAddressFamilies=AF_UNIX
MemoryMax=256M
TasksMax=64
CPUQuota=50%
""")
    run(['systemd-analyze', 'verify', str(unit)])
    run(['systemctl', 'daemon-reload'])
    run(['systemctl', 'start', UNIT])
    try:
        deadline = time.monotonic() + 60
        while True:
            try:
                recovering = sql('SELECT pg_is_in_recovery() recovering', clone=True)[0]['recovering']
                if not recovering:
                    break
            except subprocess.CalledProcessError:
                pass
            assert time.monotonic() < deadline, 'RESTORE_START_TIMEOUT'
            time.sleep(.5)
        sql(f'ALTER DATABASE thirdhand_stage RENAME TO {CLONE_DB}', clone=True)
        kwargs = dict(clone=True, database=CLONE_DB)
        assert sql("SELECT count(*)::int n FROM security.audit_events WHERE event_code='c2.restore.after_base'", **kwargs)[0]['n'] == 1
        assert sql("SELECT count(*)::int n FROM security.audit_events WHERE event_code='c2.restore.before_base'", **kwargs)[0]['n'] == 1
        STEP = 'withdraw-restored-authority'
        code = f"""const assert=require('node:assert/strict'),crypto=require('node:crypto');
        const {{isolateStagingRestore}}=require('{ISOLATE}');
        const {{createSessions}}=require('{RELEASE}/platform/identity/src/sessions');
        const sessions=createSessions({{pool,csrfKey:Buffer.from({json.dumps(key)},'base64')}}),request={{headers:{{cookie:{json.dumps(session['cookie'])}}}}};
        assert.ok(await sessions.resolveSession(request));
        await assert.rejects(isolateStagingRestore(pool,{{epochFloors:{{}},confirmation:'ISOLATE_STAGING_RESTORE'}}),{{code:'RESTORE_EPOCH_FLOOR_REQUIRED'}});
        assert.ok(await sessions.resolveSession(request));
        const before=(await pool.query('SELECT payload_bytes FROM telemetry.ingest_batch_payloads WHERE batch_id=$1',[{json.dumps(fixture['batch'])}])).rows[0].payload_bytes;
        await isolateStagingRestore(pool,{{epochFloors:{json.dumps(floor)},confirmation:'ISOLATE_STAGING_RESTORE'}});
        assert.equal(await sessions.resolveSession(request),null);
        const after=(await pool.query('SELECT payload_bytes FROM telemetry.ingest_batch_payloads WHERE batch_id=$1',[{json.dumps(fixture['batch'])}])).rows[0].payload_bytes;
        assert.equal(crypto.createHash('sha256').update(before).digest('hex'),{json.dumps(fixture['rawDigest'])});assert.deepEqual(before,after);
        console.log(JSON.stringify({{oldSessionRejected:true,missingFloorRolledBack:true,rawBytesUnchanged:true}}));"""
        checks = db(code, **kwargs)
        checks.update(sql("""SELECT
          (SELECT bool_and(revoked_at IS NOT NULL) FROM auth.sessions) sessions_revoked,
          (SELECT bool_and(consumed_at IS NOT NULL) FROM auth.one_time_tokens) tokens_consumed,
          (SELECT bool_and(revoked_at IS NOT NULL) FROM auth.mfa_credentials) mfa_revoked,
          (SELECT bool_and(revoked_at IS NOT NULL) FROM ops.device_credentials) credentials_revoked,
          (SELECT bool_and(NOT enabled) FROM ops.devices) devices_disabled,
          (SELECT control_epoch::text FROM ops.devices WHERE id=$1) epoch,
          (SELECT state FROM ops.control_leases WHERE id=$2) lease,
          (SELECT state FROM ops.control_takeovers WHERE id=$3) takeover,
          (SELECT state FROM ops.commands WHERE command_id=$4) command,
          (SELECT status FROM ops.runs WHERE id=$5) run,
          (SELECT count(*)::int FROM auth.users) users,
          (SELECT count(*)::int FROM telemetry.robot_samples) samples,
          (SELECT bool_and(status='expired') FROM ops.export_jobs) exports_expired
        """, [fixture['device'], ids['lease'], ids['takeover'], ids['command'], ids['run']], **kwargs)[0])
        assert all(checks[k] is True for k in ('oldSessionRejected', 'missingFloorRolledBack', 'rawBytesUnchanged', 'sessions_revoked', 'tokens_consumed', 'mfa_revoked', 'credentials_revoked', 'devices_disabled', 'exports_expired'))
        assert checks['epoch'] == '9007199254741002'
        assert checks['lease'] == checks['takeover'] == 'failed'
        assert checks['command'] == checks['run'] == 'unknown'
        assert checks['users'] >= 3 and checks['samples'] == 3
        report = dict(success=True, syntheticOnly=True, realDeviceHandshakeTested=False, hardwareCalls=0,
                      baseBackupVerified=True, baseBackupSeconds=round(base_seconds, 3), walSegment=segment,
                      namedRecoveryPointReached=True, cloneDatabase=CLONE_DB, cloneUnixOnly=True,
                      backupBytes=sum(p.stat().st_size for p in (ROOT / 'base').rglob('*') if p.is_file()), checks=checks)
        save('C2-restore-drill.json', report)
        print(json.dumps(report, indent=2), flush=True)
    finally:
        run(['systemctl', 'stop', UNIT])
    STEP = 'retire-synthetic-pending-fixture'
    # Preserve all records in the live staging DB, with explicit synthetic terminal states.
    db('const x=' + json.dumps(x) + r""";
      await pool.query('BEGIN');
      await pool.query("UPDATE ops.control_leases SET state='failed',released_at=now(),release_reason='C2_SYNTHETIC_DRILL_ENDED' WHERE id=$1",[x.lease]);
      await pool.query("UPDATE ops.control_takeovers SET state='failed' WHERE id=$1",[x.takeover]);
      await pool.query("UPDATE ops.commands SET state='unknown',result=jsonb_build_object('code','C2_SYNTHETIC_DRILL_ENDED') WHERE command_id=$1",[x.command]);
      await pool.query("UPDATE ops.runs SET status='unknown',ended_at=now() WHERE id=$1",[x.run]);
      await pool.query('UPDATE ops.device_credentials SET revoked_at=now() WHERE id=$1',[x.credential]);
      await pool.query('UPDATE ops.execution_instances SET ended_at=now() WHERE executor_epoch=$1',[x.executor]);
      await pool.query('UPDATE ops.device_boots SET ended_at=now() WHERE boot_id=$1',[x.boot]);
      await pool.query('UPDATE auth.one_time_tokens SET consumed_at=now() WHERE id=$1',[x.token]);
      await pool.query("UPDATE auth.sessions SET revoked_at=now(),revocation_reason='C2_SYNTHETIC_DRILL_ENDED' WHERE id=$1",[x.session]);
      await pool.query('COMMIT');console.log('{}');
    """)
    print('C2_RESTORE_CLONE_STOPPED_LIVE_FIXTURE_RETIRED', flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('C2_RESTORE_FAILED at ' + STEP + ' type ' + type(error).__name__, flush=True)
        raise SystemExit(1) from None
