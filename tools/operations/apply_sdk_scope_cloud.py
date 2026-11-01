"""SDK connection scope and latest-state release; default review is read-only. Linux root only.

Rollback keeps the additive scope column and audit data. No direct Ubuntu,
SDK, camera service, environment, port or showcase changes are permitted.
"""
import argparse,base64,gzip,io,json,shutil,types
from pathlib import Path

ROOT=Path('/var/backups/thirdhand/access-sdk-scope-20261101')
BASE=Path('/var/backups/thirdhand/access-C3f-camera-ui-20261101/apply_camera_ui_cloud.py')
BASE_SHA='d10eaa3e631f873d394f501e36588d6b4f037dbfbd2cc6145b63e4ba09ac2f4f'
GUARD=Path('/var/backups/thirdhand/initial-admins-20261101/apply.py')
GUARD_SHA='66f09cc541d3082215ee6b77c59b8616ab595dd434242d60f645fb444f519eee'
OLD=Path('/opt/thirdhand-stage/releases/dfbca02d47ca7f40')
OLD_SHA='dfbca02d47ca7f4020354567482265c5f2645a76e509a3f82cf4d23641d5aa4e'
NEW=Path('/opt/thirdhand-stage/releases/0735390c57d2ad7d')
NEW_SHA='0735390c57d2ad7d58d663818c191beb6ad8ab30183f7feeb5cd137e58c318d1'
PACKAGE_SHA='58a30ba9d6d07b4b11503f5fee8875bfc5c4af56d97e341b0dba074b72725fe5'
MIGRATION='012-sdk-connection-scope.sql'
MIGRATION_SHA='331371c9b0bf0d1cfcb0a862134213428a64b4b9285a7c906d660a65752965ed'
CHANGED={'apps/web/public/js/'+n+'.js' for n in ('admin-control','device-state','i18n-cloud-catalog')}|{
    'platform/identity/src/policy.js','platform/storage/src/leases.js',
    'services/cloud-api/src/control/control-channel.js','services/cloud-api/src/control/leases.js',
    'services/cloud-api/src/control/websocket.js','services/cloud-api/src/routes/control.js',
    'services/device-relay/src/server.js'}
ADDED={'platform/storage/migrations/'+MIGRATION}
FILES=CHANGED|ADDED

def load_verified(path,digest):
    import hashlib
    assert path.is_file() and not path.is_symlink() and path.resolve()==path
    raw=path.read_bytes();assert hashlib.sha256(raw).hexdigest()==digest
    module=types.ModuleType('thirdhand_verified_'+path.stem)
    exec(compile(raw,str(path),'exec'),module.__dict__)
    return module

def read_package(base,previous):
    raw=base.regular(ROOT/'cloud.delta.json.gz',8*1024*1024)
    base.require(base.sha(raw)==PACKAGE_SHA,'PACKAGE_DIGEST_MISMATCH')
    with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:decoded=stream.read(32*1024*1024+1)
    base.require(len(decoded)<=32*1024*1024,'PACKAGE_TOO_LARGE')
    p=json.loads(decoded);before=previous['files']
    base.require(p.get('format')==1 and p.get('oldRelease')==str(OLD) and p.get('newRelease')==str(NEW)
        and p.get('oldManifestSha256')==OLD_SHA and p.get('manifestSha256')==NEW_SHA,'PACKAGE_RELEASE_MISMATCH')
    base.require(len(before)==4656 and CHANGED<=set(before) and not ADDED&set(before),'BASELINE_INVENTORY_MISMATCH')
    base.require(set(p.get('changes',{}))==FILES,'PACKAGE_SCOPE_MISMATCH')
    base.require(p.get('beforeHashes')=={n:before.get(n) for n in FILES},'BEFORE_HASH_MISMATCH')
    manifest_raw=base64.b64decode(p['manifestBase64'],validate=True)
    base.require(base.sha(manifest_raw)==NEW_SHA,'NEW_MANIFEST_MISMATCH')
    manifest=json.loads(manifest_raw);after=manifest['files']
    base.require(set(after)==set(before)|ADDED and len(after)==4657,'NEW_INVENTORY_MISMATCH')
    base.require({n for n in set(before)|set(after) if before.get(n)!=after.get(n)}==FILES,'EXTRA_SOURCE_CHANGES')
    base.require({k:v for k,v in manifest.items() if k!='files'}=={k:v for k,v in previous.items() if k!='files'},'MANIFEST_METADATA_CHANGED')
    contents={n:base64.b64decode(data,validate=True) for n,data in p['changes'].items()}
    base.require(all(base.sha(data)==after[n] for n,data in contents.items()),'NEW_SOURCE_DIGEST_MISMATCH')
    base.require(base.sha(contents['platform/storage/migrations/'+MIGRATION])==MIGRATION_SHA,'MIGRATION_DIGEST_MISMATCH')
    return manifest_raw,contents

def configure(base):
    base.ROOT=ROOT;base.OLD=OLD;base.NEW=NEW;base.OLD_MANIFEST=OLD_SHA;base.NEW_MANIFEST=NEW_SHA
    base.PACKAGE_SHA=PACKAGE_SHA;base.OLD_FILES_COUNT=4656;base.EXPECTED_FILES=FILES
    base.read_package=lambda before:read_package(base,before)
    return base

