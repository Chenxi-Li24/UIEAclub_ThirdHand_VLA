"""
Robot arm controller  Lumos Touch R1 via startouch_sdk.
"""


class RobotController:
    """Wrapper around startouch_sdk for Lumos Touch R1."""

    def __init__(self, config):
        self.config = config

    def connect(self) -> bool:
        return True  # TODO: implement

    def disconnect(self):
        pass

    def get_joint_angles(self):
        return (0.0,) * 6  # TODO: implement

    def get_ee_pose(self):
        return (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)  # TODO: implement

    def move_j(self, joints, speed=0.3):
        pass  # TODO: implement

    def move_l(self, pose, speed=0.3):
        pass  # TODO: implement

    def move_p(self, pose, speed=0.3):
        pass  # TODO: implement

    def stop(self):
        pass

    def emergency_stop(self):
        pass
