"""
TTS Bridge — edge-tts synthesis adapter for Voice Bridge.

Synthesizes text to MP3 via the edge-tts Python module and returns base64-encoded
audio ready for WebSocket delivery to the browser.

This module deliberately does NOT import voice_agent.py so it stays free of
heavy dependencies (numpy, sounddevice, torch, faster-whisper).  The current
Python environment must provide the ``edge_tts`` module at runtime.

Usage::

    from tts_bridge import TTSBridge

    bridge = TTSBridge()
    info = bridge.synthesize_info("你好世界")
    if info:
        print(info["audio"][:40] + "...")  # base64 MP3 prefix
"""

from __future__ import annotations

import base64
import logging
import os
import subprocess
import sys
import tempfile
from typing import Optional

LOG = logging.getLogger("thirdhand.tts_bridge")


class TTSBridge:
    """Bilingual text-to-speech via ``python -m edge_tts`` to base64 MP3."""

    VOICES: dict[str, str] = {
        "en": "en-US-JennyNeural",
        "zh": "zh-CN-XiaoxiaoNeural",
    }

    def __init__(
        self,
        voice: Optional[str] = None,
        timeout: float = 15.0,
    ) -> None:
        """
        Parameters
        ----------
        voice:
            Override voice name (e.g. ``"zh-CN-XiaoxiaoNeural"``).
            When ``None`` (default), auto-detect EN vs ZH from text content.
        timeout:
            Subprocess timeout in seconds for edge-tts.
        """
        self._voice_override = voice
        self.timeout = timeout

    # ------------------------------------------------------------------
    # Voice selection
    # ------------------------------------------------------------------

    def _pick_voice(self, text: str) -> str:
        """Pick EN or ZH voice based on text content.

        Mirrors ``voice_agent.TTSEngine._pick_voice`` logic:
        if >30 % of characters are CJK, use Chinese voice; otherwise English.
        """
        if self._voice_override:
            return self._voice_override
        cjk = sum(1 for c in text if "一" <= c <= "鿿")
        return self.VOICES["zh"] if cjk > len(text) * 0.3 else self.VOICES["en"]

    # ------------------------------------------------------------------
    # Synthesis
    # ------------------------------------------------------------------

    def synthesize(self, text: str) -> Optional[tuple[str, str]]:
        """Run edge-tts and return ``(base64_mp3, voice_name)`` or ``None``.

        The returned bytes are the raw MP3 produced by edge-tts, base64-encoded
        so they can travel inside a JSON WebSocket message.
        """
        if not text.strip():
            return None

        voice = self._pick_voice(text)

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            mp3_path = tmp.name

        try:
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "edge_tts",
                    "--voice",
                    voice,
                    "--text",
                    text,
                    "--write-media",
                    mp3_path,
                ],
                capture_output=True,
                timeout=self.timeout,
                check=True,
            )

            with open(mp3_path, "rb") as fh:
                raw = fh.read()

            if not raw:
                LOG.warning("edge-tts produced empty MP3 for text=%r", text[:60])
                return None

            encoded = base64.b64encode(raw).decode("ascii")
            LOG.debug(
                "TTS synthesized voice=%s text_len=%d mp3_bytes=%d b64_len=%d",
                voice,
                len(text),
                len(raw),
                len(encoded),
            )
            return encoded, voice

        except FileNotFoundError:
            LOG.warning("Python executable not found while starting edge-tts")
            return None
        except subprocess.TimeoutExpired:
            LOG.warning("edge-tts timed out after %.0fs for text=%r", self.timeout, text[:60])
            return None
        except Exception:
            LOG.exception("edge-tts synthesis failed for text=%r", text[:60])
            return None
        finally:
            try:
                os.unlink(mp3_path)
            except OSError:
                pass

    def synthesize_info(self, text: str) -> Optional[dict]:
        """Return a payload dict for an ``assistant.audio`` message, or ``None``.

        >>> bridge = TTSBridge()
        >>> info = bridge.synthesize_info("Hello")
        >>> info["format"]
        'audio/mpeg'
        >>> info["sampleRate"]
        24000
        """
        result = self.synthesize(text)
        if result is None:
            return None
        encoded, voice = result
        return {
            "text": text,
            "audio": encoded,
            "format": "audio/mpeg",
            "sampleRate": 24000,
            "voice": voice,
        }
