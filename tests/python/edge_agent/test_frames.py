import base64
import io
import json
from pathlib import Path
import sys
import uuid
import asyncio
import time
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "services/edge-agent/src"))
from thirdhand_edge.frames import decode_frame, CameraFrame
from thirdhand_edge.media_publisher import MediaLeaseGate, publish_camera
from thirdhand_edge.protocol import ProtocolError


def test_missing_capture_timestamp_remains_unknown_instead_of_becoming_a_fresh_capture_time():
    image = io.BytesIO()
    Image.new("RGB", (4, 3), (255, 100, 0)).save(image, format="JPEG")
    frame = decode_frame(image.getvalue(), {"x-thirdhand-sequence": "7"}, received_monotonic=123.0)
    assert frame.width == 4 and frame.height == 3 and len(frame.rgb) == 36
    assert frame.captured_at_us is None and frame.health_report() is None
    known = decode_frame(image.getvalue(), {"x-thirdhand-sequence": "8", "x-thirdhand-captured-at-us": "1793350800000001", "x-thirdhand-clock-quality": "estimated", "x-thirdhand-clock-uncertainty-ms": "15"}, received_monotonic=124.0)
    assert known.health_report()["capturedAtUs"] == "1793350800000001"
    assert known.health_report()["uncertaintyMs"] == 15
    with pytest.raises(ValueError):
        decode_frame(b"not jpeg", {"x-thirdhand-sequence": "9"}, received_monotonic=125.0)


def test_publisher_lease_has_independent_monotonic_expiry_and_rejects_old_context_or_replay():
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    context = {field: str(uuid.uuid4()) for field in ("deviceId", "bootId", "executorEpoch", "connectionId", "certificateId")}
    publisher, clock = str(uuid.uuid4()), {"wall": 100000, "mono": 10.0}
    gate = MediaLeaseGate(publisher_id=publisher, trusted_keys={"test": public}, wall_ms=lambda: clock["wall"], monotonic=lambda: clock["mono"])
    def signed(sequence):
        payload = {"schema": 1, "purpose": "media_publish", **context, "keyId": "test", "publisherId": publisher, "sequence": sequence, "room": "device-test-room", "identity": "p_" + publisher, "token": "publisher-test-token", "sourceFresh": False, "frame": None, "issuedAt": clock["wall"], "expiresAt": clock["wall"] + 950}
        raw = json.dumps(payload).encode()
        return {"keyId": "test", "payloadBase64url": base64.urlsafe_b64encode(raw).decode().rstrip("="), "signatureBase64url": base64.urlsafe_b64encode(key.sign(raw)).decode().rstrip("=")}
    first = signed(1)
    gate.accept(first, context)
    assert gate.active(context)
    clock["wall"] -= 50000
    clock["mono"] += 1
    assert not gate.active(context)
    clock["wall"] = 100000
    with pytest.raises(ProtocolError):
        gate.accept(first, context)
    with pytest.raises(ProtocolError, match="MEDIA_LEASE_EXPIRED"):
        gate.accept(signed(2), context)
    publisher = str(uuid.uuid4())
    gate = MediaLeaseGate(publisher_id=publisher, trusted_keys={"test": public}, wall_ms=lambda: clock["wall"], monotonic=lambda: clock["mono"])
    gate.accept(signed(1), context)
    assert not gate.active({**context, "connectionId": str(uuid.uuid4())})
    with pytest.raises(ProtocolError):
        gate.accept({**signed(3), "signatureBase64url": "A" * 86}, context)
    assert not gate.active(context)


def test_publisher_expiry_disconnects_even_when_renewal_and_source_are_blocked():
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    context = {field: str(uuid.uuid4()) for field in ("deviceId", "bootId", "executorEpoch", "connectionId", "certificateId")}
    publisher, calls = str(uuid.uuid4()), []
    def signed(sequence):
        now = time.time_ns() // 1000000
        payload = {"schema": 1, "purpose": "media_publish", **context, "keyId": "test", "publisherId": publisher, "sequence": sequence, "room": "device-test-room", "identity": "p_" + publisher, "token": "publisher-test-token", "sourceFresh": False, "frame": None, "issuedAt": now, "expiresAt": now + 950}
        raw = json.dumps(payload).encode()
        return {"keyId": "test", "payloadBase64url": base64.urlsafe_b64encode(raw).decode().rstrip("="), "signatureBase64url": base64.urlsafe_b64encode(key.sign(raw)).decode().rstrip("=")}
    class Room:
        def __init__(self):
            async def publish(track, options):
                calls.append(("publish", options.source))
            self.local_participant = SimpleNamespace(publish_track=publish)
        async def connect(self, url, token, options):
            assert options.auto_subscribe is False
            calls.append(("connect", url))
        async def disconnect(self):
            calls.append(("disconnect",))
    class Source:
        def __init__(self, width, height):
            assert (width, height) == (2, 2)
        def capture_frame(self, video, **values):
            calls.append(("frame", values["metadata"].user_timestamp, values["metadata"].frame_id))
    rtc = SimpleNamespace(Room=Room, VideoSource=Source, RoomOptions=lambda **kw: SimpleNamespace(**kw), LocalVideoTrack=SimpleNamespace(create_video_track=lambda *a: object()), TrackPublishOptions=lambda **kw: SimpleNamespace(**kw), TrackSource=SimpleNamespace(SOURCE_CAMERA=1), VideoEncoding=lambda **kw: SimpleNamespace(**kw), FrameMetadataFeature=SimpleNamespace(FMF_USER_TIMESTAMP=0, FMF_FRAME_ID=1), FrameMetadata=lambda **kw: SimpleNamespace(**kw), VideoFrame=lambda *a: object(), VideoBufferType=SimpleNamespace(RGB24=1))
    async def run():
        async def frames():
            yield CameraFrame(2, 2, bytes(12), "17", time.monotonic(), "1793350800000001", "synchronized", 1)
            await asyncio.Event().wait()
        async def grant(context, publisher, sequence, frame):
            if sequence > 1:
                await asyncio.Event().wait()
            return signed(sequence)
        with pytest.raises(ProtocolError, match="MEDIA_LEASE_EXPIRED"):
            await asyncio.wait_for(publish_camera(frames=frames(), request_grant=grant, context=context, publisher_id=publisher, trusted_keys={"test": public}, server_url="wss://example.invalid/media", rtc_module=rtc), timeout=1.5)
    asyncio.run(run())
    assert [item[0] for item in calls].count("frame") == 1
    assert ("frame", 1793350800000001, 17) in calls
    assert calls[-1] == ("disconnect",)


def test_pinned_rtc_sdk_supports_the_negotiated_capture_metadata_contract():
    from livekit import rtc
    options = rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_CAMERA, frame_metadata_features=[rtc.FrameMetadataFeature.FMF_USER_TIMESTAMP, rtc.FrameMetadataFeature.FMF_FRAME_ID])
    metadata = rtc.FrameMetadata(user_timestamp=1793350800000001, frame_id=17)
    assert len(options.frame_metadata_features) == 2 and metadata.user_timestamp == 1793350800000001
