"""
Pick and Place task  ArUco marker -> grasp -> transport -> release -> return.

See: configs/tasks/pick_place.yaml
"""

from .base_task import BaseTask


class PickAndPlaceTask(BaseTask):
    """Detect ArUco marker, pick object, place at target location."""

    def get_state_machine(self, ccu):
        pass  # TODO: implement

    def get_detector(self):
        pass  # TODO: implement
