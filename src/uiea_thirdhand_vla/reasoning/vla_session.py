"""
VLA session management — conversation state, image buffering, history.
"""

import base64

import cv2
import numpy as np


class VLASession:
    """Manages conversation history and state for VLA interactions."""

    def __init__(self, history_size=20):
        self.history_size = history_size
        self.history: list[dict] = []  # API-compatible message list

    # ---- Message management ----

    def add_user_message(self, text: str, image_b64: str = None):
        """Add a user message with optional image to history."""
        content = []
        if image_b64:
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": image_b64,
                }
            })
        if text:
            content.append({"type": "text", "text": text})

        msg: dict[str, object] = {
            "role": "user",
            "content": content if len(content) > 1 else content[0],
        }
        self.history.append(msg)
        self._trim()

    def add_assistant_message(self, response: str | list):
        """Add assistant response to history."""
        msg: dict[str, object] = {"role": "assistant", "content": response}
        self.history.append(msg)
        self._trim()

    def add_tool_result(self, tool_use_id: str, result: str):
        """Add tool result to history."""
        msg = {
            "role": "user",
            "content": [{
                "type": "tool_result",
                "tool_use_id": tool_use_id,
                "content": result,
            }]
        }
        self.history.append(msg)
        self._trim()

    def clear(self):
        """Clear conversation history."""
        self.history = []

    def _trim(self):
        """Trim history to max size, preserving first (system) message."""
        while len(self.history) > self.history_size:
            self.history.pop(0)

    # ---- Frame encoding ----

    @staticmethod
    def encode_frame(frame: np.ndarray, quality: int = 85,
                     max_side: int = 1024) -> str:
        """
        Encode OpenCV BGR frame to base64 JPEG string.
        Returns data URL ready for API.
        """
        if frame is None:
            return ""

        # Resize if needed to keep under max_side
        h, w = frame.shape[:2]
        if max(h, w) > max_side:
            scale = max_side / max(h, w)
            new_w, new_h = int(w * scale), int(h * scale)
            frame = cv2.resize(frame, (new_w, new_h))

        _, buffer = cv2.imencode('.jpg', frame,
                                 [cv2.IMWRITE_JPEG_QUALITY, quality])
        return base64.b64encode(buffer).decode('utf-8')

    @staticmethod
    def encode_frame_high(frame: np.ndarray) -> str:
        """Encode frame at higher quality (for VLA reasoning)."""
        return VLASession.encode_frame(frame, quality=90, max_side=1024)

    @staticmethod
    def encode_frame_fast(frame: np.ndarray) -> str:
        """Encode frame at lower quality (for quick checks)."""
        return VLASession.encode_frame(frame, quality=60, max_side=512)

    # ---- History access ----

    def get_messages(self) -> list[dict]:
        """Return messages for API call."""
        return list(self.history)

    def last_assistant_text(self) -> str:
        """Get last assistant text response."""
        for msg in reversed(self.history):
            if msg["role"] == "assistant":
                if isinstance(msg["content"], str):
                    return msg["content"]
                for block in msg["content"]:
                    if block.get("type") == "text":
                        return block["text"]
        return ""
