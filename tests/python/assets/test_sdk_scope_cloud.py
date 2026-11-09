"""SDK release scope, immutable source bytes and backwards-compatible rollback."""
import base64,copy,gzip,hashlib,importlib.util,json
from contextlib import contextmanager
from pathlib import Path,PurePosixPath
from types import SimpleNamespace
from unittest.mock import patch
import pytest

REPO=Path(__file__).resolve().parents[3]

def module(name,path):
    spec=importlib.util.spec_from_file_location(name,REPO/path)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def fixture(tmp_path):
    m=module('c7_apply','tools/operations/apply_sdk_scope_cloud.py')
    builder=module('c7_build','tools/deploy/build_sdk_scope_cloud.py')
    b=module('c7_base','tools/operations/apply_camera_ui_cloud.py')
    assert m.FILES==builder.FILES and m.CHANGED==builder.CHANGED and m.ADDED==builder.ADDED
    m.OLD=PurePosixPath(m.OLD.as_posix())
    files={name:'b'*64 for name in m.CHANGED}
    files.update({f'tests/synthetic/unrelated-{n}.txt':'c'*64 for n in range(4656-len(files))})
    before={'format':1,'role':'synthetic-c7-test','files':files}
    raw=(json.dumps(before,sort_keys=True,indent=2)+'\n').encode()
    baseline=tmp_path/'baseline.json';baseline.write_bytes(raw)
    builder.OLD_SHA=m.OLD_SHA=hashlib.sha256(raw).hexdigest()
    m.ROOT=tmp_path/'candidate'
    report=builder.build(baseline,m.ROOT,read_source=lambda n:(REPO/n).read_bytes())
    m.NEW=PurePosixPath(report['newRelease']);m.NEW_SHA=report['manifestSha256'];m.PACKAGE_SHA=report['packageSha256']
    # The installer expects Git-normalized SQL; normalize this disposable fixture
    # on Windows too. Actual candidate build reads the Git index.
    m.MIGRATION_SHA=report['migrationSha256']
    return m,b,before

def test_only_11_runtime_files_change_and_all_existing_metadata_and_geometry_are_preserved(tmp_path):
    m,b,before=fixture(tmp_path);raw,contents=m.read_package(b,before);after=json.loads(raw)
    assert len(contents)==11 and len(after['files'])==4657
    assert len(m.CHANGED)==10 and len(m.ADDED)==1
    assert all(after['files'][n]==v for n,v in before['files'].items() if n not in m.CHANGED)
    assert not any(n.startswith(('drivers/','services/edge-agent/','services/robot/','showcase/')) for n in contents)
    assert after['role']==before['role']

@pytest.mark.parametrize('kind,code',[('unrelated','EXTRA_SOURCE_CHANGES'),('metadata','MANIFEST_METADATA_CHANGED'),('baseline','BEFORE_HASH_MISMATCH')])
def test_any_unreviewed_source_metadata_or_baseline_drift_blocks_deployment(tmp_path,kind,code):
    m,b,before=fixture(tmp_path)
    if kind=='baseline':
        before=copy.deepcopy(before);before['files']['services/device-relay/src/server.js']='d'*64
    else:
        target=m.ROOT/'cloud.delta.json.gz';p=json.loads(gzip.decompress(target.read_bytes()))
        manifest=json.loads(base64.b64decode(p['manifestBase64']))
        if kind=='unrelated':manifest['files']['tests/synthetic/unrelated-0.txt']='d'*64
        else:manifest['role']='changed'
        raw=(json.dumps(manifest,sort_keys=True,indent=2)+'\n').encode()
        m.NEW_SHA=p['manifestSha256']=hashlib.sha256(raw).hexdigest()
        p['manifestBase64']=base64.b64encode(raw).decode();packed=gzip.compress(json.dumps(p).encode(),mtime=0)
        target.write_bytes(packed);m.PACKAGE_SHA=hashlib.sha256(packed).hexdigest()
    with pytest.raises(b.DeploymentError,match=code):m.read_package(b,before)

@contextmanager
def context():yield

