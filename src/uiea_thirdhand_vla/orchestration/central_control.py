"""
Central Control Unit (CCU) — facade wrapping all subsystems.

The state machine talks to the CCU, not directly to robot/camera/detector.
Every motion goes through safety validation. Every detection is logged.
"""

import logging

logger = logging.getLogger(__name__)


class CentralControlUnit:
    """Facade that the state machine calls. Holds all subsystem references."""

    def __init__(self, robot, camera, detector, gripper, safety,
                 transforms, logger_inst):
        self.robot = robot
        self.camera = camera
        self.detector = detector
        self.gripper = gripper
        self.safety = safety
        self.transforms = transforms
        self.logger = logger_inst

    # ---- Robot control (with safety) ----

    def move_to_pose(self, pose, speed=0.3):
        """Safety-checked move to Cartesian pose.

        Args:
            pose: (x, y, z, roll, pitch, yaw) or (x, y, z) tuple
            speed: fraction of max speed
        """
        if not self.safety.check_pose_in_workspace(pose):
            raise Exception(f"Pose outside workspace: {pose}")

        if len(pose) == 3:
            pose = (pose[0], pose[1], pose[2], 0, 0, 0)

        self.robot.move_l(pose, speed=speed)
        logger.info(f"Move to: x={pose[0]:.4f} y={pose[1]:.4f} z={pose[2]:.4f}")

    def move_joints(self, joints, speed=0.3):
        """Safety-checked move to joint angles (degrees)."""
        if not self.safety.check_joints_in_limits(joints):
            raise Exception(f"Joint limits exceeded: {joints}")
        self.robot.move_j(joints, speed=speed)

    def open_gripper(self, position=0.06):
        """Open gripper to position (m)."""
        self.gripper.open(position)

    def close_gripper(self, position=0.02):
        """Close gripper to position (m)."""
        self.gripper.close(position)

    # ---- Perception ----

    def detect_objects(self):
        """Capture frame and run object detection."""
        frame = self.camera.capture()
        if frame is None:
            return []
        detections = self.detector.detect(frame)
        self.logger.log_detections(detections)
        return detections

    def get_frame(self):
        """Capture a single frame."""
        return self.camera.capture()
