"""
Camera interface  Lumos Ego camera via FastUMI_Camera SDK.

See: https://github.com/lumos-open/FastUMI_Camera
"""
class Camera:
    """Wrapper around Lumos Ego camera stream."""

    def __init__(self, config):
        self.config = config
        self._is_open = False

    def open(self) -> bool:
        self._is_open = True
        return True

    def capture(self):
        if not self._is_open:
            raise RuntimeError("Camera not opened")
        return None  # TODO: implement

    def close(self):
        self._is_open = False

    @property
    def is_open(self) -> bool:
        return self._is_open
