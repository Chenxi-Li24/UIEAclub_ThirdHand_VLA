"""Camera publication has its own signed, monotonic short lease; no SDK imports."""
import time
import uuid
import asyncio

from .protocol import ProtocolError, verify_envelope
from .media_renewal import cache_verified_credentials, reconstruct_renewal, verify_signed_media_payload, validate_frame, BINDING


class MediaLeaseGate:
    def __init__(self, *, publisher_id, trusted_keys, wall_ms=None, monotonic=None, allow_compact=False):
        uuid.UUID(publisher_id)
        self.publisher_id, self.keys = publisher_id, trusted_keys
        self.wall = wall_ms or (lambda: time.time_ns() // 1000000)
        self.mono = monotonic or time.monotonic
        self.deadline, self.sequence, self.context, self.payload = float("-inf"), 0, None, None
        self.failed = False
        self.allow_compact, self._credentials = allow_compact is True, None

    def accept(self, envelope, context, *, expected_sequence=None):
        try:
            # Sample monotonic first: a scheduling pause between clock reads
            # may shorten an authorization, but must never extend its deadline.
            received_mono, received_wall = self.mono(), self.wall()
            previous_deadline = self.deadline if self.context is not None else None
            if self.failed or previous_deadline is not None and received_mono >= previous_deadline:
                raise ProtocolError("MEDIA_LEASE_EXPIRED")
            signed = verify_signed_media_payload(envelope, self.keys) if self.allow_compact else None
            compact = signed is not None and signed.get('purpose') == 'media_renewal'
            if compact:
                payload = reconstruct_renewal(signed, context, self._credentials, publisher_id=self.publisher_id,
                                              last_sequence=self.sequence, expected_sequence=expected_sequence,
                                              now=received_wall, monotonic=received_mono)
            else:
                payload = verify_envelope(envelope, self.keys, context, now_ms=received_wall)
            expected = {"schema", "purpose", "deviceId", "bootId", "executorEpoch", "connectionId", "certificateId", "keyId", "publisherId", "sequence", "room", "identity", "token", "sourceFresh", "frame", "issuedAt", "expiresAt"}
            if not compact and (set(payload) != expected or payload["purpose"] != "media_publish") or payload["publisherId"] != self.publisher_id or payload["identity"] != "p_" + self.publisher_id or type(payload["sequence"]) is not int or payload["sequence"] <= self.sequence or expected_sequence is not None and payload['sequence'] != expected_sequence or payload["expiresAt"] - payload["issuedAt"] > 1000 or type(payload["sourceFresh"]) is not bool or not isinstance(payload["room"], str) or not 1 <= len(payload["room"]) <= 128 or not isinstance(payload["token"], str) or not 1 <= len(payload["token"]) <= 8192:
                raise ProtocolError("INVALID_MEDIA_LEASE")
            if self.context is not None and self.context != context:
                raise ProtocolError("WRONG_CONTEXT")
            signed_deadline = received_mono + min(950, payload['expiresAt'] - received_wall) / 1000
            next_credentials = self._credentials
            if self.allow_compact and not compact:
                validate_frame(payload['frame'], payload['sourceFresh'])
                next_credentials = cache_verified_credentials(payload, context, now=received_wall, monotonic=received_mono, previous=self._credentials)
            commit_anchor_mono, committed_wall = self.mono(), self.wall()
            committed_mono = self.mono()
            deadline = min(signed_deadline, commit_anchor_mono + min(950, payload['expiresAt'] - committed_wall) / 1000)
            if self.failed or previous_deadline is not None and committed_mono >= previous_deadline or committed_mono >= deadline or committed_wall >= payload['expiresAt']:
                raise ProtocolError("MEDIA_LEASE_EXPIRED")
            if next_credentials is not None and (committed_wall >= next_credentials.expires_at or deadline > next_credentials.deadline):
                raise ProtocolError('MEDIA_CREDENTIALS_EXPIRED')
            self.context, self.sequence, self.payload = dict(context), payload["sequence"], payload
            self._credentials, self.deadline = next_credentials, deadline
            return payload
        except Exception:
            self.invalidate()
            raise

    def invalidate(self):
        self.deadline, self.failed, self._credentials, self.payload = float('-inf'), True, None, None

    def credential_hint(self):
        cache = self._credentials
        if cache is None or self.failed or not self.active(self.context) or self.wall() >= cache.expires_at or self.mono() >= cache.deadline:
            return None
        return {'digest': cache.digest, 'publisherId': self.publisher_id, 'context': dict(zip(BINDING, cache.context))}

    def active(self, context):
        return not self.failed and self.context == context and self.mono() < self.deadline

    def require(self, context):
        if not self.active(context):
            raise ProtocolError("MEDIA_LEASE_EXPIRED")
        return self.payload


async def publish_camera(*, frames, request_grant, context, publisher_id, trusted_keys, server_url,
                         rtc_module=None, on_grant=None, compact_renewals=False, on_credentials=None):
    """One video-only publisher. No reconnect, microphone, SDK or recording path.

    Renewal and a50ms monotonic monitor remain runnable while RTC connects or the
    camera source blocks. Any failed/expired grant tears down publication; a
    caller may establish a fresh publication, never replay robot actions.
    """
    if rtc_module is None:
        from livekit import rtc as rtc_module
    rtc = rtc_module
    # Legacy Robot media-health forwarding requires the original full signature.
    # Never forward a reconstructed renewal as though it were a signed full grant.
    gate = MediaLeaseGate(publisher_id=publisher_id, trusted_keys=trusted_keys,
                          allow_compact=compact_renewals is True and on_grant is None)
    first = await asyncio.wait_for(anext(frames), timeout=3)
    sequence, published = 1, None
    envelope = await request_grant(context, publisher_id, sequence, None)
    grant = gate.accept(envelope, context, expected_sequence=sequence)
    if on_credentials:
        on_credentials(gate.credential_hint())
    if on_grant:
        await on_grant(envelope)
    room = rtc.Room()

    async def renew():
        nonlocal sequence
        while True:
            # A verified reply may already have spent part of its lease in
            # transit. Reserve the unchanged 600 ms request budget plus one
            # monitor tick instead of always adding another 200 ms delay.
            remaining = gate.deadline - time.monotonic()
            await asyncio.sleep(min(0.2, max(0.0, remaining - 0.65)))
            gate.require(context)
            sequence += 1
            envelope = await request_grant(context, publisher_id, sequence, published.health_report() if published else None)
            gate.accept(envelope, context, expected_sequence=sequence)
            if on_credentials:
                on_credentials(gate.credential_hint())
            if on_grant:
                await on_grant(envelope)

    async def monitor():
        while True:
            gate.require(context)
            await asyncio.sleep(0.05)

    async def stream():
        nonlocal published
        await room.connect(server_url, grant["token"], options=rtc.RoomOptions(auto_subscribe=False))
        gate.require(context)
        source = rtc.VideoSource(first.width, first.height)
        track = rtc.LocalVideoTrack.create_video_track("camera", source)
        options = rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_CAMERA, simulcast=False,
                                         video_encoding=rtc.VideoEncoding(max_bitrate=800000, max_framerate=15),
                                         frame_metadata_features=[rtc.FrameMetadataFeature.FMF_USER_TIMESTAMP, rtc.FrameMetadataFeature.FMF_FRAME_ID])
        await room.local_participant.publish_track(track, options)
        frame, last_sent = first, float("-inf")
        while True:
            gate.require(context)
            if (frame.width, frame.height) != (first.width, first.height):
                raise ProtocolError("CAMERA_DIMENSIONS_CHANGED")
            if time.monotonic() - frame.received_monotonic <= 0.5 and time.monotonic() - last_sent >= 1 / 15:
                metadata = rtc.FrameMetadata(frame_id=int(frame.frame_id))
                if frame.captured_at_us is not None:
                    metadata.user_timestamp = int(frame.captured_at_us)
                video = rtc.VideoFrame(frame.width, frame.height, rtc.VideoBufferType.RGB24, frame.rgb)
                source.capture_frame(video, timestamp_us=int(frame.received_monotonic * 1000000), metadata=metadata)
                published, last_sent = frame, time.monotonic()
            try:
                frame = await anext(frames)
            except StopAsyncIteration as exc:
                raise ProtocolError("CAMERA_SOURCE_ENDED") from exc

    tasks = [asyncio.create_task(function()) for function in (renew, monitor, stream)]
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            await task
    finally:
        gate.invalidate()
        if on_credentials:
            try:
                on_credentials(None)
            except Exception:
                pass
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        try:
            await asyncio.wait_for(room.disconnect(), timeout=2)
        except Exception:
            pass
        await frames.aclose()
