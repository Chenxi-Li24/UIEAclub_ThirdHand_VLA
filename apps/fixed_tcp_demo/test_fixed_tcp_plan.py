"""Run the unchanged planner against a fake arm; no SDK or CAN access."""

from pathlib import Path
from tempfile import TemporaryDirectory

from demo import DemoConfig, FixedTcpDemo


class FakeArm:
    def __init__(self):
        self.motion_calls = 0

    def get_ee_pose_euler(self):
        return [0.48, 0.0, 0.36], [0.0, 0.0, 0.0]

    def get_joint_positions(self):
        return [0.0] * 6

    def solve_ik(self, pos, quat, q_seed=None):
        return [0.0] * 6, True

    def set_joint_waypoints(self, *args, **kwargs):
        self.motion_calls += 1
        raise AssertionError("dry-run must not command motion")


def test_dry_run_planner():
    arm = FakeArm()
    with TemporaryDirectory() as directory:
        demo = FixedTcpDemo(arm, config=DemoConfig(duration_sec=10, max_cone_deg=25),
                            log_dir=Path(directory))
        try:
            demo.run_forever()
            assert arm.motion_calls == 0
            assert demo.log_path.exists()
        finally:
            demo.logger.close()


if __name__ == "__main__":
    test_dry_run_planner()
