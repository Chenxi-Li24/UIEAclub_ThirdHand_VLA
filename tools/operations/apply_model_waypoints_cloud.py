"""C6 fixed model-only waypoint release. Default review is read-only.

Reuses the byte-pinned C3f release installer and initial-admin lease guard that
are already installed on this server. No arbitrary dependency discovery.
Rollback preserves saved points and the explicitly approved table grants.
"""
import argparse,base64,gzip,hashlib,io,json,types
from pathlib import Path

ROOT=Path('/var/backups/thirdhand/access-C6-model-waypoints-20261101')
BASE=Path('/var/backups/thirdhand/access-C3f-camera-ui-20261101/apply_camera_ui_cloud.py')
BASE_SHA='d10eaa3e631f873d394f501e36588d6b4f037dbfbd2cc6145b63e4ba09ac2f4f'
GUARD=Path('/var/backups/thirdhand/initial-admins-20261101/apply.py')
GUARD_SHA='66f09cc541d3082215ee6b77c59b8616ab595dd434242d60f645fb444f519eee'
OLD=Path('/opt/thirdhand-stage/releases/registration-approval-a570d928578cb5bb')
OLD_SHA='4ece5d6ce0577bfce2e734dbe43f6df617484b01868242f9b813a250f171f552'
NEW=Path('/opt/thirdhand-stage/releases/7c7f4b5f3792288e')
NEW_SHA='7c7f4b5f3792288ec42d98ddbd25151ae192a766f8a7f16fd996afe6ba35f63c'
PACKAGE_SHA='654eb9f00887beca0ef228d051d1cbf8223e8bd0ed81dcf6d629801bfdf453d5'
GRANT_SHA='9f73fa546cc27fac83eb88f8f192966e8234642dea400c9d1bd24bc4c615b67c'
ADDED={'apps/web/public/css/model-waypoints.css','apps/web/public/js/model-waypoints.js',
       'platform/storage/src/model-waypoints.js','services/cloud-api/src/routes/waypoints.js'}
CHANGED={'apps/web/public/js/cloud-workspace.js','apps/web/public/js/simulation-controller.js',
         'apps/web/public/js/workspace-session.js','services/cloud-api/src/server.js','services/cloud-api/src/workspace-pages.js'}
FILES=ADDED|CHANGED

def load_verified(path,digest):
    assert path.is_file() and not path.is_symlink() and path.resolve()==path
    raw=path.read_bytes();assert hashlib.sha256(raw).hexdigest()==digest
    module=types.ModuleType('thirdhand_verified_'+path.stem)
    exec(compile(raw,str(path),'exec'),module.__dict__)
    return module

def read_package(base,previous):
    raw=base.regular(ROOT/'cloud.delta.json.gz',4*1024*1024)
    base.require(base.sha(raw)==PACKAGE_SHA,'PACKAGE_DIGEST_MISMATCH')
    with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:decoded=stream.read(16*1024*1024+1)
    base.require(len(decoded)<=16*1024*1024,'PACKAGE_TOO_LARGE')
    p=json.loads(decoded)
    base.require(p.get('format')==1 and p.get('oldRelease')==str(OLD) and p.get('newRelease')==str(NEW)
        and p.get('oldManifestSha256')==OLD_SHA and p.get('manifestSha256')==NEW_SHA,'PACKAGE_RELEASE_MISMATCH')
    before=previous['files']
    base.require(len(before)==4630 and set(p.get('changes',{}))==FILES,'PACKAGE_SCOPE_MISMATCH')
    base.require(CHANGED<=set(before) and not ADDED&set(before),'BASELINE_INVENTORY_MISMATCH')
    base.require(p.get('beforeHashes')=={n:before.get(n) for n in FILES},'BEFORE_HASH_MISMATCH')
    manifest_raw=base64.b64decode(p['manifestBase64'],validate=True)
    base.require(base.sha(manifest_raw)==NEW_SHA,'NEW_MANIFEST_MISMATCH')
    manifest=json.loads(manifest_raw);after=manifest['files']
    base.require(set(after)==set(before)|ADDED and len(after)==4634,'NEW_INVENTORY_MISMATCH')
    base.require({n for n in set(before)|set(after) if before.get(n)!=after.get(n)}==FILES,'EXTRA_SOURCE_CHANGES')
    base.require({k:v for k,v in manifest.items() if k!='files'}=={k:v for k,v in previous.items() if k!='files'},'MANIFEST_METADATA_CHANGED')
    contents={n:base64.b64decode(v,validate=True) for n,v in p['changes'].items()}
    base.require(all(base.sha(v)==after[n] for n,v in contents.items()),'NEW_SOURCE_DIGEST_MISMATCH')
    return manifest_raw,contents

