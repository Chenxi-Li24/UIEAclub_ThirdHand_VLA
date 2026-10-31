import asyncio
import base64
from contextlib import contextmanager
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import socket
import ssl
import sys
import threading
import uuid

import pytest
from cryptography.hazmat.primitives import serialization

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'services/edge-agent/src'))
from pki_fixture import generate
from thirdhand_edge.outbox import Outbox
from thirdhand_edge.transport import DeviceConfig
from thirdhand_edge import upload, runtime


@contextmanager
def endpoint(root, modes=None):
    generate(root)
    key = serialization.load_pem_private_key((root / 'device.key').read_bytes(), password=None)
    state = {'connections': 0, 'requests': [], 'modes': list(modes or []),
             'started': threading.Event(), 'release': threading.Event()}

    class Server(ThreadingHTTPServer):
        daemon_threads = True
        def get_request(self):
            peer, address = super().get_request()
            state['connections'] += 1
            peer.settimeout(3)
            return peer, address

    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'
        def log_message(self, *_args):
            pass

        def do_POST(self):
            assert self.path == '/edge/v1/telemetry-batches' and self.connection.getpeercert()
            value = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            raw = base64.urlsafe_b64decode(value['payloadBase64url'] + '==')
            key.public_key().verify(base64.urlsafe_b64decode(value['signatureBase64url'] + '=='), raw)
            assert hashlib.sha256(raw).hexdigest() == value['digest']
            state['requests'].append({'wire': value, 'payload': raw})
            mode = state['modes'].pop(0) if state['modes'] else 'ok'
            state['started'].set()
            if mode == 'block':
                state['release'].wait(3)
            if mode == 'lost':
                self.connection.shutdown(socket.SHUT_RDWR)
                self.connection.close()
                self.close_connection = True
                return
            ack = {'batchId': value['batchId'], 'digest': value['digest'], 'persisted': True}
            if mode == 'mismatch':
                ack['digest'] = '0' * 64
            data = b'x' * 4097 if mode == 'oversized' else json.dumps(ack).encode()
            self.send_response(302 if mode == 'redirect' else 200)
            self.send_header('Content-Type', 'application/json')
            if mode == 'redirect':
                self.send_header('Location', 'https://must-not-follow.invalid/private')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError, ssl.SSLError):
                pass

    server = Server(('127.0.0.1', 0), Handler)
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(root / 'server.pem', root / 'server.key')
    tls.load_verify_locations(root / 'ca.pem')
    tls.verify_mode = ssl.CERT_REQUIRED
    server.socket = tls.wrap_socket(server.socket, server_side=True)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    config = DeviceConfig(url=f'wss://localhost:{server.server_port}/edge/v1/connect',
                          device_id=str(uuid.uuid4()), boot_id=str(uuid.uuid4()),
                          certificate=root / 'device.pem', private_key=root / 'device.key', ca_file=root / 'ca.pem')
    try:
        yield config, state
    finally:
        state['release'].set()
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)


def outbox(root, config, count):
    box = Outbox(root / 'outbox.sqlite', device_id=config.device_id, boot_id=config.boot_id)
    for index in range(count):
        box.append_sample({'capturedAt': '2026-10-31T12:00:00.000Z', 'monotonicNs': str(index),
                           'clockQuality': 'estimated', 'jointPositionRad': [0, 1, -1, 0, 0, 0],
                           'sdkConnected': False, 'moving': False})
        box.seal_batch('robot_samples')
    return box


def test_legacy_upload_api_reuses_one_verified_connection_across_multiple_batches(tmp_path):
    with endpoint(tmp_path) as (config, state):
        box = outbox(tmp_path, config, 3)
        try:
            assert asyncio.run(upload.upload_pending(config, box)) == {'acknowledged': 3}
            assert state['connections'] == 1
            assert len(state['requests']) == 3 and box.pending_batches() == []
        finally:
            box.close()


def test_long_lived_client_reuses_tls_and_cached_key_across_drain_rounds(tmp_path, monkeypatch):
    with endpoint(tmp_path) as (config, state):
        box = outbox(tmp_path, config, 3)
        calls = {'key': 0, 'tls': 0}
        load_key, create_tls = upload.serialization.load_pem_private_key, upload.create_tls_context
        def key(*args, **kwargs):
            calls['key'] += 1
            return load_key(*args, **kwargs)
        def tls(*args, **kwargs):
            calls['tls'] += 1
            context = create_tls(*args, **kwargs)
            assert context.check_hostname and context.verify_mode == ssl.CERT_REQUIRED
            return context
        monkeypatch.setattr(upload.serialization, 'load_pem_private_key', key)
        monkeypatch.setattr(upload, 'create_tls_context', tls)
        assert hasattr(upload, 'TelemetryUploadClient'), 'A persistent upload client is required'
        client = upload.TelemetryUploadClient(config)
        async def run():
            assert await client.upload_pending(box, limit=1) == {'acknowledged': 1}
            assert await client.upload_pending(box, limit=2) == {'acknowledged': 2}
        try:
            asyncio.run(run())
            assert calls == {'key': 1, 'tls': 1} and state['connections'] == 1
        finally:
            client.close()
            box.close()


