import base64
import hashlib
import hmac
import json
from pathlib import Path
import sys
import uuid

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'services/edge-agent/src'))
from thirdhand_edge.media_publisher import MediaLeaseGate
from thirdhand_edge import media_publisher
from thirdhand_edge.protocol import ProtocolError

BINDING = ('deviceId', 'bootId', 'executorEpoch', 'connectionId', 'certificateId')
def encoded(value):
    return base64.urlsafe_b64encode(value).decode().rstrip('=')
def raw_json(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()
def credential_digest(payload):
    values = ['thirdhand-media-credentials-v1', payload['keyId'], *[payload[name] for name in BINDING],
              payload['publisherId'], payload['room'], payload['identity'], payload['token']]
    return encoded(hashlib.sha256(raw_json(values)).digest())

def fixture(*, bound=False, allow=True, jwt_seconds=30, not_before=100):
    keys = {name: Ed25519PrivateKey.generate() for name in ('test-key', 'rotated-key')}
    trusted = {name: key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo) for name, key in keys.items()}
    clock = {'wall': 100000, 'mono': 10.0}
    context = {name: str(uuid.uuid4()) for name in BINDING}
    if not bound:
        context['executorEpoch'] = None
    publisher = str(uuid.uuid4())
    room, identity = 'd_' + context['deviceId'] + '_' + str(uuid.uuid4()), 'p_' + publisher
    def token(nonce=1):
        value = encoded(raw_json({'alg': 'HS256', 'typ': 'JWT'})) + '.' + encoded(raw_json({
            'sub': identity, 'exp': 100 + jwt_seconds, **({'nbf': not_before} if not_before is not None else {}), 'metadata': str(nonce),
            'video': {'room': room, 'roomJoin': True, 'canPublish': True, 'canSubscribe': False,
                      'canPublishData': False, 'canUpdateOwnMetadata': False, 'canPublishSources': ['camera']}}))
        return value + '.' + encoded(hmac.new(b'test-only-jwt-key', value.encode(), hashlib.sha256).digest())
    def sign(value, key_id='test-key'):
        payload = {**value, 'keyId': key_id}
        raw = raw_json(payload)
        return {'keyId': key_id, 'payloadBase64url': encoded(raw), 'signatureBase64url': encoded(keys[key_id].sign(raw))}
    def full(sequence=1, nonce=1, key_id='test-key', changes=None):
        return sign({'schema': 1, 'purpose': 'media_publish', **context, 'publisherId': publisher,
                     'sequence': sequence, 'room': room, 'identity': identity, 'token': token(nonce),
                     'sourceFresh': False, 'frame': None, 'issuedAt': clock['wall'], 'expiresAt': clock['wall'] + 950, **(changes or {})}, key_id)
    first = full()
    full_payload = json.loads(base64.urlsafe_b64decode(first['payloadBase64url'] + '=='))
    def compact(sequence=2, *, changes=None, key_id='test-key'):
        value = {'schema': 1, 'purpose': 'media_renewal', 'context': [context[name] for name in BINDING],
                 'publisherId': publisher, 'sequence': sequence, 'credentialDigest': credential_digest(full_payload),
                 'sourceFresh': False, 'frame': None, 'issuedAt': clock['wall'], 'expiresAt': clock['wall'] + 950}
        return sign({**value, **(changes or {})}, key_id)
    gate = MediaLeaseGate(publisher_id=publisher, trusted_keys=trusted,
                          wall_ms=lambda: clock['wall'], monotonic=lambda: clock['mono'])
    gate.allow_compact = allow
    return gate, context, clock, full_payload, first, full, compact


@pytest.mark.parametrize('bound', [False, True])
def test_verified_full_grant_then_compact_renewal_reuses_only_exact_cached_credentials(bound):
    gate, context, _, original, first, _, compact = fixture(bound=bound)
    gate.accept(first, context)
    assert hasattr(gate, 'credential_hint'), 'Verified credential hints must be explicit'
    hint = gate.credential_hint()
    assert hint['digest'] == credential_digest(original) and hint['context'] == context
    result = gate.accept(compact(), context, expected_sequence=2)
    if result['token'] != original['token'] or result['room'] != original['room'] or result['identity'] != original['identity']:
        pytest.fail('Reconstructed credentials differ from the verified original')
    assert result['purpose'] == 'media_renewal' and result['sequence'] == 2 and gate.active(context)


