"""
VLA API client  Anthropic/DeepSeek/OpenAI-compatible cloud API.
"""
class VLAClient:
    """Cloud VLA API client for vision-language reasoning."""

    def __init__(self, config):
        self.config = config

    async def reason(self, frame, context, session):
        """Send camera frame + context to cloud VLA, return recommendation."""
        return None  # TODO: implement

    def _encode_frame(self, frame) -> str:
        """Encode numpy frame to base64 JPEG."""
        return ""  # TODO: implement
