"""Signed synthetic leases; no SDK, CAN or network access."""
import base64
import json
from pathlib import Path
import sys
from uuid import uuid4
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'services/edge-agent/src'))
from thirdhand_edge.lease import verify_lease
from thirdhand_edge.protocol import ProtocolError


def signed(offset, span=1000, scope='sdk'):
    key = Ed25519PrivateKey.generate()
    binding = {k: str(uuid4()) for k in ('deviceId', 'bootId', 'executorEpoch', 'connectionId', 'certificateId')}
    value = dict(schema=1, keyId='test', purpose='lease_renew', **binding, leaseId=str(uuid4()),
                 leaseEpoch=1, sequence=1, scope=scope, issuedAt=10000+offset, expiresAt=10000+offset+span)
    raw = json.dumps(value).encode()
    b64 = lambda v: base64.urlsafe_b64encode(v).decode().rstrip('=')
    envelope = dict(keyId='test', payloadBase64url=b64(raw), signatureBase64url=b64(key.sign(raw)))
    keys = {'test': key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)}
    return envelope, keys, binding


@pytest.mark.parametrize('offset', [-999, -100, -10, -1, 0, 1, 10, 100, 500])
@pytest.mark.parametrize('scope', ['sdk', 'control'])
def test_small_clock_offset_keeps_signed_one_second_span(offset, scope):
    args = signed(offset, scope=scope)
    value = verify_lease(*args, now_ms=10000)
    assert value['expiresAt'] - value['issuedAt'] == 1000


@pytest.mark.parametrize('offset,span', [(-1000, 1000), (501, 1000), (-500, 1001), (0, 0)])
def test_expired_future_or_overlong_lease_still_rejected(offset, span):
    with pytest.raises(ProtocolError):
        verify_lease(*signed(offset, span), now_ms=10000)
