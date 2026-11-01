import base64
import gzip
import importlib.util
import json
from pathlib import Path
import time

import pytest

REPO = Path(__file__).resolve().parents[3]


@pytest.fixture
def site(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location('active_device', REPO / 'tools/operations/apply_sdk_scope_device.py')
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    home = tmp_path / 'home'; base = home / 'source'; root = home / 'ops'; units = home / 'units'
    for p in (base, root, units):
        p.mkdir(parents=True)
    for k, v in [('HOME', home), ('BASE', base), ('ROOT', root), ('UNITS', units)]:
        monkeypatch.setattr(m, k, v)
    groups = []
    changes = {'agent-old/runtime.py': b'new state worker', 'robot-old/services/robot/src/remote-gateway.js': b'new timestamp'}
    for old, new, files in [('agent-old', 'agent-new', {'runtime.py': b'old', 'upload.py': b'keep uploader'}),
                            ('robot-old', 'robot-new', {'services/robot/src/remote-gateway.js': b'old', 'guard.py': b'keep guard'})]:
        before = {}
        for name, raw in files.items():
            p = base / old / name; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(raw); before[name] = m.sha(raw)
        after = {n: m.sha(changes.get(old+'/'+n, raw)) for n, raw in files.items()}
        groups.append({'old': old, 'new': new, 'before': before, 'after': after})
    hashes = {}
    for unit in (m.EDGE, m.ROBOT):
        (units / unit).write_bytes(b'original unit'); hashes[unit] = m.sha(b'original unit')
        (units / (unit+'.d')).mkdir()
    packed = gzip.compress(json.dumps({'changes': {n: base64.b64encode(v).decode() for n,v in changes.items()}}).encode())
    (root/'device.delta.json.gz').write_bytes(packed)
    pins = {'snapshots': groups, 'unitHashes': hashes, 'changes': {n:m.sha(v) for n,v in changes.items()},
            'packageSha256':m.sha(packed), 'dropins':{u+'.d/zzz-sdk-scope-state.conf':'[Service]\n# @HOME@\n' for u in (m.EDGE,m.ROBOT)}}
    raw = json.dumps(pins).encode(); (root/'active-pins.json').write_bytes(raw); monkeypatch.setattr(m,'PINS_SHA',m.sha(raw))
    proof = root/'clearance.json'
    proof.write_text(json.dumps({'schema':1,'phase':'SDK-scope-state','deviceId':m.DEVICE,'checkedAt':int(time.time()*1000),
                                'activeLeases':0,'activeCommands':0,'sdkConnected':False,'moving':False,'readOnly':True,'recordingHealthy':True}))
    proof.chmod(0o600)
    values={'ActiveState':'inactive','NeedDaemonReload':'no','Environment':'PYTHONPATH='+str(base/'agent-old'),
            'ExecStart':'{ argv[]='+str(base/'robot-old/services/robot/src/server.js')+' ; }'}
    monkeypatch.setattr(m,'system_show',lambda unit,key:values[key])
    return m,pins,proof,values


def test_review_does_not_create_snapshots_or_activate_units(site):
    m,p,proof,v=site
    assert m.execute()['applied'] is False
    assert not (m.BASE/'agent-new').exists()
    assert not (m.ROOT/'applied.json').exists()


def test_apply_preserves_old_roots_and_rollback_does_not_need_package_or_new_sources(site):
    m,p,proof,v=site
    assert m.execute(apply=True,clearance_path=proof)['servicesStarted'] is False
    for g in p['snapshots']:
        assert m.inventory(m.BASE/g['old']) == g['before']
        assert m.inventory(m.BASE/g['new']) == g['after']
    (m.ROOT/'device.delta.json.gz').write_bytes(b'damaged')
    (m.BASE/'agent-new/runtime.py').write_bytes(b'damaged')
    assert m.execute(rollback=True,clearance_path=proof)['rolledBack'] is True
    for n in p['dropins']:
        assert not (m.UNITS/n).exists()
    assert (m.BASE/'agent-new').exists(), 'Rollback never recursively deletes snapshots'


@pytest.mark.parametrize('key,value,code', [('Environment','PYTHONPATH=/other','ACTIVE_AGENT_PATH_CHANGED'),
    ('ExecStart','{ argv[]=/other/server.js ; }','ACTIVE_ROBOT_PATH_CHANGED'),
    ('NeedDaemonReload','yes','UNLOADED_UNIT_CHANGE'),('ActiveState','active','SERVICES_MUST_BE_STOPPED')])
def test_actual_service_binding_and_stopped_state_are_required(site,key,value,code):
    m,p,proof,v=site;v[key]=value
    with pytest.raises(ValueError,match=code):m.execute(apply=True,clearance_path=proof)
    assert not (m.BASE/'agent-new').exists()


@pytest.mark.parametrize('field,value',[('activeLeases',1),('sdkConnected',True),('checkedAt',0),('recordingHealthy',False)])
def test_unknown_active_or_expired_clearance_blocks_all_writes(site,field,value):
    m,p,proof,v=site;d=json.loads(proof.read_text());d[field]=value;proof.write_text(json.dumps(d))
    with pytest.raises(ValueError,match='CLEARANCE_REQUIRED'):m.execute(apply=True,clearance_path=proof)
    assert not (m.BASE/'agent-new').exists()


def test_concurrent_unit_or_old_source_changes_are_preserved(site):
    m,p,proof,v=site
    other=m.UNITS/(m.EDGE+'.d/other.conf');other.write_text('other task')
    with pytest.raises(ValueError,match='UNEXPECTED_DROPIN'):m.execute()
    assert other.read_text()=='other task'
    other.unlink();(m.BASE/'agent-old/runtime.py').write_text('other task')
    with pytest.raises(ValueError,match='ACTIVE_SNAPSHOT_CHANGED'):m.execute()


def test_partial_activation_removes_only_our_unchanged_dropins(site,monkeypatch):
    m,p,proof,v=site;original=m.exclusive;count=[0]
    def write(path,raw):
        if path.name=='zzz-sdk-scope-state.conf':
            count[0]+=1
            if count[0]==2:raise OSError('synthetic write failure')
        original(path,raw)
    monkeypatch.setattr(m,'exclusive',write)
    with pytest.raises(OSError,match='synthetic'):m.execute(apply=True,clearance_path=proof)
    assert not any((m.UNITS/n).exists() for n in p['dropins'])
    for g in p['snapshots']:assert m.inventory(m.BASE/g['old'])==g['before']


def test_rollback_refuses_foreign_dropin_content(site):
    m,p,proof,v=site;m.execute(apply=True,clearance_path=proof)
    path=m.UNITS/next(iter(p['dropins']));path.write_text('other task')
    with pytest.raises(ValueError,match='ROLLBACK_DROPIN_CHANGED'):m.execute(rollback=True,clearance_path=proof)
    assert path.read_text()=='other task'
