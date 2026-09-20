from __future__ import annotations

import asyncio
import json
import sys

import websockets


class WakeWordDetector:
    def __init__(self, config):
        w = config.get("wake_word", {})
        self.phrase = str(w.get("phrase", "thirdhand")).lower().replace(" ", "")
        self.speech_ws = w.get("speech_ws_url", "ws://127.0.0.1:3004/v1/voice")
        self.enable_stdin = bool(w.get("enable_stdin", True))

    def _match(self, text):
        t = str(text).lower().replace(" ", "").replace("-", "")
        return self.phrase in t or "thirdhand" in t

    async def events(self):
        queue = asyncio.Queue()
        tasks = []
        if self.enable_stdin:
            async def stdin_loop():
                while True:
                    line = await asyncio.to_thread(sys.stdin.readline)
                    if not line:
                        await asyncio.sleep(0.2)
                        continue
                    if self._match(line):
                        await queue.put({"type": "wake_event", "source": "stdin", "text": line.strip()})
            tasks.append(asyncio.create_task(stdin_loop()))

        async def speech_loop():
            while True:
                try:
                    async with websockets.connect(self.speech_ws, open_timeout=2) as ws:
                        async for raw in ws:
                            try:
                                msg = json.loads(raw)
                            except Exception:
                                continue
                            text = msg.get("text") or msg.get("transcript") or msg.get("final") or ""
                            if msg.get("type") in {"transcript.final", "transcript.partial"} and self._match(text):
                                await queue.put({"type": "wake_event", "source": "speech", "text": text})
                except Exception:
                    await asyncio.sleep(3)
        tasks.append(asyncio.create_task(speech_loop()))
        try:
            while True:
                yield await queue.get()
        finally:
            for task in tasks:
                task.cancel()
