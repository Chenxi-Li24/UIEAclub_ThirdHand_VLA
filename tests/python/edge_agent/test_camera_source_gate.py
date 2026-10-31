import http.client
import io
import threading
from email.message import Message
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'services/edge-agent/src'))
from thirdhand_edge.camera_source_gate import create_source_gate


def test_source_gate_authenticates_before_opening_the_existing_camera():
    calls = []
    server = create_source_gate(token='a' * 64, port=0, open_source=lambda: calls.append(True))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        for path, headers in [('/edge-media/v1/raw', {}), ('/edge-media/v1/raw', {'X-ThirdHand-Media-Token': 'b' * 64}),
                              ('/edge-media/v1/raw', {'X-ThirdHand-Media-Token': 'a' * 64, 'Origin': 'https://example.invalid'}),
                              ('/edge-media/v1/raw?token=anything', {'X-ThirdHand-Media-Token': 'a' * 64})]:
            client = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=2)
            client.request('GET', path, headers=headers)
            response = client.getresponse()
            assert response.status in (403, 404)
            response.read()
            client.close()
        assert calls == []
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_source_gate_preserves_frame_headers_and_allows_only_one_upstream_reader():
    release = threading.Event()
    payload = b'--frame\r\nContent-Type: image/jpeg\r\nX-ThirdHand-Sequence: 42\r\nContent-Length: 4\r\n\r\nTEST\r\n'
    calls = []

    class Source:
        def __init__(self):
            self.headers = Message()
            self.headers['Content-Type'] = 'multipart/x-mixed-replace; boundary=frame'
            self.sent = False
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read1(self, _):
            release.wait(2)
            if self.sent: return b''
            self.sent = True
            return payload

    def open_source():
        calls.append(True)
        return Source()

    server = create_source_gate(token='a' * 64, port=0, open_source=open_source)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        first = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=3)
        first.request('GET', '/edge-media/v1/raw', headers={'X-ThirdHand-Media-Token': 'a' * 64})
        response = first.getresponse()
        assert response.status == 200
        second = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=2)
        second.request('GET', '/edge-media/v1/raw', headers={'X-ThirdHand-Media-Token': 'a' * 64})
        busy = second.getresponse()
        assert busy.status == 429
        busy.read()
        second.close()
        release.set()
        assert response.read() == payload
        first.close()
        assert calls == [True]
        assert b'Captured-At' not in payload
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
