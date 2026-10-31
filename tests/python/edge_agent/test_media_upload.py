import asyncio
import base64
import json
from pathlib import Path
import ssl
import sys
import threading
from types import SimpleNamespace
import uuid

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

sys.path.insert(0,str(Path(__file__).resolve().parents[3]/'services/edge-agent/src'))
from thirdhand_edge import media_upload
from thirdhand_edge.protocol import ProtocolError


def fixture(tmp_path,monkeypatch,statuses=None,blocked=False):
    key=Ed25519PrivateKey.generate();path=tmp_path/'device.key'
    path.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()));path.chmod(0o600)
    monkeypatch.setattr(media_upload,'create_tls_context',lambda _:ssl.create_default_context())
    clock=[1700000000000000000];monkeypatch.setattr(media_upload.time,'time_ns',lambda:clock[0])
    connections=[];requests=[];statuses=list(statuses or [200]);started=threading.Event();release=threading.Event();finished=threading.Event()
    class Socket:
        def settimeout(self,value):assert value==.6
        def shutdown(self,_):release.set()
    class Response:
        will_close=False
        def __init__(self,status):self.status=status
        def read(self,limit):assert limit==24001;return b'{"envelope":{"fixture":true}}'
        def close(self):pass
    class Connection:
        def __init__(self,host,port,*,context,timeout):
            assert host=='edge.example.invalid' and port==443 and context.check_hostname and context.verify_mode==ssl.CERT_REQUIRED
            assert timeout==5
            self.sock=None;self.closed=False;connections.append(self)
        def connect(self):clock[0]+=2000000000;self.sock=Socket()
        def request(self,method,path,body,headers):
            assert self.auto_open==0
            assert method=='POST' and path=='/edge/v1/media-grant' and headers=={'Content-Type':'application/json'}
            envelope=json.loads(body);raw=base64.urlsafe_b64decode(envelope['payloadBase64url']+'==')
            key.public_key().verify(base64.urlsafe_b64decode(envelope['signatureBase64url']+'=='),raw)
            payload=json.loads(raw);assert payload['issuedAt']==clock[0]//1000000
            assert payload['expiresAt']-payload['issuedAt']==950
            requests.append(payload)
        def getresponse(self):
            started.set()
            try:
                if blocked:assert release.wait(2)
                return Response(statuses.pop(0) if len(statuses)>1 else statuses[0])
            finally:finished.set()
        def close(self):self.closed=True;release.set()
    monkeypatch.setattr(media_upload.http.client,'HTTPSConnection',Connection)
    monkeypatch.setattr(media_upload,'_CoalescedHTTPSConnection',Connection)
    client=media_upload.MediaGrantClient(SimpleNamespace(url='wss://edge.example.invalid/edge/v1/connect',private_key=path))
    return client,connections,requests,started,finished


def test_camera_grants_reuse_verified_tls_and_sign_after_the_connection_handshake(tmp_path,monkeypatch):
    client,connections,requests,_,_=fixture(tmp_path,monkeypatch)
    async def check():
        for sequence in [1,2,3]:assert await client.request({},str(uuid.uuid4()),sequence,None)=={'fixture':True}
    try:asyncio.run(check())
    finally:client.close()
    assert len(connections)==1 and len(requests)==3 and connections[0].closed


def test_bad_http_response_is_not_retried_and_the_connection_is_discarded(tmp_path,monkeypatch):
    client,connections,requests,_,_=fixture(tmp_path,monkeypatch,statuses=[503,200])
    async def check():
        with pytest.raises(ProtocolError,match='MEDIA_GRANT_UNAVAILABLE'):await client.request({},str(uuid.uuid4()),1,None)
        assert len(requests)==1 and connections[0].closed
        assert await client.request({},str(uuid.uuid4()),2,None)=={'fixture':True}
    try:asyncio.run(check())
    finally:client.close()
    assert len(connections)==2


def test_cancelling_a_grant_closes_the_inflight_connection(tmp_path,monkeypatch):
    client,connections,_,started,finished=fixture(tmp_path,monkeypatch,blocked=True)
    async def check():
        task=asyncio.create_task(client.request({},str(uuid.uuid4()),1,None))
        assert await asyncio.to_thread(started.wait,1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):await task
        assert await asyncio.to_thread(finished.wait,1)
    try:asyncio.run(check())
    finally:client.close()
    assert connections[0].closed


