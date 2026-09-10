"""
Core data types shared across all modules.

Defines the "vocabulary" that every subsystem speaks:
pose representations, joint states, detection results, etc.
"""

from dataclasses import dataclass, field


@dataclass
class Pose:
    """Cartesian pose in robot base frame.

    position: [x, y, z] in meters
    orientation: [roll, pitch, yaw] in radians (intrinsic XYZ Euler)
    """

    position: tuple[float, float, float] = (0.0, 0.0, 0.0)
    orientation: tuple[float, float, float] = (0.0, 0.0, 0.0)

    def __repr__(self) -> str:
        x, y, z = self.position
        r, p, yw = self.orientation
        return f"Pose(pos=({x:.4f},{y:.4f},{z:.4f}), rpy=({r:.3f},{p:.3f},{yw:.3f}))"


@dataclass
class JointState:
    """Robot joint state (6-DOF)."""

    positions: tuple[float, ...] = (0.0,) * 6  # degrees
    velocities: tuple[float, ...] = (0.0,) * 6  # degrees/s
    torques: tuple[float, ...] = (0.0,) * 6     # N·m (if available)


@dataclass
class Detection:
    """Single object detection result in image space."""

    id: int | str                    # marker ID or class name
    label: str                       # human-readable label
    confidence: float                # 0.0–1.0
    corners_2d: list[tuple[float, float]] = field(default_factory=list)
    center_pixel: tuple[int, int] = (0, 0)
    pose_camera: Pose | None = None  # in camera frame (if solvePnP)
    pose_base: Pose | None = None    # in robot base frame


@dataclass
class TaskConfig:
    """Configuration for a specific task instance."""

    task_name: str
    detector_type: str = "aruco"
    params: dict = field(default_factory=dict)
