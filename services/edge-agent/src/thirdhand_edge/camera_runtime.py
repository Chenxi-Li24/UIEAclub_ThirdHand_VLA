"""Camera-only transport: no Robot client, SDK connection or command worker."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import stat
import tomllib
from urllib.parse import urlsplit
from urllib.error import HTTPError
import uuid

from .frames import LocalCameraSource
from .media_publisher import publish_camera
from .media_upload import MediaGrantClient
from .protocol import ProtocolError
from .transport import DeviceConfig, connect_device


def camera_failure(error):
    """Stable diagnostics without third-party messages, URLs, JWTs or key text."""
    known={'MEDIA_GRANT_UNAVAILABLE','MEDIA_LEASE_EXPIRED','CAMERA_SOURCE_ENDED',
           'CAMERA_SEQUENCE_NOT_ADVANCING','CAMERA_ONLY_CONTEXT_REQUIRED','CAMERA_DIMENSIONS_CHANGED',
           'MEDIA_CREDENTIAL_CACHE_MISS','MEDIA_CREDENTIAL_CACHE_MISMATCH','MEDIA_CREDENTIALS_EXPIRED','INVALID_MEDIA_SEQUENCE'}
    causes=[]
    seen=set()
    while error is not None and id(error) not in seen and len(causes)<4:
        seen.add(id(error));item={'type':type(error).__name__}
        if isinstance(error,ProtocolError) and len(error.args)==1 and error.args[0] in known:
            item['code']=error.args[0]
            metrics=getattr(error,'media_metrics',{})
            if isinstance(metrics,dict):
                if metrics.get('phase') in {'connect','request_send','response_headers','response_body','response_parse'}:
                    item['phase']=metrics['phase']
                if type(metrics.get('elapsedMs')) is int and 0<=metrics['elapsedMs']<=60000:
                    item['elapsedMs']=metrics['elapsedMs']
                for name in ('queueMs','connectMs','sendMs','headersMs','bodyMs','parseMs'):
                    if type(metrics.get(name)) is int and 0<=metrics[name]<=60000:
                        item[name]=metrics[name]
                recent=metrics.get('recentSuccessMs')
                if isinstance(recent,list) and len(recent)<=8 and all(type(x) is int and 0<=x<=60000 for x in recent):
                    item['recentSuccessMs']=recent
                if type(metrics.get('httpStatus')) is int and 400<=metrics['httpStatus']<=599:
                    item['httpStatus']=metrics['httpStatus']
        if isinstance(error,HTTPError) and type(error.code) is int and 400<=error.code<=599:
            item['httpStatus']=error.code
        causes.append(item);error=error.__cause__
    return {'event':'camera.unavailable','controlAuthorized':False,'causes':causes}


async def run_camera_session(device, *, source, grants, trusted_keys, server_url,
                             transport=connect_device, publisher=publish_camera):
    ready = asyncio.get_running_loop().create_future()
    iterator = None

    async def connected(message):
        if message.get('type') != 'connected':
            return
        context = message.get('context', {})
        if message.get('controlAuthorized') is not False or context.get('executorEpoch') is not None or context.get('deviceId') != device.device_id or context.get('bootId') != device.boot_id:
            raise ProtocolError('CAMERA_ONLY_CONTEXT_REQUIRED')
        if not ready.done():
            ready.set_result(context)

    async def frames():
        nonlocal iterator
        iterator = source.iter_frames()
        # Existing Vision may immediately return a cached JPEG from its previous
        # subscriber. Wait for the next strictly advancing source sequence.
        cached = await asyncio.to_thread(next, iterator, None)
        if cached is None:
            raise ProtocolError('CAMERA_SOURCE_ENDED')
        previous = int(cached.frame_id)
        try:
            while True:
                frame = await asyncio.to_thread(next, iterator, None)
                if frame is None:
                    return
                if int(frame.frame_id) <= previous:
                    raise ProtocolError('CAMERA_SEQUENCE_NOT_ADVANCING')
                previous = int(frame.frame_id)
                yield frame
        finally:
            try:
                iterator.close()
            except ValueError:
                pass  # An outstanding local read has its own bounded timeout.

    async def publication():
        context = await asyncio.wait_for(ready, timeout=10)
        options = {}
        if getattr(grants, 'compact_renewals', False) is True:
            options = {'compact_renewals': True, 'on_credentials': grants.remember_credentials}
        await publisher(frames=frames(), request_grant=grants.request, context=context,
                        publisher_id=str(uuid.uuid4()), trusted_keys=trusted_keys, server_url=server_url, **options)

    tasks = [asyncio.create_task(transport(device, connected)), asyncio.create_task(publication())]
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            await task
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        close = getattr(grants, 'close', None)
        if close is not None:
            close()


def load_camera_config(path):
    path = Path(path).resolve()
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or os.name == 'posix' and info.st_mode & 0o077:
        raise ValueError('Owner-only camera configuration required')
    value = tomllib.loads(path.read_text(encoding='utf-8'))
    required = {'url', 'device_id', 'certificate', 'private_key', 'source_url', 'source_token_file', 'signing_keys_file', 'media_server_url'}
    if set(value) - (required | {'ca_file'}) or not required <= set(value):
        raise ValueError('Invalid camera-only configuration fields')
    for name in required | {'ca_file'}:
        if name in value and (not isinstance(value[name], str) or not value[name] or '\0' in value[name]):
            raise ValueError('Invalid camera-only configuration string')
    server = urlsplit(value['media_server_url'])
    if server.scheme != 'wss' or not server.hostname or server.username or server.password or server.query or server.fragment or server.path != '/media':
        raise ValueError('Exact WSS camera signaling endpoint required')
    for name in ['certificate', 'private_key', 'source_token_file', 'signing_keys_file', 'ca_file']:
        if name in value:
            value[name] = (path.parent / value[name]).resolve()
    device = DeviceConfig(url=value['url'],device_id=value['device_id'],boot_id=str(uuid.uuid4()),
                          certificate=value['certificate'],private_key=value['private_key'],ca_file=value.get('ca_file'))
    source = LocalCameraSource(url=value['source_url'],token_file=value['source_token_file'])
    keys = json.loads(value['signing_keys_file'].read_text(encoding='utf-8'))
    if not isinstance(keys, dict) or not 1 <= len(keys) <= 4 or not all(isinstance(k,str) and isinstance(v,str) for k,v in keys.items()):
        raise ValueError('Invalid camera signing public keys')
    return device, source, keys, value['media_server_url']


def main():
    parser = argparse.ArgumentParser(description='Camera-only outbound publisher; no Robot/SDK access')
    parser.add_argument('--config',type=Path,required=True)
    args = parser.parse_args()
    os.umask(0o077)
    try:
        device, source, keys, server_url = load_camera_config(args.config)
        asyncio.run(run_camera_session(device,source=source,grants=MediaGrantClient(device,compact_renewals=True),trusted_keys=keys,server_url=server_url))
    except KeyboardInterrupt:
        pass
    except Exception as error:
        print(json.dumps(camera_failure(error)),flush=True)
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
