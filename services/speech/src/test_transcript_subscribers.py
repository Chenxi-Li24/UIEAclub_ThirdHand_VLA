import asyncio
import json
import unittest

try:
    from websockets.asyncio.client import connect
    from websockets.asyncio.server import serve
except ImportError:
    from websockets import connect, serve

from websockets.exceptions import ConnectionClosed
from voice_bridge import (VoiceBridge, ConnectionContext, TRANSCRIPT_SUBPROTOCOL,
                          WEBSOCKET_SUBPROTOCOL)


class TranscriptSubscriberTests(unittest.IsolatedAsyncioTestCase):
    async def test_final_fanout_is_read_only_and_does_not_create_audio_session(self):
        bridge = VoiceBridge(asr=None, claude_factory=None)
        async with serve(bridge.handle_connection, "127.0.0.1", 0,
                         subprotocols=[WEBSOCKET_SUBPROTOCOL, TRANSCRIPT_SUBPROTOCOL]) as server:
            port = server.sockets[0].getsockname()[1]
            async with connect(f"ws://127.0.0.1:{port}/v1/transcripts",
                               subprotocols=[TRANSCRIPT_SUBPROTOCOL]) as ws:
                for _ in range(50):
                    if bridge.transcript_subscribers:
                        break
                    await asyncio.sleep(0.01)
                assert not bridge.connections
                class Origin:
                    sent = []
                    async def send(self, raw):
                        self.sent.append(json.loads(raw))
                origin = Origin()
                context = ConnectionContext(websocket=origin)
                await bridge._send(context, "transcript.partial", "s", {"text": "nod"})
                await bridge._send(context, "transcript.final", "s", {"text": "nod", "segmentId": "1"})
                final = json.loads(await asyncio.wait_for(ws.recv(), 1))
                assert final == origin.sent[-1]
                assert final["type"] == "transcript.final"
                await ws.send(json.dumps({"type": "session.start"}))
                with self.assertRaises(ConnectionClosed):
                    await ws.recv()
        assert not bridge.connections and not bridge.transcript_subscribers

    async def test_slow_subscriber_queue_is_bounded_and_has_no_replay(self):
        bridge = VoiceBridge(asr=None, claude_factory=None)
        queue = asyncio.Queue(maxsize=8)
        bridge.transcript_subscribers[1] = queue
        for i in range(20):
            bridge._publish_transcript({"type": "transcript.final", "messageId": str(i)})
        assert queue.qsize() == 8
        assert (await queue.get())["messageId"] == "12"
        bridge._publish_transcript({"type": "transcript.partial", "messageId": "ignored"})
        assert queue.qsize() == 7