@pytest.mark.parametrize('failure,code', [('mismatch', 'UPLOAD_ACK_MISMATCH'), ('lost', 'UPLOAD_UNAVAILABLE')])
def test_bad_or_missing_ack_retains_exact_batch_and_only_a_later_call_retries(tmp_path, failure, code):
    with endpoint(tmp_path, [failure, 'ok']) as (config, state):
        box = outbox(tmp_path, config, 1)
        saved = box.pending_batches()[0]
        assert hasattr(upload, 'TelemetryUploadClient'), 'A persistent upload client is required'
        client = upload.TelemetryUploadClient(config)
        async def run():
            assert await client.upload_pending(box) == {'acknowledged': 0, 'error': code}
            assert len(state['requests']) == 1 and box.pending_batches()[0] == saved
            assert await client.upload_pending(box) == {'acknowledged': 1}
        try:
            asyncio.run(run())
            assert state['requests'][0] == state['requests'][1]
            assert state['connections'] == 2 and box.pending_batches() == []
        finally:
            client.close()
            box.close()


@pytest.mark.parametrize('failure', ['redirect', 'oversized'])
def test_redirect_or_oversized_response_never_acknowledges_or_retries(tmp_path, failure):
    with endpoint(tmp_path, [failure]) as (config, state):
        box = outbox(tmp_path, config, 1)
        assert hasattr(upload, 'TelemetryUploadClient'), 'A persistent upload client is required'
        client = upload.TelemetryUploadClient(config)
        try:
            assert asyncio.run(client.upload_pending(box)) == {'acknowledged': 0, 'error': 'UPLOAD_UNAVAILABLE'}
            assert len(state['requests']) == 1 and len(box.pending_batches()) == 1
        finally:
            client.close()
            box.close()


def test_cancel_closes_the_inflight_connection_and_keeps_the_unacknowledged_batch(tmp_path):
    with endpoint(tmp_path, ['block']) as (config, state):
        box = outbox(tmp_path, config, 1)
        saved = box.pending_batches()[0]
        assert hasattr(upload, 'TelemetryUploadClient'), 'A persistent upload client is required'
        client = upload.TelemetryUploadClient(config)
        async def run():
            task = asyncio.create_task(client.upload_pending(box))
            assert await asyncio.to_thread(state['started'].wait, 5)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert box.pending_batches()[0] == saved
            assert await client.upload_pending(box) == {'acknowledged': 0, 'error': 'UPLOAD_UNAVAILABLE'}
        try:
            asyncio.run(run())
            assert len(state['requests']) == 1
        finally:
            state['release'].set()
            client.close()
            box.close()


def test_upload_worker_keeps_one_client_and_drains_backlog_without_a_one_second_pause(tmp_path, monkeypatch):
    clients, sleeps, closed = [], [], []
    count = [0]
    class Box:
        def __init__(self, *_args, **_kwargs):
            pass
        def pending_batches(self, **_kwargs):
            return [object()] if count[0] == 1 else []
        def close(self):
            closed.append('box')
    async def drain(*_args, **_kwargs):
        count[0] += 1
        return {'acknowledged': 20 if count[0] == 1 else 5}
    class Client:
        def __init__(self, config):
            clients.append(config)
        upload_pending = staticmethod(drain)
        def close(self):
            closed.append('client')
    async def sleep(delay):
        sleeps.append(delay)
        if len(sleeps) == 2:
            raise RuntimeError('test-worker-complete')
    monkeypatch.setattr(runtime, 'Outbox', Box)
    monkeypatch.setattr(runtime, 'TelemetryUploadClient', Client, raising=False)
    monkeypatch.setattr(runtime, 'upload_pending', drain, raising=False)
    monkeypatch.setattr(runtime.asyncio, 'sleep', sleep)
    config = {'state_directory': tmp_path / 'state', 'url': 'wss://edge.example.invalid/edge/v1/connect',
              'device_id': str(uuid.uuid4()), 'certificate': tmp_path / 'device.pem', 'private_key': tmp_path / 'device.key'}
    with pytest.raises(RuntimeError, match='test-worker-complete'):
        runtime.run_worker(config, 'upload', str(uuid.uuid4()))
    assert sleeps == [0, 1] and len(clients) == 1
    assert closed == ['client', 'box']
