"""Install the approved C3a read-only adapter without editing the site checkout."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import secrets
import shlex
import shutil
import subprocess
import tarfile
import time
import urllib.request

BASE = Path('/home/nieqingcao/.local/share/thirdhand-stage-device/20261031')
SITE = Path('/home/nieqingcao/ThirdHand/UIEAclub_ThirdHand_VLA')
UNITS = Path('/home/nieqingcao/.config/systemd/user')
ROBOT_UNIT = 'thirdhand-tcp-calibration-robot.service'
AGENT_UNIT = 'thirdhand-stage-edge-read-only.service'
NODE = SITE / 'local/runtimes/node/bin/node'
PYTHON = Path('/home/nieqingcao/.local/share/thirdhand-media-acceptance/20261031/venv/bin/python')
DEVICE = 'ee625a57-049a-4c5d-92e1-9578ab9d21c3'
ROBOT_SHA = 'b250c684d8dcd3a878858ab893761302a99342b053a21471ab5851e227e39377'
AGENT_SHA = '5d093cd7e4a6f65afbf056f026d1d50b8522d06af020cf04a7b3c6c3d1328895'
SDK_SHA = '0f4b5f72241392f8a9faf20cc0e42917197a8d417e4db3de8380f0eb01b88be9'


def run(args, data=None, env=None):
    return subprocess.run([str(a) for a in args], input=data, text=True, check=True, capture_output=True, env=env).stdout


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, text):
    assert not path.is_symlink()
    path.write_text(text); path.chmod(0o600)


def health():
    with urllib.request.urlopen('http://127.0.0.1:3000/health', timeout=3) as response:
        return json.load(response)


def validate():
    assert os.getuid() == 1000 and BASE.resolve() == BASE and not BASE.is_symlink()
    assert SITE.is_dir() and (SITE / 'node_modules/ws/package.json').is_file()
    incoming = BASE / 'incoming'
    assert sha(incoming / 'C3-robot-read-only.tar.gz') == ROBOT_SHA
    assert sha(incoming / 'C3a-agent-source.tar.gz') == AGENT_SHA
    with tarfile.open(incoming / 'C3-robot-read-only.tar.gz') as archive:
        manifest = json.load(archive.extractfile('robot-read-only-manifest.json'))
    assert manifest['readOnly'] is True and manifest['automaticSdkConnect'] is False
    assert all(sha(SITE / 'services/robot/src' / name) == value for name, value in manifest['original'].items())
    raw = run(['systemctl', '--user', 'show', ROBOT_UNIT, '-p', 'Environment', '--value'])
    environment = dict(value.split('=', 1) for value in shlex.split(raw) if '=' in value)
    expected = {'STARTOUCH_PYTHON': str(SITE / 'local/runtimes/python/bin/python'),
        'STARTOUCH_SDK_PATH': str(SITE / 'local/sdk/startouch'),
        'STARTOUCH_MODULE_PATH': str(SITE / 'local/generated/startouch-python/startouch_sdk/interface_py'),
        'STARTOUCH_FOLLOW_URDF': str(SITE / 'assets/robot/startouch-v3/FastTouchV3.SLDASM.urdf'),
        'THIRDHAND_READY_FILE': str(SITE / 'runtime/live/main-step1/robot.ready'),
        'ROBOT_HOST': '127.0.0.1', 'ROBOT_PORT': '3000', 'STARTOUCH_SPEED_SCALE': '0.05'}
    assert all(environment.get(key) == value for key, value in expected.items())
    assert sha(Path(environment['STARTOUCH_MODULE_PATH']) / 'startouchclass.py') == SDK_SHA
    current = health()
    assert current['robot']['connected'] is False and current['robot']['moving'] is False
    return {'validated': True, 'siteSourceUnchanged': True, 'runtimeBindings': expected,
            'sdkConnected': False, 'motionCommands': 0}


def extract(archive, destination, manifest_name):
    assert destination.parent == BASE and not destination.exists()
    destination.mkdir(mode=0o700)
    with tarfile.open(archive) as tar:
        seen = set()
        for member in tar:
            name = PurePosixPath(member.name)
            assert member.isfile() and not name.is_absolute() and '..' not in name.parts and member.name not in seen
            seen.add(member.name); target = destination.joinpath(*name.parts)
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with tar.extractfile(member) as source, target.open('xb') as output:
                shutil.copyfileobj(source, output)
            target.chmod(0o600)
    manifest = json.loads((destination / manifest_name).read_text())
    assert all(sha(destination / name) == digest for name, digest in manifest['files'].items())


def rollback(agent_launched):
    run(['systemctl', '--user', 'stop', AGENT_UNIT])
    if agent_launched:
        current = health()
        # Never restore legacy ingress over an unconfirmed SDK connection.
        assert current['robot']['connected'] is False and current['robot']['moving'] is False
    drop = UNITS / (ROBOT_UNIT + '.d') / '99-read-only-sdk.conf'
    if drop.exists():
        drop.rename(BASE / 'before' / '99-read-only-sdk.withdrawn.conf')
    run(['systemctl', '--user', 'daemon-reload'])
    run(['systemctl', '--user', 'restart', ROBOT_UNIT])


def install():
    os.umask(0o077); result = validate()
    before = BASE / 'before'; assert not before.exists(); before.mkdir(mode=0o700)
    write(before / 'effective-robot-unit.txt', run(['systemctl', '--user', 'cat', ROBOT_UNIT]))
    write(before / 'preflight.json', json.dumps(result, indent=2))
    incoming, private = BASE / 'incoming', BASE / 'private'
    assert private.resolve() == private and private.stat().st_mode & 0o077 == 0
    public = json.loads((incoming / 'enrollment-public.json').read_text())
    assert set(public) == {'deviceId', 'credentialId', 'readOnly', 'certificatePem', 'caPem', 'signingKeys', 'expiresAt'}
    assert public['deviceId'] == DEVICE and public['readOnly'] is True
    assert set(public['signingKeys']) == {'sdk-stage-readonly-v1'}
    assert all(value.startswith('-----BEGIN PUBLIC KEY-----') for value in public['signingKeys'].values())
    write(private / 'device.pem', public['certificatePem']); write(private / 'ca.pem', public['caPem'])
    assert run(['openssl', 'x509', '-in', private / 'device.pem', '-pubkey', '-noout']).strip() == run(['openssl', 'pkey', '-in', private / 'device.key', '-pubout']).strip()
    run(['openssl', 'verify', '-purpose', 'sslclient', '-CAfile', private / 'ca.pem', private / 'device.pem'])
    write(private / 'cloud-publickeys.json', json.dumps(public['signingKeys']))
    token = private / 'edge.token'; assert not token.exists(); write(token, secrets.token_hex(32) + '\n')
    write(private / 'robot.env', f'THIRDHAND_DEVICE_ID={DEVICE}\nROBOT_EDGE_TOKEN_FILE={token}\nROBOT_CLOUD_SIGNING_KEYS_FILE={private / "cloud-publickeys.json"}\n')
    (BASE / 'state').mkdir(mode=0o700)
    config = {'url': 'wss://edge.uiea-thirdhand.com/edge/v1/connect', 'device_id': DEVICE,
        # The private CA issues the CLIENT certificate. The public edge server
        # uses a public CA, validated by the system trust store (as the camera).
        'certificate': str(private / 'device.pem'), 'private_key': str(private / 'device.key'),
        'robot_origin': 'http://127.0.0.1:3000', 'robot_token_file': str(token),
        'signing_keys_file': str(private / 'cloud-publickeys.json'), 'state_directory': str(BASE / 'state'),
        'outbox_max_bytes': 268435456}
    toml = '\n'.join(f'{key} = {json.dumps(value)}' for key, value in config.items())
    toml += '\n[versions]\nschema = 1\nsdk = "sha256:' + SDK_SHA + '"\nframePolicy = "measured-flange-v1"\n'
    write(private / 'agent.toml', toml)
    extract(incoming / 'C3-robot-read-only.tar.gz', BASE / 'robot', 'robot-read-only-manifest.json')
    extract(incoming / 'C3a-agent-source.tar.gz', BASE / 'agent-source', 'agent-source-manifest.json')
    # RobotController resolves the shared contract validator by a relative path.
    # Retain the site's exact validator/schemas, as well as its Node packages.
    contracts = SITE / 'platform/contracts'
    target = BASE / 'robot/platform/contracts'; target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(contracts, target, ignore=shutil.ignore_patterns('node_modules', '__pycache__'))
    write(BASE / 'robot/site-contracts-manifest.json', json.dumps({
        str(p.relative_to(target)): sha(p) for p in target.rglob('*') if p.is_file()}, indent=2))
    run([NODE, '-e', 'require(process.argv[1])', BASE / 'robot/services/robot/src/server.js'],
        env={**os.environ, 'NODE_PATH': str(SITE / 'node_modules')})
    # Config parsing imports no SDK and performs no connection.
    run([PYTHON, '-c', 'from thirdhand_edge.runtime import load_runtime_config;load_runtime_config(' + repr(str(private / 'agent.toml')) + ')'],
        env={**os.environ, 'PYTHONPATH': str(BASE / 'agent-source')})
    drop = UNITS / (ROBOT_UNIT + '.d') / '99-read-only-sdk.conf'; assert not drop.exists()
    unit = UNITS / AGENT_UNIT; assert not unit.exists()
    drop.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(incoming / '99-read-only-sdk.conf', drop)
    shutil.copyfile(incoming / AGENT_UNIT, unit); drop.chmod(0o644); unit.chmod(0o644)
    agent_launched = False
    try:
        run(['systemctl', '--user', 'daemon-reload']); run(['systemctl', '--user', 'restart', ROBOT_UNIT])
        for attempt in range(40):
            try:
                current = health(); assert current['robot']['connected'] is False
                break
            except Exception:
                if attempt == 39: raise
                time.sleep(0.25)
        request = urllib.request.Request('http://127.0.0.1:3000/edge-control/v1/context', headers={'x-thirdhand-edge-token': token.read_text().strip()})
        with urllib.request.urlopen(request, timeout=3) as response:
            context = json.load(response)
        assert context['readOnly'] is True and context['sdkConnected'] is False
        agent_launched = True
        run(['systemctl', '--user', 'enable', '--now', AGENT_UNIT])
    except Exception:
        try: rollback(agent_launched)
        except Exception as error: write(before / 'rollback-failed.json', json.dumps({'errorType': type(error).__name__}))
        raise
    result.update({'installed': True, 'readOnly': True, 'automaticSdkConnect': False,
                   'certificateExpiresAt': public['expiresAt']})
    write(BASE / 'installed.json', json.dumps(result, indent=2)); return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--install', action='store_true'); args = parser.parse_args()
    print(json.dumps(install() if args.install else validate()))
