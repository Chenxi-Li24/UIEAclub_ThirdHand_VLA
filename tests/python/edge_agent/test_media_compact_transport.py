import asyncio
from pathlib import Path
import sys
import uuid

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'services/edge-agent/src'))
from thirdhand_edge import media_upload
from thirdhand_edge.protocol import ProtocolError
from test_media_upload import fixture


def setup(tmp_path, monkeypatch):
    client, connections, requests, _, _ = fixture(tmp_path, monkeypatch)
    original = media_upload._CoalescedHTTPSConnection.request
    headers_seen = []
    def observe(self, method, path, body, headers):
        headers_seen.append(dict(headers))
        return original(self, method, path, body, {'Content-Type': headers['Content-Type']})
    monkeypatch.setattr(media_upload._CoalescedHTTPSConnection, 'request', observe)
    client.compact_renewals = True
    context = {name: str(uuid.uuid4()) for name in ('deviceId', 'bootId', 'executorEpoch', 'connectionId', 'certificateId')}
    context['executorEpoch'] = None
    publisher = str(uuid.uuid4())
    return client, connections, requests, headers_seen, context, publisher


def test_compact_headers_are_explicit_and_cache_hint_is_bound_to_the_exact_publication(tmp_path, monkeypatch):
    client, _, requests, headers, context, publisher = setup(tmp_path, monkeypatch)
    assert hasattr(client, 'remember_credentials'), 'Only verified Gate hints may be reused'
    async def run():
        await client.request(context, publisher, 1, None)
        assert headers[-1].get('X-ThirdHand-Media-Grant') == 'compact-v1'
        assert 'X-ThirdHand-Media-Credentials' not in headers[-1]
        await client.request(context, publisher, 2, None)
        assert 'X-ThirdHand-Media-Credentials' not in headers[-1], 'Raw unverified HTTP responses cannot seed a credential hint'
        client.remember_credentials({'digest': 'A' * 43, 'publisherId': publisher, 'context': context})
        await client.request(context, publisher, 3, None)
        assert headers[-1].get('X-ThirdHand-Media-Credentials') == 'A' * 43
        await client.request(context, str(uuid.uuid4()), 1, None)
        assert 'X-ThirdHand-Media-Credentials' not in headers[-1]
        await client.request({**context, 'connectionId': str(uuid.uuid4())}, publisher, 4, None)
        assert 'X-ThirdHand-Media-Credentials' not in headers[-1]
    try:
        asyncio.run(run())
        assert [value['sequence'] for value in requests] == [1, 2, 3, 1, 4]
    finally:
        client.close()


def test_cancellation_prevents_a_late_http_worker_from_restoring_the_verified_hint(tmp_path, monkeypatch):
    client, connections, _, started, finished = fixture(tmp_path, monkeypatch, blocked=True)
    hint = {'digest': 'A' * 43, 'publisherId': str(uuid.uuid4()), 'context': {name: str(uuid.uuid4()) for name in ('deviceId', 'bootId', 'executorEpoch', 'connectionId', 'certificateId')}}
    client.remember_credentials(hint)
    async def run():
        task = asyncio.create_task(client.request(hint['context'], hint['publisherId'], 1, None))
        assert await asyncio.to_thread(started.wait, 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert await asyncio.to_thread(finished.wait, 1)
        with pytest.raises(ProtocolError):
            client.remember_credentials(hint)
        with pytest.raises(ProtocolError):
            await client.request(hint['context'], hint['publisherId'], 2, None)
    try:
        asyncio.run(run())
        assert connections[0].closed
    finally:
        client.close()


def test_transport_failure_terminates_cache_and_cannot_be_revived_by_another_hint(tmp_path, monkeypatch):
    client, _, _, _, context, publisher = setup(tmp_path, monkeypatch)
    assert hasattr(client, 'remember_credentials'), 'Only verified Gate hints may be reused'
    hint = {'digest': 'A' * 43, 'publisherId': publisher, 'context': context}
    client.remember_credentials(hint)
    monkeypatch.setattr(media_upload._CoalescedHTTPSConnection, 'getresponse', lambda _self: (_ for _ in ()).throw(TimeoutError()))
    async def run():
        with pytest.raises(ProtocolError):
            await client.request(context, publisher, 1, None)
        with pytest.raises(ProtocolError):
            client.remember_credentials(hint)
        client.remember_credentials(None)  # cleanup is always permitted
    try:
        asyncio.run(run())
    finally:
        client.close()
