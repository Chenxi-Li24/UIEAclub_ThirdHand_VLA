import base64
import gzip
import importlib.util
import json
from pathlib import Path, PurePosixPath

import pytest

spec = importlib.util.spec_from_file_location('duration_builder', Path(__file__).resolve().parents[3] / 'tools/deploy/build_sdk_duration_candidate.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)

OLD = b'class Test:\n    def _require_remote_lease(self):\n        pass\n\n    def connect(self):\n        pass\n\n    def ik(self):\n        return 1\n'
NEW = OLD.replace(b'        pass', b'        return True')
INSTALLED = OLD.replace(b'return 1', b'return "preserved IK seed"')


@pytest.fixture
def inputs(tmp_path, monkeypatch):
    def source(rev, path):
        if path.endswith('/startouch_bridge.py'):
            return OLD if rev.endswith('^') else NEW
        return (rev + ':' + path).encode()
    monkeypatch.setattr(builder, 'git_bytes', source)
    files = {p: builder.sha(source(builder.SOURCE+'^', p)) for p in builder.FILES['cloud']}
    files.update({f'keep/{i}': 'b'*64 for i in range(4658-len(files))})
    raw = builder.pretty({'files': files, 'deviceControl': 'explicit-read-only'})
    cloud = tmp_path/'cloud.json'; cloud.write_bytes(raw)
    monkeypatch.setattr(builder, 'OLD_SHA', builder.sha(raw))
    device = {'context': {'sdkConnected': False, 'readOnly': True}}
    home = PurePosixPath('/home/synthetic-user')
    for group, count in [('edge', 24), ('robot', 37)]:
        root = home/'.local/share/thirdhand-stage-device/20261031'/builder.NAMES[group]
        files = {}
        for p in builder.FILES[group]:
            data = INSTALLED if p.endswith('/startouch_bridge.py') else source(builder.SOURCE+'^', p)
            target = p.removeprefix('services/edge-agent/src/') if group == 'edge' else p
            files[target] = builder.sha(data)
        files.update({f'keep/{i}': 'c'*64 for i in range(count-len(files))})
        device[group] = {'source': str(root), 'files': files, 'links': {}, 'unitHashes': {},
                         'state': {'ActiveState': 'active', 'NeedDaemonReload': 'no'}}
        if group == 'edge':
            device[group]['pythonpath'] = ['PYTHONPATH='+str(root), 'THIRDHAND_SDK_TIMING=0']
        else:
            binary = home/'ThirdHand/UIEAclub_ThirdHand_VLA/local/runtimes/node/bin/node'
            device[group]['state']['ExecStart'] = 'argv[]='+str(binary)+' '+str(root/'services/robot/src/server.js')+' ;'
    baseline = tmp_path/'device.json'; baseline.write_text(json.dumps(device))
    worker = tmp_path/'worker.py'; worker.write_bytes(INSTALLED)
    return cloud, baseline, worker, tmp_path/'out'


def test_fixed_eight_changes_preserve_every_unrelated_file_and_worker_ik(inputs):
    report = builder.build(*inputs)
    package = json.loads(gzip.decompress((inputs[-1]/'sdk-duration-candidate.json.gz').read_bytes()))
    assert sum(len(package[g]['changes']) for g in builder.FILES) == 8
    for group in builder.FILES:
        p = package[group]
        assert set(p['before']) == set(p['after'])
        assert {n for n in p['after'] if p['before'][n] != p['after'][n]} == set(p['changes'])
        for name, raw in p['changes'].items():
            assert builder.sha(base64.b64decode(raw)) == p['after'][name]
    worker = base64.b64decode(package['robot']['changes']['services/robot/src/startouch_bridge.py'])
    assert b'preserved IK seed' in worker and worker.count(b'return True') == 2
    assert report['packageSha256'] == builder.sha((inputs[-1]/'sdk-duration-candidate.json.gz').read_bytes())


@pytest.mark.parametrize('kind', ['cloud', 'sdk', 'scope', 'hash', 'worker', 'entry', 'timing', 'link'])
def test_drift_fails_before_output(inputs, kind):
    cloud, baseline, worker, out = inputs
    device = json.loads(baseline.read_text())
    if kind == 'cloud': cloud.write_bytes(b'{}')
    elif kind == 'sdk': device['context']['sdkConnected'] = True
    elif kind == 'scope': device['robot']['source'] += '-other'
    elif kind == 'hash': device['edge']['files']['thirdhand_edge/lease.py'] = '0'*64
    elif kind == 'worker': worker.write_bytes(INSTALLED.replace(b'pass', b'raise RuntimeError'))
    elif kind == 'entry': device['robot']['state']['ExecStart'] = 'other'
    elif kind == 'timing': device['edge']['pythonpath'][-1] = 'THIRDHAND_SDK_TIMING=1'
    else: device['robot']['links']['bad'] = '/tmp/unrelated'
    baseline.write_text(json.dumps(device))
    with pytest.raises(ValueError): builder.build(*inputs)
    assert not out.exists()


def test_worker_merge_refuses_changes_outside_selected_functions_or_inside_installed_function():
    with pytest.raises(ValueError): builder.merge_worker(OLD, NEW.replace(b'return 1', b'return 2'), INSTALLED)
    with pytest.raises(ValueError): builder.merge_worker(OLD, NEW, INSTALLED.replace(b'pass', b'raise RuntimeError'))
