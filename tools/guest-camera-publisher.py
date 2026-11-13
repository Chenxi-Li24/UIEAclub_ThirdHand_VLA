#!/usr/bin/env python3
"""Publish a bounded raw camera preview; never calls robot/control endpoints."""
import os
import time
import urllib.request

TARGET = os.environ['GUEST_CAMERA_UPLOAD_URL']
TOKEN = os.environ['GUEST_CAMERA_UPLOAD_TOKEN']
SOURCE = 'http://127.0.0.1:3100/camera/xvisio/raw'
MAX_BYTES = 1024 * 1024

def run():
    while True:
        try:
            with urllib.request.urlopen(SOURCE, timeout=5) as stream:
                buffer = b''
                last_sent = 0
                while True:
                    chunk = stream.read1(65536)
                    if not chunk:
                        break
                    buffer += chunk
                    while True:
                        start = buffer.find(b'\xff\xd8')
                        end = buffer.find(b'\xff\xd9', max(start, 0) + 2)
                        if start < 0 or end < 0:
                            break
                        frame, buffer = buffer[start:end + 2], buffer[end + 2:]
                        if len(frame) <= MAX_BYTES and time.monotonic() - last_sent >= 2:
                            request = urllib.request.Request(TARGET, data=frame, headers={
                                'Content-Type': 'image/jpeg', 'Authorization': 'Bearer ' + TOKEN})
                            with urllib.request.urlopen(request, timeout=5) as response:
                                response.read(1024)
                            last_sent = time.monotonic()
                    if len(buffer) > MAX_BYTES:
                        raise ValueError('Frame exceeds preview limit')
        except Exception:
            # Do not log tokens, image data or private URLs.
            print('Camera preview unavailable; retrying.', flush=True)
        time.sleep(3)

if __name__ == '__main__':
    run()
