"""C2 acceptance entry: real isolated PostgreSQL and no-hardware API composition."""
import os
from pathlib import Path
import subprocess


def test_no_hardware_remote_acceptance():
    root = Path(__file__).resolve().parents[3]
    assert os.environ.get('TEST_DATABASE_URL'), 'TEST_DATABASE_URL is required; no skipped database acceptance'
    node = os.environ.get('NODE_EXECUTABLE', 'node')
    names = ['staging-runtime', 'staging-mailbox', 'accounts', 'admin', 'mfa', 'sessions',
             'auth-ui', 'account-security-ui', 'preferences', 'simulation-isolation',
             'history-http', 'exports', 'takeovers', 'restore-state', 'tutorial-adapter']
    result = subprocess.run([node, '--test', '--test-concurrency=4',
                             *[f'tests/node/public_access/{name}.test.js' for name in names]],
                            cwd=root, text=True, encoding='utf-8', capture_output=True, timeout=240)
    assert result.returncode == 0, (result.stdout + result.stderr)[-18000:]
    assert 'skip' not in result.stdout.lower() or 'skipped 0' in result.stdout.lower(), result.stdout[-3000:]
