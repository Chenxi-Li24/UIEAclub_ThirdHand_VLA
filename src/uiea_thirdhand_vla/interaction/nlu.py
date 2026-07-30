"""
NLU (Natural Language Understanding)  local small model intent parser.

Maps natural language commands to structured intents for the state machine.
"""
from dataclasses import dataclass


@dataclass
class Intent:
    action: str  # start_task, stop, pause, resume, estop, go_home, jog
    task_name: str | None = None
    params: dict = None

    def __post_init__(self):
        if self.params is None:
            self.params = {}


class NLUEngine:
    """Intent parser using local small language model."""

    def __init__(self, config):
        self.config = config

    def parse(self, text: str) -> Intent | None:
        return None  # TODO: implement
