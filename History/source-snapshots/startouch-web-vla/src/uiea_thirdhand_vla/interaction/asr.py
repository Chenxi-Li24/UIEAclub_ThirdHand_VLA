"""
ASR (Automatic Speech Recognition)  faster-whisper / SenseVoice wrapper.
"""
class ASREngine:
    """Speech-to-text using local Whisper model."""

    def __init__(self, config):
        self.config = config

    def load_model(self):
        pass  # TODO: implement

    def transcribe(self, audio_data) -> str:
        return ""  # TODO: implement
