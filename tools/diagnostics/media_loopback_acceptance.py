"""Real camera/RTC loopback acceptance. No public listener, SDK or recording.

Uses an ephemeral test-only lease issuer and JWT key. Cloud authentication is
tested separately; this tool establishes actual codec/SFU/frame compatibility.
"""
import argparse
import asyncio
import base64
from datetime import datetime, timezone
import hashlib
import hmac
import json
import logging
import os
from pathlib import Path
import secrets
import socket
import subprocess
import threading
import time
import urllib.request
import uuid


async def test_video(prefix, source_root):
    import sys
    sys.path.insert(0,str(source_root/'services/edge-agent/src'))
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from livekit import rtc
    from thirdhand_edge.camera_source_gate import create_source_gate
    from thirdhand_edge.frames import LocalCameraSource
    from thirdhand_edge.media_publisher import publish_camera

    logging.getLogger('livekit').setLevel(logging.ERROR)
    ports=[17980,*range(17982,17992)]
    for port in ports:
        for kind in [socket.SOCK_STREAM] if port==17980 else [socket.SOCK_DGRAM]:
            with socket.socket(socket.AF_INET,kind) as probe:probe.bind(('127.0.0.1',port))
    run=prefix/('loopback-'+uuid.uuid4().hex[:12]);run.mkdir(mode=0o700)
    key_id,api_secret='localtest_'+secrets.token_hex(8),secrets.token_urlsafe(48)
    config=run/'livekit.yaml'
    content={'port':ports[0],'bind_addresses':['127.0.0.1'],
             'rtc':{'node_ip':'127.0.0.1','use_external_ip':False,'tcp_port':0,
                    'port_range_start':17982,'port_range_end':17991,
                    'enable_loopback_candidate':True,'interfaces':{'includes':['lo']},'ips':{'includes':['127.0.0.1/32']}},
             'keys':{key_id:api_secret},'logging':{'level':'error'}}
    # JSON is a strict YAML subset; no interpolation or credential-bearing argv.
    config.write_text(json.dumps(content));config.chmod(0o600)
    logs=(run/'sfu.private.log').open('wb');os.chmod(run/'sfu.private.log',0o600)
    process=subprocess.Popen([str(prefix/'bin/livekit-server'),'--config',str(config),'--bind','127.0.0.1'],stdout=logs,stderr=logs)
    gate=None;gate_thread=None;room=None;publication=None;consumers=[]
    frames=[];enough=asyncio.Event();room_name='acceptance_'+uuid.uuid4().hex
    b64=lambda value:base64.urlsafe_b64encode(value).decode().rstrip('=')
    def token(identity,publish):
        now=int(time.time());header=b64(json.dumps({'alg':'HS256','typ':'JWT'}).encode())
        body=b64(json.dumps({'iss':key_id,'sub':identity,'nbf':now-5,'exp':now+120,
                            'video':{'room':room_name,'roomJoin':True,'canSubscribe':not publish,'canPublish':publish,
                                     'canPublishData':False,'canUpdateOwnMetadata':False,
                                     **({'canPublishSources':['camera']} if publish else {})}},separators=(',',':')).encode())
        value=header+'.'+body;return value+'.'+b64(hmac.new(api_secret.encode(),value.encode(),hashlib.sha256).digest())
    try:
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        for _ in range(50):
            if process.poll() is not None:raise RuntimeError('SFU_START_FAILED')
            try:
                with opener.open('http://127.0.0.1:17980/',timeout=.3) as response:
                    if response.status==200:break
            except OSError:await asyncio.sleep(.1)
        else:raise RuntimeError('SFU_NOT_READY')
        socket_rows=subprocess.run(['ss','-H','-ltnup'],capture_output=True,text=True,check=True).stdout.splitlines()
        own=[row for row in socket_rows if 'pid='+str(process.pid)+',' in row]
        (run/'initial-listeners.json').write_text(json.dumps(own,indent=2))
        assert own and all('127.0.0.1:' in row for row in own),'SFU_NON_LOOPBACK_LISTENER'
        source_token=secrets.token_hex(32);token_file=run/'source-token';token_file.write_text(source_token);token_file.chmod(0o600)
        gate=create_source_gate(token=source_token,port=0)
        gate_thread=threading.Thread(target=gate.serve_forever,daemon=True);gate_thread.start()
        source=LocalCameraSource(url='http://127.0.0.1:%d/edge-media/v1/raw'%gate.server_port,token_file=token_file)
        async def raw_frames():
            iterator=source.iter_frames()
            try:
                await asyncio.to_thread(next,iterator,None)  # drop cached first JPEG
                while True:
                    frame=await asyncio.to_thread(next,iterator,None)
                    if frame is None:return
                    yield frame
            finally:
                try:iterator.close()
                except ValueError:pass
        sign_key=Ed25519PrivateKey.generate()
        trusted={'acceptance':sign_key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo).decode()}
        context={key:str(uuid.uuid4()) for key in ['deviceId','bootId','certificateId','connectionId']};context['executorEpoch']=None
        publisher_id=str(uuid.uuid4());publisher_token=token('p_'+publisher_id,True)
        async def grant(ctx,pub,seq,frame):
            now=time.time_ns()//1000000
            payload={'schema':1,'purpose':'media_publish',**ctx,'keyId':'acceptance','publisherId':pub,'sequence':seq,
                     'room':room_name,'identity':'p_'+pub,'token':publisher_token,'sourceFresh':False,'frame':None,
                     'issuedAt':now,'expiresAt':now+950}
            raw=json.dumps(payload,separators=(',',':')).encode()
            return {'keyId':'acceptance','payloadBase64url':b64(raw),'signatureBase64url':b64(sign_key.sign(raw))}
        room=rtc.Room()
        async def receive(track):
            stream=rtc.VideoStream(track,format=rtc.VideoBufferType.RGB24,capacity=1)
            try:
                async for event in stream:
                    meta=event.metadata
                    frames.append({'width':event.frame.width,'height':event.frame.height,'frameId':meta.frame_id if meta else None,
                                   'userTimestamp':meta.user_timestamp if meta else None})
                    if len(frames)>=8:enough.set();return
            finally:await stream.aclose()
        @room.on('track_subscribed')
        def subscribed(track,*_):
            if track.kind==rtc.TrackKind.KIND_VIDEO:consumers.append(asyncio.create_task(receive(track)))
        await room.connect('ws://127.0.0.1:17980',token('viewer_'+uuid.uuid4().hex,False),options=rtc.RoomOptions(auto_subscribe=True,rtc_config=rtc.RtcConfiguration(ice_servers=[])))
        publication=asyncio.create_task(publish_camera(frames=raw_frames(),request_grant=grant,context=context,
                                                     publisher_id=publisher_id,trusted_keys=trusted,server_url='ws://127.0.0.1:17980'))
        wait=asyncio.create_task(enough.wait())
        done,_=await asyncio.wait([wait,publication],timeout=20,return_when=asyncio.FIRST_COMPLETED)
        if publication in done:await publication
        assert enough.is_set(),'NO_DECODED_CAMERA_FRAMES'
        ids=[f['frameId'] for f in frames]
        assert all(isinstance(v,int) and v>0 for v in ids) and len(set(ids))>=6,'FRAME_METADATA_MISSING'
        own=[row for row in subprocess.run(['ss','-H','-ltnup'],capture_output=True,text=True,check=True).stdout.splitlines() if 'pid='+str(process.pid)+',' in row]
        (run/'active-listeners.json').write_text(json.dumps(own,indent=2))
        assert own and all('127.0.0.1:' in row for row in own),'SFU_NON_LOOPBACK_LISTENER'
        result={'success':True,'checkedAt':datetime.now(timezone.utc).isoformat(),'realCamera':True,'realWebRtcSfu':True,
                'sfuVersion':'1.13.11','receivedFrames':frames,'loopbackListenersOnly':True,'captureTimeVerified':False,
                'cloudAuthenticationTested':False,'sdkActions':0,'recording':False,'remoteMotionAuthorized':False}
        (run/'result.json').write_text(json.dumps(result,indent=2))
        print(json.dumps(result,indent=2),flush=True)
    finally:
        if publication:publication.cancel();await asyncio.gather(publication,return_exceptions=True)
        for task in consumers:task.cancel()
        if consumers:await asyncio.gather(*consumers,return_exceptions=True)
        if room:await room.disconnect()
        if gate:await asyncio.to_thread(gate.shutdown);gate.server_close()
        if gate_thread:gate_thread.join(timeout=2)
        process.terminate()
        try:process.wait(timeout=5)
        except subprocess.TimeoutExpired:process.kill();process.wait(timeout=2)
        logs.close()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--prefix',type=Path,required=True);parser.add_argument('--source',type=Path,required=True)
    args=parser.parse_args();os.umask(0o077)
    assert args.prefix.resolve()==Path('/home/nieqingcao/.local/share/thirdhand-media-acceptance/20261031')
    assert args.source.resolve().is_relative_to(args.prefix.resolve())
    asyncio.run(test_video(args.prefix,args.source))


if __name__=='__main__':main()
