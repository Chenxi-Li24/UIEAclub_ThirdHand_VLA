import base64
import hashlib
import json

from thirdhand_edge.lease_timing import LeaseTiming


def envelope(**updates):
    data = dict(purpose='lease_renew', scope='sdk', issuedAt=1000, private='must-not-log')
    data.update(updates)
    raw = base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip('=')
    return dict(payloadBase64url=raw, signatureBase64url='secret-signature')


def test_stages_share_exact_wire_hash_and_exclude_private_fields():
    now = [1.0]
    records = []
    timing = LeaseTiming(enabled=True, mono=lambda: now[0], wall=lambda: 10, sink=records.append)
    value = envelope()
    trace = timing.begin(value, (1, 10))
    trace.mark('received')
    now[0] += .025
    trace.mark('lock_acquired')
    now[0] += .010
    trace.mark('local_reply')
    trace.mark('secret')
    trace.finish('active')
    trace.finish('active')
    assert len(records) == 1
    record = records[0]
    assert record['trace'] == hashlib.sha256(value['payloadBase64url'].encode('ascii')).hexdigest()
    assert record['marks'] == dict(received=0, lock_acquired=25, local_reply=35)
    assert record['startedAtMs'] == 10000
    assert not any(s in json.dumps(record) for s in ('must-not-log', 'secret', 'signatureBase64url'))


def test_disabled_expired_budget_and_broken_sink_cannot_affect_requests():
    assert LeaseTiming(enabled=False).begin(envelope()) is None
    now = [0]
    records = []
    timing = LeaseTiming(enabled=True, mono=lambda: now[0], sink=records.append, limit=1, window=10)
    first, second = timing.begin(envelope()), timing.begin(envelope())
    first.finish('active')
    second.finish('active')
    assert len(records) == 1
    assert timing.begin(envelope()) is None
    expiring = LeaseTiming(enabled=True, mono=lambda: now[0], sink=records.append, window=1)
    trace = expiring.begin(envelope())
    now[0] = 2
    trace.finish('active')
    assert len(records) == 1 and expiring.begin(envelope()) is None
    def broken(_):
        raise RuntimeError('sink failure')
    LeaseTiming(enabled=True, sink=broken).begin(envelope()).finish('active')


def test_malformed_non_sdk_and_motion_are_not_traced():
    timing = LeaseTiming(enabled=True)
    for value in ({}, {'payloadBase64url': 3}, {'payloadBase64url': '!'},
                  {'payloadBase64url': 'a' * 16385}, envelope(scope='control'),
                  envelope(purpose='command'), envelope(purpose='stop')):
        assert timing.begin(value) is None
