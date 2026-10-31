"""Bounded, publication-local credential reuse after a verified full grant."""
from dataclasses import dataclass
import base64
import hashlib
import json
import math

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .protocol import ProtocolError, decode_b64, parse_json

BINDING = ('deviceId', 'bootId', 'executorEpoch', 'connectionId', 'certificateId')
MAX_SEQUENCE = 9007199254740991


def verify_signed_media_payload(envelope, trusted_keys):
    # Media-only parser: exact bytes are verified before any JSON is parsed.
    # Command/control envelope interpretation is deliberately not changed.
    if not isinstance(envelope, dict) or set(envelope) != {'keyId', 'payloadBase64url', 'signatureBase64url'}:
        raise ProtocolError('INVALID_ENVELOPE')
    key_id = envelope['keyId']
    if not isinstance(key_id, str) or key_id not in trusted_keys:
        raise ProtocolError('UNKNOWN_KEY')
    raw, signature = decode_b64(envelope['payloadBase64url']), decode_b64(envelope['signatureBase64url'], 86)
    try:
        supplied = trusted_keys[key_id]
        key = serialization.load_pem_public_key(supplied.encode() if isinstance(supplied, str) else supplied)
        if not isinstance(key, Ed25519PublicKey) or len(signature) != 64:
            raise ProtocolError('INVALID_KEY')
        key.verify(signature, raw)
    except (ValueError, InvalidSignature) as error:
        raise ProtocolError('INVALID_SIGNATURE') from error
    payload = parse_json(raw)
    if not isinstance(payload, dict) or payload.get('keyId') != key_id or type(payload.get('schema')) is not int or payload['schema'] != 1:
        raise ProtocolError('INVALID_PAYLOAD')
    return payload


def validate_frame(frame, source_fresh):
    if type(source_fresh) is not bool or source_fresh and frame is None:
        raise ProtocolError('INVALID_MEDIA_FRAME')
    if frame is None:
        return
    if not isinstance(frame, dict) or set(frame) != {'frameId', 'capturedAtUs', 'clockQuality', 'uncertaintyMs'}:
        raise ProtocolError('INVALID_MEDIA_FRAME')
    for name in ('frameId', 'capturedAtUs'):
        value = frame[name]
        if not isinstance(value, str) or not 1 <= len(value) <= 19 or not value.isascii() or not value.isdecimal():
            raise ProtocolError('INVALID_MEDIA_FRAME')
    uncertainty = frame['uncertaintyMs']
    if frame['clockQuality'] not in ('synchronized', 'estimated', 'unreliable') or type(uncertainty) not in (int, float) or not math.isfinite(uncertainty) or not 0 <= uncertainty <= 60000:
        raise ProtocolError('INVALID_MEDIA_FRAME')


@dataclass(frozen=True)
class CredentialCache:
    digest: str
    key_id: str
    context: tuple
    publisher_id: str
    room: str
    identity: str
    token: str
    expires_at: int
    deadline: float


def cache_verified_credentials(payload, context, *, now, monotonic, previous=None):
    # The complete JWT was authenticated by the outer full Ed25519 envelope.
    # Its claims are parsed for identity/permission/expiration bounds; no inbound
    # unsigned JWT is accepted as an authorization source here.
    try:
        parts = payload['token'].split('.')
        if len(parts) != 3:
            raise ProtocolError('INVALID_MEDIA_CREDENTIALS')
        header = parse_json(decode_b64(parts[0], 2048))
        claims = parse_json(decode_b64(parts[1], 16384))
        if len(decode_b64(parts[2], 86)) != 32:
            raise ProtocolError('INVALID_MEDIA_CREDENTIALS')
        video = claims.get('video', {})
        expiry = claims.get('exp')
        nbf = claims.get('nbf')
        if not isinstance(header, dict) or header.get('alg') != 'HS256' or claims.get('sub') != payload['identity'] or type(expiry) is not int or not 0 < expiry <= MAX_SEQUENCE // 1000 or nbf is not None and (type(nbf) is not int or nbf * 1000 > now + 500) or not isinstance(video, dict) or video.get('room') != payload['room'] or video.get('roomJoin') is not True or video.get('canPublish') is not True or video.get('canSubscribe') is not False or video.get('canPublishData') is not False or video.get('canUpdateOwnMetadata') is not False or video.get('canPublishSources') != ['camera'] or any(video.get(name) for name in ('roomAdmin', 'roomCreate', 'roomRecord', 'ingressAdmin')):
            raise ProtocolError('INVALID_MEDIA_CREDENTIALS')
        expiry *= 1000
        fields = [context[name] for name in BINDING]
        digest_input = ['thirdhand-media-credentials-v1', payload['keyId'], *fields, payload['publisherId'], payload['room'], payload['identity'], payload['token']]
        raw = json.dumps(digest_input, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')
        digest = base64.urlsafe_b64encode(hashlib.sha256(raw).digest()).decode().rstrip('=')
        deadline = monotonic + (expiry - now) / 1000
        if previous is not None and previous.digest == digest:
            deadline = min(deadline, previous.deadline)
        if payload['expiresAt'] > expiry or deadline < monotonic + (payload['expiresAt'] - now) / 1000:
            raise ProtocolError('MEDIA_CREDENTIALS_EXPIRED')
        return CredentialCache(digest, payload['keyId'], tuple(fields), payload['publisherId'], payload['room'], payload['identity'], payload['token'], expiry, deadline)
    except (KeyError, TypeError, AttributeError, ValueError) as error:
        if isinstance(error, ProtocolError):
            raise
        raise ProtocolError('INVALID_MEDIA_CREDENTIALS') from error


def reconstruct_renewal(payload, context, cache, *, publisher_id, last_sequence, expected_sequence, now, monotonic):
    expected = {'schema', 'purpose', 'keyId', 'context', 'publisherId', 'sequence', 'credentialDigest', 'sourceFresh', 'frame', 'issuedAt', 'expiresAt'}
    if set(payload) != expected or payload['purpose'] != 'media_renewal' or cache is None:
        raise ProtocolError('MEDIA_CREDENTIAL_CACHE_MISS')
    fields = [context[name] for name in BINDING]
    if type(payload['context']) is not list or len(payload['context']) != len(BINDING) or payload['context'] != fields or cache.context != tuple(fields) or payload['publisherId'] != publisher_id or cache.publisher_id != publisher_id or payload['keyId'] != cache.key_id or payload['credentialDigest'] != cache.digest:
        raise ProtocolError('MEDIA_CREDENTIAL_CACHE_MISMATCH')
    sequence, issued, expires = payload['sequence'], payload['issuedAt'], payload['expiresAt']
    if type(sequence) is not int or not last_sequence < sequence <= MAX_SEQUENCE or type(expected_sequence) is not int or sequence != expected_sequence:
        raise ProtocolError('INVALID_MEDIA_SEQUENCE')
    if type(issued) is not int or type(expires) is not int or issued > now + 500 or expires <= now or not 0 < expires - issued <= 950 or expires > cache.expires_at or monotonic + (expires - now) / 1000 > cache.deadline:
        raise ProtocolError('MEDIA_CREDENTIALS_EXPIRED')
    validate_frame(payload['frame'], payload['sourceFresh'])
    # This is an internal validated result, never a newly signed full envelope.
    return {**payload, **context, 'room': cache.room, 'identity': cache.identity, 'token': cache.token}
