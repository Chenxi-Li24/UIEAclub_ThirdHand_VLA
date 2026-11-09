import base64
import gzip
import importlib.util
import json
from pathlib import Path, PurePosixPath

import pytest

spec = importlib.util.spec_from_file_location('clock_builder', Path(__file__).resolve().parents[3] / 'tools/deploy/build_sdk_clock_candidate.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


@pytest.fixture
def inputs(tmp_path, monkeypatch):
    monkeypatch.setattr(builder, 'git_bytes', lambda rev, path: (rev + ':' + path).encode())
    files = {p: 'a'*64 for p in builder.FILES['cloud']}
    files.update({f'preserved/{i}': 'b'*64 for i in range(4658-len(files))})
    raw = builder.pretty({'files': files, 'deviceControl': 'explicit-read-only-enrollment'})
    cloud = tmp_path / 'cloud.json'
    cloud.write_bytes(raw)
    monkeypatch.setattr(builder, 'OLD_SHA', builder.sha(raw))
    home = PurePosixPath('/') / 'home' / 'synthetic-user'
    device = {'context': {'sdkConnected': False, 'readOnly': True}}
    for group, name in builder.NAMES.items():
        source = home / '.local/share/thirdhand-stage-device/20261031' / name
        paths = builder.FILES[group]
        device[group] = {'source': str(source), 'files': {p: builder.sha(builder.git_bytes(builder.SOURCE+'^', repo)) for p, repo in paths.items()},
                         'links': {}, 'unitHashes': {str(home / '.config/systemd/user' / builder.UNITS[group]): 'c'*64},
                         'state': {'ActiveState': 'active', 'NeedDaemonReload': 'no'}}
        device[group]['files']['preserved-source'] = 'd'*64
        if group == 'edge':
            device[group]['pythonpath'] = ['PYTHONPATH='+str(source), 'THIRDHAND_SDK_TIMING=0']
        else:
            binary = home / 'ThirdHand/UIEAclub_ThirdHand_VLA/local/runtimes/node/bin/node'
            device[group]['state']['ExecStart'] = '{ argv[]='+str(binary)+' '+str(source / 'services/robot/src/server.js')+' ; }'
    baseline = tmp_path / 'device.json'
    baseline.write_text(json.dumps(device))
    return cloud, baseline, tmp_path / 'out'


def test_package_contains_only_fixed_five_deltas_and_preserves_all_other_files(inputs):
    cloud, device, out = inputs
    report = builder.build(cloud, device, out)
    raw = (out / 'sdk-clock-candidate.json.gz').read_bytes()
    package = json.loads(gzip.decompress(raw))
    assert report['packageSha256'] == builder.sha(raw)
    for group, paths in builder.FILES.items():
        side = package[group]
        assert {p for p in side['after'] if side['after'][p] != side['before'][p]} == set(paths)
        assert set(side['after']) == set(side['before'])
        assert set(side['changes']) == set(paths)
        for p, data in side['changes'].items():
            assert builder.sha(base64.b64decode(data)) == side['after'][p]
    assert 'THIRDHAND_SDK_TIMING=0' in package['edge']['dropInText']
    assert package['robot']['newSource'] in package['robot']['dropInText']
    assert json.loads(base64.b64decode(package['cloud']['manifestBase64']))['deviceControl'] == 'explicit-read-only-enrollment'


@pytest.mark.parametrize('change', ['cloud', 'source', 'active_sdk', 'target_hash', 'robot_entry', 'diagnostic'])
def test_drift_and_unsafe_preconditions_reject_before_writing_output(inputs, change):
    cloud, device, out = inputs
    value = json.loads(device.read_text())
    if change == 'cloud':
        cloud.write_text('{}')
    elif change == 'source':
        value['edge']['source'] += '-other'
    elif change == 'active_sdk':
        value['context']['sdkConnected'] = True
    elif change == 'target_hash':
        value['robot']['files']['services/robot/src/control-policy.js'] = 'e'*64
    elif change == 'robot_entry':
        value['robot']['state']['ExecStart'] = 'unexpected'
    else:
        value['edge']['pythonpath'][1] = 'THIRDHAND_SDK_TIMING=1'
    device.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        builder.build(cloud, device, out)
    assert not out.exists()
