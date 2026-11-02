import base64
import gzip
import importlib.util
import json
from pathlib import Path, PurePosixPath

import pytest

spec = importlib.util.spec_from_file_location('heartbeat_builder', Path(__file__).resolve().parents[3] / 'tools/deploy/build_sdk_browser_heartbeat_candidate.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


@pytest.fixture
def inputs(tmp_path, monkeypatch):
    monkeypatch.setattr(builder, 'git_bytes', lambda rev, path: (rev + ':' + path).encode())
    files = {p: builder.sha(builder.git_bytes(builder.SOURCE+'^', p)) for p in builder.FILES['cloud']}
    files.update({f'preserved/{i}': 'b'*64 for i in range(4658-len(files))})
    raw = builder.pretty({'files': files, 'deviceControl': 'explicit-read-only-enrollment'})
    cloud = tmp_path / 'cloud.json'; cloud.write_bytes(raw)
    monkeypatch.setattr(builder, 'OLD_SHA', builder.sha(raw))
    device = {'context': {'sdkConnected': False, 'readOnly': True}}
    home = PurePosixPath('/') / 'home' / 'synthetic-user'
    for group, count in [('edge', 24), ('robot', 37)]:
        source = home / builder.SOURCE_TAIL / builder.NAMES[group]
        files = {p: builder.sha(builder.git_bytes(builder.SOURCE+'^', p)) for p in builder.FILES.get(group, [])}
        files.update({f'preserved/{i}': 'd'*64 for i in range(count-len(files))})
        device[group] = {'source': str(source), 'files': files, 'links': {}, 'unitHashes': {},
                         'state': {'ActiveState': 'active', 'NeedDaemonReload': 'no'}}
        if group == 'edge':
            device[group]['pythonpath'] = ['PYTHONPATH='+str(source), 'THIRDHAND_SDK_TIMING=0']
        else:
            binary = str(home / 'ThirdHand/UIEAclub_ThirdHand_VLA/local/runtimes/node/bin/node')
            device[group]['state']['ExecStart'] = '{ argv[]='+binary+' '+str(source / 'services/robot/src/server.js')+' ; }'
    baseline = tmp_path / 'device.json'; baseline.write_text(json.dumps(device))
    return cloud, baseline, tmp_path / 'out'


def test_only_six_deltas_and_one_entry_preserve_unrelated_code(inputs):
    cloud, device, out = inputs
    report = builder.build(cloud, device, out)
    raw = (out / 'sdk-browser-heartbeat-candidate.json.gz').read_bytes()
    value = json.loads(gzip.decompress(raw))
    assert report['packageSha256'] == builder.sha(raw)
    assert value['edgeBaseline'] == json.loads(device.read_text())['edge']
    for group, paths in builder.FILES.items():
        side = value[group]
        assert set(side['before']) == set(side['after'])
        assert {p for p in side['after'] if side['before'][p] != side['after'][p]} == set(paths)
        assert set(side['changes']) == set(paths)
        for p, data in side['changes'].items():
            assert builder.sha(base64.b64decode(data)) == side['after'][p]
    assert value['robot']['newSource'] in value['robot']['dropInText']
    assert json.loads(base64.b64decode(value['cloud']['manifestBase64']))['deviceControl'] == 'explicit-read-only-enrollment'


@pytest.mark.parametrize('change', ['cloud', 'source', 'active_sdk', 'target_hash', 'robot_entry', 'diagnostic', 'count', 'symlink'])
def test_baseline_or_precondition_drift_refuses_output(inputs, change):
    cloud, device, out = inputs; value = json.loads(device.read_text())
    if change == 'cloud':
        cloud.write_text('{}')
    elif change == 'source':
        value['robot']['source'] += '-other'
    elif change == 'active_sdk':
        value['context']['sdkConnected'] = True
    elif change == 'target_hash':
        value['robot']['files']['services/robot/src/startouch-bridge.js'] = 'e'*64
    elif change == 'robot_entry':
        value['robot']['state']['ExecStart'] = 'unexpected'
    elif change == 'diagnostic':
        value['edge']['pythonpath'][1] = 'THIRDHAND_SDK_TIMING=1'
    elif change == 'count':
        value['edge']['files'].popitem()
    else:
        value['robot']['links']['unexpected'] = '/tmp/other'
    device.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        builder.build(cloud, device, out)
    assert not out.exists()
