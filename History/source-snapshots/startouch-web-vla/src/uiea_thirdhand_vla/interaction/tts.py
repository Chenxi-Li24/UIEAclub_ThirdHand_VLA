"""
TTS (Text-to-Speech)  edge-tts / PiperTTS wrapper.
"""
class TTSEngine:
    """Text-to-speech using local TTS engine."""

    def __init__(self, config):
        self.config = config

    def speak(self, text: str):
        pass  # TODO: implement
