"""Private one-reader adapter for an already-running Vision camera stream.

This process never opens camera hardware, imports a Robot client or changes frame
metadata. Missing capture timestamps remain missing and cannot authorize motion.
"""
import argparse
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import re
import stat
import threading
import urllib.request


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, *args, **kwargs):
        raise ValueError('Vision source must not redirect')


def create_source_gate(*, token, port=3112, open_source=None):
    if not isinstance(token, str) or not re.fullmatch(r'[a-f0-9]{64}', token):
        raise ValueError('Owner-only source token required')
    if type(port) is not int or not 0 <= port <= 65535:
        raise ValueError('Invalid source port')
    if open_source is None:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
        def open_source():
            return opener.open('http://127.0.0.1:3100/camera/xvisio/raw', timeout=3)
    occupied = threading.BoundedSemaphore(1)

    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def log_message(self, *_):
            pass  # Never log request credentials, query strings or frame content.

        def deny(self, status):
            self.send_response(status)
            self.send_header('Content-Length', '0')
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()

        def do_GET(self):
            if self.path != '/edge-media/v1/raw':
                self.deny(404)
                return
            supplied = self.headers.get_all('X-ThirdHand-Media-Token', [])
            if self.headers.get('Origin') is not None or self.headers.get('Cookie') is not None or len(supplied) != 1 or not re.fullmatch(r'[a-f0-9]{64}', supplied[0]) or not hmac.compare_digest(token, supplied[0]):
                self.deny(403)
                return
            if not occupied.acquire(blocking=False):
                self.deny(429)
                return
            started = False
            try:
                with open_source() as source:
                    if source.headers.get_content_type() != 'multipart/x-mixed-replace' or source.headers.get_param('boundary') != 'frame':
                        raise ValueError('Existing Vision stream unavailable')
                    self.send_response(200)
                    self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=frame')
                    self.send_header('Cache-Control', 'no-store')
                    self.send_header('Connection', 'close')
                    self.end_headers()
                    self.close_connection = True
                    started = True
                    while True:
                        chunk = source.read1(65536)
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        self.wfile.flush()
            except (OSError, ValueError):
                if not started:
                    self.deny(503)
                self.close_connection = True
            finally:
                occupied.release()

    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    server.daemon_threads = True
    return server


def main():
    parser = argparse.ArgumentParser(description='Private read-only camera source adapter')
    parser.add_argument('--token-file', type=Path, required=True)
    parser.add_argument('--port', type=int, default=3112)
    args = parser.parse_args()
    info = args.token_file.lstat()
    if not stat.S_ISREG(info.st_mode) or os.name == 'posix' and info.st_mode & 0o077:
        raise ValueError('Owner-only regular token file required')
    server = create_source_gate(token=args.token_file.read_text(encoding='ascii').strip(), port=args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
