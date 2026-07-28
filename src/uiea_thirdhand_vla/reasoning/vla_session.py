"""
VLA session management  conversation state, image buffering.
"""
class VLASession:
    """Manages conversation history and state for a VLA interaction."""

    def __init__(self, history_size=20):
        self.history_size = history_size
        self.history = []

    def add_user_message(self, text, image_b64=None):
        pass  # TODO: implement

    def add_assistant_message(self, response):
        pass  # TODO: implement

    def clear(self):
        self.history = []
