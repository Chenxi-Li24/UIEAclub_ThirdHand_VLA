"""
ArUco Tag Sorting task  detect multiple markers, sort into designated zones.

See: configs/tasks/ar_tag_sort.yaml
"""

from .base_task import BaseTask


class ArTagSortTask(BaseTask):
    """Sort objects by ArUco marker ID into designated bins."""

    def get_state_machine(self, ccu):
        pass  # TODO: implement

    def get_detector(self):
        pass  # TODO: implement