@pytest.mark.parametrize('fault', ['digest', 'publisher', 'key', 'sequence', 'request-sequence', 'context-device', 'context-boot', 'context-executor', 'context-connection', 'context-certificate', 'frame', 'purpose', 'expiry'])
def test_compact_binding_failure_is_terminal_and_clears_the_cache(fault):
    gate, context, clock, _, first, full, compact = fixture(bound=True)
    gate.accept(first, context)
    assert hasattr(gate, 'credential_hint'), 'Verified credential hints must be explicit'
    changes, key_id, expected = {}, 'test-key', 2
    if fault == 'digest':
        changes['credentialDigest'] = 'A' * 43
    if fault == 'publisher':
        changes['publisherId'] = str(uuid.uuid4())
    if fault == 'key':
        key_id = 'rotated-key'
    if fault == 'sequence':
        changes['sequence'] = 1
    if fault == 'request-sequence':
        changes['sequence'] = 3
    if fault.startswith('context-'):
        changes['context'] = [context[name] for name in BINDING]
        index = ['context-device', 'context-boot', 'context-executor', 'context-connection', 'context-certificate'].index(fault)
        changes['context'][index] = None if index == 2 else str(uuid.uuid4())
    if fault == 'frame':
        changes.update(sourceFresh=True, frame=None)
    if fault == 'purpose':
        changes['purpose'] = 'lease_renew'
    if fault == 'expiry':
        changes['expiresAt'] = clock['wall'] + 951
    with pytest.raises(ProtocolError):
        gate.accept(compact(changes=changes, key_id=key_id), context, expected_sequence=expected)
    assert gate.credential_hint() is None and not gate.active(context)
    with pytest.raises(ProtocolError):
        gate.accept(full(3), context)


def test_first_grant_cannot_be_compact_and_legacy_mode_cannot_accept_compact():
    for mode in ('first', 'legacy'):
        gate, context, _, _, first, _, compact = fixture(allow=mode != 'legacy')
        if mode == 'legacy':
            gate.accept(first, context)
        with pytest.raises(ProtocolError):
            gate.accept(compact(), context, expected_sequence=2)


@pytest.mark.parametrize('allow', [False, True])
def test_a_full_shaped_renewal_purpose_cannot_bypass_compact_verification(allow):
    gate, context, _, _, _, full, _ = fixture(allow=allow)
    with pytest.raises(ProtocolError):
        gate.accept(full(changes={'purpose': 'media_renewal'}), context, expected_sequence=1)


def test_compact_grant_cannot_extend_the_cached_jwt_expiration():
    gate, context, clock, _, first, _, compact = fixture(jwt_seconds=1)
    gate.accept(first, context)
    assert hasattr(gate, 'credential_hint'), 'Verified credential hints must be explicit'
    clock['wall'] += 200
    clock['mono'] += .2
    with pytest.raises(ProtocolError):
        gate.accept(compact(), context, expected_sequence=2)
    assert gate.credential_hint() is None


def test_changed_full_credentials_require_the_new_digest_and_replay_is_rejected():
    gate, context, _, _, first, full, compact = fixture()
    gate.accept(first, context)
    assert hasattr(gate, 'credential_hint'), 'Verified credential hints must be explicit'
    old = gate.credential_hint()['digest']
    gate.accept(full(2, nonce=2), context)
    assert gate.credential_hint()['digest'] != old
    with pytest.raises(ProtocolError):
        gate.accept(compact(3), context, expected_sequence=3)


def test_a_previously_accepted_compact_response_cannot_be_replayed():
    gate, context, _, _, first, _, compact = fixture()
    gate.accept(first, context)
    renewal = compact()
    gate.accept(renewal, context, expected_sequence=2)
    with pytest.raises(ProtocolError):
        gate.accept(renewal, context, expected_sequence=2)
    assert gate.credential_hint() is None and not gate.active(context)


