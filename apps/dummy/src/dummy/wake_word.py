from __future__ import annotations

import asyncio
from collections import OrderedDict
import json
import re
import sys

import websockets


class WakeWordDetector:
    """Read final local ASR transcripts; never open a second audio session."""

    def __init__(self, config):
        options = config.get("wake_word", {})
        self.phrase = self._normalize(options.get("phrase", "thirdhand"))
        self.speech_ws = options.get("speech_ws_url", "ws://127.0.0.1:3004/v1/transcripts")
        self.enable_stdin = bool(options.get("enable_stdin", True))
        defaults = {"nod": "nod", "wiggle": "wiggle", "tilt": "head_tilt",
                    "\u70b9\u5934": "nod", "\u6447\u6446": "wiggle",
                    "\u6b6a\u5934": "head_tilt"}
        self.actions = {self._normalize(k): str(v) for k, v in options.get("actions", defaults).items()}
        self._seen = OrderedDict()

    @staticmethod
    def _normalize(text):
        return re.sub(r"[\s.,!?\u3002\uff0c\uff01\uff1f-]+", "", str(text).lower())

    def _action(self, text):
        text = self._normalize(text)
        if text == self.phrase:
            return "wake_up"
        if self.phrase and text.startswith(self.phrase):
            text = text[len(self.phrase):]
        return self.actions.get(text)

    def _match(self, text):
        return self._action(text) is not None

    def transcript_event(self, message):
        if message.get("type") != "transcript.final":
            return None
        text = message.get("payload", {}).get("text", "")
        action = self._action(text)
        key = message.get("messageId") or (message.get("sessionId"), message.get("payload", {}).get("segmentId"), text)
        if not action or key in self._seen:
            return None
        self._seen[key] = True
        if len(self._seen) > 256:
            self._seen.popitem(last=False)
        return {"type": "wake_event", "source": "speech", "text": text, "action": action}

    async def events(self):
        queue = asyncio.Queue(maxsize=4)
        loop = asyncio.get_running_loop()
        registered_stdin = False

        def offer(event):
            if event is None:
                return
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(event)

        def stdin_ready():
            line = sys.stdin.readline()
            if not line:
                loop.remove_reader(sys.stdin.fileno())
                return
            action = self._action(line)
            if action:
                offer({"type": "wake_event", "source": "stdin", "text": line.strip(), "action": action})

        if self.enable_stdin:
            try:
                loop.add_reader(sys.stdin.fileno(), stdin_ready)
                registered_stdin = True
            except (AttributeError, OSError, NotImplementedError, ValueError):
                # Do not leave an uncancellable blocking readline thread at exit.
                pass

        async def speech_loop():
            while True:
                try:
                    async with websockets.connect(
                        self.speech_ws, subprotocols=["thirdhand.transcripts.v1"],
                        open_timeout=2, close_timeout=1, max_queue=8,
                    ) as ws:
                        async for raw in ws:
                            if not isinstance(raw, str):
                                continue
                            try:
                                offer(self.transcript_event(json.loads(raw)))
                            except (ValueError, TypeError, AttributeError):
                                continue
                except (OSError, websockets.exceptions.WebSocketException):
                    await asyncio.sleep(3)

        task = asyncio.create_task(speech_loop())
        try:
            while True:
                yield await queue.get()
        finally:
            if registered_stdin:
                loop.remove_reader(sys.stdin.fileno())
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
