"""C2g root-only backup/preflight. Never prints environment or credential values."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
from datetime import datetime, timezone


def command(args):
    return subprocess.run(args, check=True, capture_output=True, text=True, timeout=45).stdout


def main():
    assert os.geteuid() == 0
    os.umask(0o077)
    current = Path('/opt/thirdhand-stage/current').resolve()
    assert current == Path('/opt/thirdhand-stage/releases/c8f42e8d92bbe2c7')
    main_index = Path('/www/wwwroot/uiea-thirdhand-static/index.html')
    assert hashlib.sha256(main_index.read_bytes()).hexdigest() == '639bb62379c763ebbd4610125cafc3ebff3aa14debb0c3ca2f50ee75d1a478bd'
    root = Path('/var/backups/thirdhand') / ('access-C2g-camera-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    root.mkdir(mode=0o700)
    files = ['/etc/thirdhand-stage/cloud.env', '/etc/nginx/sites-available/staging.uiea-thirdhand.com',
             '/etc/nginx/sites-available/edge.uiea-thirdhand.com', '/etc/nginx/nginx.conf',
             '/etc/group', '/etc/gshadow', '/etc/systemd/system/thirdhand-stage.service']
    hashes = {}
    for name in files:
        source = Path(name)
        if not source.is_file():
            raise RuntimeError('BACKUP_SOURCE_MISSING')
        target = root / name.lstrip('/')
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        hashes[name] = hashlib.sha256(source.read_bytes()).hexdigest()
    for name in ['/etc/systemd/system/thirdhand-stage.service.d', '/etc/ufw']:
        source = Path(name)
        if source.is_dir():
            shutil.copytree(source, root / name.lstrip('/'))
    dump = root / 'thirdhand-stage.before-camera.dump'
    with dump.open('xb') as output:
        subprocess.run(['runuser', '-u', 'postgres', '--', '/usr/lib/postgresql/17/bin/pg_dump',
                        '-h', '/run/thirdhand-stage-db', '-p', '55440', '-Fc', 'thirdhand_stage'],
                       stdout=output, stderr=subprocess.PIPE, check=True, timeout=45)
    (root / 'listeners.before.txt').write_text(command(['ss', '-lntup']))
    (root / 'firewall.before.txt').write_text(command(['ufw', 'status', 'numbered']))
    (root / 'iptables.before.txt').write_text(command(['iptables-save']))
    (root / 'units.before.txt').write_text(command(['systemctl', 'show', 'thirdhand-stage.service',
          'thirdhand-stage-export.service', 'thirdhand-probe-relay.service', 'nginx.service',
          '--property=Id,ActiveState,User,Group,SupplementaryGroups,MemoryCurrent,MemoryMax,RuntimeDirectory']))
    mem = {k: int(v.split()[0]) for k, v in (line.split(':', 1) for line in Path('/proc/meminfo').read_text().splitlines())
           if k in ['MemTotal', 'MemAvailable']}
    result = {'backup': str(root), 'currentRelease': str(current), 'sourceHashes': hashes,
              'dumpBytes': dump.stat().st_size, 'memoryKiB': mem, 'mainIndexPreserved': True,
              'configurationApplied': False}
    (root / 'backup.json').write_text(json.dumps(result, indent=2))
    pointer = Path('/var/backups/thirdhand/C2g-backup-path')
    assert not pointer.exists()
    pointer.write_text(str(root) + '\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