def test_same_credential_full_responses_do_not_extend_cache_across_wall_clock_rollback():
    gate, context, clock, _, first, full, _ = fixture(not_before=None)
    gate.accept(first, context)
    assert hasattr(gate, 'credential_hint'), 'Verified credential hints must be explicit'
    clock['wall'] -= 10000
    with pytest.raises(ProtocolError):
        for sequence in range(2, 37):
            clock['wall'] += 900
            clock['mono'] += .9
            gate.accept(full(sequence), context)
    assert gate.credential_hint() is None


@pytest.mark.parametrize('kind', ['full', 'compact'])
def test_verification_crossing_the_previous_deadline_cannot_commit_a_new_lease(monkeypatch, kind):
    gate, context, clock, _, first, full, compact = fixture()
    gate.accept(first, context)
    clock['wall'] += 800
    clock['mono'] += .8
    name = 'cache_verified_credentials' if kind == 'full' else 'reconstruct_renewal'
    original = getattr(media_publisher, name)
    def delayed(*args, **kwargs):
        result = original(*args, **kwargs)
        clock['wall'] += 200
        clock['mono'] += .2
        return result
    monkeypatch.setattr(media_publisher, name, delayed)
    with pytest.raises(ProtocolError, match='MEDIA_LEASE_EXPIRED'):
        gate.accept(full(2) if kind == 'full' else compact(), context, expected_sequence=2)
    assert gate.credential_hint() is None and not gate.active(context)


@pytest.mark.parametrize('processing_ms', [200, 1000])
def test_first_grant_deadline_accounts_for_time_spent_verifying_credentials(monkeypatch, processing_ms):
    gate, context, clock, _, first, _, _ = fixture()
    original = media_publisher.cache_verified_credentials
    def delayed(*args, **kwargs):
        result = original(*args, **kwargs)
        clock['wall'] += processing_ms
        clock['mono'] += processing_ms / 1000
        return result
    monkeypatch.setattr(media_publisher, 'cache_verified_credentials', delayed)
    if processing_ms >= 950:
        with pytest.raises(ProtocolError, match='MEDIA_LEASE_EXPIRED'):
            gate.accept(first, context)
        assert gate.credential_hint() is None
        return
    gate.accept(first, context)
    clock.update(wall=100951, mono=10.951)
    assert not gate.active(context), 'Verification duration cannot extend the signed grant lifetime'


def test_terminal_invalidation_during_verification_cannot_restore_a_cache(monkeypatch):
    gate, context, _, _, first, _, _ = fixture()
    original = media_publisher.cache_verified_credentials
    def invalidated(*args, **kwargs):
        result = original(*args, **kwargs)
        gate.invalidate()
        return result
    monkeypatch.setattr(media_publisher, 'cache_verified_credentials', invalidated)
    with pytest.raises(ProtocolError, match='MEDIA_LEASE_EXPIRED'):
        gate.accept(first, context)
    assert gate.credential_hint() is None and not gate.active(context)


def test_scheduler_pause_between_wall_and_monotonic_reads_cannot_extend_first_grant():
    gate, context, clock, _, first, _, _ = fixture()
    def paused_wall():
        value = clock['wall']
        clock['wall'] += 200
        clock['mono'] += .2
        return value
    gate.wall = paused_wall
    gate.accept(first, context)
    clock.update(wall=100951, mono=10.951)
    assert not gate.active(context), 'A stale UTC sample cannot be added to a later monotonic reading'


def test_pause_during_final_wall_sample_cannot_revive_previous_lease():
    gate, context, clock, _, first, full, _ = fixture()
    gate.accept(first, context)
    clock['wall'] += 800
    clock['mono'] += .8
    renewal = full(2)
    calls = 0
    def paused_wall():
        nonlocal calls
        calls += 1
        value = clock['wall']
        if calls == 2:
            clock['wall'] += 200
            clock['mono'] += .2
        return value
    gate.wall = paused_wall
    with pytest.raises(ProtocolError, match='MEDIA_LEASE_EXPIRED'):
        gate.accept(renewal, context, expected_sequence=2)
    assert not gate.active(context)
