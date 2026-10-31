import asyncio
import base64
import json
from pathlib import Path
import sys
import time
from types import SimpleNamespace
import uuid

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'services/edge-agent/src'))
from thirdhand_edge.frames import CameraFrame
from thirdhand_edge.media_publisher import MediaLeaseGate, publish_camera
from thirdhand_edge.protocol import ProtocolError


def signer():
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    context = {name: str(uuid.uuid4()) for name in ('deviceId', 'bootId', 'executorEpoch', 'connectionId', 'certificateId')}
    publisher = str(uuid.uuid4())

    def sign(sequence, now=None):
        now = time.time_ns() // 1000000 if now is None else now
        value = {'schema': 1, 'purpose': 'media_publish', **context, 'keyId': 'test',
                 'publisherId': publisher, 'sequence': sequence, 'room': 'test-room',
                 'identity': 'p_' + publisher, 'token': 'test-only-media-token',
                 'sourceFresh': False, 'frame': None, 'issuedAt': now, 'expiresAt': now + 950}
        raw = json.dumps(value).encode()
        return {'keyId': 'test', 'payloadBase64url': base64.urlsafe_b64encode(raw).decode().rstrip('='),
                'signatureBase64url': base64.urlsafe_b64encode(key.sign(raw)).decode().rstrip('=')}

    return {'test': public}, context, publisher, sign


def test_expired_publication_cannot_be_revived_by_a_new_signed_sequence():
    keys, context, publisher, sign = signer()
    clock = {'wall': 100000, 'mono': 0.0}
    gate = MediaLeaseGate(publisher_id=publisher, trusted_keys=keys,
                          wall_ms=lambda: clock['wall'], monotonic=lambda: clock['mono'])
    gate.accept(sign(1, clock['wall']), context)
    clock.update(wall=100951, mono=0.951)
    with pytest.raises(ProtocolError, match='MEDIA_LEASE_EXPIRED'):
        gate.accept(sign(2, clock['wall']), context)
    assert not gate.active(context)


def test_rejected_publication_cannot_resume_even_if_the_next_signature_is_valid():
    keys, context, publisher, sign = signer()
    gate = MediaLeaseGate(publisher_id=publisher, trusted_keys=keys)
    gate.accept(sign(1), context)
    with pytest.raises(ProtocolError):
        gate.accept({**sign(2), 'signatureBase64url': 'A' * 86}, context)
    with pytest.raises(ProtocolError, match='MEDIA_LEASE_EXPIRED'):
        gate.accept(sign(3), context)
    assert not gate.active(context)


def test_renewal_starts_early_when_a_valid_delayed_response_has_little_lease_time_left():
    keys, context, publisher, sign = signer()
    requests = []

    async def run():
        renewed = asyncio.Event()

        async def frames():
            yield CameraFrame(2, 2, bytes(12), '1', time.monotonic())
            await renewed.wait()

        async def grant(_context, _publisher, sequence, _frame):
            requests.append(sequence)
            if sequence == 1:
                # The response remains valid but only has about 300 ms left.
                # A fixed 200 ms wait plus the next 150 ms response needlessly
                # misses that unchanged deadline.
                return sign(sequence, time.time_ns() // 1000000 - 650)
            await asyncio.sleep(0.15)
            return sign(sequence)

        async def on_grant(envelope):
            value = json.loads(base64.urlsafe_b64decode(envelope['payloadBase64url'] + '=='))
            if value['sequence'] == 2:
                renewed.set()

        class Room:
            def __init__(self):
                async def publish(*_args):
                    pass
                self.local_participant = SimpleNamespace(publish_track=publish)

            async def connect(self, *_args, **_kwargs):
                pass

            async def disconnect(self):
                pass

        rtc = SimpleNamespace(Room=Room, VideoSource=lambda *_: SimpleNamespace(capture_frame=lambda *_a, **_k: None),
                              RoomOptions=lambda **kw: SimpleNamespace(**kw),
                              LocalVideoTrack=SimpleNamespace(create_video_track=lambda *_: object()),
                              TrackPublishOptions=lambda **kw: SimpleNamespace(**kw), TrackSource=SimpleNamespace(SOURCE_CAMERA=1),
                              VideoEncoding=lambda **kw: SimpleNamespace(**kw),
                              FrameMetadataFeature=SimpleNamespace(FMF_USER_TIMESTAMP=0, FMF_FRAME_ID=1),
                              FrameMetadata=lambda **kw: SimpleNamespace(**kw), VideoFrame=lambda *_: object(),
                              VideoBufferType=SimpleNamespace(RGB24=1))
        with pytest.raises(ProtocolError, match='CAMERA_SOURCE_ENDED'):
            await asyncio.wait_for(publish_camera(frames=frames(), request_grant=grant,
                                                  context=context, publisher_id=publisher,
                                                  trusted_keys=keys, server_url='wss://example.invalid/media',
                                                  rtc_module=rtc, on_grant=on_grant), timeout=1.5)

    asyncio.run(run())
    assert requests[:2] == [1, 2]
