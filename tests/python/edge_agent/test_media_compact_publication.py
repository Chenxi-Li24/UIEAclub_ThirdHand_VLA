import asyncio
import time
from types import SimpleNamespace

import pytest

from test_media_compact import fixture
from thirdhand_edge import media_publisher
from thirdhand_edge.frames import CameraFrame
from thirdhand_edge.protocol import ProtocolError


def rtc():
    class Room:
        def __init__(self):
            async def publish(*_args):
                pass
            self.local_participant = SimpleNamespace(publish_track=publish)
        async def connect(self, *_args, **_kwargs):
            pass
        async def disconnect(self):
            pass
    return SimpleNamespace(Room=Room, VideoSource=lambda *_: SimpleNamespace(capture_frame=lambda *_a, **_k: None),
                           RoomOptions=lambda **kw: SimpleNamespace(**kw), LocalVideoTrack=SimpleNamespace(create_video_track=lambda *_: object()),
                           TrackPublishOptions=lambda **kw: SimpleNamespace(**kw), TrackSource=SimpleNamespace(SOURCE_CAMERA=1),
                           VideoEncoding=lambda **kw: SimpleNamespace(**kw), FrameMetadataFeature=SimpleNamespace(FMF_USER_TIMESTAMP=0, FMF_FRAME_ID=1),
                           FrameMetadata=lambda **kw: SimpleNamespace(**kw), VideoFrame=lambda *_: object(), VideoBufferType=SimpleNamespace(RGB24=1))


@pytest.mark.parametrize('legacy_forwarding', [False, True])
def test_only_verified_gate_credentials_seed_http_hints_and_legacy_bound_forwarding_stays_full(monkeypatch, legacy_forwarding):
    gate, context, clock, original, first, full, compact = fixture(bound=legacy_forwarding)
    monkeypatch.setattr(media_publisher, 'time', SimpleNamespace(time_ns=lambda: clock['wall'] * 1000000, monotonic=time.monotonic))
    hints, forwarded, requested = [], [], []
    async def run():
        complete = asyncio.Event()
        async def frames():
            yield CameraFrame(2, 2, bytes(12), '1', time.monotonic())
            await complete.wait()
        def credentials(value):
            hints.append(value)
            if len(hints) == 2 and not legacy_forwarding:
                complete.set()
        async def forward(envelope):
            forwarded.append(envelope)
            if len(forwarded) == 2:
                complete.set()
        async def request(_context, _publisher, sequence, _frame):
            requested.append(sequence)
            if sequence == 1:
                assert not hints
                return first
            assert hints and ((hints[-1] is None) if legacy_forwarding else (hints[-1] is not None))
            return full(sequence) if legacy_forwarding else compact(sequence)
        with pytest.raises(ProtocolError, match='CAMERA_SOURCE_ENDED'):
            await media_publisher.publish_camera(frames=frames(), request_grant=request, context=context,
                                                publisher_id=original['publisherId'], trusted_keys=gate.keys,
                                                server_url='wss://example.invalid/media', rtc_module=rtc(), compact_renewals=True,
                                                on_credentials=credentials, on_grant=forward if legacy_forwarding else None)
    asyncio.run(run())
    assert requested == [1, 2] and hints[-1] is None
    if legacy_forwarding:
        assert all(value is None for value in hints)
        assert len(forwarded) == 2
    else:
        assert hints[0]['digest'] == hints[1]['digest'] and not forwarded


def test_invalid_full_signature_never_seeds_a_credential_hint(monkeypatch):
    gate, context, clock, original, first, _, _ = fixture()
    monkeypatch.setattr(media_publisher, 'time', SimpleNamespace(time_ns=lambda: clock['wall'] * 1000000, monotonic=time.monotonic))
    hints = []
    async def run():
        async def frames():
            yield CameraFrame(2, 2, bytes(12), '1', time.monotonic())
        async def request(*_args):
            return {**first, 'signatureBase64url': 'A' * 86}
        with pytest.raises(ProtocolError):
            await media_publisher.publish_camera(frames=frames(), request_grant=request, context=context,
                                                publisher_id=original['publisherId'], trusted_keys=gate.keys,
                                                server_url='wss://example.invalid/media', rtc_module=rtc(),
                                                compact_renewals=True, on_credentials=hints.append)
    asyncio.run(run())
    assert all(value is None for value in hints)
