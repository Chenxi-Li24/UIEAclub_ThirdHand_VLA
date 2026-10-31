import asyncio
from pathlib import Path
import sys
from types import SimpleNamespace
import uuid
import json
import urllib.error

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'services/edge-agent/src'))
from thirdhand_edge.camera_runtime import run_camera_session
from thirdhand_edge.protocol import ProtocolError


def test_camera_session_uses_read_only_device_context_and_discards_the_cached_first_frame():
    device=SimpleNamespace(device_id=str(uuid.uuid4()),boot_id=str(uuid.uuid4()))
    context={'deviceId':device.device_id,'bootId':device.boot_id,'executorEpoch':None,'certificateId':str(uuid.uuid4()),'connectionId':str(uuid.uuid4())}
    stopped=[]

    async def transport(config,on_message):
        try:
            assert config is device
            await on_message({'type':'connected','context':context,'controlAuthorized':False})
            await asyncio.Event().wait()
        finally:stopped.append(True)

    class Source:
        def iter_frames(self):
            yield SimpleNamespace(frame_id='40')
            yield SimpleNamespace(frame_id='99')

    async def publisher(**kwargs):
        assert kwargs['context']==context
        frame=await anext(kwargs['frames'])
        assert frame.frame_id=='99'
        await kwargs['frames'].aclose()

    asyncio.run(run_camera_session(device,source=Source(),grants=SimpleNamespace(request=object()),trusted_keys={},server_url='wss://staging.example.invalid/media',transport=transport,publisher=publisher))
    assert stopped==[True]


def test_camera_session_rejects_a_control_bound_context_before_reading_camera_frames():
    device=SimpleNamespace(device_id=str(uuid.uuid4()),boot_id=str(uuid.uuid4()))
    async def transport(config,on_message):
        await on_message({'type':'connected','controlAuthorized':False,'context':{'deviceId':device.device_id,'bootId':device.boot_id,'executorEpoch':str(uuid.uuid4())}})
    class Source:
        def iter_frames(self):raise AssertionError('Camera source must not be opened')
    with pytest.raises(ProtocolError,match='CAMERA_ONLY_CONTEXT_REQUIRED'):
        asyncio.run(run_camera_session(device,source=Source(),grants=None,trusted_keys={},server_url='wss://staging.example.invalid/media',transport=transport))


def test_camera_failure_diagnostics_include_codes_and_types_without_exception_text_or_tokens():
    from thirdhand_edge.camera_runtime import camera_failure
    secret='eyJprivate.secret.token PRIVATE KEY password=do-not-log'
    error=ProtocolError('MEDIA_GRANT_UNAVAILABLE')
    error.__cause__=TimeoutError(secret)
    report=camera_failure(error)
    assert report['causes']==[{'type':'ProtocolError','code':'MEDIA_GRANT_UNAVAILABLE'},{'type':'TimeoutError'}]
    assert report['controlAuthorized'] is False
    assert secret not in json.dumps(report)
    http=urllib.error.HTTPError('https://secret.invalid/?token='+secret,503,secret,{},None)
    assert camera_failure(http)['causes']==[{'type':'HTTPError','httpStatus':503}]
    assert 'do-not-log' not in json.dumps(camera_failure(ProtocolError('do-not-log')))