def configure(base):
    base.ROOT=ROOT;base.OLD=OLD;base.NEW=NEW;base.OLD_MANIFEST=OLD_SHA;base.NEW_MANIFEST=NEW_SHA
    base.PACKAGE_SHA=PACKAGE_SHA;base.OLD_FILES_COUNT=4630;base.EXPECTED_FILES=FILES
    base.read_package=lambda previous:read_package(base,previous)
    return base

def permissions(guard):
    return json.loads(guard.sql("SELECT json_build_object('schemaUsage',has_schema_privilege('thirdhand-stage','simulation','USAGE'),'tableSelect',has_table_privilege('thirdhand-stage','simulation.user_programs','SELECT'),'tableInsert',has_table_privilege('thirdhand-stage','simulation.user_programs','INSERT'),'tableDelete',has_table_privilege('thirdhand-stage','simulation.user_programs','DELETE'));"))

def execute(apply=False,rollback=False):
    if not __debug__:raise RuntimeError('PYTHON_OPTIMIZATION_NOT_ALLOWED')
    base=configure(load_verified(BASE,BASE_SHA));guard=load_verified(GUARD,GUARD_SHA)
    base.require_identity();base.frozen()
    grant=None
    if not rollback:
        grant=base.regular(ROOT/'model-waypoint-grants.sql',4096)
        base.require(base.sha(grant)==GRANT_SHA,'GRANT_DIGEST_MISMATCH')
    if not apply and not rollback:
        report=base.execute();before=permissions(guard)
        base.require(all(v is False for v in before.values()),'TABLE_PERMISSIONS_CHANGED')
        base.require(guard.sql("SELECT count(*) FROM ops.commands WHERE state IN ('accepted','started');")=='0','COMMAND_OCCUPIED')
        return {**report,'permissionChanges':['simulation.USAGE','simulation.user_programs.SELECT,INSERT,DELETE'],'beforePermissions':before}
    with base.installation_lock(),guard.quiescent_lease_admission():
        base.require(guard.sql("SELECT count(*) FROM ops.commands WHERE state IN ('accepted','started');")=='0','COMMAND_OCCUPIED')
        if rollback:return {**base.rollback_locked(),'savedPointsRetained':True,'tableGrantsRetained':True}
        base.prepare()
        before=permissions(guard);base.require(all(v is False for v in before.values()),'TABLE_PERMISSIONS_CHANGED')
        # Keep a usable source rollback receipt even if a later source-copy step
        # fails. Retained grants/data are part of the explicit approved scope.
        base.save_backup(base.protected_hashes())
        (ROOT/'grant-before-public.json').write_text(json.dumps(before,sort_keys=True)+'\n')
        (ROOT/'grant-before-public.json').chmod(0o600)
        # psql meta-command is CLI-only; execute the fixed two GRANTs atomically.
        guard.sql(grant.decode().replace('\\set ON_ERROR_STOP on\n',''))
        base.require(all(v is True for v in permissions(guard).values()),'GRANT_UNCONFIRMED')
        return {**base.apply_locked(),'tableGrantsApplied':True,'savedPointsRetainedOnRollback':True}

if __name__=='__main__':
    p=argparse.ArgumentParser();m=p.add_mutually_exclusive_group();m.add_argument('--apply',action='store_true');m.add_argument('--rollback',action='store_true');a=p.parse_args()
    try:print(json.dumps(execute(a.apply,a.rollback),sort_keys=True))
    except Exception as error:
        print(json.dumps({'applied':False,'code':getattr(error,'code',type(error).__name__),'tableGrantsMayBeRetained':bool(a.apply),'reviewRequired':True},sort_keys=True));raise SystemExit(2)
