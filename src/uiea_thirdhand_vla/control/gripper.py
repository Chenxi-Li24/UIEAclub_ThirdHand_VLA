"""
Gripper controller  TypeFZ / TypeLJ via startouch_sdk.
"""


class Gripper:
    """Gripper control for Lumos Touch R1."""

    def __init__(self, config):
        self.config = config

    def open(self, distance_mm=None):
        pass  # TODO: implement

    def close(self, force=None):
        pass  # TODO: implement

    def get_distance(self) -> float:
        return 0.0  # TODO: implement

    def is_grasped(self) -> bool:
        return False  # TODO: implement
