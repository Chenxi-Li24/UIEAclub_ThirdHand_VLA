import copy,importlib.util,json
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
    root=REPO/'.superpowers/sdd/2026-11-01-personal-model-waypoints'
    m.ROOT=root/'deployment-candidate'
    before=json.loads((root/'baseline-registration-manifest.json').read_bytes())
    return m,b,before

def test_exact_frozen_package_preserves_account_camera_and_all_other_sources(tmp_path):
    m,b,before=fixture(tmp_path)
    raw,contents=m.read_package(b,before)
    after=json.loads(raw)
    assert set(contents)==m.FILES and len(contents)==9
    assert len(after['files'])==4634
    assert all(after['files'][name]==digest for name,digest in before['files'].items() if name not in m.CHANGED)
    assert after['files']['apps/web/public/js/camera-view.js']==before['files']['apps/web/public/js/camera-view.js']
    assert after['files']['platform/identity/src/accounts.js']==before['files']['platform/identity/src/accounts.js']

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