def test_default_review_never_migrates_restarts_or_changes_a_release(tmp_path):
    m,b,_=fixture(tmp_path);calls=[]
    base=SimpleNamespace(require_identity=lambda:None,frozen=lambda:None,require=b.require,
      prepare=lambda:(None,None,None,{'applied':False}))
    def sql(query):
        calls.append(query);assert query.startswith('SELECT')
        return json.dumps({'checksum':None,'columns':0}) if 'json_build_object' in query else '0'
    with patch.object(m,'load_verified',side_effect=[base,SimpleNamespace(sql=sql)]),patch.object(m,'configure',side_effect=lambda v:v):
        result=m.execute()
    assert result['applied'] is False and len(calls)==2

def test_rollback_does_not_read_package_or_drop_scope_and_audit_data(tmp_path):
    m,b,_=fixture(tmp_path);calls=[]
    base=SimpleNamespace(require_identity=lambda:None,frozen=lambda:None,require=b.require,
      installation_lock=context,rollback_locked=lambda:calls.append('rollback') or {'rolledBack':True})
    def sql(query):assert query.startswith('SELECT');return '0'
    guard=SimpleNamespace(quiescent_lease_admission=context,sql=sql)
    with patch.object(m,'load_verified',side_effect=[base,guard]),patch.object(m,'configure',side_effect=lambda v:v):
        result=m.execute(rollback=True)
    assert result['rolledBack'] and result['scopeDataRetained'] and calls==['rollback']

def test_atomic_migration_uses_shared_lock_time_bounds_and_checksum_and_can_resume_after_source_rollback(tmp_path):
    m,b,_=fixture(tmp_path);raw=(REPO/'platform/storage/migrations/012-sdk-connection-scope.sql').read_bytes()
    state={'checksum':None,'columns':0};calls=[]
    def sql(query):
        if query.startswith('SELECT'):return json.dumps(state)
        calls.append(query)
        assert query.startswith('BEGIN;') and query.endswith('COMMIT;')
        assert "lock_timeout='3s'" in query and "statement_timeout='15s'" in query
        assert 'pg_try_advisory_lock(240103,1)' in query and m.MIGRATION_SHA in query
        assert 'LOCK TABLE ops.control_leases IN SHARE MODE' in query
        assert "RAISE EXCEPTION 'DEVICE_OCCUPIED'" in query
        assert 'DROP ' not in query and 'GRANT ' not in query
        state.update(checksum=m.MIGRATION_SHA,columns=1)
        return ''
    guard=SimpleNamespace(sql=sql)
    m.migrate(b,guard,raw);m.migrate(b,guard,raw)
    assert len(calls)==1,'retained migration is never applied twice'
    state['checksum']='d'*64
    with pytest.raises(b.DeploymentError,match='LEASE_SCHEMA_CHANGED'):m.migrate(b,guard,raw)

def test_ddl_finishes_before_separate_admission_guard_is_acquired(tmp_path):
    m,b,_=fixture(tmp_path);events=[];held=False
    @contextmanager
    def admission():
        nonlocal held
        assert events==['migrated'];held=True
        try:yield
        finally:held=False
    base=SimpleNamespace(require_identity=lambda:None,frozen=lambda:None,require=b.require,
        installation_lock=context,prepare=lambda:(None,{'platform/storage/migrations/'+m.MIGRATION:b'sql'}, {}, {}),
        save_backup=lambda _:None)
    guard=SimpleNamespace(quiescent_lease_admission=admission)
    def migration(*args):
        assert not held;events.append('migrated')
    def apply(*args):
        assert held;events.append('switched');return {'applied':True}
    with patch.object(m,'load_verified',side_effect=[base,guard]),patch.object(m,'configure',side_effect=lambda v:v), \
         patch.object(m,'check_schema',return_value={'checksum':None,'columns':0}),patch.object(m,'no_commands'), \
         patch.object(m,'migrate',side_effect=migration),patch.object(m,'apply_locked',side_effect=apply):
        assert m.execute(apply=True)['applied']
    assert events==['migrated','switched']
