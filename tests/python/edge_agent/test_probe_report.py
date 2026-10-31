import asyncio
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'services/edge-agent/src'))
from thirdhand_edge import probe


def test_unexpected_disconnect_ends_probe_without_retry_or_secret_exception(monkeypatch):
    attempts = []
    async def failing(config, *args, **kwargs):
        attempts.append(config.boot_id)
        raise RuntimeError('private key material and sensitive endpoint')
    monkeypatch.setattr(probe, 'connect_device', failing)
    values = {'url': 'wss://example.test/edge/v1/connect',
              'device_id': 'd9935e75-68ab-4697-b9bd-bb01b6e4cc1b',
              'certificate': Path('not-read.pem'), 'private_key': Path('not-read.key')}
    report = asyncio.run(probe.run_probe(values, duration_seconds=1, cycles=3))
    assert report['completed'] is False
    assert report['completedCycles'] == 0
    assert report['controlAuthorized'] is False
    assert len(attempts) == 1
    assert report['error'] == 'DEVICE_PROBE_FAILED'
    assert 'sensitive' not in json.dumps(report)
    assert 'private key' not in json.dumps(report)
