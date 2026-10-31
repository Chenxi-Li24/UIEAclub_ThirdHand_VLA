"""Fixed-target public-certificate reload for the actual system Nginx.

No certificate issuance, device CA changes, configuration edits or private-key
output. This candidate is not installed merely because it exists in Git.
"""
import os
from pathlib import Path
import socket
import ssl
import subprocess
import sys
import time

TARGETS = tuple((host, Path('/www/server/panel/vhost/cert') / host / 'fullchain.pem',
                 Path('/www/server/panel/vhost/cert') / host / 'privkey.pem')
                for host in ('uiea-thirdhand.com', 'edge.uiea-thirdhand.com'))


def served_leaf(host):
    context = ssl.create_default_context()
    with socket.create_connection(('127.0.0.1', 443), timeout=1) as connection:
        with context.wrap_socket(connection, server_hostname=host) as tls:
            return tls.getpeercert(binary_form=True)


def reload_public_tls(targets=TARGETS, *, run=subprocess.run, peer=served_leaf):
    try:
        expected = {}
        for host, cert, key in targets:
            if not cert.is_file() or not key.is_file() or key.is_symlink():
                raise ValueError('Missing fixed certificate file')
            if os.name == 'posix':
                if key.stat().st_uid != 0:
                    raise ValueError('Unexpected private key owner')
                if key.stat().st_mode & 0o777 != 0o600:
                    key.chmod(0o600)
            run(['/usr/bin/openssl', 'verify', '-CApath', '/etc/ssl/certs', '-purpose', 'sslserver',
                 '-verify_hostname', host, '-untrusted', str(cert), str(cert)],
                capture_output=True, check=True, timeout=10)
            expected[host] = run(['/usr/bin/openssl', 'x509', '-in', str(cert), '-outform', 'DER'],
                                 capture_output=True, check=True, timeout=10).stdout
        run(['/usr/sbin/nginx', '-t'], capture_output=True, check=True, timeout=10)

        def matches():
            try:
                return all(peer(host) == der for host, der in expected.items())
            except (OSError, ssl.SSLError):
                return False

        if matches():
            return False
        run(['/bin/systemctl', 'reload', 'nginx'], capture_output=True, check=True, timeout=15)
        deadline = time.monotonic() + 5
        while True:
            if matches():
                return True
            if time.monotonic() >= deadline:
                raise ValueError('Public certificate did not converge')
            time.sleep(.1)
    except Exception:
        raise RuntimeError('PUBLIC_TLS_RELOAD_FAILED') from None


def main():
    if sys.platform != 'linux' or os.geteuid() != 0:
        print('PUBLIC_TLS_ROOT_LINUX_REQUIRED', file=sys.stderr)
        raise SystemExit(1)
    try:
        changed = reload_public_tls()
        print('PUBLIC_TLS_RELOADED_AND_VERIFIED' if changed else 'PUBLIC_TLS_UNCHANGED')
    except RuntimeError:
        print('PUBLIC_TLS_RELOAD_FAILED', file=sys.stderr)
        raise SystemExit(1)


if __name__ == '__main__':
    main()
