"""
Base task abstract class  all tasks inherit from this.
"""

from abc import ABC, abstractmethod


class BaseTask(ABC):
    """Abstract base for all robot tasks."""

    def __init__(self, config):
        self.config = config

    @abstractmethod
    def get_state_machine(self, ccu):
        """Return a configured StateMachine for this task."""
        ...

    @abstractmethod
    def get_detector(self):
        """Return the appropriate detector for this task."""
        ...
