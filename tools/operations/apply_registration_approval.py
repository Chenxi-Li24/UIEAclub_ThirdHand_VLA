"""Account registration/application rollout. Preserves the already-imported initial batch."""
import argparse
import base64
from contextlib import contextmanager
import fcntl
import hashlib
import http.client
import json
import os
from pathlib import Path
import runpy
import selectors
import shutil
import subprocess
import uuid

ROOT = Path('/var/backups/thirdhand/registration-approval-20261101')
BASE = Path('/opt/thirdhand-stage')
OLD = BASE / 'releases/initial-admins-ff7ea312a93fef15'
ENV = Path('/etc/thirdhand-stage/cloud.env')
NODE = BASE / 'node-v24.22.1/bin/node'
PACKAGE_SHA = 'a570d928578cb5bb49dda7590c350d10e5c63f46ed314f959533828c957c4e9d'
assert hashlib.sha256(Path('/var/backups/thirdhand/initial-admins-20261101/apply.py').read_bytes()).hexdigest() == '66f09cc541d3082215ee6b77c59b8616ab595dd434242d60f645fb444f519eee'
H = runpy.run_path('/var/backups/thirdhand/initial-admins-20261101/apply.py')
FILES = {'apps/web/public/js/account-security.js','apps/web/public/js/admin-access.js','apps/web/public/js/i18n-cloud-catalog.js','platform/identity/src/accounts.js','platform/identity/src/bootstrap-admin.js','platform/storage/src/users.js','services/cloud-api/src/config.js','services/cloud-api/src/server.js','services/cloud-api/src/workspace-pages.js','services/cloud-api/src/routes/admin-applications.js'}


def sha(value):
    return hashlib.sha256(value).hexdigest()


def request(path, body=None):
    connection = http.client.HTTPConnection('127.0.0.1', 3202, timeout=5)
    headers = {}
    if body is not None:
        body = json.dumps(body)
        headers = {'Content-Type':'application/json','Origin':'https://staging.uiea-thirdhand.com'}
    connection.request('POST' if body is not None else 'GET', path, body, headers)
    response = connection.getresponse()
    result = response.status, response.read()
    connection.close()
    return result


def check_release(root, manifest):
    assert root.resolve() == root and root.parent == BASE / 'releases'
    assert all(not child.is_symlink() for child in root.rglob('*'))
    assert {child.relative_to(root).as_posix() for child in root.rglob('*') if child.is_file()} == set(manifest['files']) | {'manifest.json'}
    assert all(sha((root / name).read_bytes()) == digest for name,digest in manifest['files'].items())


def initial_batch_snapshot():
    return H['sql']("SELECT json_build_object('seal',(SELECT row_to_json(b) FROM auth.initial_admin_batch b),'members',(SELECT json_agg(email ORDER BY email) FROM auth.initial_admin_allowlist));")


def applications_snapshot():
    return H['sql']("SELECT count(*)::text||':'||COALESCE(max(created_at)::text,'')||':'||COALESCE(max(reviewed_at)::text,'') FROM auth.admin_applications;")