def test_timeout_diagnostics_identify_the_transport_phase_without_request_data(tmp_path,monkeypatch):
    from thirdhand_edge.camera_runtime import camera_failure
    client,_,_,_,_=fixture(tmp_path,monkeypatch)
    def timed_out(_):raise TimeoutError('private token must not appear')
    monkeypatch.setattr(media_upload.http.client.HTTPSConnection,'getresponse',timed_out)
    async def check():
        with pytest.raises(ProtocolError) as failure:await client.request({},str(uuid.uuid4()),1,None)
        cause=camera_failure(failure.value)['causes'][0]
        assert cause.get('phase')=='response_headers',camera_failure(failure.value)
        assert type(cause['elapsedMs']) is int and 0<=cause['elapsedMs']<=60000
        assert 'private token' not in json.dumps(camera_failure(failure.value))
    try:asyncio.run(check())
    finally:client.close()


def test_grant_timing_callback_contains_only_bounded_phase_metrics(tmp_path,monkeypatch):
    client,_,_,_,_=fixture(tmp_path,monkeypatch)
    timings=[];client.on_timing=timings.append
    async def check():
        assert await client.request({'private':'must-not-log'},str(uuid.uuid4()),1,None)=={'fixture':True}
    try:asyncio.run(check())
    finally:client.close()
    assert len(timings)==1
    row=timings[0]
    assert row['stage']=='media_ack' and row['outcome']=='accepted'
    names={'traceId','stage','outcome','phase','elapsedMs','queueMs','connectMs','sendMs','headersMs','bodyMs','parseMs'}
    assert set(row)<=names
    for name,value in row.items():
        if name.endswith('Ms'):assert type(value) is int and 0<=value<=60000
    assert 'must-not-log' not in json.dumps(row)


def test_small_signed_reports_send_headers_and_body_together_over_real_verified_tls(tmp_path,monkeypatch):
    """A split short request lost its header and exceeded the publication deadline."""
    from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
    from pki_fixture import generate
    from thirdhand_edge.transport import DeviceConfig
    generate(tmp_path)
    key=serialization.load_pem_private_key((tmp_path/'device.key').read_bytes(),password=None)
    received=[];writes=[]
    class Handler(BaseHTTPRequestHandler):
        protocol_version='HTTP/1.1'
        def log_message(self,*_):pass
        def do_POST(self):
            assert self.connection.getpeercert()
            assert self.path=='/edge/v1/media-grant'
            value=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            raw=base64.urlsafe_b64decode(value['payloadBase64url']+'==')
            key.public_key().verify(base64.urlsafe_b64decode(value['signatureBase64url']+'=='),raw)
            payload=json.loads(raw)
            assert payload['expiresAt']-payload['issuedAt']==950
            received.append(payload)
            response=b'{"envelope":{"fixture":true}}'
            self.send_response(200);self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(response)));self.end_headers()
            self.wfile.write(response)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(tmp_path/'server.pem',tmp_path/'server.key')
    tls.load_verify_locations(tmp_path/'ca.pem');tls.verify_mode=ssl.CERT_REQUIRED
    server.socket=tls.wrap_socket(server.socket,server_side=True)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    original_send=ssl.SSLSocket.sendall
    def observed_send(sock,data,*args,**kwargs):
        if sock.getpeername()[1]==server.server_port:writes.append(len(data))
        return original_send(sock,data,*args,**kwargs)
    monkeypatch.setattr(ssl.SSLSocket,'sendall',observed_send)
    device=DeviceConfig(url=f'wss://localhost:{server.server_port}/edge/v1/connect',
        device_id=str(uuid.uuid4()),boot_id=str(uuid.uuid4()),certificate=tmp_path/'device.pem',
        private_key=tmp_path/'device.key',ca_file=tmp_path/'ca.pem')
    client=media_upload.MediaGrantClient(device)
    async def check():
        for sequence in (1,2):
            before=len(writes)
            assert await client.request({},str(uuid.uuid4()),sequence,None)=={'fixture':True}
            assert len(writes)-before==1,'The short signed report must not send its header separately'
    try:asyncio.run(check())
    finally:
        client.close();server.shutdown();server.server_close();thread.join(timeout=2)
    assert [value['sequence'] for value in received]==[1,2]
