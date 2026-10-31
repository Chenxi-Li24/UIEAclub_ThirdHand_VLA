"""Build an isolated adapter around the site's existing, possibly dirty Robot source.

Never overwrite the checkout or silently replace its controller/SDK policies.
The resulting server is permanently read-only, including when env flags change.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import tarfile

REPO = Path(__file__).resolve().parents[2]


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise ValueError('Site source differs; review the adapter before deployment')
    return text.replace(old, new)


def build(source, archive):
    original = {p.name: p.read_bytes() for p in source.iterdir()
                if p.is_file() and p.suffix in ('.js', '.py') and not p.name.startswith('._')}
    server = original['server.js'].decode('utf-8')
    server = replace_once(server, "const { RobotController } = require('./robot-controller');",
        "const { RobotController } = require('./robot-controller');\nconst {createRemoteRobotGateway}=require('./remote-gateway');")
    server = replace_once(server, '  const controller = new RobotController(config.robot);', '''  const controller = new RobotController(config.robot);
  if(config.remote?.enabled!==true)throw Error('READ_ONLY_REMOTE_MODE_REQUIRED');
  const edge=loadExecutionToken({tokenFile:config.remote.edgeTokenFile});
  const signingKeys=new Map(Object.entries(JSON.parse(fs.readFileSync(config.remote.cloudSigningKeysFile,'utf8'))));
  const remoteGateway=createRemoteRobotGateway({controller,deviceId:config.remote.deviceId,token:edge.token,signingKeys,readOnly:true});''')
    server = replace_once(server, '  const server = http.createServer((request, response) => {',
        '  const server = http.createServer(async (request, response) => {\n    if(await remoteGateway.handle(request,response))return;')
    server = replace_once(server, "  server.on('upgrade', (request, socket, head) => {",
        "  server.on('upgrade', (request, socket, head) => {\n    socket.end('HTTP/1.1 403 Forbidden\\r\\nConnection: close\\r\\n\\r\\n');return;")
    server = replace_once(server, '      closing = true;', '      closing = true;\n      await remoteGateway.close();')
    config = original['config.js'].decode('utf-8')
    config = replace_once(config, '    robot: {', '''    remote:{enabled:env.ROBOT_ACCESS_MODE==='remote',readOnly:true,
      deviceId:env.THIRDHAND_DEVICE_ID,edgeTokenFile:env.ROBOT_EDGE_TOKEN_FILE,
      cloudSigningKeysFile:env.ROBOT_CLOUD_SIGNING_KEYS_FILE},
    robot: {''')
    files = {'services/robot/src/' + name: data for name, data in original.items()}
    files['services/robot/src/server.js'] = server.encode()
    files['services/robot/src/config.js'] = config.encode()
    for relative in ['services/robot/src/remote-gateway.js', 'services/robot/src/control-policy.js',
                     'services/robot/src/lease-watchdog.js', 'services/device-relay/src/envelope.js',
                     'services/device-relay/src/protocol.js']:
        files[relative] = (REPO / relative).read_bytes()
    sha = lambda data: hashlib.sha256(data).hexdigest()
    manifest = {'format': 1, 'readOnly': True, 'automaticSdkConnect': False,
                'original': {name: sha(data) for name, data in original.items()},
                'files': {name: sha(data) for name, data in files.items()}}
    files['robot-read-only-manifest.json'] = (json.dumps(manifest, sort_keys=True, indent=2) + '\n').encode()
    with tarfile.open(archive, 'w:gz') as tar:
        for name, data in sorted(files.items()):
            entry = tarfile.TarInfo(name); entry.mode = 0o644; entry.size = len(data)
            tar.addfile(entry, io.BytesIO(data))
    return {'path': str(archive), 'sha256': sha(archive.read_bytes()), 'files': len(files),
            'modifiedSiteFiles': ['server.js', 'config.js'], 'readOnly': True}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--archive', type=Path, required=True); args = parser.parse_args()
    print(json.dumps(build(args.source.resolve(), args.archive.resolve())))