@contextmanager
def quiescent_applications():
    process=subprocess.Popen(H['PG'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,bufsize=1)
    try:
        process.stdin.write("BEGIN; SET LOCAL lock_timeout='5s'; LOCK TABLE auth.admin_applications IN SHARE MODE; SELECT 'APPLICATION_GUARD_READY';\n")
        process.stdin.flush()
        with selectors.DefaultSelector() as ready:
            ready.register(process.stdout,selectors.EVENT_READ)
            assert ready.select(10), 'APPLICATION_GUARD_TIMEOUT'
        assert process.stdout.readline().strip()=='APPLICATION_GUARD_READY', 'APPLICATION_GUARD_UNAVAILABLE'
        yield
    finally:
        if process.poll() is None:
            try:
                process.communicate('ROLLBACK;\n\\q\n',timeout=10)
            except (OSError,subprocess.TimeoutExpired):
                process.terminate();process.communicate(timeout=10)


def runtime_check(root, environment):
    script = """const c=require('./services/cloud-api/src/config').loadCloudConfig();
if(c.smtp.allowedRecipients!==undefined)throw Error('REGISTRATION_NOT_OPEN');
const mail=require('./platform/identity/src/smtp').createSmtpMailer(c.smtp);
try{mail.ensureAvailable({to:'new-observer@example.invalid'});console.log('OPEN_MAIL_POLICY_VALIDATED_NO_SEND');}finally{mail.close();} """
    return H['run']([NODE,'-e',script],cwd=root,env={**os.environ,**H['config'](environment)}).stdout.decode().strip()


def review():
    assert os.geteuid() == 0
    assert (BASE / 'current').resolve() == OLD
    assert sha((ROOT / 'package.json').read_bytes()) == PACKAGE_SHA
    package = json.loads((ROOT / 'package.json').read_bytes())
    assert package['format'] == 1 and set(package['files']) == FILES
    # Pin the prior immutable manifest through the first rollout's verified report.
    prior = json.loads(Path('/var/backups/thirdhand/initial-admins-20261101/applied.json').read_text())
    assert prior['release'] == str(OLD) and prior['listed'] == 8 and prior['sealed'] == 1
    manifest = json.loads((OLD / 'manifest.json').read_bytes())
    assert sha((OLD / 'manifest.json').read_bytes()) == package['oldManifestSha256']
    check_release(OLD,manifest)
    for name,item in package['files'].items():
        assert manifest['files'].get(name) == item['before']
        assert sha(base64.b64decode(item['contents'],validate=True)) == item['after']
    initial = initial_batch_snapshot()
    snapshot = json.loads(initial)
    assert snapshot['seal']['member_count'] == 8 and len(snapshot['members']) == 8
    H['idle']()
    environment = ENV.read_bytes()
    assert H['config'](environment).get('REGISTRATION_MODE','restricted') == 'restricted'
    assert request('/healthz')[0] == 200
    print(json.dumps({'reviewed':True,'sourceFiles':len(FILES),'initialBatchPreserved':True,'noActiveControl':True,'currentRelease':str(OLD)}))
    return package,manifest,environment,initial


def main(apply=False):
    os.umask(0o077)
    with H['SHARED_LOCK'].open('r+') as shared, (ROOT / 'operation.lock').open('a') as own:
        fcntl.flock(shared,fcntl.LOCK_EX|fcntl.LOCK_NB)
        fcntl.flock(own,fcntl.LOCK_EX|fcntl.LOCK_NB)
        package,manifest,original,initial = review()
        initial_applications = applications_snapshot()
        if not apply:
            return
        assert not (ROOT / 'applied.json').exists()
        H['private'](ROOT / 'cloud.env.before',original)
        with (ROOT / 'database.before.dump').open('xb') as output:
            subprocess.run(['runuser','-u','postgres','--','/usr/lib/postgresql/17/bin/pg_dump','-h','/run/thirdhand-stage-db','-p','55440','-d','thirdhand_stage','-Fc'],stdout=output,check=True)
        destination = BASE / ('releases/registration-approval-' + sha((ROOT / 'package.json').read_bytes())[:16])
        assert not destination.exists()
        shutil.copytree(OLD,destination)
        for name,item in package['files'].items():
            target=destination/name
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(base64.b64decode(item['contents'],validate=True))
            target.chmod(0o644)
            manifest['files'][name]=item['after']
        (destination/'manifest.json').write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n')
        check_release(destination,manifest)
        for name in FILES:
            H['run']([NODE,'--check',destination/name])
        lines=[line for line in original.decode().splitlines() if not line.startswith(('SMTP_ALLOWED_RECIPIENTS_JSON=','REGISTRATION_MODE='))]
        next_env=('\n'.join(lines)+'\nREGISTRATION_MODE=open\n').encode()
        before=H['config'](original);after=H['config'](next_env)
        assert {k:v for k,v in before.items() if k not in ('SMTP_ALLOWED_RECIPIENTS_JSON','REGISTRATION_MODE')} == {k:v for k,v in after.items() if k!='REGISTRATION_MODE'}
        assert runtime_check(destination,next_env)=='OPEN_MAIL_POLICY_VALIDATED_NO_SEND'
        switched=False
        owned_env=original
        try:
            assert (BASE/'current').resolve()==OLD and ENV.read_bytes()==original
            with H['quiescent_lease_admission']():
                H['run'](['systemctl','stop','thirdhand-stage.service'])
            H['idle']()
            H['set_env'](next_env)
            owned_env=next_env
            H['select_release'](destination)
            switched=True
            H['run'](['systemctl','start','thirdhand-stage.service'])
            H['health']()
            assert initial_batch_snapshot()==initial
            for route in ['/api/v1/me/admin-application','/api/v1/admin/applications','/control-assets/js/admin-access.js']:
                assert request(route)[0]==401
            # Invalid password fails before DB insert or mail send; the new email is not allowlisted.
            status,body=request('/api/v1/auth/register',{'username':'open_policy_probe','email':'new-observer@example.invalid','displayName':'Policy probe','password':'short'})
            assert status==400 and json.loads(body)['error']=='INVALID_PASSWORD'
            H['idle']()
            pid=int(H['run'](['systemctl','show','thirdhand-stage.service','--no-pager','-p','MainPID','--value']).stdout)
            assert Path('/proc/%d/cwd'%pid).resolve()==destination
            process_env=dict(value.decode().split('=',1) for value in Path('/proc/%d/environ'%pid).read_bytes().split(b'\0') if b'=' in value)
            assert process_env.get('REGISTRATION_MODE')=='open' and 'SMTP_ALLOWED_RECIPIENTS_JSON' not in process_env
            check_release(destination,manifest)
            report={'applied':True,'release':str(destination),'sourceFilesVerified':len(manifest['files']),'registration':'open Observer after email verification','adminApproval':'different admin with fresh password and MFA','initialBatchPreserved':True,'protectedRoutesUnauthenticated':401,'registrationPolicyProbe':'INVALID_PASSWORD, no account created or mail sent','apiPid':pid}
            H['private'](ROOT/'applied.json',json.dumps(report,indent=2).encode())
            print(json.dumps(report))
        except Exception:
            eligible=(BASE/'current').resolve() in (OLD,destination) and ENV.read_bytes()==owned_env and initial_batch_snapshot()==initial
            rollback=False
            if eligible:
                with H['quiescent_lease_admission'](),quiescent_applications():
                    H['run'](['systemctl','stop','thirdhand-stage.service'])
                    # Drain committed application activity before deciding on rollback.
                    rollback=applications_snapshot()==initial_applications and ENV.read_bytes()==owned_env and (BASE/'current').resolve() in (OLD,destination)
                    if rollback:
                        H['select_release'](OLD)
                        H['set_env'](original)
                    H['run'](['systemctl','start','thirdhand-stage.service'])
                H['health']()
            H['private'](ROOT/'failed.json',json.dumps({'failed':True,'rolledBack':rollback,'manualReviewRequired':not rollback,'initialBatchRetained':True}).encode())
            raise


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--apply',action='store_true');args=parser.parse_args()
    try:
        main(args.apply)
    except Exception as error:
        print(json.dumps({'failed':True,'type':type(error).__name__,'reviewPrivateLogs':True}));raise SystemExit(1)