def schema_state(guard):
    return json.loads(guard.sql("SELECT json_build_object('checksum',(SELECT checksum FROM public.thirdhand_schema_migrations WHERE version='012-sdk-connection-scope.sql'),'columns',(SELECT count(*) FROM information_schema.columns WHERE table_schema='ops' AND table_name='control_leases' AND column_name='scope'));"))

def check_schema(base,guard):
    state=schema_state(guard)
    base.require(state=={'checksum':None,'columns':0} or state=={'checksum':MIGRATION_SHA,'columns':1},'LEASE_SCHEMA_CHANGED')
    return state

def no_commands(base,guard):
    base.require(guard.sql("SELECT count(*) FROM ops.commands WHERE state IN ('accepted','started') OR (state='unknown' AND expires_at>now());")=='0','COMMAND_OCCUPIED')

def migrate(base,guard,raw):
    base.require(base.sha(raw)==MIGRATION_SHA,'MIGRATION_DIGEST_MISMATCH')
    state=check_schema(base,guard)
    if state['checksum'] is None:
        # Same lock as the standard migration runner; a busy runner fails fast.
        guard.sql("BEGIN; SET LOCAL lock_timeout='3s'; SET LOCAL statement_timeout='15s'; "
          "DO $$ BEGIN IF NOT pg_try_advisory_lock(240103,1) THEN RAISE EXCEPTION 'MIGRATION_BUSY'; END IF; END $$;\n"
          +raw.decode('utf8')+"\nINSERT INTO public.thirdhand_schema_migrations(version,checksum) VALUES ('"+MIGRATION+"','"+MIGRATION_SHA+"'); COMMIT;")
    base.require(schema_state(guard)=={'checksum':MIGRATION_SHA,'columns':1},'MIGRATION_UNCONFIRMED')

def apply_locked(base,guard):
    manifest,contents,invariants,report=base.prepare();before=check_schema(base,guard)
    no_commands(base,guard);base.save_backup(invariants)
    receipt=ROOT/'lease-schema-before-public.json'
    if not receipt.exists():
        with receipt.open('xb') as output:output.write((json.dumps(before,sort_keys=True)+'\n').encode())
        receipt.chmod(0o600)
    staging=base.safe_path(base.staging_path());shutil.copytree(OLD,staging,symlinks=False)
    for name,raw in contents.items():
        target=staging/name
        base.require(target.is_relative_to(staging),'UNSAFE_SOURCE_TARGET')
        target.parent.mkdir(parents=True,exist_ok=True);base.safe_path(target.parent)
        target.write_bytes(raw);target.chmod(0o644)
    (staging/'manifest.json').write_bytes(manifest);base.check_release(staging,NEW_SHA)
    base.checkpoint(invariants,expected=OLD)
    base.require(not NEW.exists() and not NEW.is_symlink(),'CANDIDATE_PATH_OCCUPIED');staging.rename(NEW)
    # Additive columns are backward-compatible with OLD; never drop on rollback.
    migrate(base,guard,contents['platform/storage/migrations/'+MIGRATION]);switched=False
    try:
        no_commands(base,guard);base.checkpoint(invariants,expected=OLD,candidate=True)
        base.switch(NEW);switched=True;base.checkpoint(invariants,expected=NEW,candidate=True)
        base.restart();base.checkpoint(invariants,expected=NEW,candidate=True)
        base.require(base.current_target()==NEW,'APPLICATION_UNCONFIRMED')
    except BaseException as error:
        outcome='not-needed'
        if switched:
            try:base.rollback_locked();outcome='restored'
            except Exception:outcome='blocked'
        raise base.DeploymentError(getattr(error,'code','APPLICATION_FAILED'),rollback=outcome) from None
    return {**report,'applied':True,'databaseMigrations':[MIGRATION],'permissionChanges':['authenticated-sdk-connect-only'],'scopeDataRetainedOnRollback':True}

def execute(apply=False,rollback=False):
    if not __debug__:raise RuntimeError('PYTHON_OPTIMIZATION_NOT_ALLOWED')
    base=configure(load_verified(BASE,BASE_SHA));guard=load_verified(GUARD,GUARD_SHA)
    base.require_identity();base.frozen()
    if not apply and not rollback:
        report=base.prepare()[3];state=check_schema(base,guard);no_commands(base,guard)
        return {**report,'databaseMigrations':[MIGRATION],'permissionChanges':['authenticated-sdk-connect-only'],'leaseSchemaBefore':state,'restartUnits':['thirdhand-stage.service']}
    with base.installation_lock(),guard.quiescent_lease_admission():
        no_commands(base,guard)
        if rollback:return {**base.rollback_locked(),'scopeDataRetained':True}
        return apply_locked(base,guard)

if __name__=='__main__':
    p=argparse.ArgumentParser();m=p.add_mutually_exclusive_group();m.add_argument('--apply',action='store_true');m.add_argument('--rollback',action='store_true');a=p.parse_args()
    try:print(json.dumps(execute(a.apply,a.rollback),sort_keys=True))
    except Exception as error:
        print(json.dumps({'applied':False,'code':getattr(error,'code',type(error).__name__),'rollback':getattr(error,'rollback',None),'scopeDataMayBeRetained':bool(a.apply),'reviewRequired':True},sort_keys=True));raise SystemExit(2)
