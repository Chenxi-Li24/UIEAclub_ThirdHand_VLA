import base64,copy,gzip,hashlib,importlib.util,json
from contextlib import contextmanager
from pathlib import Path,PurePosixPath
from types import SimpleNamespace
from unittest.mock import patch
import pytest

REPO=Path(__file__).resolve().parents[3]
def module(name,relative):
    spec=importlib.util.spec_from_file_location(name,REPO/relative);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
def fixture(tmp_path):
    m=module('waypoint_apply','tools/operations/apply_model_waypoints_cloud.py')
    # The installer is Linux-only; keep its release identifiers POSIX on Windows.
    m.OLD=PurePosixPath(m.OLD.as_posix());m.NEW=PurePosixPath(m.NEW.as_posix())
    b=module('waypoint_base','tools/operations/apply_camera_ui_cloud.py')
    builder=module('waypoint_builder','tools/deploy/build_model_waypoints_release.py')
    # Build an isolated public fixture from tracked sources. Production's
    # one-time baseline/package pins stay untouched; no local deployment
    # receipts, database exports or ignored .superpowers files are required.
    files={name:hashlib.sha256(('prior '+name).encode()).hexdigest() for name in m.CHANGED}
    files.update({name:'b'*64 for name in ('apps/web/public/js/camera-view.js','platform/identity/src/accounts.js')})
    files.update({f'tests/synthetic/unrelated-{n}.txt':'c'*64 for n in range(4630-len(files))})
    before={'format':1,'role':'synthetic-model-release-test','files':files}
    raw=(json.dumps(before,sort_keys=True,indent=2)+'\n').encode()
    baseline=tmp_path/'baseline.json';baseline.write_bytes(raw)
    builder.OLD_SHA=m.OLD_SHA=hashlib.sha256(raw).hexdigest()
    m.ROOT=tmp_path/'candidate'
    report=builder.build(baseline,m.ROOT)
    m.NEW=PurePosixPath(report['newRelease']);m.NEW_SHA=report['manifestSha256']
    m.PACKAGE_SHA=report['packageSha256']
    return m,b,before

def test_nine_file_delta_preserves_account_camera_and_all_other_sources(tmp_path):
    m,b,before=fixture(tmp_path)
    raw,contents=m.read_package(b,before)
    after=json.loads(raw)
    assert set(contents)==m.FILES and len(contents)==9
    assert len(after['files'])==4634
    assert all(after['files'][name]==digest for name,digest in before['files'].items() if name not in m.CHANGED)
    assert after['files']['apps/web/public/js/camera-view.js']==before['files']['apps/web/public/js/camera-view.js']
    assert after['files']['platform/identity/src/accounts.js']==before['files']['platform/identity/src/accounts.js']


@pytest.mark.parametrize('kind,code', [('unrelated','EXTRA_SOURCE_CHANGES'),('metadata','MANIFEST_METADATA_CHANGED')])
def test_reviewed_package_rejects_changes_outside_the_nine_sources(tmp_path,kind,code):
    m,b,before=fixture(tmp_path)
    path=m.ROOT/'cloud.delta.json.gz';package=json.loads(gzip.decompress(path.read_bytes()))
    manifest=json.loads(base64.b64decode(package['manifestBase64']))
    if kind=='unrelated':manifest['files']['platform/identity/src/accounts.js']='d'*64
    else:manifest['role']='changed-role'
    raw=(json.dumps(manifest,sort_keys=True,indent=2)+'\n').encode()
    m.NEW_SHA=package['manifestSha256']=hashlib.sha256(raw).hexdigest()
    package['manifestBase64']=base64.b64encode(raw).decode()
    packed=gzip.compress(json.dumps(package).encode(),mtime=0);path.write_bytes(packed)
    m.PACKAGE_SHA=hashlib.sha256(packed).hexdigest()
    with pytest.raises(b.DeploymentError,match=code):m.read_package(b,before)

def test_package_cannot_be_applied_to_a_changed_server_baseline(tmp_path):
    m,b,before=fixture(tmp_path)
    before=copy.deepcopy(before);before['files']['services/cloud-api/src/server.js']='a'*64
    with pytest.raises(b.DeploymentError,match='BEFORE_HASH_MISMATCH'):m.read_package(b,before)

def test_fixed_archive_digest_rejects_truncation(tmp_path):
    m,b,before=fixture(tmp_path);m.ROOT=tmp_path
    (tmp_path/'cloud.delta.json.gz').write_bytes(b'truncated')
    with pytest.raises(b.DeploymentError,match='PACKAGE_DIGEST_MISMATCH'):m.read_package(b,before)

@contextmanager
def context():yield

def test_rollback_never_requires_upload_package_or_grant_file(tmp_path):
    m,_,_=fixture(tmp_path);calls=[]
    def forbidden(*args):raise AssertionError('must not read an upload during rollback')
    base=SimpleNamespace(require_identity=lambda:None,frozen=lambda:None,installation_lock=context,
        regular=forbidden,rollback_locked=lambda:calls.append('rollback') or {'rolledBack':True},require=lambda ok,code:None if ok else (_ for _ in ()).throw(AssertionError(code)))
    guard=SimpleNamespace(quiescent_lease_admission=context,sql=lambda query:'0')
    with patch.object(m,'load_verified',side_effect=[base,guard]),patch.object(m,'configure',side_effect=lambda b:b):r=m.execute(rollback=True)
    assert r['rolledBack'] and r['savedPointsRetained'] and r['tableGrantsRetained']
    assert calls==['rollback']

def test_default_review_never_executes_grants_or_switches(tmp_path):
    m,_,_=fixture(tmp_path);calls=[]
    grants=(REPO/'deploy/public-access/staging/model-waypoint-grants.sql').read_bytes()
    base=SimpleNamespace(require_identity=lambda:None,frozen=lambda:None,regular=lambda *_:grants,
        sha=lambda _:m.GRANT_SHA,require=lambda ok,code:None if ok else (_ for _ in ()).throw(AssertionError(code)),
        execute=lambda:calls.append('review') or {'applied':False})
    def sql(query):
        assert query.startswith('SELECT') and 'GRANT ' not in query
        return json.dumps({'schemaUsage':False,'tableSelect':False,'tableInsert':False,'tableDelete':False}) if 'json_build_object' in query else '0'
    with patch.object(m,'load_verified',side_effect=[base,SimpleNamespace(sql=sql)]),patch.object(m,'configure',side_effect=lambda b:b):r=m.execute()
    assert r['applied'] is False and calls==['review'] and len(r['permissionChanges'])==2
