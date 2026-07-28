"""
Central Control Unit (CCU)  facade wrapping all subsystems with safety checks.

The state machine talks to the CCU, not directly to robot/camera/detector.
Every motion goes through safety validation. Every detection is logged.
"""


class CentralControlUnit:
    """Facade that the state machine calls. Holds all subsystem references."""

    def __init__(self, robot, camera, detector, gripper, safety, logger):
        self.robot = robot
        self.camera = camera
        self.detector = detector
        self.gripper = gripper
        self.safety = safety
        self.logger = logger

    def move_to_pose(self, pose, speed=0.3):
        """Safety-checked move to Cartesian pose."""
        if not self.safety.check_pose_in_workspace(pose):
            raise Exception("Pose outside workspace")
        self.robot.move_l(pose, speed=speed)

    def move_joints(self, joints, speed=0.3):
        """Safety-checked move to joint angles."""
        if not self.safety.check_joints_in_limits(joints):
            raise Exception("Joint limits exceeded")
        self.robot.move_j(joints, speed=speed)

    def detect_objects(self):
        """Capture frame and run object detection."""
        frame = self.camera.capture()
        detections = self.detector.detect(frame)
        return detections
