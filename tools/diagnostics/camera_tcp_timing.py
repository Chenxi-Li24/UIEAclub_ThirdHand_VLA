"""Bounded TCP metadata capture for the approved camera link investigation.

No packet payload, certificate, authorization header or media content is saved.
Run on the camera Ubuntu host; observe only its existing cloud TLS connection.
"""
import argparse
import datetime
import json
import os
from pathlib import Path
import subprocess
import time

os.umask(0o077)
parser = argparse.ArgumentParser()
parser.add_argument('--seconds', type=int, default=120)
duration = parser.parse_args().seconds
if not 30 <= duration <= 600:
    raise ValueError('Capture duration must be between30 and600 seconds')
base = Path.home() / '.local/share/thirdhand-stage-camera/20261031/diagnostics'
base.mkdir(mode=0o700, exist_ok=True)
stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
target = base / ('tcp-timing-' + stamp)
target.mkdir(mode=0o700)
start = datetime.datetime.now(datetime.timezone.utc)
with (target / 'tcp-metadata.txt').open('x') as output, (target / 'capture-status.txt').open('x') as errors:
    process = subprocess.Popen(['sudo', '-n', 'timeout', '--signal=TERM', '--kill-after=3', str(duration),
        '/usr/sbin/tcpdump', '-tt', '-nn', '-S', '-l', '-i', 'wlp7s0',
        'host', '47.94.95.244', 'and', 'tcp', 'port', '443'], stdout=output, stderr=errors)
    samples = []
    try:
        for _ in range(duration):
            samples.append({'utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                'tcp': subprocess.run(['ss', '-tin', 'dst', '47.94.95.244:443'],
                                     capture_output=True, text=True, check=True).stdout})
            if process.poll() is not None:
                break
            time.sleep(1)
        process.wait(timeout=8)
    finally:
        if process.poll() is None:
            subprocess.run(['sudo', '-n', 'kill', '-TERM', str(process.pid)], check=True)
            process.wait(timeout=8)
    (target / 'tcp-stats.json').write_text(json.dumps(samples, indent=2))
finish = datetime.datetime.now(datetime.timezone.utc)
journal = subprocess.run(['journalctl', '-u', 'thirdhand-stage-camera-publisher.service',
    '--since', start.astimezone().strftime('%Y-%m-%d %H:%M:%S'),
    '--until', finish.astimezone().strftime('%Y-%m-%d %H:%M:%S'), '-o', 'json', '--no-pager'],
    capture_output=True, text=True, check=True)
events = []
for line in journal.stdout.splitlines():
    row = json.loads(line)
    try:
        message = json.loads(row.get('MESSAGE', ''))
    except (ValueError, TypeError):
        continue
    if message.get('event') != 'camera.unavailable':
        continue
    events.append({'utc': datetime.datetime.fromtimestamp(int(row['__REALTIME_TIMESTAMP']) / 1e6,
        datetime.timezone.utc).isoformat(), 'causes': [{k: v for k, v in cause.items()
        if k in {'type', 'code', 'phase', 'elapsedMs', 'recentSuccessMs', 'httpStatus'}}
        for cause in message.get('causes', [])]})
report = {'start': start.isoformat(), 'finish': finish.isoformat(),
    'captureExit': process.returncode, 'captureBytes': (target / 'tcp-metadata.txt').stat().st_size,
    'sampleCount': len(samples), 'failures': events, 'directory': str(target)}
(target / 'report.json').write_text(json.dumps(report, indent=2))
print(json.dumps(report))
